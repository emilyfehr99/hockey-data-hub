"""
NHL Player Deep Metadata & Draft Enrichment
===========================================
Fetches rich player details (draft details, career totals, headshot URLs,
birth cities) from api-web.nhle.com and enriches dim_players.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional
import duckdb
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("enrich_player_metadata")

BASE_DIR = Path(__file__).resolve().parent.parent
PARQUET_BASE = BASE_DIR / "data" / "parquet"
DIM_PLAYERS_PATH = PARQUET_BASE / "dim_players.parquet"
DUCKDB_PATH = BASE_DIR / "data" / "duckdb" / "hockey_master.duckdb"


def fetch_player_landing(pid: int) -> Optional[Dict[str, Any]]:
    url = f"https://api-web.nhle.com/v1/player/{pid}/landing"
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (HockeyDataHub/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(0.3)
        except Exception:
            time.sleep(0.3)
    return None


def run_enrichment(limit: Optional[int] = None, max_workers: int = 8):
    if not DIM_PLAYERS_PATH.exists():
        logger.error(f"dim_players not found at {DIM_PLAYERS_PATH}")
        return

    df = pd.read_parquet(DIM_PLAYERS_PATH)
    logger.info(f"Loaded {len(df)} players from {DIM_PLAYERS_PATH}")

    # Ensure target columns exist
    new_cols = [
        "headshot_url", "hero_image_url", "birth_city", "birth_state_province",
        "draft_team", "career_gp", "career_goals", "career_assists", "career_points"
    ]
    for col in new_cols:
        if col not in df.columns:
            df[col] = None

    # Filter players with nhl_player_id
    nhl_mask = df["nhl_player_id"].notna()
    nhl_indices = df[nhl_mask].index.tolist()
    if limit:
        nhl_indices = nhl_indices[:limit]

    logger.info(f"Enriching metadata for {len(nhl_indices)} NHL players using {max_workers} threads...")

    def process_idx(idx):
        pid = int(df.at[idx, "nhl_player_id"])
        data = fetch_player_landing(pid)
        if not data:
            return idx, {}

        draft = data.get("draftDetails") or {}
        totals = (data.get("careerTotals") or {}).get("regularSeason") or {}
        
        info = {
            "headshot_url": data.get("headshot"),
            "hero_image_url": data.get("heroImage"),
            "birth_city": (data.get("birthCity") or {}).get("default"),
            "birth_state_province": (data.get("birthStateProvince") or {}).get("default"),
            "draft_year": draft.get("year"),
            "draft_round": draft.get("round"),
            "draft_overall": draft.get("overallPick"),
            "draft_team": draft.get("teamAbbrev"),
            "career_gp": totals.get("gamesPlayed"),
            "career_goals": totals.get("goals"),
            "career_assists": totals.get("assists"),
            "career_points": totals.get("points")
        }
        return idx, info

    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {executor.submit(process_idx, idx): idx for idx in nhl_indices}
        for future in concurrent.futures.as_completed(future_to_idx):
            idx, res = future.result()
            for k, v in res.items():
                if v is not None:
                    df.at[idx, k] = v
            completed += 1
            if completed % 100 == 0 or completed == len(nhl_indices):
                logger.info(f"Enriched {completed}/{len(nhl_indices)} players...")

    # Save enriched parquet
    df.to_parquet(DIM_PLAYERS_PATH, index=False)
    logger.info(f"Saved enriched dim_players to {DIM_PLAYERS_PATH}")

    # Synchronize DuckDB
    if DUCKDB_PATH.exists():
        conn = duckdb.connect(str(DUCKDB_PATH))
        conn.execute("DROP TABLE IF EXISTS dim_players;")
        conn.execute(f"CREATE TABLE dim_players AS SELECT * FROM read_parquet('{DIM_PLAYERS_PATH}');")
        conn.close()
        logger.info("Synchronized DuckDB dim_players table.")


def main():
    parser = argparse.ArgumentParser(description="Enrich Player Metadata")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of players to enrich")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent HTTP worker threads")
    args = parser.parse_args()

    run_enrichment(limit=args.limit, max_workers=args.workers)


if __name__ == "__main__":
    main()
