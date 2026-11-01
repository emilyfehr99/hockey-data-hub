"""
Event-Level Play-by-Play Extractor
==================================
Compiles and normalizes event-level PBP files (with rink coordinates,
durations, actions, and player tags) into partitioned, sorted Parquet.
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("extract_event_pbp")

BASE_DIR = Path(__file__).resolve().parent.parent
PARQUET_BASE = BASE_DIR / "data" / "parquet"
DIM_PLAYERS_PATH = PARQUET_BASE / "dim_players.parquet"
PBP_SOURCE_DIR = Path(os.getenv("RAW_PBP_DIR", ""))


def normalize_name(text: Optional[str]) -> str:
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", stripped).lower()
    return re.sub(r"\s+", " ", cleaned).strip()


def categorize_action(action: str) -> str:
    act = (action or "").lower()
    if "entri" in act:
        return "entry"
    elif "breakout" in act or "exit" in act:
        return "exit"
    elif "shot" in act or "scoring chance" in act:
        return "shot"
    elif "pass" in act:
        return "pass"
    elif "faceoff" in act:
        return "faceoff"
    elif "recover" in act or "retrieval" in act:
        return "retrieval"
    elif "loss" in act or "turnover" in act:
        return "turnover"
    elif "challenge" in act or "battle" in act:
        return "battle"
    return "other"


def run_event_pbp_compiler(max_files: Optional[int] = None):
    if not PBP_SOURCE_DIR.exists():
        logger.warning(f"Raw PBP directory not found at {PBP_SOURCE_DIR}")
        return

    # Load player lookup
    norm_to_uuid: Dict[str, str] = {}
    if DIM_PLAYERS_PATH.exists():
        df_p = pd.read_parquet(DIM_PLAYERS_PATH)
        for _, r in df_p.iterrows():
            u = str(r["player_uuid"])
            fn = normalize_name(r.get("full_name"))
            if fn:
                norm_to_uuid[fn] = u
                parts = fn.split()
                if len(parts) > 1:
                    norm_to_uuid[f"{parts[-1]} {' '.join(parts[:-1])}"] = u

    csv_files = sorted(glob.glob(str(PBP_SOURCE_DIR / "*.csv")))
    if max_files:
        csv_files = csv_files[:max_files]

    logger.info(f"Compiling event PBP records from {len(csv_files)} game files...")

    all_dfs = []
    for fpath in csv_files:
        try:
            match = re.search(r"game_(\d+)_pbp", os.path.basename(fpath))
            match_id = int(match.group(1)) if match else 0

            df = pd.read_csv(fpath)
            if df.empty:
                continue

            df.rename(columns={
                "ID": "event_id",
                "start": "start_sec",
                "end": "end_sec",
                "duration": "duration_sec",
                "player": "player_name",
                "team": "team_name",
                "action": "action_type",
                "half": "period"
            }, inplace=True)

            df["match_id"] = match_id
            df["action_category"] = df["action_type"].apply(categorize_action)

            def lookup_uuid(name_str):
                norm = normalize_name(name_str)
                if norm in norm_to_uuid:
                    return norm_to_uuid[norm]
                if norm:
                    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"pbp:{norm}"))
                return None

            df["player_uuid"] = df["player_name"].apply(lookup_uuid)
            all_dfs.append(df)
        except Exception as e:
            logger.warning(f"Error parsing {fpath}: {e}")

    if not all_dfs:
        logger.info("No valid PBP files compiled.")
        return

    full_pbp = pd.concat(all_dfs, ignore_index=True)
    full_pbp.sort_values(by=["match_id", "event_id"], inplace=True)

    out_dir = PARQUET_BASE / "fct_event_pbp"
    out_dir.mkdir(parents=True, exist_ok=True)
    full_pbp.to_parquet(out_dir / "part-0.parquet", index=False)
    logger.info(f"Successfully compiled {len(full_pbp):,d} event PBP records to {out_dir}")


def main():
    parser = argparse.ArgumentParser(description="Compile Event-Level Play-by-Play")
    parser.add_argument("--max-files", type=int, default=None, help="Limit number of game files")
    args = parser.parse_args()

    run_event_pbp_compiler(max_files=args.max_files)


if __name__ == "__main__":
    main()
