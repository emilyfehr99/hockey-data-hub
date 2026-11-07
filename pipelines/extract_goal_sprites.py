"""
Goal Tracking Sprite & Trajectory Extractor
===========================================
Extracts 10 Hz high-frequency optical tracking coordinates for goals
(puck trajectory and all on-ice player positions leading up to a goal)
from league gamecenter replay feeds into partitioned Parquet.
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
logger = logging.getLogger("extract_goal_sprites")

BASE_DIR = Path(__file__).resolve().parent.parent
PARQUET_BASE = BASE_DIR / "data" / "parquet"
DIM_PLAYERS_PATH = PARQUET_BASE / "dim_players.parquet"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Referer": "https://www.nhl.com/",
    "Origin": "https://www.nhl.com"
}


def fetch_url(url: str, headers: Dict[str, str], retries: int = 2) -> Optional[Any]:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(0.5)
        except Exception:
            time.sleep(0.5)
    return None


def get_current_season() -> int:
    try:
        url = "https://api-web.nhle.com/v1/schedule/now"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
            for d in data.get("gameWeek", []):
                for g in d.get("games", []):
                    if g.get("season"):
                        return int(g["season"])
    except Exception:
        pass
    import datetime
    now = datetime.datetime.now()
    year = now.year if now.month >= 9 else now.year - 1
    return year * 10000 + (year + 1)


def get_recent_finished_game_ids(limit: int = 5) -> List[int]:
    try:
        url = "https://api-web.nhle.com/v1/schedule/now"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        finished = []
        for d in data.get("gameWeek", []):
            for g in d.get("games", []):
                if g.get("gameState") in ["FINAL", "OFF"] and g.get("id"):
                    finished.append(int(g["id"]))
        return finished[-limit:] if finished else []
    except Exception:
        return []


class GoalSpriteExtractor:
    def __init__(self):
        self.player_map: Dict[int, str] = {}
        self._load_crosswalk()

    def _load_crosswalk(self):
        if DIM_PLAYERS_PATH.exists():
            df_p = pd.read_parquet(DIM_PLAYERS_PATH)
            for _, r in df_p.dropna(subset=["nhl_player_id"]).iterrows():
                self.player_map[int(r["nhl_player_id"])] = str(r["player_uuid"])
            logger.info(f"Loaded {len(self.player_map)} player ID crosswalk records.")

    def extract_game_goals(self, game_id: int) -> List[Dict[str, Any]]:
        """Extract all goal events and their 10 Hz trajectory tracking frames."""
        pbp_url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
        pbp_data = fetch_url(pbp_url, headers={"User-Agent": "Mozilla/5.0"})
        if not pbp_data:
            return []

        season_id = pbp_data.get("season", int(str(game_id)[:4] + str(int(str(game_id)[:4]) + 1)))
        plays = pbp_data.get("plays", [])
        goal_plays = [p for p in plays if p.get("typeDescKey") == "goal"]

        logger.info(f"Game {game_id}: Found {len(goal_plays)} goal events.")
        all_frames: List[Dict[str, Any]] = []

        for goal in goal_plays:
            event_id = goal.get("eventId")
            period = goal.get("periodDescriptor", {}).get("number", 1)
            details = goal.get("details", {})
            scoring_player_id = details.get("scoringPlayerId")
            scoring_team_id = details.get("eventOwnerTeamId")
            sprite_url = goal.get("pptReplayUrl")

            if not sprite_url:
                continue

            # Fetch the high-frequency sprite frames
            sprite_frames = fetch_url(sprite_url, headers=BROWSER_HEADERS)
            if not sprite_frames or not isinstance(sprite_frames, list):
                continue

            for f_idx, frame in enumerate(sprite_frames):
                ts = frame.get("timeStamp")
                on_ice = frame.get("onIce", {})

                for entity_key, entity in on_ice.items():
                    raw_pid = entity.get("playerId")
                    pid = int(raw_pid) if raw_pid and str(raw_pid).isdigit() else None
                    team_abbrev = entity.get("teamAbbrev")
                    sweater = entity.get("sweaterNumber")
                    sweater_num = int(sweater) if sweater and str(sweater).isdigit() else None

                    # Classify entity
                    if str(entity_key) == "1" or not pid:
                        ent_type = "puck"
                    else:
                        ent_type = "skater"

                    is_scoring_side = (entity.get("teamId") == scoring_team_id)

                    all_frames.append({
                        "game_id": game_id,
                        "event_id": event_id,
                        "season_id": season_id,
                        "period": period,
                        "frame_index": f_idx,
                        "timestamp": ts,
                        "entity_type": ent_type,
                        "player_id": pid,
                        "player_uuid": self.player_map.get(pid),
                        "sweater_number": sweater_num,
                        "team_tricode": team_abbrev,
                        "is_scoring_team": is_scoring_side,
                        "coord_x": entity.get("x"),
                        "coord_y": entity.get("y")
                    })

        return all_frames

    def run_games(self, game_ids: List[int], season: int):
        out_dir = PARQUET_BASE / "fct_goal_sprites" / f"season={season}"
        out_file = out_dir / "part-0.parquet"
        existing_df = None
        existing_game_ids = set()
        if out_file.exists():
            try:
                existing_df = pd.read_parquet(out_file)
                if "game_id" in existing_df.columns:
                    existing_game_ids = set(existing_df["game_id"].unique())
            except Exception:
                pass

        pending_game_ids = [gid for gid in game_ids if gid not in existing_game_ids]
        if not pending_game_ids:
            logger.info("All specified games already have goal sprites extracted.")
            return

        all_records = []
        for gid in pending_game_ids:
            records = self.extract_game_goals(gid)
            all_records.extend(records)
            time.sleep(0.2)

        if not all_records and existing_df is None:
            logger.info("No goal sprite frames collected.")
            return

        new_df = pd.DataFrame(all_records) if all_records else pd.DataFrame()
        if existing_df is not None and not existing_df.empty:
            df = pd.concat([existing_df, new_df], ignore_index=True)
            df.drop_duplicates(subset=["game_id", "event_id", "frame_index", "entity_type", "player_id"], keep="last", inplace=True)
        else:
            df = new_df

        if not df.empty:
            df.sort_values(by=["game_id", "event_id", "frame_index", "entity_type"], inplace=True)
            out_dir.mkdir(parents=True, exist_ok=True)
            df.to_parquet(out_file, index=False)
            logger.info(f"Saved {len(df):,d} high-frequency goal sprite frames to {out_dir}")


def main():
    parser = argparse.ArgumentParser(description="Extract Goal Tracking Sprites")
    parser.add_argument("--game-id", type=int, help="Single game ID (e.g. 2024020008)")
    parser.add_argument("--season", default="current", help="Target season (e.g. 20262027 or 'current')")
    parser.add_argument("--recent-games", type=int, default=None, help="Extract goal sprites for N most recent games")
    args = parser.parse_args()

    season = get_current_season() if str(args.season).lower() == "current" else int(args.season)
    extractor = GoalSpriteExtractor()
    if args.game_id:
        extractor.run_games([args.game_id], season=season)
    elif args.recent_games:
        recent = get_recent_finished_game_ids(limit=args.recent_games)
        if recent:
            logger.info(f"Found {len(recent)} recent finished games: {recent}")
            extractor.run_games(recent, season=season)
        else:
            logger.info("No recent finished games found to extract sprites for.")
    else:
        sample_games = [2024020008, 2024020009, 2024020010]
        extractor.run_games(sample_games, season=season)


if __name__ == "__main__":
    main()
