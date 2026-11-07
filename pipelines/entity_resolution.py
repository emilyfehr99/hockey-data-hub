"""
Entity Resolution Engine
========================
Harmonizes player identities across multi-tier tracking sources,
generating canonical UUIDs and a unified player dimension table.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
import duckdb
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("entity_resolution")

BASE_DIR = Path(__file__).resolve().parent.parent
DUCKDB_PATH = BASE_DIR / "data" / "duckdb" / "hockey_master.duckdb"
PARQUET_PATH = BASE_DIR / "data" / "parquet" / "dim_players.parquet"

TRANSITION_DB_ENV = os.getenv("TRANSITION_DB_PATH", "").strip()
LOCAL_TRACKING_DB = Path(TRANSITION_DB_ENV) if TRANSITION_DB_ENV else None

MICROSTATS_CACHE_ENV = os.getenv("MICROSTATS_CACHE_PATH", "").strip()
LOCAL_CACHE_DB = Path(MICROSTATS_CACHE_ENV) if MICROSTATS_CACHE_ENV else None

RESOLVED_SHEET_ENV = os.getenv("RESOLVED_SHEET_PATH", "").strip()
RESOLVED_SHEET_PATH = Path(RESOLVED_SHEET_ENV) if RESOLVED_SHEET_ENV else None


def is_valid_file(p: Optional[Path]) -> bool:
    return bool(p and str(p).strip() and p.is_file() and p.stat().st_size > 0)


NHL_TEAMS_ALL = [
    "ANA", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL",
    "DAL", "DET", "EDM", "FLA", "LAK", "MIN", "MTL", "NJD",
    "NSH", "NYI", "NYR", "OTT", "PHI", "PIT", "SEA", "SJS",
    "STL", "TBL", "TOR", "UTA", "VAN", "VGK", "WPG", "WSH"
]


def normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", stripped).lower()
    return re.sub(r"\s+", " ", cleaned).strip()


@dataclass
class PlayerDimension:
    player_uuid: str
    nhl_player_id: Optional[int] = None
    tracking_player_id: Optional[int] = None
    player_slug: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    birth_date: Optional[str] = None
    draft_year: Optional[int] = None
    draft_round: Optional[int] = None
    draft_overall: Optional[int] = None
    draft_team: Optional[str] = None
    primary_position: Optional[str] = None
    shoots_catches: Optional[str] = None
    height_inches: Optional[int] = None
    weight_lbs: Optional[int] = None
    birth_country: Optional[str] = None
    birth_city: Optional[str] = None
    birth_state_province: Optional[str] = None
    current_team: Optional[str] = None
    headshot_url: Optional[str] = None
    hero_image_url: Optional[str] = None
    career_gp: Optional[int] = None
    career_goals: Optional[int] = None
    career_assists: Optional[int] = None
    career_points: Optional[int] = None
    is_active_nhl: bool = False


class EntityResolver:
    def __init__(self):
        self.players_by_uuid: Dict[str, PlayerDimension] = {}
        self.nhl_id_to_uuid: Dict[int, str] = {}
        self.tracking_id_to_uuid: Dict[int, str] = {}
        self.slug_to_uuid: Dict[str, str] = {}
        self.norm_name_to_uuids: Dict[str, List[str]] = {}

    def _get_or_create_uuid(
        self,
        nhl_id: Optional[int] = None,
        tracking_id: Optional[int] = None,
        slug: Optional[str] = None,
        fallback_key: Optional[str] = None
    ) -> str:
        if nhl_id and nhl_id in self.nhl_id_to_uuid:
            return self.nhl_id_to_uuid[nhl_id]
        if tracking_id and tracking_id in self.tracking_id_to_uuid:
            return self.tracking_id_to_uuid[tracking_id]
        if slug and slug in self.slug_to_uuid:
            return self.slug_to_uuid[slug]

        if nhl_id:
            uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"nhl:{nhl_id}"))
        elif tracking_id:
            uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"trk:{tracking_id}"))
        elif slug:
            uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"slug:{slug}"))
        else:
            uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"gen:{fallback_key}"))

        return uid

    def add_player(self, p: PlayerDimension):
        self.players_by_uuid[p.player_uuid] = p
        if p.nhl_player_id:
            self.nhl_id_to_uuid[p.nhl_player_id] = p.player_uuid
        if p.tracking_player_id:
            self.tracking_id_to_uuid[p.tracking_player_id] = p.player_uuid
        if p.player_slug:
            self.slug_to_uuid[p.player_slug] = p.player_uuid

        norm = normalize_text(p.full_name)
        if norm:
            self.norm_name_to_uuids.setdefault(norm, []).append(p.player_uuid)

    def upsert_player(self, p: PlayerDimension):
        if p.player_uuid in self.players_by_uuid:
            existing = self.players_by_uuid[p.player_uuid]
            if p.is_active_nhl is not None:
                existing.is_active_nhl = p.is_active_nhl
            if p.current_team:
                existing.current_team = p.current_team
            if p.first_name and not existing.first_name:
                existing.first_name = p.first_name
            if p.last_name and not existing.last_name:
                existing.last_name = p.last_name
            if p.full_name and not existing.full_name:
                existing.full_name = p.full_name
            if p.primary_position and not existing.primary_position:
                existing.primary_position = p.primary_position
            if p.shoots_catches and not existing.shoots_catches:
                existing.shoots_catches = p.shoots_catches
            if p.height_inches and not existing.height_inches:
                existing.height_inches = p.height_inches
            if p.weight_lbs:
                existing.weight_lbs = p.weight_lbs
            if p.birth_date and not existing.birth_date:
                existing.birth_date = p.birth_date
            if p.birth_country and not existing.birth_country:
                existing.birth_country = p.birth_country
            if p.nhl_player_id and not existing.nhl_player_id:
                existing.nhl_player_id = p.nhl_player_id
                self.nhl_id_to_uuid[p.nhl_player_id] = p.player_uuid
            if p.tracking_player_id and not existing.tracking_player_id:
                existing.tracking_player_id = p.tracking_player_id
                self.tracking_id_to_uuid[p.tracking_player_id] = p.player_uuid
            if p.player_slug and not existing.player_slug:
                existing.player_slug = p.player_slug
                self.slug_to_uuid[p.player_slug] = p.player_uuid
        else:
            self.add_player(p)

    def load_existing_dimension(self):
        if not PARQUET_PATH.exists():
            return
        logger.info(f"Loading existing player dimension from {PARQUET_PATH}...")
        df = pd.read_parquet(PARQUET_PATH)
        int_fields = {
            "nhl_player_id", "tracking_player_id", "draft_year", "draft_round",
            "draft_overall", "height_inches", "weight_lbs", "career_gp",
            "career_goals", "career_assists", "career_points"
        }
        loaded = 0
        for _, row in df.iterrows():
            clean_dict = {}
            for k, v in row.to_dict().items():
                if k not in PlayerDimension.__dataclass_fields__:
                    continue
                if pd.isna(v):
                    clean_dict[k] = None
                elif k in int_fields:
                    try:
                        clean_dict[k] = int(v)
                    except (ValueError, TypeError):
                        clean_dict[k] = None
                elif k == "is_active_nhl":
                    clean_dict[k] = bool(v)
                else:
                    clean_dict[k] = str(v)
            p = PlayerDimension(**clean_dict)
            self.add_player(p)
            loaded += 1
        logger.info(f"Loaded {loaded} existing players from {PARQUET_PATH}.")

    def load_league_active_rosters(self):
        logger.info("Ingesting active rosters from league API...")
        # Mark all existing as inactive before checking current rosters
        for p in self.players_by_uuid.values():
            p.is_active_nhl = False

        count = 0
        for team in NHL_TEAMS_ALL:
            url = f"https://api-web.nhle.com/v1/roster/{team}/current"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (HockeyDataHub/1.0)"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                
                for group in ["forwards", "defensemen", "goalies"]:
                    for item in data.get(group, []):
                        nhl_id = item.get("id")
                        if not nhl_id:
                            continue
                        
                        uid = self._get_or_create_uuid(nhl_id=nhl_id)
                        fn = item.get("firstName", {}).get("default", "")
                        ln = item.get("lastName", {}).get("default", "")
                        full_name = f"{fn} {ln}".strip()
                        
                        p = PlayerDimension(
                            player_uuid=uid,
                            nhl_player_id=nhl_id,
                            first_name=fn,
                            last_name=ln,
                            full_name=full_name,
                            birth_date=item.get("birthDate"),
                            primary_position=item.get("positionCode"),
                            shoots_catches=item.get("shootsCatches"),
                            height_inches=item.get("heightInInches"),
                            weight_lbs=item.get("weightInPounds"),
                            birth_country=item.get("birthCountry"),
                            current_team=team,
                            is_active_nhl=True
                        )
                        self.upsert_player(p)
                        count += 1
            except Exception as e:
                logger.warning(f"Could not fetch roster for {team}: {e}")

        logger.info(f"Loaded {count} active players.")

    def load_resolved_sheet_players(self):
        if not is_valid_file(RESOLVED_SHEET_PATH):
            return
        logger.info("Loading pre-resolved sheet player mappings...")
        with open(RESOLVED_SHEET_PATH, "r") as f:
            data = json.load(f)
        
        linked = 0
        for sheet_key, val in data.items():
            pid_str = val.get("playerId")
            if not pid_str:
                continue
            try:
                pid = int(pid_str)
            except ValueError:
                continue

            resolved_name = val.get("resolved_name", sheet_key)
            uid = self._get_or_create_uuid(nhl_id=pid)
            
            p = PlayerDimension(
                player_uuid=uid,
                nhl_player_id=pid,
                full_name=resolved_name,
                primary_position=val.get("position"),
                current_team=val.get("team"),
                is_active_nhl=val.get("active", False)
            )
            self.upsert_player(p)
            linked += 1

        logger.info(f"Incorporated {len(data)} sheet players ({linked} new entries).")

    def link_transition_players(self):
        if not is_valid_file(LOCAL_TRACKING_DB):
            return
        logger.info("Resolving players from transition tracking database...")
        conn = sqlite3.connect(LOCAL_TRACKING_DB)
        c = conn.cursor()
        c.execute("SELECT DISTINCT slug, name, team, position FROM players;")
        rows = c.fetchall()
        conn.close()

        matched = 0
        created = 0
        for slug, name, team, pos in rows:
            norm_name = normalize_text(name)
            target_uuid = None

            if norm_name in self.norm_name_to_uuids:
                candidates = self.norm_name_to_uuids[norm_name]
                if len(candidates) == 1:
                    target_uuid = candidates[0]
                else:
                    for cand_uid in candidates:
                        cand = self.players_by_uuid[cand_uid]
                        if cand.current_team == team:
                            target_uuid = cand_uid
                            break
                    if not target_uuid:
                        target_uuid = candidates[0]

            if target_uuid:
                p = self.players_by_uuid[target_uuid]
                p.player_slug = slug
                self.slug_to_uuid[slug] = target_uuid
                matched += 1
            else:
                uid = self._get_or_create_uuid(slug=slug, fallback_key=f"slug:{slug}")
                p = PlayerDimension(
                    player_uuid=uid,
                    player_slug=slug,
                    full_name=name,
                    primary_position=pos,
                    current_team=team,
                    is_active_nhl=False
                )
                self.add_player(p)
                created += 1

        logger.info(f"Transition Resolution: {matched} linked to league IDs, {created} new non-roster entries.")

    def link_cached_micro_players(self):
        if not is_valid_file(LOCAL_CACHE_DB):
            return
        logger.info("Resolving players from cached tracking records...")
        conn = sqlite3.connect(LOCAL_CACHE_DB)
        c = conn.cursor()
        c.execute("SELECT response FROM api_cache WHERE payload_raw LIKE '%players_stat%';")
        
        cached_players: Dict[int, Dict[str, Any]] = {}
        for (resp,) in c.fetchall():
            try:
                data = json.loads(resp)
                first_obj = data.get("data", [])[0]
                stat_dict = next(iter(first_obj.values())) if isinstance(first_obj, dict) else {}
                for team_key in ["team1", "team2"]:
                    t_info = stat_dict.get(team_key, {})
                    t_name = t_info.get("name_eng")
                    for p in t_info.get("stat", []):
                        pid = p.get("player_id")
                        if pid and pid not in cached_players:
                            cached_players[pid] = {
                                "tracking_id": pid,
                                "name_eng": p.get("name_eng", ""),
                                "team": t_name
                            }
            except Exception:
                pass
        conn.close()

        matched = 0
        created = 0
        for t_id, info in cached_players.items():
            name = info["name_eng"]
            norm_name = normalize_text(name)
            
            parts = norm_name.split()
            inverted_norm = f"{' '.join(parts[1:])} {parts[0]}".strip() if len(parts) > 1 else ""

            target_uuid = None
            if norm_name in self.norm_name_to_uuids:
                target_uuid = self.norm_name_to_uuids[norm_name][0]
            elif inverted_norm and inverted_norm in self.norm_name_to_uuids:
                target_uuid = self.norm_name_to_uuids[inverted_norm][0]

            if target_uuid:
                p = self.players_by_uuid[target_uuid]
                p.tracking_player_id = t_id
                self.tracking_id_to_uuid[t_id] = target_uuid
                matched += 1
            else:
                uid = self._get_or_create_uuid(tracking_id=t_id)
                p = PlayerDimension(
                    player_uuid=uid,
                    tracking_player_id=t_id,
                    full_name=name,
                    current_team=info["team"],
                    is_active_nhl=False
                )
                self.add_player(p)
                created += 1

        logger.info(f"Micro-Tracking Resolution: {matched} matched to existing players, {created} prospect/junior records added.")

    def export_canonical_dimension(self):
        rows = [asdict(p) for p in self.players_by_uuid.values()]
        df = pd.DataFrame(rows)
        
        PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(PARQUET_PATH, index=False)
        logger.info(f"Saved {len(df)} canonical players to {PARQUET_PATH}")

        DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
        db = duckdb.connect(str(DUCKDB_PATH))
        db.execute("DROP TABLE IF EXISTS dim_players;")
        db.execute(f"CREATE TABLE dim_players AS SELECT * FROM read_parquet('{PARQUET_PATH}');")
        count = db.execute("SELECT COUNT(*) FROM dim_players;").fetchone()[0]
        db.close()
        logger.info(f"DuckDB dim_players synchronized with {count} rows.")


def run_phase_1():
    resolver = EntityResolver()
    resolver.load_existing_dimension()
    resolver.load_league_active_rosters()
    resolver.load_resolved_sheet_players()
    resolver.link_transition_players()
    resolver.link_cached_micro_players()
    resolver.export_canonical_dimension()


if __name__ == "__main__":
    run_phase_1()
