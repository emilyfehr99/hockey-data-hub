"""
Possession & Danger Rates Extractor
===================================
Extracts advanced 5v5 on-ice possession metrics, danger rates,
line combinations, and goaltender danger splits into Parquet.
Supports backwards historical iteration.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("extract_possession")

BASE_DIR = Path(__file__).resolve().parent.parent
PARQUET_BASE = BASE_DIR / "data" / "parquet"
DIM_PLAYERS_PATH = PARQUET_BASE / "dim_players.parquet"

FEED_BASE_URL = os.getenv("ADVANCED_METRICS_BASE_URL", "")


def toi_to_seconds(toi_str: Any) -> int:
    if not toi_str or pd.isna(toi_str):
        return 0
    s = str(toi_str).strip()
    try:
        if ":" in s:
            parts = s.split(":")
            return int(float(parts[0]) * 60 + float(parts[1]))
        return int(float(s) * 60)
    except Exception:
        return 0


class PossessionExtractor:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("DATA_FEED_KEY", "")
        self.player_map: Dict[int, str] = {}
        self._load_player_crosswalk()

    def _load_player_crosswalk(self):
        if DIM_PLAYERS_PATH.exists():
            df = pd.read_parquet(DIM_PLAYERS_PATH)
            for _, r in df.dropna(subset=["nhl_player_id"]).iterrows():
                self.player_map[int(r["nhl_player_id"])] = str(r["player_uuid"])
            logger.info(f"Loaded {len(self.player_map)} player mappings for possession metrics.")

    def _fetch_table(self, endpoint: str, params: Dict[str, Any]) -> Optional[pd.DataFrame]:
        """Fetch and parse data table from endpoint."""
        if self.api_key:
            params["key"] = self.api_key

        qs = urllib.parse.urlencode(params)
        url = f"{FEED_BASE_URL}/{endpoint}?{qs}"
        
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (HockeyDataHub/1.0)",
                "Accept": "text/html,application/xhtml+xml"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            
            if "No results found" in html:
                return None
            
            tables = pd.read_html(io.StringIO(html))
            if not tables:
                return None
            
            df = max(tables, key=len)
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except Exception as e:
            logger.warning(f"Error fetching {endpoint}: {e}")
            return None

    def extract_skater_on_ice(self, season: int) -> Optional[pd.DataFrame]:
        """Fetch 5v5 On-Ice possession & danger metrics for all skaters."""
        params = {
            "fromseason": str(season),
            "thruseason": str(season),
            "stype": "2",          # Regular season
            "sit": "5v5",          # 5-on-5
            "score": "all",
            "stdoi": "oi",         # On-Ice
            "rate": "n",           # Counts
            "team": "all",
            "pos": "any",
            "loc": "any",
            "gp": "1",             # Min 1 GP
            "gpf": "s"             # Season totals
        }
        logger.info(f"Fetching 5v5 on-ice stats for season {season}...")
        df = self._fetch_table("playerteams.php", params)
        if df is None or df.empty:
            return None
        
        df["season_id"] = season
        df["situation"] = "5v5"
        if "TOI" in df.columns:
            df["toi_seconds"] = df["TOI"].apply(toi_to_seconds)
        
        return df

    def extract_goalie_stats(self, season: int) -> Optional[pd.DataFrame]:
        """Fetch goalie stats with danger breakdown."""
        params = {
            "fromseason": str(season),
            "thruseason": str(season),
            "stype": "2",
            "sit": "5v5",
            "score": "all",
            "stdoi": "g",          # Goalie
            "rate": "n",
            "team": "all",
            "pos": "any",
            "loc": "any",
            "gp": "1",
            "gpf": "s"
        }
        logger.info(f"Fetching goalie danger splits for season {season}...")
        df = self._fetch_table("playerteams.php", params)
        if df is None or df.empty:
            return None
        
        df["season_id"] = season
        if "TOI" in df.columns:
            df["toi_seconds"] = df["TOI"].apply(toi_to_seconds)
        return df

    def extract_line_combinations(self, season: int) -> Optional[pd.DataFrame]:
        """Fetch forward lines and defense pairings."""
        params = {
            "fromseason": str(season),
            "thruseason": str(season),
            "stype": "2",
            "sit": "5v5",
            "score": "all",
            "rate": "n",
            "team": "all",
            "vteam": "all",
            "view": "line",
            "loc": "any",
            "gpfilt": "none",
            "strict": "incl"
        }
        logger.info(f"Fetching line combinations for season {season}...")
        df = self._fetch_table("linestats.php", params)
        if df is None or df.empty:
            return None
        
        df["season_id"] = season
        df["unit_type"] = "forward_line"
        df["situation"] = "5v5"
        if "TOI" in df.columns:
            df["toi_seconds"] = df["TOI"].apply(toi_to_seconds)
        return df

    def run_season(self, season: int):
        """Extract and persist all tables for a season to Parquet."""
        # 1. Skaters
        df_skaters = self.extract_skater_on_ice(season)
        if df_skaters is not None and not df_skaters.empty:
            out_dir = PARQUET_BASE / "fct_skater_possession" / f"season={season}"
            out_dir.mkdir(parents=True, exist_ok=True)
            df_skaters.to_parquet(out_dir / "part-0.parquet", index=False)
            logger.info(f"Saved {len(df_skaters)} skater rows to {out_dir}")
        time.sleep(1.0)

        # 2. Goalies
        df_goalies = self.extract_goalie_stats(season)
        if df_goalies is not None and not df_goalies.empty:
            out_dir = PARQUET_BASE / "fct_goalie_danger" / f"season={season}"
            out_dir.mkdir(parents=True, exist_ok=True)
            df_goalies.to_parquet(out_dir / "part-0.parquet", index=False)
            logger.info(f"Saved {len(df_goalies)} goalie rows to {out_dir}")
        time.sleep(1.0)

        # 3. Lines
        df_lines = self.extract_line_combinations(season)
        if df_lines is not None and not df_lines.empty:
            out_dir = PARQUET_BASE / "fct_line_pairings" / f"season={season}"
            out_dir.mkdir(parents=True, exist_ok=True)
            df_lines.to_parquet(out_dir / "part-0.parquet", index=False)
            logger.info(f"Saved {len(df_lines)} line combo rows to {out_dir}")
        time.sleep(1.0)


def main():
    parser = argparse.ArgumentParser(description="Extract 5v5 Possession & Combination Data")
    parser.add_argument("--season", type=int, default=20242025, help="Single season (e.g. 20242025)")
    parser.add_argument("--backfill-from", type=int, help="Start backwards backfill from season")
    parser.add_argument("--backfill-to", type=int, default=20072008, help="End backwards backfill at season")
    args = parser.parse_args()

    extractor = PossessionExtractor()
    if args.backfill_from:
        curr = args.backfill_from
        while curr >= args.backfill_to:
            logger.info(f"=== Backfilling Season {curr} ===")
            extractor.run_season(curr)
            start_yr = curr // 10000 - 1
            curr = start_yr * 10000 + (start_yr + 1)
    else:
        extractor.run_season(args.season)


if __name__ == "__main__":
    main()
