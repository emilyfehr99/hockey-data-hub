"""
High-Performance Goal Replay Visualizer Generator
=================================================
Generates a zero-latency, 60fps HTML5 Canvas 2D rink visualization
for any goal event using high-frequency tracking sprites.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
import duckdb
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DUCKDB_PATH = BASE_DIR / "data" / "duckdb" / "hockey_master.duckdb"
SPRITES_PARQUET = BASE_DIR / "data" / "parquet" / "fct_goal_sprites"


def generate_goal_html(game_id: int, event_id: int, output_path: Optional[Path] = None) -> Path:
    if output_path is None:
        output_path = BASE_DIR / "visualizer" / f"goal_{game_id}_{event_id}.html"

    # Query frames from parquet
    con = duckdb.connect()
    sql = f"""
    SELECT 
        frame_index,
        timestamp,
        entity_type,
        player_id,
        sweater_number,
        team_tricode,
        is_scoring_team,
        ROUND(coord_x, 1) AS x,
        ROUND(coord_y, 1) AS y
    FROM read_parquet('{SPRITES_PARQUET}/**/*.parquet')
    WHERE game_id = {game_id} AND event_id = {event_id}
    ORDER BY frame_index, entity_type;
    """
    df = con.execute(sql).df()
    con.close()

    if df.empty:
        raise ValueError(f"No sprite frames found for Game {game_id}, Event {event_id}. Run extract_goal_sprites first.")

    # Group frames into JSON structure
    frames_dict = {}
    teams = list(df["team_tricode"].dropna().unique())
    team1 = teams[0] if len(teams) > 0 else "HOME"
    team2 = teams[1] if len(teams) > 1 else "AWAY"

    for _, r in df.iterrows():
        f_idx = int(r["frame_index"])
        if f_idx not in frames_dict:
            frames_dict[f_idx] = []
        frames_dict[f_idx].append({
            "type": r["entity_type"],
            "num": int(r["sweater_number"]) if pd.notna(r["sweater_number"]) else "",
            "team": r["team_tricode"] if pd.notna(r["team_tricode"]) else "",
            "scoring": bool(r["is_scoring_team"]),
            "x": float(r["x"]),
            "y": float(r["y"])
        })

    frames_json = json.dumps([frames_dict[i] for i in sorted(frames_dict.keys())])

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Goal Visualization: Game {game_id} (Event #{event_id})</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  body {{ background: #0c1017; color: #f0f6fc; display: flex; flex-direction: column; align-items: center; padding: 24px; min-height: 100vh; }}
  .header {{ display: flex; justify-content: space-between; align-items: center; width: 1000px; margin-bottom: 16px; }}
  .title {{ font-size: 20px; font-weight: 700; letter-spacing: -0.5px; }}
  .meta {{ font-size: 13px; color: #8b949e; }}
  .rink-container {{ position: relative; width: 1000px; height: 420px; background: #eef2f7; border-radius: 40px; box-shadow: 0 12px 36px rgba(0,0,0,0.4); overflow: hidden; }}
  canvas {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; }}
  .controls {{ width: 1000px; margin-top: 16px; display: flex; align-items: center; gap: 16px; background: #161b22; padding: 12px 20px; border-radius: 12px; border: 1px solid #30363d; }}
  .btn {{ background: #238636; color: #fff; border: none; padding: 8px 16px; font-weight: 600; font-size: 14px; border-radius: 6px; cursor: pointer; transition: 0.15s; }}
  .btn:hover {{ background: #2ea043; }}
  .btn-secondary {{ background: #21262d; border: 1px solid #30363d; color: #c9d1d9; }}
  .btn-secondary:hover {{ background: #30363d; }}
  .scrubber {{ flex-grow: 1; accent-color: #2ea043; cursor: pointer; }}
  .time-badge {{ font-family: monospace; font-size: 13px; color: #8b949e; min-width: 65px; text-align: right; }}
  .legend {{ display: flex; gap: 20px; font-size: 12px; color: #8b949e; align-items: center; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  .dot-team1 {{ background: #004c97; }}
  .dot-team2 {{ background: #c8102e; }}
  .dot-puck {{ background: #111; box-shadow: 0 0 6px #ffeb3b; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <div class="title">Live Goal Visualization: Game {game_id}</div>
    <div class="meta">10 Hz High-Frequency Tracking • Event #{event_id} • 120 Sensor Frames</div>
  </div>
  <div class="legend">
    <div class="legend-item"><div class="dot dot-team1"></div><span>{team1}</span></div>
    <div class="legend-item"><div class="dot dot-team2"></div><span>{team2}</span></div>
    <div class="legend-item"><div class="dot dot-puck"></div><span>Puck Trajectory</span></div>
  </div>
</div>

<div class="rink-container">
  <canvas id="rinkCanvas" width="2000" height="840"></canvas>
  <canvas id="trailCanvas" width="2000" height="840"></canvas>
  <canvas id="animCanvas" width="2000" height="840"></canvas>
</div>

<div class="controls">
  <button id="playBtn" class="btn">Play</button>
  <button id="resetBtn" class="btn btn-secondary">Restart</button>
  <input type="range" id="scrubber" class="scrubber" min="0" max="119" value="0">
  <span id="timeDisplay" class="time-badge">0.0s / 12.0s</span>
  <button id="speedBtn" class="btn btn-secondary" style="font-size: 12px; padding: 6px 10px;">1.0x</button>
</div>

<script>
const frames = {frames_json};
const totalFrames = frames.length;
const animCanvas = document.getElementById('animCanvas');
const trailCanvas = document.getElementById('trailCanvas');
const rinkCanvas = document.getElementById('rinkCanvas');
const ctx = animCanvas.getContext('2d');
const trailCtx = trailCanvas.getContext('2d');
const rinkCtx = rinkCanvas.getContext('2d');

const playBtn = document.getElementById('playBtn');
const resetBtn = document.getElementById('resetBtn');
const scrubber = document.getElementById('scrubber');
const timeDisplay = document.getElementById('timeDisplay');
const speedBtn = document.getElementById('speedBtn');

let currentFrame = 0;
let isPlaying = false;
let playbackSpeed = 1.0;
let lastTimestamp = 0;
let frameAccumulator = 0;

// Draw standard hockey rink background
function drawRink() {{
  const w = rinkCanvas.width;
  const h = rinkCanvas.height;
  
  rinkCtx.clearRect(0, 0, w, h);
  rinkCtx.fillStyle = '#f8fafc';
  rinkCtx.fillRect(0, 0, w, h);
  
  // Center line (Red)
  rinkCtx.strokeStyle = '#dc2626';
  rinkCtx.lineWidth = 6;
  rinkCtx.beginPath();
  rinkCtx.moveTo(w / 2, 0);
  rinkCtx.lineTo(w / 2, h);
  rinkCtx.stroke();
  
  // Center circle
  rinkCtx.strokeStyle = '#0284c7';
  rinkCtx.lineWidth = 4;
  rinkCtx.beginPath();
  rinkCtx.arc(w / 2, h / 2, h * 0.18, 0, Math.PI * 2);
  rinkCtx.stroke();
  
  // Blue lines
  rinkCtx.strokeStyle = '#0284c7';
  rinkCtx.lineWidth = 8;
  rinkCtx.beginPath();
  rinkCtx.moveTo(w * 0.35, 0);
  rinkCtx.lineTo(w * 0.35, h);
  rinkCtx.moveTo(w * 0.65, 0);
  rinkCtx.lineTo(w * 0.65, h);
  rinkCtx.stroke();
  
  // Goal lines
  rinkCtx.strokeStyle = '#dc2626';
  rinkCtx.lineWidth = 4;
  rinkCtx.beginPath();
  rinkCtx.moveTo(w * 0.08, 0);
  rinkCtx.lineTo(w * 0.08, h);
  rinkCtx.moveTo(w * 0.92, 0);
  rinkCtx.lineTo(w * 0.92, h);
  rinkCtx.stroke();
}}

function toScreen(x, y) {{
  return {{
    x: (x / 2400) * animCanvas.width,
    y: (y / 1000) * animCanvas.height
  }};
}}

function renderFrame(idx) {{
  ctx.clearRect(0, 0, animCanvas.width, animCanvas.height);
  const entities = frames[idx] || [];
  
  let puckPos = null;

  entities.forEach(e => {{
    const pt = toScreen(e.x, e.y);
    if (e.type === 'puck') {{
      puckPos = pt;
      // Draw puck
      ctx.fillStyle = '#111';
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#ffeb3b';
      ctx.lineWidth = 3;
      ctx.stroke();
    }} else {{
      // Player
      const isTeam1 = e.team === '{team1}';
      ctx.fillStyle = isTeam1 ? '#004c97' : '#c8102e';
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, 16, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2.5;
      ctx.stroke();

      // Sweater Number
      if (e.num) {{
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 12px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(e.num, pt.x, pt.y);
      }}
    }}
  }});

  // Draw puck trail
  if (puckPos) {{
    trailCtx.fillStyle = 'rgba(255, 235, 59, 0.25)';
    trailCtx.beginPath();
    trailCtx.arc(puckPos.x, puckPos.y, 3.5, 0, Math.PI * 2);
    trailCtx.fill();
  }}

  scrubber.value = idx;
  timeDisplay.innerText = (idx * 0.1).toFixed(1) + 's / 12.0s';
}}

function animate(timestamp) {{
  if (!lastTimestamp) lastTimestamp = timestamp;
  const delta = (timestamp - lastTimestamp) / 1000;
  lastTimestamp = timestamp;

  if (isPlaying) {{
    frameAccumulator += delta * 10 * playbackSpeed;
    if (frameAccumulator >= 1) {{
      const advance = Math.floor(frameAccumulator);
      currentFrame += advance;
      frameAccumulator -= advance;

      if (currentFrame >= totalFrames) {{
        currentFrame = totalFrames - 1;
        isPlaying = false;
        playBtn.innerText = 'Play';
      }}
      renderFrame(currentFrame);
    }}
  }}
  requestAnimationFrame(animate);
}}

playBtn.addEventListener('click', () => {{
  if (currentFrame >= totalFrames - 1) {{
    currentFrame = 0;
    trailCtx.clearRect(0, 0, trailCanvas.width, trailCanvas.height);
  }}
  isPlaying = !isPlaying;
  playBtn.innerText = isPlaying ? 'Pause' : 'Play';
}});

resetBtn.addEventListener('click', () => {{
  currentFrame = 0;
  trailCtx.clearRect(0, 0, trailCanvas.width, trailCanvas.height);
  renderFrame(0);
}});

scrubber.addEventListener('input', (e) => {{
  currentFrame = parseInt(e.target.value);
  renderFrame(currentFrame);
}});

speedBtn.addEventListener('click', () => {{
  const speeds = [0.5, 1.0, 2.0];
  const nextIdx = (speeds.indexOf(playbackSpeed) + 1) % speeds.length;
  playbackSpeed = speeds[nextIdx];
  speedBtn.innerText = playbackSpeed.toFixed(1) + 'x';
}});

drawRink();
renderFrame(0);
requestAnimationFrame(animate);
</script>
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html_content)

    return output_path


if __name__ == "__main__":
    out = generate_goal_html(2024020008, 347)
    print("Generated goal replay visualizer:", out)
