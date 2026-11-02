# Hockey Data Hub

A columnar hockey data warehouse storing over 850,000 unified records across player bios, game logs, shot-level $(x, y)$ coordinates, line combinations, and event-level transition tracking. 

Built on DuckDB and partitioned Apache Parquet for zero-copy SQL querying and low-memory analysis.

---

## What’s Inside

| Table | Format | Description |
| :--- | :--- | :--- |
| **`dim_players`** | Parquet / DuckDB | 4,000+ players with draft pedigree (round, overall pick, team), career totals, and physical vitals. |
| **`fct_skater_game`** | Partitioned Parquet | Game-by-game skater production, TOI (in seconds), shots, hits, blocks, and faceoffs. |
| **`fct_goalie_game`** | Partitioned Parquet | Game-by-game goaltender performance, decisions, shots against, saves, and save percentages. |
| **`fct_shot_coordinates`** | Parquet / DuckDB | 85,000+ individual shots mapped with rink $(x, y)$ coordinates, shot types, rebound flags, and rush flags. |
| **`fct_event_pbp`** | Parquet / DuckDB | 720,000+ event-level micro-actions (controlled entries, breakouts, passes, battles) with durations and locations. |
| **`fct_goal_sprites`** | Partitioned Parquet | 10 Hz high-frequency puck and skater tracking coordinates (120 frames per goal) for 60fps 2D replay rendering. |
| **`fct_skater_transitions`** | Partitioned Parquet | 5v5 transition metrics, entry denial rates, carried breakout percentages, and microstat game scores. |
| **`fct_line_pairings`** | Partitioned Parquet | Forward trios and defensive pairings with 5v5 time on ice and possession rates. |

---

## Quickstart

### 1. Installation
Clone the repo and install dependencies:
```bash
git clone https://github.com/emilyfehr99/hockey-data-hub.git
cd hockey-data-hub

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Using the CLI
Verify database tables and register all views automatically on first run:
```bash
python3 cli.py status
```

Look up any player to view draft pedigree, career marks, and universal IDs:
```bash
python3 cli.py search pastrnak
python3 cli.py search mcdavid
```

Run ad-hoc SQL queries directly from your terminal:
```bash
python3 cli.py query "SELECT full_name, career_goals, career_points FROM dim_players WHERE career_points >= 1000 ORDER BY career_points DESC LIMIT 5;"
```

Generate an interactive 60fps HTML5 rink visualizer for any goal:
```bash
python3 cli.py render-goal 2024020008 347 --open
```

---

## Querying with Python & DuckDB

You can query the database directly in Python with zero memory overhead:

```python
from cli import get_connection

# Connect to master database (auto-registers all views on first load)
con = get_connection()

# Top rush-shot creators with coordinates
query = """
SELECT 
    p.full_name,
    COUNT(*) AS rush_shots,
    SUM(CASE WHEN s.is_goal THEN 1 ELSE 0 END) AS rush_goals,
    ROUND(AVG(s.coord_x), 1) AS avg_shot_depth
FROM fct_shot_coordinates s
JOIN dim_players p ON s.shooter_uuid = p.player_uuid
WHERE s.is_rush = TRUE
GROUP BY p.full_name
HAVING COUNT(*) >= 15
ORDER BY rush_shots DESC
LIMIT 10;
"""

print(con.execute(query).df())
```

Or query any Parquet partition directly without opening DuckDB:
```python
import duckdb

df = duckdb.execute("""
    SELECT player_name, action_category, COUNT(*) as events
    FROM fct_event_pbp
    GROUP BY player_name, action_category
    ORDER BY events DESC
    LIMIT 10;
""").df()
```

---

## Project Ideas You Can Build With This

### 1. Custom Expected Goals (xG) Model
Train an xG classifier (XGBoost or Logistic Regression) using the features in `fct_shot_coordinates`:
* Calculate Euclidean distance to center-net and shot angle from $(x, y)$.
* Factor in shot type (wrist, slap, snap, backhand, tip-in).
* Measure the probability multiplier when shots originate off a rebound (`is_rebound = True`) or rush (`is_rush = True`).

### 2. Neutral Zone Transition & Zone Entry Efficiency
Combine transition tracking from `fct_skater_transitions` with event logs in `fct_event_pbp`:
* Compare carry-in percentage versus dump-and-chase frequency by team.
* Quantify how controlled zone entries correlate with shots generated on the next sequence.

### 3. Forward Line & Defense Pair Chemistry
Analyze unit synergy using `fct_line_pairings`:
* Isolate player results when paired together versus away from each other.
* Identify defensive pairings that suppress high-danger chances despite starting primarily in the defensive zone.

### 4. Goaltender Rebound Control & Danger Profile
Use `fct_shot_coordinates` and `fct_goalie_game` to study goaltending rebound vulnerability:
* Which goaltenders allow the highest percentage of secondary shot attempts within 3 seconds of an initial save?
* Map shot locations on goalies to identify glove-side versus blocker-side finishing tendencies.

### 5. Draft Pick Value & Production Aging Curves
Use `dim_players` and `fct_skater_game` to study draft capital efficiency:
* Plot career points per game as a function of draft pick number (Pick 1 through 224).
* Track scoring trajectories across player ages (18 to 35) to model peak performance windows.

### 6. Zero-Latency 2D Goal Replays & Spatial Heatmaps
Replay any scoring sequence using 10 Hz sensor tracking data stored in `fct_goal_sprites`:
* Track puck trajectory, skater speeds, and defensive spacing leading up to a goal.
* Render standalone 60fps HTML5 Canvas rink animations without external dependencies or cloud latency.

---

## Automated Backfills & Daily Updates

The repository includes GitHub Actions workflows configured to update datasets without burning local machine CPU:
* **Manual Backfill:** Trigger the backfill workflow from the Actions tab for any season range (e.g. `20242025` down to `20072008`).
* **Daily Live Sync:** Runs automatically every morning during the active season to keep game logs, line combos, and player dimension records up to date.
