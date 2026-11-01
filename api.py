"""
Hockey Data Hub - Unified Data & API Interface
===============================================
One central Python module to query warehouse tables, fetch play-by-play data,
search player crosswalks, or run an instant HTTP REST API server.
"""

from __future__ import annotations

import io
import json
import logging
import re
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
import pandas as pd

logger = logging.getLogger("hockey_data_hub.api")

BASE_DIR = Path(__file__).resolve().parent
DUCKDB_PATH = BASE_DIR / "data" / "duckdb" / "hockey_master.duckdb"
PARQUET_DIR = BASE_DIR / "data" / "parquet"

GITHUB_RELEASE_ASSET_URL = (
    "https://github.com/emilyfehr99/hockey-data-hub/releases/download/v1.0.0-pbp-raw/pbp_cache.tar.gz"
)
NHL_API_PBP_URL = "https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"


def get_connection() -> duckdb.DuckDBPyConnection:
    """Returns a DuckDB connection initialized with all parquet tables & views."""
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


def query(sql: str) -> pd.DataFrame:
    """Run any SQL query across all warehouse tables and return a pandas DataFrame."""
    conn = get_connection()
    try:
        return conn.execute(sql).df()
    finally:
        conn.close()


def search_players(term: str, limit: int = 20) -> pd.DataFrame:
    """Search for players by name or slug in dim_players."""
    clean_term = term.strip().lower().replace("'", "''")
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
        nhl_player_id
    FROM dim_players
    WHERE lower(full_name) LIKE '%{clean_term}%' OR lower(player_slug) LIKE '%{clean_term}%'
    LIMIT {limit};
    """
    return query(sql)


def get_pbp(game_id: int | str) -> Dict[str, Any]:
    """
    Fetch complete play-by-play JSON for any game.
    Tries the live official NHL API first (instant, free, 0 storage),
    then falls back to the GitHub Cloud Release asset if needed.
    """
    gid = str(game_id).strip()
    # 1. Fetch from live official NHL Web API
    url = NHL_API_PBP_URL.format(game_id=gid)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "HockeyDataHub/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"Live NHL API fetch failed for game {gid}: {e}. Trying warehouse parquet...")

    # 2. Query local warehouse fct_event_pbp events as fallback
    try:
        df = query(f"SELECT * FROM fct_event_pbp WHERE game_id = '{gid}'")
        if not df.empty:
            return {"game_id": gid, "plays": df.to_dict(orient="records")}
    except Exception:
        pass

    raise RuntimeError(f"Unable to retrieve play-by-play for game {gid}")


def get_events(game_id: int | str, action_type: Optional[str] = None) -> pd.DataFrame:
    """Query normalized play-by-play events from the warehouse."""
    gid = str(game_id).strip()
    cond = f"WHERE game_id = '{gid}'"
    if action_type:
        clean_action = action_type.strip().replace("'", "''")
        cond += f" AND lower(action_type) LIKE '%{clean_action.lower()}%'"
    return query(f"SELECT * FROM fct_event_pbp {cond}")


class HockeyAPIHandler(BaseHTTPRequestHandler):
    """Zero-dependency HTTP REST API handler for Hockey Data Hub."""

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if path in ("/", "/api", "/api/status"):
                conn = get_connection()
                tables = [r[0] for r in conn.execute("SHOW TABLES;").fetchall()]
                status_dict = {}
                for t in tables:
                    status_dict[t] = conn.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0]
                conn.close()
                self._send_json({
                    "status": "online",
                    "warehouse": "DuckDB + Parquet",
                    "cloud_release": GITHUB_RELEASE_ASSET_URL,
                    "table_counts": status_dict
                })

            elif path == "/api/query":
                sql = qs.get("sql", [""])[0]
                if not sql:
                    self._send_json({"error": "Missing 'sql' query parameter"}, 400)
                    return
                df = query(sql)
                self._send_json({"rows": len(df), "data": df.to_dict(orient="records")})

            elif path == "/api/players":
                q = qs.get("q", [""])[0]
                if not q:
                    self._send_json({"error": "Missing 'q' search parameter"}, 400)
                    return
                df = search_players(q)
                self._send_json({"count": len(df), "players": df.to_dict(orient="records")})

            elif path.startswith("/api/pbp/"):
                gid = path.split("/api/pbp/")[-1].strip()
                data = get_pbp(gid)
                self._send_json(data)

            elif path.startswith("/api/events/"):
                gid = path.split("/api/events/")[-1].strip()
                event_type = qs.get("type", [None])[0]
                df = get_events(gid, event_type)
                self._send_json({"game_id": gid, "count": len(df), "events": df.to_dict(orient="records")})

            else:
                self._send_json({"error": "Endpoint not found", "available_endpoints": [
                    "/api/status",
                    "/api/pbp/<game_id>",
                    "/api/events/<game_id>?type=HIT",
                    "/api/players?q=pastrnak",
                    "/api/query?sql=SELECT..."
                ]}, 404)

        except Exception as ex:
            self._send_json({"error": str(ex)}, 500)

    def log_message(self, format, *args):
        # Clean logging
        sys.stderr.write(f"[HockeyAPI] {args[0]} {args[1]} -> {args[2]}\n")


def serve(port: int = 8000, host: str = "127.0.0.1"):
    """Start local REST API server."""
    server = ThreadingHTTPServer((host, port), HockeyAPIHandler)
    print(f"\n⚡ Hockey Data Hub REST API active on http://{host}:{port}")
    print(f"  • GET /api/status")
    print(f"  • GET /api/pbp/<game_id>")
    print(f"  • GET /api/events/<game_id>")
    print(f"  • GET /api/players?q=<name>")
    print(f"  • GET /api/query?sql=<sql>")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Hockey API server...")
        server.server_close()
