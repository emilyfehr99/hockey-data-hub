"""
NHL Official API Game Extractor
===============================
Extracts game-by-game boxscores and player stats (skaters & goalies)
directly from api-web.nhle.com and writes partitioned Parquet files.
Supports backwards historical iteration.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("extract_nhl")

BASE_DIR = Path(__file__).resolve().parent.parent
PARQUET_BASE = BASE_DIR / "data" / "parquet"
DIM_PLAYERS_PATH = PARQUET_BASE / "dim_players.parquet"

NHL_TEAMS = [
    "ANA", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL",
    "DAL", "DET", "EDM", "FLA", "LAK", "MIN", "MTL", "NJD",
    "NSH", "NYI", "NYR", "OTT", "PHI", "PIT", "SEA", "SJS",
    "STL", "TBL", "TOR", "UTA", "VAN", "VGK", "WPG", "WSH"
]


def toi_to_seconds(toi_str: Optional[str]) -> int:
    """Convert MM:SS string to integer seconds."""
    if not toi_str or not isinstance(toi_str, str):
        return 0
    try:
        parts = toi_str.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(float(toi_str))
    except Exception:
        return 0


def get_current_season() -> int:
    """Detect current active NHL season dynamically."""
    try:
        url = "https://api-web.nhle.com/v1/schedule/now"
        data = fetch_json(url)
        if data:
            gw = data.get("gameWeek", [])
            for d in gw:
                for g in d.get("games", []):
                    if g.get("season"):
                        return int(g["season"])
    except Exception:
        pass
    import datetime
    now = datetime.datetime.now()
    year = now.year if now.month >= 9 else now.year - 1
    return year * 10000 + (year + 1)


def fetch_json(url: str, retries: int = 3, delay: float = 0.5) -> Optional[Dict[str, Any]]:
    """Polite HTTP fetch with retries and exponential backoff."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (HockeyDataHub/1.0; mailto:contact@hockeydatahub.org)"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(delay * (2 ** attempt))
        except Exception:
            time.sleep(delay * (2 ** attempt))
    return None


class NHLExtractor:
    def __init__(self):
        self.player_map: Dict[int, str] = {}
        self._load_player_crosswalk()

    def _load_player_crosswalk(self):
        if DIM_PLAYERS_PATH.exists():
            df = pd.read_parquet(DIM_PLAYERS_PATH)
            for _, r in df.dropna(subset=["nhl_player_id"]).iterrows():
                self.player_map[int(r["nhl_player_id"])] = str(r["player_uuid"])
            logger.info(f"Loaded {len(self.player_map)} NHL ID -> UUID mappings.")

    def get_season_games(self, season: int) -> List[Dict[str, Any]]:
        """Retrieve all regular season and playoff games for a given season."""
        logger.info(f"Gathering game list for season {season}...")
        seen_games = {}
        
        # Pull team schedules across a representative set of teams
        for team in NHL_TEAMS[:10]:  # 10 teams cover almost all league games
            url = f"https://api-web.nhle.com/v1/club-schedule-season/{team}/{season}"
            data = fetch_json(url)
            if not data:
                continue
            for g in data.get("games", []):
                gid = g.get("id")
                # gameType 2 = regular season, 3 = playoffs
                if gid and g.get("gameType") in [2, 3] and g.get("gameState") in ["FINAL", "OFF"]:
                    seen_games[gid] = {
                        "game_id": gid,
                        "season_id": season,
                        "game_date": g.get("gameDate"),
                        "home_team": g.get("homeTeam", {}).get("abbrev"),
                        "away_team": g.get("awayTeam", {}).get("abbrev")
                    }
            time.sleep(0.2)

        games_list = sorted(seen_games.values(), key=lambda x: x["game_id"])
        logger.info(f"Found {len(games_list)} finished games for season {season}.")
        return games_list

    def extract_game(self, game_info: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Extract skater and goalie records for a single game."""
        gid = game_info["game_id"]
        season = game_info["season_id"]
        gdate = game_info["game_date"]
        url = f"https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore"
        data = fetch_json(url)
        if not data:
            return [], []

        player_by_game = data.get("playerByGameStats", {})
        skater_rows = []
        goalie_rows = []

        for side in ["awayTeam", "homeTeam"]:
            team_info = player_by_game.get(side, {})
            team_code = data.get(side, {}).get("abbrev", "")
            opp_side = "homeTeam" if side == "awayTeam" else "awayTeam"
            opp_code = data.get(opp_side, {}).get("abbrev", "")
            is_home = (side == "homeTeam")

            # Skaters (forwards + defense)
            for pos_group in ["forwards", "defense"]:
                for p in team_info.get(pos_group, []):
                    pid = p.get("playerId")
                    if not pid:
                        continue
                    p_uuid = self.player_map.get(pid)
                    toi_sec = toi_to_seconds(p.get("toi"))

                    skater_rows.append({
                        "game_id": gid,
                        "player_uuid": p_uuid,
                        "season_id": season,
                        "game_date": gdate,
                        "team_tricode": team_code,
                        "opponent_tricode": opp_code,
                        "is_home": is_home,
                        "situation": "all",
                        "has_nhl_pbp": True,
                        "toi_seconds": toi_sec,
                        "goals": p.get("goals", 0),
                        "assists": p.get("assists", 0),
                        "points": p.get("points", 0),
                        "shots": p.get("shots", 0),
                        "hits": p.get("hits", 0),
                        "blocks": p.get("blockedShots", 0),
                        "pim": p.get("pim", 0),
                        "faceoff_pct": p.get("faceoffWinningPctg")
                    })

            # Goalies
            for g in team_info.get("goalies", []):
                pid = g.get("playerId")
                if not pid:
                    continue
                p_uuid = self.player_map.get(pid)
                toi_sec = toi_to_seconds(g.get("toi"))
                decision = g.get("decision")

                goalie_rows.append({
                    "game_id": gid,
                    "player_uuid": p_uuid,
                    "season_id": season,
                    "game_date": gdate,
                    "team_tricode": team_code,
                    "opponent_tricode": opp_code,
                    "decision": decision,
                    "toi_seconds": toi_sec,
                    "shots_against": g.get("shotsAgainst", 0),
                    "saves": g.get("saves", 0),
                    "goals_against": g.get("goalsAgainst", 0),
                    "save_pct": g.get("savePctg"),
                    "shutout": (g.get("goalsAgainst", 1) == 0 and toi_sec >= 3600)
                })

        return skater_rows, goalie_rows

    def run_season(self, season: int, max_games: Optional[int] = None, incremental: bool = True):
        """Extract all games for a season and save to Parquet."""
        games = self.get_season_games(season)
        if max_games:
            games = games[:max_games]

        skater_file = PARQUET_BASE / "fct_skater_game" / f"season={season}" / "part-0.parquet"
        goalie_file = PARQUET_BASE / "fct_goalie_game" / f"season={season}" / "part-0.parquet"

        existing_skater_df = None
        existing_goalie_df = None
        synced_game_ids = set()

        if incremental and skater_file.exists():
            try:
                existing_skater_df = pd.read_parquet(skater_file)
                if "game_id" in existing_skater_df.columns:
                    synced_game_ids = set(existing_skater_df["game_id"].unique())
            except Exception as e:
                logger.warning(f"Could not read existing skater parquet: {e}")

        if incremental and goalie_file.exists():
            try:
                existing_goalie_df = pd.read_parquet(goalie_file)
            except Exception as e:
                logger.warning(f"Could not read existing goalie parquet: {e}")

        games_to_fetch = [g for g in games if g["game_id"] not in synced_game_ids]
        if not games_to_fetch:
            logger.info(f"All {len(games)} games for season {season} are already synced.")
            return

        logger.info(f"Syncing {len(games_to_fetch)} new/pending games (out of {len(games)} total games)...")
        all_skaters = []
        all_goalies = []

        for i, g in enumerate(games_to_fetch, 1):
            s_rows, g_rows = self.extract_game(g)
            all_skaters.extend(s_rows)
            all_goalies.extend(g_rows)
            if i % 50 == 0 or i == len(games_to_fetch):
                logger.info(f"Progress: {i}/{len(games_to_fetch)} games processed.")
            time.sleep(0.1)

        # Merge and write Parquet partitions
        if all_skaters or existing_skater_df is not None:
            skater_dir = PARQUET_BASE / "fct_skater_game" / f"season={season}"
            skater_dir.mkdir(parents=True, exist_ok=True)
            new_skater_df = pd.DataFrame(all_skaters) if all_skaters else pd.DataFrame()
            if existing_skater_df is not None and not existing_skater_df.empty:
                df_skaters = pd.concat([existing_skater_df, new_skater_df], ignore_index=True)
                df_skaters.drop_duplicates(subset=["game_id", "player_uuid"], keep="last", inplace=True)
            else:
                df_skaters = new_skater_df

            if not df_skaters.empty:
                df_skaters.to_parquet(skater_dir / "part-0.parquet", index=False)
                logger.info(f"Saved {len(df_skaters)} skater game rows to {skater_dir}")

        if all_goalies or existing_goalie_df is not None:
            goalie_dir = PARQUET_BASE / "fct_goalie_game" / f"season={season}"
            goalie_dir.mkdir(parents=True, exist_ok=True)
            new_goalie_df = pd.DataFrame(all_goalies) if all_goalies else pd.DataFrame()
            if existing_goalie_df is not None and not existing_goalie_df.empty:
                df_goalies = pd.concat([existing_goalie_df, new_goalie_df], ignore_index=True)
                df_goalies.drop_duplicates(subset=["game_id", "player_uuid"], keep="last", inplace=True)
            else:
                df_goalies = new_goalie_df

            if not df_goalies.empty:
                df_goalies.to_parquet(goalie_dir / "part-0.parquet", index=False)
                logger.info(f"Saved {len(df_goalies)} goalie game rows to {goalie_dir}")


def main():
    parser = argparse.ArgumentParser(description="Extract NHL Official Game Data")
    parser.add_argument("--season", default="current", help="Single season (e.g., 20262027 or 'current')")
    parser.add_argument("--backfill-from", help="Start backwards backfill from season (e.g., 'current' or 20262027)")
    parser.add_argument("--backfill-to", type=int, default=20072008, help="End backwards backfill at season")
    parser.add_argument("--max-games", type=int, default=None, help="Limit games per season (for testing)")
    parser.add_argument("--force", action="store_true", help="Force re-extraction of already synced games")
    args = parser.parse_args()

    extractor = NHLExtractor()
    if args.backfill_from:
        curr = get_current_season() if str(args.backfill_from).lower() == "current" else int(args.backfill_from)
        while curr >= args.backfill_to:
            logger.info(f"=== Backfilling Season {curr} ===")
            extractor.run_season(curr, max_games=args.max_games, incremental=not args.force)
            # Decrement by 1 year (e.g. 20242025 -> 20232024)
            start_yr = curr // 10000 - 1
            curr = start_yr * 10000 + (start_yr + 1)
    else:
        target_season = get_current_season() if str(args.season).lower() == "current" else int(args.season)
        extractor.run_season(target_season, max_games=args.max_games, incremental=not args.force)


if __name__ == "__main__":
    main()
