"""
Skater Transition & Playmaking Extractor
========================================
Extracts, unpacks, and sorts micro-tracking data (controlled entries,
carried breakouts, shot assists, and game scores) into Parquet.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("extract_transitions")

BASE_DIR = Path(__file__).resolve().parent.parent
PARQUET_BASE = BASE_DIR / "data" / "parquet"
DIM_PLAYERS_PATH = PARQUET_BASE / "dim_players.parquet"
LOCAL_TRACKING_DB = Path(os.getenv("TRANSITION_DB_PATH", ""))


def run_transition_extraction(target_season: Optional[str] = None):
    if not LOCAL_TRACKING_DB.exists():
        logger.warning(f"Local tracking database not found at {LOCAL_TRACKING_DB}")
        return

    # Load player crosswalk
    player_map: Dict[str, str] = {}
    if DIM_PLAYERS_PATH.exists():
        df_p = pd.read_parquet(DIM_PLAYERS_PATH)
        slug_col = "player_slug"
        for _, r in df_p.dropna(subset=[slug_col]).iterrows():
            player_map[str(r[slug_col])] = str(r["player_uuid"])
        logger.info(f"Loaded {len(player_map)} player slug crosswalk records.")

    conn = sqlite3.connect(LOCAL_TRACKING_DB)
    query = "SELECT slug, name, team, position, season, games, toi_5v5, stats_json FROM players"
    if target_season:
        query += f" WHERE season = '{target_season}'"
    query += " ORDER BY season, team, name;"

    df = pd.read_sql_query(query, conn)
    conn.close()

    if df.empty:
        logger.info("No tracking records found matching criteria.")
        return

    logger.info(f"Processing {len(df)} player records across available seasons...")

    # Unpack stats_json
    records = []
    for _, row in df.iterrows():
        base_record = {
            "player_uuid": player_map.get(row["slug"]),
            "player_slug": row["slug"],
            "player_name": row["name"],
            "team": row["team"],
            "position": row["position"],
            "season": row["season"],
            "games_tracked": row["games"],
            "toi_5v5_minutes": row["toi_5v5"],
        }
        
        # Parse JSON microstats
        stats = {}
        if row["stats_json"]:
            try:
                stats = json.loads(row["stats_json"])
            except Exception:
                pass
        
        merged = {**base_record, **stats}
        records.append(merged)

    unpacked_df = pd.DataFrame(records)

    # Sort deterministically
    unpacked_df.sort_values(by=["season", "team", "player_name"], inplace=True)

    # Group and write by season partition
    for season_val, group_df in unpacked_df.groupby("season"):
        is_playoffs = "p" in str(season_val).lower()
        clean_season = str(season_val).replace("-", "").replace("p", "")
        season_type = "playoffs" if is_playoffs else "regular"
        out_dir = PARQUET_BASE / "fct_skater_transitions" / f"season={clean_season}" / f"type={season_type}"
        out_dir.mkdir(parents=True, exist_ok=True)
        group_df.to_parquet(out_dir / "part-0.parquet", index=False)
        logger.info(f"Saved {len(group_df)} sorted transition records to {out_dir}")


def main():
    parser = argparse.ArgumentParser(description="Extract and Normalize Skater Transitions")
    parser.add_argument("--season", type=str, help="Filter specific season (e.g., 2025-26p)")
    args = parser.parse_args()

    run_transition_extraction(target_season=args.season)


if __name__ == "__main__":
    main()
