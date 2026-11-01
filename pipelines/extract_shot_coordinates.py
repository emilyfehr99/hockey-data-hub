"""
NHL Shot Coordinates Extractor
==============================
Parses shot-level coordinate data, shot types (wrist, slap, snap, backhand),
rebound flags, and rush flags from local PBP shot streams into Parquet.
"""

from __future__ import annotations

import glob
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("extract_shot_coordinates")

BASE_DIR = Path(__file__).resolve().parent.parent
PARQUET_BASE = BASE_DIR / "data" / "parquet"
DIM_PLAYERS_PATH = PARQUET_BASE / "dim_players.parquet"
GOALIE_HUB_DATA = Path("/Users/emilyfehr8/CascadeProjects/nhl-goalie-hub/data")


def run_shot_extraction():
    if not GOALIE_HUB_DATA.exists():
        logger.warning(f"Goalie hub data not found at {GOALIE_HUB_DATA}")
        return

    # Load player lookup
    nhl_to_uuid: Dict[int, str] = {}
    if DIM_PLAYERS_PATH.exists():
        df_p = pd.read_parquet(DIM_PLAYERS_PATH)
        for _, r in df_p.dropna(subset=["nhl_player_id"]).iterrows():
            nhl_to_uuid[int(r["nhl_player_id"])] = str(r["player_uuid"])

    shot_files = sorted(glob.glob(str(GOALIE_HUB_DATA / "pbp-shots-*.jsonl")))
    logger.info(f"Found {len(shot_files)} shot coordinate JSONL files.")

    all_shots = []
    for fpath in shot_files:
        with open(fpath, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    game_obj = json.loads(line)
                    gid = game_obj.get("g")
                    shots = game_obj.get("s", [])

                    for idx, s in enumerate(shots):
                        gl_id = s.get("gl")
                        sh_id = s.get("sh")

                        all_shots.append({
                            "game_id": gid,
                            "shot_index": idx,
                            "period": s.get("pd"),
                            "team_id": s.get("tm"),
                            "shooter_uuid": nhl_to_uuid.get(sh_id),
                            "goalie_uuid": nhl_to_uuid.get(gl_id),
                            "shooter_nhl_id": sh_id,
                            "goalie_nhl_id": gl_id,
                            "coord_x": s.get("x"),
                            "coord_y": s.get("y"),
                            "shot_type": s.get("ty"),
                            "is_goal": bool(s.get("isGoal")),
                            "is_rebound": bool(s.get("rb")),
                            "is_rush": bool(s.get("ru")),
                            "score_state": s.get("sc")
                        })
                except Exception:
                    pass

    if not all_shots:
        logger.info("No shot records extracted.")
        return

    df_shots = pd.DataFrame(all_shots)
    df_shots.sort_values(by=["game_id", "shot_index"], inplace=True)

    out_dir = PARQUET_BASE / "fct_shot_coordinates"
    out_dir.mkdir(parents=True, exist_ok=True)
    df_shots.to_parquet(out_dir / "part-0.parquet", index=False)
    logger.info(f"Saved {len(df_shots):,d} sorted shot coordinates to {out_dir}")


def main():
    run_shot_extraction()


if __name__ == "__main__":
    main()
