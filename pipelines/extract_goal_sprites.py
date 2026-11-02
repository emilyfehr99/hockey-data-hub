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
        all_records = []
        for gid in game_ids:
            records = self.extract_game_goals(gid)
            all_records.extend(records)
            time.sleep(0.2)

        if not all_records:
            logger.info("No goal sprite frames collected.")
            return

        df = pd.DataFrame(all_records)
        df.sort_values(by=["game_id", "event_id", "frame_index", "entity_type"], inplace=True)

        out_dir = PARQUET_BASE / "fct_goal_sprites" / f"season={season}"
        out_dir.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out_dir / "part-0.parquet", index=False)
        logger.info(f"Saved {len(df):,d} high-frequency goal sprite frames to {out_dir}")


def main():
    parser = argparse.ArgumentParser(description="Extract Goal Tracking Sprites")
    parser.add_argument("--game-id", type=int, help="Single game ID (e.g. 2024020008)")
    parser.add_argument("--season", type=int, default=20242025, help="Target season")
    args = parser.parse_args()

    extractor = GoalSpriteExtractor()
    if args.game_id:
        extractor.run_games([args.game_id], season=args.season)
    else:
        # Default sample games
        sample_games = [2024020008, 2024020009, 2024020010]
        extractor.run_games(sample_games, season=args.season)


if __name__ == "__main__":
    main()
