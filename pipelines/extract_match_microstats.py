"""
Match Microstats & Prospect Compiler
====================================
Extracts and normalizes microstats, scoring chances, puck battles,
and junior/prospect metrics into sorted Parquet datasets.
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
logger = logging.getLogger("extract_match_microstats")

BASE_DIR = Path(__file__).resolve().parent.parent
PARQUET_BASE = BASE_DIR / "data" / "parquet"
DIM_PLAYERS_PATH = PARQUET_BASE / "dim_players.parquet"
LOCAL_CACHE_DB = Path(os.getenv("MICROSTATS_CACHE_PATH", ""))

PARAM_MAP = {
    1: "gp",
    17: "toi_seconds",
    50: "toi_sec_alt",
    73: "passes_total",
    74: "passes_accurate",
    84: "shots_on_goal",
    116: "zone_entries",
    121: "scoring_chances",
    197: "scoring_chances_contributed",
    240: "goals_for_on_ice",
    306: "high_danger_scoring_chances"
}


def run_microstats_extraction():
    if not LOCAL_CACHE_DB.exists():
        logger.warning(f"Local microstats cache not found at {LOCAL_CACHE_DB}")
        return

    # Load player crosswalk
    player_map: Dict[int, str] = {}
    if DIM_PLAYERS_PATH.exists():
        df_p = pd.read_parquet(DIM_PLAYERS_PATH)
        target_col = "tracking_player_id"
        for _, r in df_p.dropna(subset=[target_col]).iterrows():
            player_map[int(r[target_col])] = str(r["player_uuid"])
        logger.info(f"Loaded {len(player_map)} player ID -> player_uuid crosswalk records.")

    conn = sqlite3.connect(LOCAL_CACHE_DB)
    c = conn.cursor()
    c.execute("SELECT id, payload_raw, response FROM api_cache WHERE payload_raw LIKE '%players_stat%';")
    rows = c.fetchall()
    conn.close()

    logger.info(f"Parsing match stat records from {len(rows)} cached match responses...")

    extracted_records = []
    for cache_id, payload_raw, resp in rows:
        match_id = None
        if payload_raw:
            try:
                p_json = json.loads(payload_raw)
                match_id = p_json.get("params", {}).get("match_id")
            except Exception:
                pass

        try:
            data = json.loads(resp)
            first_obj = data.get("data", [])[0]
            # Get player stats dictionary regardless of internal key
            stat_dict = next(iter(first_obj.values())) if isinstance(first_obj, dict) else {}
            
            for team_key in ["team1", "team2"]:
                t_info = stat_dict.get(team_key, {})
                t_name = t_info.get("name_eng", "")
                for p in t_info.get("stat", []):
                    pid = p.get("player_id")
                    if not pid:
                        continue
                    
                    row = {
                        "match_id": match_id or cache_id,
                        "tracking_player_id": pid,
                        "player_uuid": player_map.get(pid),
                        "player_name": p.get("name_eng", ""),
                        "sweater_number": p.get("num"),
                        "team_name": t_name,
                        "toi_seconds": 0.0,
                        "shots_on_goal": 0,
                        "scoring_chances": 0,
                        "zone_entries": 0,
                        "passes_total": 0,
                        "passes_accurate": 0,
                        "hd_scoring_chances": 0
                    }

                    for param in p.get("params", []):
                        p_id = param.get("p")
                        val = param.get("v")
                        if val is None:
                            continue
                        
                        if p_id in [17, 50]:
                            row["toi_seconds"] = max(row["toi_seconds"], float(val))
                        elif p_id == 84:
                            row["shots_on_goal"] = int(val)
                        elif p_id == 121:
                            row["scoring_chances"] = int(val)
                        elif p_id == 116:
                            row["zone_entries"] = int(val)
                        elif p_id == 73:
                            row["passes_total"] = int(val)
                        elif p_id == 74:
                            row["passes_accurate"] = int(val)
                        elif p_id == 306:
                            row["hd_scoring_chances"] = int(val)

                    extracted_records.append(row)
        except Exception:
            pass

    if not extracted_records:
        logger.info("No valid player records parsed.")
        return

    df = pd.DataFrame(extracted_records)
    # Sort deterministically
    df.sort_values(by=["team_name", "player_name", "match_id"], inplace=True)

    out_dir = PARQUET_BASE / "fct_match_microstats"
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_dir / "part-0.parquet", index=False)
    logger.info(f"Saved {len(df):,d} sorted match microstat records to {out_dir}")


def main():
    run_microstats_extraction()


if __name__ == "__main__":
    main()
