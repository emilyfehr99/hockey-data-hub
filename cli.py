"""
Hockey Data Hub CLI
===================
Unified command-line interface to explore, harmonize, and query
hockey tracking data, shot coordinates, and game logs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import duckdb
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DUCKDB_PATH = BASE_DIR / "data" / "duckdb" / "hockey_master.duckdb"
PARQUET_DIR = BASE_DIR / "data" / "parquet"


def get_connection() -> duckdb.DuckDBPyConnection:
    """Connect to master database, automatically initializing tables and views from Parquet if needed."""
    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DUCKDB_PATH))
    if PARQUET_DIR.exists():
        tables = [r[0] for r in conn.execute("SHOW TABLES;").fetchall()]
        dim_file = PARQUET_DIR / "dim_players.parquet"
        if "dim_players" not in tables and dim_file.exists():
            conn.execute(f"CREATE TABLE dim_players AS SELECT * FROM read_parquet('{dim_file}');")
        for p in sorted(PARQUET_DIR.iterdir()):
            if p.is_dir() and list(p.glob("**/*.parquet")):
                conn.execute(f"CREATE OR REPLACE VIEW {p.name} AS SELECT * FROM read_parquet('{p}/**/*.parquet');")
    return conn


def cmd_resolve(args):
    """Run Entity Resolution to build/update dim_players."""
    from pipelines.entity_resolution import run_phase_1
    print("Running Entity Resolution Engine...")
    run_phase_1()
    print("Entity resolution completed successfully.")


def cmd_status(args):
    """Show database summary and row counts across all Parquet datasets and DuckDB views."""
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

    conn = get_connection()
    tables = [r[0] for r in conn.execute("SHOW TABLES;").fetchall()]
    print(f"\nDuckDB Master Views ({DUCKDB_PATH}):")
    for t in tables:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0]
        print(f"  • {t:32s}: {cnt:>8,d} rows")
    conn.close()


def cmd_search(args):
    """Search for a player across all linked IDs, draft details, and career stats."""
    query = args.query.strip().lower()
    conn = get_connection()
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


def cmd_query(args):
    """Run an ad-hoc SQL query against the master database."""
    conn = get_connection()
    try:
        df = conn.execute(args.sql).df()
        print(df.to_string(index=False) if not df.empty else "Query returned 0 rows.")
    except Exception as e:
        print(f"Query Error: {e}")
    finally:
        conn.close()


def cmd_pbp(args):
    """Fetch play-by-play for any game via unified API."""
    import json
    from api import get_pbp, get_events
    if args.events_only:
        df = get_events(args.game_id, args.type)
        if df.empty:
            print(f"No events found for game {args.game_id} in local warehouse.")
        else:
            print(df.to_string(index=False))
        return

    data = get_pbp(args.game_id)
    if args.json_output:
        print(json.dumps(data, indent=2))
    else:
        plays = data.get("plays", [])
        away = data.get("awayTeam", {}).get("abbrev", "AWAY")
        home = data.get("homeTeam", {}).get("abbrev", "HOME")
        score = f"{data.get('awayTeam', {}).get('score', 0)} - {data.get('homeTeam', {}).get('score', 0)}"
        print(f"\n🏒 Game {args.game_id}: {away} @ {home} ({score})")
        print(f"Total plays recorded: {len(plays):,d}")
        goals = [p for p in plays if p.get("typeDescKey") == "goal"]
        if goals:
            print("\nScoring Summary:")
            for g in goals:
                period = g.get("periodDescriptor", {}).get("number", "?")
                time_in = g.get("timeInPeriod", "")
                desc = g.get("details", {}).get("desc", g.get("typeDescKey"))
                print(f"  • P{period} {time_in}: {desc}")


def cmd_serve(args):
    """Launch instant REST API server."""
    from api import serve
    serve(port=args.port, host=args.host)


def cmd_render_goal(args):
    """Generate interactive 60fps HTML5 rink visualizer for a goal event."""
    from visualizer.generate_visualizer import generate_goal_html
    out_path = Path(args.output) if args.output else None
    try:
        res = generate_goal_html(args.game_id, args.event_id, output_path=out_path)
        print(f"Goal replay visualizer generated successfully:")
        print(f"  • File: {res}")
        if args.open:
            import webbrowser
            webbrowser.open(f"file://{res.resolve()}")
    except Exception as e:
        print(f"Error rendering goal visualizer: {e}")


def main():
    parser = argparse.ArgumentParser(description="Hockey Data Hub CLI - Unified Hockey Data Warehouse & API")
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

    # query
    p_query = subparsers.add_parser("query", help="Run SQL query on master database")
    p_query.add_argument("sql", type=str, help="SQL query string")
    p_query.set_defaults(func=cmd_query)

    # pbp
    p_pbp = subparsers.add_parser("pbp", help="Fetch play-by-play for any game ID")
    p_pbp.add_argument("game_id", type=str, help="NHL Game ID (e.g. 2024020001)")
    p_pbp.add_argument("--json", dest="json_output", action="store_true", help="Output full raw JSON")
    p_pbp.add_argument("--events-only", action="store_true", help="Query warehouse normalized events")
    p_pbp.add_argument("--type", type=str, default=None, help="Filter event type (e.g. HIT, GOAL, SHOT)")
    p_pbp.set_defaults(func=cmd_pbp)

    # serve
    p_srv = subparsers.add_parser("serve", help="Start local HTTP REST API server")
    p_srv.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    p_srv.add_argument("--host", type=str, default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    p_srv.set_defaults(func=cmd_serve)

    # render-goal
    p_goal = subparsers.add_parser("render-goal", help="Generate zero-latency 60fps HTML5 rink visualizer for a goal")
    p_goal.add_argument("game_id", type=int, help="Game ID (e.g. 2024020008)")
    p_goal.add_argument("event_id", type=int, help="Event ID (e.g. 347)")
    p_goal.add_argument("--output", "-o", type=str, default=None, help="Output HTML file path")
    p_goal.add_argument("--open", action="store_true", help="Automatically open generated visualizer in browser")
    p_goal.set_defaults(func=cmd_render_goal)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
