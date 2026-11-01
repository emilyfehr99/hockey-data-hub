"""
Hockey Data Hub CLI
===================
Unified command-line interface to extract, harmonize, and query
hockey data across NHL API, NST, A3Z, and Hudl/InStat.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import duckdb
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DUCKDB_PATH = BASE_DIR / "data" / "duckdb" / "hockey_master.duckdb"


def cmd_resolve(args):
    """Run Entity Resolution to build/update dim_players."""
    from pipelines.entity_resolution import run_phase_1
    print("Running Entity Resolution Engine...")
    run_phase_1()
    print("Entity resolution completed successfully.")


def cmd_status(args):
    """Show database summary and row counts across all Parquet datasets and DuckDB views."""
    PARQUET_DIR = BASE_DIR / "data" / "parquet"
    print("=== Hockey Data Hub Storage Status ===")
    print(f"Parquet Base: {PARQUET_DIR}")
    
    if PARQUET_DIR.exists():
        for p in sorted(PARQUET_DIR.iterdir()):
            if p.is_file() and p.name.endswith(".parquet"):
                cnt = duckdb.execute(f"SELECT COUNT(*) FROM read_parquet('{p}');").fetchone()[0]
                print(f"  • {p.name:32s}: {cnt:>8,d} rows")
            elif p.is_dir():
                parquet_files = list(p.glob("**/*.parquet"))
                if parquet_files:
                    cnt = duckdb.execute(f"SELECT COUNT(*) FROM read_parquet('{p}/**/*.parquet');").fetchone()[0]
                    print(f"  • {p.name:32s}: {cnt:>8,d} rows ({len(parquet_files)} files)")

    if DUCKDB_PATH.exists():
        print(f"\nDuckDB Master Views ({DUCKDB_PATH}):")
        conn = duckdb.connect(str(DUCKDB_PATH))
        # Ensure views exist for any parquet dirs
        for p in sorted(PARQUET_DIR.iterdir()):
            if p.is_dir() and list(p.glob("**/*.parquet")):
                conn.execute(f"CREATE OR REPLACE VIEW {p.name} AS SELECT * FROM read_parquet('{p}/**/*.parquet');")
        tables = [r[0] for r in conn.execute("SHOW TABLES;").fetchall()]
        for t in tables:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0]
            print(f"  • {t:32s}: {cnt:>8,d} rows")
        conn.close()


def cmd_search(args):
    """Search for a player across all linked IDs, draft details, and career stats."""
    if not DUCKDB_PATH.exists():
        print("Database not initialized. Run resolve first.")
        return

    query = args.query.strip().lower()
    conn = duckdb.connect(str(DUCKDB_PATH))
    sql = f"""
    SELECT 
        full_name,
        primary_position AS pos,
        current_team AS team,
        draft_year,
        draft_round,
        draft_overall,
        draft_team,
        career_gp,
        career_goals,
        career_points,
        headshot_url,
        player_uuid,
        nhl_player_id,
        tracking_player_id,
        player_slug
    FROM dim_players
    WHERE lower(full_name) LIKE '%{query}%' OR lower(player_slug) LIKE '%{query}%'
    LIMIT 10;
    """
    df = conn.execute(sql).df()
    if df.empty:
        print(f"No players found matching '{query}'.")
    else:
        for _, r in df.iterrows():
            print(f"\n★ {r['full_name']} ({r['pos']} - {r['team']})")
            if pd.notna(r['draft_year']):
                print(f"  • Draft: {int(r['draft_year'])} Round {int(r['draft_round'])} (Pick #{int(r['draft_overall'])}) by {r['draft_team']}")
            if pd.notna(r['career_gp']):
                print(f"  • Career Totals: {int(r['career_gp'])} GP | {int(r['career_goals'])} Goals | {int(r['career_points'])} Points")
            if pd.notna(r['headshot_url']):
                print(f"  • Headshot: {r['headshot_url']}")
            print(f"  • IDs: UUID={r['player_uuid']} | League={r['nhl_player_id']} | Tracking={r['tracking_player_id']} | Slug={r['player_slug']}")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Hockey Data Hub CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # resolve
    p_res = subparsers.add_parser("resolve", help="Harmonize players into dim_players")
    p_res.set_defaults(func=cmd_resolve)

    # status
    p_stat = subparsers.add_parser("status", help="Show database table stats")
    p_stat.set_defaults(func=cmd_status)

    # search
    p_search = subparsers.add_parser("search", help="Search players in crosswalk")
    p_search.add_argument("query", type=str, help="Player name or slug")
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
