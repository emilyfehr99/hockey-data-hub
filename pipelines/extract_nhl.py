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

    def run_season(self, season: int, max_games: Optional[int] = None):
        """Extract all games for a season and save to Parquet."""
        games = self.get_season_games(season)
        if max_games:
            games = games[:max_games]

        all_skaters = []
        all_goalies = []

        logger.info(f"Extracting boxscores for {len(games)} games...")
        for i, g in enumerate(games, 1):
            s_rows, g_rows = self.extract_game(g)
            all_skaters.extend(s_rows)
            all_goalies.extend(g_rows)
            if i % 50 == 0 or i == len(games):
                logger.info(f"Progress: {i}/{len(games)} games processed.")
            time.sleep(0.1)

        # Write Parquet partitions
        if all_skaters:
            skater_dir = PARQUET_BASE / "fct_skater_game" / f"season={season}"
            skater_dir.mkdir(parents=True, exist_ok=True)
            df_skaters = pd.DataFrame(all_skaters)
            df_skaters.to_parquet(skater_dir / "part-0.parquet", index=False)
            logger.info(f"Saved {len(df_skaters)} skater game rows to {skater_dir}")

        if all_goalies:
            goalie_dir = PARQUET_BASE / "fct_goalie_game" / f"season={season}"
            goalie_dir.mkdir(parents=True, exist_ok=True)
            df_goalies = pd.DataFrame(all_goalies)
            df_goalies.to_parquet(goalie_dir / "part-0.parquet", index=False)
            logger.info(f"Saved {len(df_goalies)} goalie game rows to {goalie_dir}")


def main():
    parser = argparse.ArgumentParser(description="Extract NHL Official Game Data")
    parser.add_argument("--season", type=int, default=20242025, help="Single season (e.g., 20242025)")
    parser.add_argument("--backfill-from", type=int, help="Start backwards backfill from season (e.g., 20242025)")
    parser.add_argument("--backfill-to", type=int, default=20072008, help="End backwards backfill at season")
    parser.add_argument("--max-games", type=int, default=None, help="Limit games per season (for testing)")
    args = parser.parse_args()

    extractor = NHLExtractor()
    if args.backfill_from:
        curr = args.backfill_from
        while curr >= args.backfill_to:
            logger.info(f"=== Backfilling Season {curr} ===")
            extractor.run_season(curr, max_games=args.max_games)
            # Decrement by 1 year (e.g. 20242025 -> 20232024)
            start_yr = curr // 10000 - 1
            curr = start_yr * 10000 + (start_yr + 1)
    else:
        extractor.run_season(args.season, max_games=args.max_games)


if __name__ == "__main__":
    main()
