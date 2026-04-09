"""
dashboard.py - Local web dashboard served on localhost:8080.
"""

import json
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

DB_PATH = Path.home() / ".claude" / "usage.db"


def get_dashboard_data(db_path=DB_PATH):
    if not db_path.exists():
        return {"error": "Database not found. Run: claudepulse scan"}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # ── All models (for filter UI) ────────────────────────────────────────────
    model_rows = conn.execute("""
        SELECT COALESCE(model, 'unknown') as model
        FROM turns
        GROUP BY model
        ORDER BY SUM(input_tokens + output_tokens) DESC
    """).fetchall()
    all_models = [r["model"] for r in model_rows]

    # ── Daily per-model, ALL history (client filters by range) ────────────────
    daily_rows = conn.execute("""
        SELECT
            substr(timestamp, 1, 10)   as day,
            COALESCE(model, 'unknown') as model,
            SUM(input_tokens)          as input,
            SUM(output_tokens)         as output,
            SUM(cache_read_tokens)     as cache_read,
            SUM(cache_creation_tokens) as cache_creation,
            COUNT(*)                   as turns
        FROM turns
        GROUP BY day, model
        ORDER BY day, model
    """).fetchall()

    daily_by_model = [{
        "day":            r["day"],
        "model":          r["model"],
        "input":          r["input"] or 0,
        "output":         r["output"] or 0,
        "cache_read":     r["cache_read"] or 0,
        "cache_creation": r["cache_creation"] or 0,
        "turns":          r["turns"] or 0,
    } for r in daily_rows]

    # ── All sessions (client filters by range and model) ──────────────────────
    session_rows = conn.execute("""
        SELECT
            session_id, project_name, first_timestamp, last_timestamp,
            total_input_tokens, total_output_tokens,
            total_cache_read, total_cache_creation, model, turn_count
        FROM sessions
        ORDER BY last_timestamp DESC
    """).fetchall()

    sessions_all = []
    for r in session_rows:
        try:
            t1 = datetime.fromisoformat(r["first_timestamp"].replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(r["last_timestamp"].replace("Z", "+00:00"))
            duration_min = round((t2 - t1).total_seconds() / 60, 1)
        except Exception:
            duration_min = 0
        sessions_all.append({
            "session_id":    r["session_id"][:8],
            "project":       r["project_name"] or "unknown",
            "last":          (r["last_timestamp"] or "")[:16].replace("T", " "),
            "last_date":     (r["last_timestamp"] or "")[:10],
            "duration_min":  duration_min,
            "model":         r["model"] or "unknown",
            "turns":         r["turn_count"] or 0,
            "input":         r["total_input_tokens"] or 0,
            "output":        r["total_output_tokens"] or 0,
            "cache_read":    r["total_cache_read"] or 0,
            "cache_creation": r["total_cache_creation"] or 0,
        })

    # ── Hourly activity heatmap (day-of-week x hour) ───────────────────────────
    # Uses raw turn timestamps. Client can re-aggregate if needed, but we
    # pre-aggregate here to keep the payload small.
    hourly_rows = conn.execute("""
        SELECT
            substr(timestamp, 1, 10)   as day,
            substr(timestamp, 12, 2)   as hour,
            COALESCE(model, 'unknown') as model,
            COUNT(*)                   as turns,
            SUM(input_tokens + output_tokens) as tokens
        FROM turns
        WHERE timestamp IS NOT NULL AND length(timestamp) >= 13
        GROUP BY day, hour, model
    """).fetchall()

    hourly_by_model = [{
        "day":    r["day"],
        "hour":   int(r["hour"]) if r["hour"] is not None else 0,
        "model":  r["model"],
        "turns":  r["turns"] or 0,
        "tokens": r["tokens"] or 0,
    } for r in hourly_rows]

    conn.close()

    return {
        "all_models":      all_models,
        "daily_by_model":  daily_by_model,
        "hourly_by_model": hourly_by_model,
        "sessions_all":    sessions_all,
        "generated_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>claudepulse — Claude Code usage dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  /* Linear design system — dark-mode-native, luminance stacking, indigo-violet accent */
  :root {
    --bg-marketing: #08090a;
    --bg-panel: #0f1011;
    --bg-surface-1: #141516;
    --bg-surface-2: #191a1b;
    --bg-surface-3: #23252a;
    --bg-hover: #28282c;

    --text-primary: #f7f8f8;
    --text-secondary: #d0d6e0;
    --text-tertiary: #8a8f98;
    --text-quaternary: #62666d;

    --accent: #5e6ad2;
    --accent-bright: #7170ff;
    --accent-hover: #828fff;

    --border-subtle: rgba(255,255,255,0.05);
    --border-standard: rgba(255,255,255,0.08);
    --border-strong: rgba(255,255,255,0.12);
    --border-solid: #23252a;

    --surface-ghost: rgba(255,255,255,0.02);
    --surface-subtle: rgba(255,255,255,0.04);
    --surface-raised: rgba(255,255,255,0.05);

    --success: #10b981;

    --font-sans: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
    --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { background: var(--bg-marketing); }
  body {
    color: var(--text-secondary);
    font-family: var(--font-sans);
    font-size: 15px;
    font-weight: 400;
    line-height: 1.60;
    letter-spacing: -0.165px;
    font-feature-settings: "cv01", "ss03";
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    min-height: 100vh;
  }

  header { background: var(--bg-marketing); padding: 28px 32px 20px; display: flex; align-items: center; justify-content: space-between; gap: 24px; flex-wrap: wrap; max-width: 1280px; margin: 0 auto; width: 100%; border-bottom: 1px solid var(--border-subtle); }
  header h1 { font-family: var(--font-sans); font-size: 17px; font-weight: 510; color: var(--text-primary); line-height: 1.0; letter-spacing: -0.165px; display: flex; align-items: center; gap: 10px; }
  header h1 .logo-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-bright); box-shadow: 0 0 12px rgba(113,112,255,0.6); }
  header .meta { color: var(--text-quaternary); font-size: 12px; font-family: var(--font-mono); font-weight: 400; display: flex; align-items: center; gap: 10px; }
  header .meta .pulse-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--success); box-shadow: 0 0 8px rgba(16,185,129,0.5); animation: pulse-fresh 2s ease-in-out infinite; }
  header .meta .pulse-dot.stale { background: #fbbf24; box-shadow: 0 0 8px rgba(251,191,36,0.5); animation: none; }
  header .meta .pulse-dot.failed { background: #f87171; box-shadow: 0 0 8px rgba(248,113,113,0.6); animation: none; }
  header .meta .refresh-btn { background: transparent; border: none; color: var(--text-tertiary); cursor: pointer; font-family: var(--font-mono); font-size: 12px; padding: 2px 6px; border-radius: 4px; transition: color 0.12s, background 0.12s; }
  header .meta .refresh-btn:hover { color: var(--text-primary); background: var(--surface-subtle); }
  @keyframes pulse-fresh { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.55; transform: scale(0.88); } }

  .hero { max-width: 1280px; margin: 0 auto; padding: 80px 32px 64px; }
  .hero-eyebrow { font-family: var(--font-mono); font-size: 12px; color: var(--text-tertiary); margin-bottom: 20px; text-transform: uppercase; letter-spacing: 0.08em; }
  .hero-title { font-family: var(--font-sans); font-size: 56px; font-weight: 510; line-height: 1.0; letter-spacing: -1.232px; color: var(--text-primary); margin-bottom: 20px; font-feature-settings: "cv01", "ss03"; }
  .hero-sub { font-size: 18px; line-height: 1.60; color: var(--text-tertiary); max-width: 640px; margin-bottom: 32px; letter-spacing: -0.165px; }
  .command-block { display: inline-flex; align-items: center; gap: 14px; padding: 14px 20px; border: 1px solid var(--border-standard); border-radius: 8px; background: var(--surface-ghost); font-family: var(--font-mono); font-size: 14px; color: var(--text-primary); }
  .command-block .prompt { color: var(--text-quaternary); user-select: none; }

  #filter-bar-wrap { position: sticky; top: 0; z-index: 20; background: rgba(8,9,10,0.85); backdrop-filter: saturate(140%) blur(14px); -webkit-backdrop-filter: saturate(140%) blur(14px); border-bottom: 1px solid var(--border-subtle); transition: box-shadow 0.2s; }
  #filter-bar-wrap.is-stuck { box-shadow: 0 1px 0 rgba(255,255,255,0.05), 0 8px 24px rgba(0,0,0,0.4); }
  #filter-bar { background: transparent; padding: 14px 32px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; max-width: 1280px; margin: 0 auto; }
  .filter-label { font-size: 12px; font-weight: 510; color: var(--text-tertiary); white-space: nowrap; letter-spacing: -0.13px; text-transform: uppercase; letter-spacing: 0.06em; }
  .filter-sep { width: 1px; height: 20px; background: var(--border-standard); flex-shrink: 0; }
  #model-checkboxes { display: flex; flex-wrap: wrap; gap: 6px; }
  .model-cb-label { display: inline-flex; align-items: center; padding: 5px 12px; border-radius: 9999px; border: 1px solid var(--border-solid); background: transparent; cursor: pointer; font-size: 12px; font-family: var(--font-mono); font-weight: 510; color: var(--text-tertiary); user-select: none; transition: color 0.12s, border-color 0.12s, background 0.12s; }
  .model-cb-label:hover { border-color: var(--border-strong); color: var(--text-secondary); }
  .model-cb-label.checked { background: var(--surface-raised); border-color: var(--border-strong); color: var(--text-primary); }
  .model-cb-label input { display: none; }
  .filter-btn { padding: 5px 14px; border-radius: 6px; border: 1px solid var(--border-standard); background: var(--surface-ghost); color: var(--text-secondary); font-size: 13px; font-weight: 510; cursor: pointer; white-space: nowrap; font-family: var(--font-sans); letter-spacing: -0.13px; transition: background 0.12s, border-color 0.12s; }
  .filter-btn:hover { background: var(--surface-subtle); border-color: var(--border-strong); color: var(--text-primary); }
  .range-group { display: flex; gap: 2px; flex-shrink: 0; padding: 3px; background: var(--surface-ghost); border: 1px solid var(--border-subtle); border-radius: 8px; }
  .range-btn { padding: 5px 12px; background: transparent; border: none; border-radius: 5px; color: var(--text-tertiary); font-size: 12px; font-weight: 510; cursor: pointer; font-family: var(--font-sans); letter-spacing: -0.13px; transition: background 0.12s, color 0.12s; }
  .range-btn:hover { color: var(--text-secondary); }
  .range-btn.active { background: var(--surface-raised); color: var(--text-primary); }

  .container { max-width: 1280px; margin: 0 auto; padding: 48px 32px 80px; }
  .stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 64px; }
  .stat-card { background: var(--surface-ghost); border: 1px solid var(--border-standard); border-radius: 12px; padding: 20px 22px 18px; transition: background 0.12s, border-color 0.12s; }
  .stat-card:hover { background: var(--surface-subtle); border-color: var(--border-strong); }
  .stat-card .label { color: var(--text-tertiary); font-size: 11px; font-weight: 510; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.08em; }
  .stat-card .value { font-family: var(--font-sans); font-size: 28px; font-weight: 510; line-height: 1.0; color: var(--text-primary); letter-spacing: -0.616px; font-feature-settings: "cv01", "ss03"; }
  .stat-card .sub { color: var(--text-quaternary); font-size: 11px; margin-top: 8px; font-family: var(--font-mono); }
  .stat-card .delta { display: inline-flex; align-items: center; gap: 4px; margin-top: 10px; padding: 3px 8px; border-radius: 9999px; font-family: var(--font-mono); font-size: 10px; font-weight: 510; letter-spacing: -0.06px; border: 1px solid var(--border-subtle); background: var(--surface-ghost); }
  .stat-card .delta.up { color: var(--text-secondary); }
  .stat-card .delta.down { color: var(--text-tertiary); }
  .stat-card .delta.flat { color: var(--text-quaternary); }
  .stat-card .delta .arrow { font-size: 10px; line-height: 1; }

  .charts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 64px; }
  .chart-card { background: var(--surface-ghost); border: 1px solid var(--border-standard); border-radius: 12px; padding: 24px; }
  .chart-card.wide { grid-column: 1 / -1; }
  .chart-card.compact { padding-bottom: 18px; }
  .chart-card h2 { font-family: var(--font-sans); font-size: 15px; font-weight: 590; color: var(--text-primary); margin-bottom: 20px; letter-spacing: -0.165px; font-feature-settings: "cv01", "ss03"; }
  .chart-wrap { position: relative; height: 260px; }
  .chart-wrap.tall { height: 340px; }
  .chart-card.compact .chart-wrap { height: 220px; }

  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 10px 14px; font-size: 11px; font-weight: 510; color: var(--text-tertiary); border-bottom: 1px solid var(--border-standard); text-transform: uppercase; letter-spacing: 0.06em; font-family: var(--font-sans); }
  td { padding: 12px 14px; border-bottom: 1px solid var(--border-subtle); font-size: 13px; color: var(--text-secondary); letter-spacing: -0.13px; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: var(--surface-ghost); }
  .model-tag { display: inline-block; padding: 3px 10px; border-radius: 9999px; font-size: 11px; font-family: var(--font-mono); font-weight: 510; background: transparent; border: 1px solid var(--border-solid); color: var(--text-secondary); }
  .cost { color: var(--text-primary); font-family: var(--font-mono); font-weight: 500; }
  .cost-na { color: var(--text-quaternary); font-family: var(--font-mono); font-size: 11px; }
  .num { font-family: var(--font-mono); color: var(--text-secondary); font-weight: 400; }
  .muted { color: var(--text-quaternary); }
  .section-title { font-family: var(--font-sans); font-size: 15px; font-weight: 590; color: var(--text-primary); margin-bottom: 16px; letter-spacing: -0.165px; font-feature-settings: "cv01", "ss03"; }
  .table-card { background: var(--surface-ghost); border: 1px solid var(--border-standard); border-radius: 12px; padding: 20px 20px 12px; margin-bottom: 16px; overflow-x: auto; }
  .table-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
  .table-header .section-title { margin-bottom: 0; }
  .table-tools { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .search-input {
    background: var(--surface-ghost);
    border: 1px solid var(--border-standard);
    border-radius: 6px;
    padding: 6px 12px;
    font-family: var(--font-sans);
    font-size: 13px;
    font-weight: 400;
    color: var(--text-primary);
    letter-spacing: -0.13px;
    min-width: 220px;
    outline: none;
    transition: border-color 0.12s, background 0.12s;
  }
  .search-input::placeholder { color: var(--text-quaternary); }
  .search-input:focus { border-color: var(--border-strong); background: var(--surface-subtle); }
  .export-btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 6px 12px;
    border-radius: 6px;
    border: 1px solid var(--border-standard);
    background: var(--surface-ghost);
    color: var(--text-secondary);
    font-family: var(--font-sans);
    font-size: 12px;
    font-weight: 510;
    cursor: pointer;
    letter-spacing: -0.13px;
    transition: background 0.12s, border-color 0.12s, color 0.12s;
  }
  .export-btn:hover { background: var(--surface-subtle); border-color: var(--border-strong); color: var(--text-primary); }
  .export-btn .icon { font-size: 11px; opacity: 0.7; }

  /* Heatmap */
  .heatmap-wrap { display: flex; flex-direction: column; gap: 7px; padding: 6px 0 2px; position: relative; }
  .heatmap-row { display: grid; grid-template-columns: 36px repeat(24, 1fr); gap: 4px; align-items: center; }
  .heatmap-label { font-family: var(--font-mono); font-size: 11px; color: var(--text-tertiary); text-align: right; padding-right: 6px; font-weight: 400; transition: color 0.12s; }
  .heatmap-label.is-hover { color: var(--text-primary); }
  .heatmap-cell { aspect-ratio: 1; border-radius: 4px; background: #17181b; border: 1px solid rgba(255,255,255,0.06); min-height: 15px; transition: transform 0.12s, box-shadow 0.12s, border-color 0.12s; cursor: pointer; }
  .heatmap-cell.is-hover { transform: scale(1.06); box-shadow: 0 0 0 1px rgba(255,255,255,0.52); border-color: rgba(255,255,255,0.36); z-index: 2; position: relative; }
  .heatmap-cell.is-selected { box-shadow: 0 0 0 1px rgba(255,255,255,0.44), inset 0 0 0 1px rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.32); }
  .heatmap-summary { margin-top: 14px; padding: 10px 14px; border-radius: 8px; background: var(--surface-ghost); border: 1px solid var(--border-subtle); font-family: var(--font-mono); font-size: 11px; color: var(--text-tertiary); letter-spacing: -0.06px; display: flex; flex-wrap: wrap; gap: 18px; }
  .heatmap-summary strong { color: var(--text-primary); font-weight: 500; }
  .heatmap-summary .clear-hour { margin-left: auto; color: var(--accent-bright); cursor: pointer; text-decoration: none; border-bottom: 1px solid rgba(113,112,255,0.4); }
  .heatmap-summary .clear-hour:hover { color: var(--text-primary); border-bottom-color: var(--text-primary); }
  /* Floating tooltip */
  .heatmap-tooltip {
    position: fixed; pointer-events: none; z-index: 50;
    background: var(--bg-surface-2); border: 1px solid var(--border-strong); border-radius: 8px;
    padding: 10px 12px; font-family: var(--font-mono); font-size: 11px; color: var(--text-primary);
    box-shadow: 0 8px 32px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.05) inset;
    transform: translate(-50%, calc(-100% - 10px));
    opacity: 0; transition: opacity 0.08s;
    white-space: nowrap;
    letter-spacing: -0.06px;
  }
  .heatmap-tooltip.visible { opacity: 1; }
  .heatmap-tooltip .tt-label { color: var(--text-tertiary); font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px; display: block; }
  .heatmap-tooltip .tt-val { color: var(--text-primary); font-weight: 500; }
  .heatmap-tooltip .tt-sub { color: var(--text-tertiary); margin-top: 4px; }
  .heatmap-cell[data-level="0"] { background: #17181b; border-color: rgba(255,255,255,0.06); }
  .heatmap-cell[data-level="1"] { background: #3b82f6; border-color: #3b82f6; }  /* sonnet blue */
  .heatmap-cell[data-level="2"] { background: #a78bfa; border-color: #a78bfa; } /* purple */
  .heatmap-cell[data-level="3"] { background: #34d399; border-color: #34d399; }  /* green */
  .heatmap-cell[data-level="4"] { background: #fbbf24; border-color: #fbbf24; }  /* yellow */
  .heatmap-axis { display: grid; grid-template-columns: 36px repeat(24, 1fr); gap: 4px; margin-top: 6px; font-family: var(--font-mono); font-size: 10px; color: var(--text-tertiary); }
  .heatmap-axis span { text-align: center; }
  .heatmap-legend { display: flex; align-items: center; gap: 8px; margin-top: 10px; font-family: var(--font-mono); font-size: 10px; color: var(--text-tertiary); }
  .heatmap-legend .swatches { display: flex; gap: 3px; }
  .heatmap-legend .sw { width: 12px; height: 12px; border-radius: 3px; border: 1px solid var(--border-subtle); }

  /* Empty state */
  .empty-state {
    max-width: 560px; margin: 96px auto; padding: 48px 40px;
    background: var(--surface-ghost); border: 1px solid var(--border-standard);
    border-radius: 16px; text-align: center;
  }
  .empty-state h2 { font-family: var(--font-sans); font-size: 22px; font-weight: 510; letter-spacing: -0.44px; color: var(--text-primary); margin-bottom: 12px; }
  .empty-state p { font-size: 14px; line-height: 1.6; color: var(--text-tertiary); margin-bottom: 20px; letter-spacing: -0.13px; }
  .empty-state .command-block { margin-top: 8px; }

  /* Expandable session rows */
  tbody tr.session-row { cursor: pointer; transition: background 0.12s; }
  tbody tr.session-row.expanded td { background: var(--surface-subtle); }
  tbody tr.detail-row td { padding: 0; border-bottom: 1px solid var(--border-subtle); background: var(--bg-panel); }
  .session-detail { padding: 20px 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px 24px; animation: fade-in 0.18s ease-out; }
  .session-detail .field { display: flex; flex-direction: column; gap: 4px; }
  .session-detail .field .k { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-quaternary); font-weight: 510; }
  .session-detail .field .v { font-size: 13px; color: var(--text-primary); font-family: var(--font-mono); letter-spacing: -0.13px; }
  .session-detail .bar { grid-column: 1 / -1; display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: var(--surface-ghost); border: 1px solid var(--border-subtle); margin-top: 4px; }
  .session-detail .bar > span { display: block; height: 100%; }
  .session-detail .bar .b-input   { background: #3b82f6; }
  .session-detail .bar .b-output  { background: #a78bfa; }
  .session-detail .bar .b-cread   { background: #34d399; }
  .session-detail .bar .b-ccreate { background: #fbbf24; }
  @keyframes fade-in { from { opacity: 0; transform: translateY(-2px); } to { opacity: 1; transform: translateY(0); } }

  /* Keyboard cheatsheet overlay */
  .cheatsheet-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.6); backdrop-filter: blur(4px); z-index: 100; display: none; align-items: center; justify-content: center; animation: fade-in 0.15s ease-out; }
  .cheatsheet-backdrop.open { display: flex; }
  .cheatsheet {
    background: var(--bg-surface-2); border: 1px solid var(--border-standard); border-radius: 14px;
    padding: 28px 32px; min-width: 360px; max-width: 480px;
    box-shadow: 0 24px 80px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.04) inset;
  }
  .cheatsheet h3 { font-family: var(--font-sans); font-size: 16px; font-weight: 590; color: var(--text-primary); letter-spacing: -0.16px; margin-bottom: 16px; font-feature-settings: "cv01", "ss03"; }
  .cheatsheet .rows { display: grid; grid-template-columns: auto 1fr; gap: 10px 18px; align-items: center; }
  .cheatsheet kbd {
    display: inline-block;
    padding: 3px 8px; min-width: 22px; text-align: center;
    background: var(--surface-raised); border: 1px solid var(--border-standard); border-radius: 5px;
    font-family: var(--font-mono); font-size: 11px; font-weight: 500; color: var(--text-primary);
    box-shadow: 0 1px 0 rgba(0,0,0,0.3);
  }
  .cheatsheet .desc { color: var(--text-tertiary); font-size: 13px; letter-spacing: -0.13px; }
  .cheatsheet .hint { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border-subtle); font-size: 11px; color: var(--text-quaternary); font-family: var(--font-mono); text-align: center; }

  footer { border-top: 1px solid var(--border-subtle); padding: 36px 32px; margin-top: 32px; background: var(--bg-marketing); }
  .footer-content { max-width: 1280px; margin: 0 auto; }
  .footer-content p { color: var(--text-quaternary); font-size: 12px; line-height: 1.60; margin-bottom: 6px; letter-spacing: -0.13px; }
  .footer-content p:last-child { margin-bottom: 0; }
  .footer-content a { color: var(--text-secondary); text-decoration: none; border-bottom: 1px solid var(--border-standard); transition: color 0.12s, border-color 0.12s; }
  .footer-content a:hover { color: var(--text-primary); border-bottom-color: var(--border-strong); }

  ::selection { background: rgba(94,106,210,0.35); color: var(--text-primary); }
  :focus-visible { outline: 2px solid var(--accent-bright); outline-offset: 2px; border-radius: 4px; }

  /* Subtle noise/texture on body for depth (inert) */
  body::before {
    content: "";
    position: fixed; inset: 0; pointer-events: none;
    background:
      radial-gradient(1200px 600px at 80% -10%, rgba(94,106,210,0.06), transparent 60%),
      radial-gradient(900px 500px at -10% 30%, rgba(113,112,255,0.04), transparent 60%);
    z-index: 0;
  }
  header, #filter-bar, .hero, .container, footer { position: relative; z-index: 1; }

  @media (max-width: 768px) {
    .charts-grid { grid-template-columns: 1fr; }
    .chart-card.wide { grid-column: 1; }
    header, #filter-bar, .container, footer, .hero { padding-left: 20px; padding-right: 20px; }
    .hero { padding-top: 48px; padding-bottom: 40px; }
    .hero-title { font-size: 36px; letter-spacing: -0.792px; }
    .container { padding-top: 32px; padding-bottom: 48px; }
    header h1 { font-size: 15px; }
  }
</style>
</head>
<body>
<header>
  <h1><span class="logo-dot"></span>claudepulse</h1>
  <div class="meta" id="meta">
    <span class="pulse-dot" id="pulse-dot"></span>
    <span id="meta-text">Loading&hellip;</span>
    <button class="refresh-btn" id="refresh-btn" title="Refresh now (R)">&#x21bb;</button>
  </div>
</header>

<section class="hero">
  <div class="hero-eyebrow">Claude Code &middot; local token ledger</div>
  <h2 class="hero-title">A live pulse<br>on every token.</h2>
  <p class="hero-sub">Claude Code writes detailed usage logs locally — tokens, models, sessions, projects — regardless of your plan. claudepulse reads them and turns them into a dark, focused dashboard. API, Pro, Max.</p>
  <div class="command-block"><span class="prompt">&gt;</span> claudepulse</div>
</section>

<div id="filter-bar-wrap"><div id="filter-bar">
  <div class="filter-label">Models</div>
  <div id="model-checkboxes"></div>
  <button class="filter-btn" onclick="selectAllModels()">All</button>
  <button class="filter-btn" onclick="clearAllModels()">None</button>
  <div class="filter-sep"></div>
  <div class="filter-label">Range</div>
  <div class="range-group">
    <button class="range-btn" data-range="7d"  onclick="setRange('7d')">7d</button>
    <button class="range-btn" data-range="30d" onclick="setRange('30d')">30d</button>
    <button class="range-btn" data-range="90d" onclick="setRange('90d')">90d</button>
    <button class="range-btn" data-range="all" onclick="setRange('all')">All</button>
  </div>
</div></div>

<div class="container">
  <div class="stats-row" id="stats-row"></div>
  <div class="charts-grid">
    <div class="chart-card wide">
      <h2 id="daily-chart-title">Daily Token Usage</h2>
      <div class="chart-wrap tall"><canvas id="chart-daily"></canvas></div>
    </div>
    <div class="chart-card">
      <h2>Cost Efficiency &mdash; $/1K output tokens</h2>
      <div class="chart-wrap"><canvas id="chart-efficiency"></canvas></div>
    </div>
    <div class="chart-card compact">
      <h2>By Model</h2>
      <div class="chart-wrap"><canvas id="chart-model"></canvas></div>
    </div>
    <div class="chart-card wide">
      <h2>Top Projects by Tokens</h2>
      <div class="chart-wrap tall"><canvas id="chart-project"></canvas></div>
    </div>
    <div class="chart-card wide">
      <h2>Activity Heatmap &mdash; when you work</h2>
      <div id="heatmap" class="heatmap-wrap"></div>
      <div class="heatmap-axis" id="heatmap-axis"></div>
      <div class="heatmap-legend">
        <span>Less</span>
        <div class="swatches">
          <div class="sw" data-level="0" style="background: #17181b;"></div>
          <div class="sw" style="background: #3b82f6;"></div>
          <div class="sw" style="background: #a78bfa;"></div>
          <div class="sw" style="background: #34d399;"></div>
          <div class="sw" style="background: #fbbf24;"></div>
        </div>
        <span>More</span>
      </div>
      <div id="heatmap-summary" class="heatmap-summary"></div>
    </div>
  </div>
  <div class="heatmap-tooltip" id="heatmap-tooltip"></div>
  <div class="table-card">
    <div class="table-header">
      <div class="section-title">Recent Sessions</div>
      <div class="table-tools">
        <input id="session-search" class="search-input" type="search" placeholder="Search by project, session, model…" aria-label="Search sessions">
        <button class="export-btn" onclick="exportSessionsCSV()"><span class="icon">&#x2913;</span> Export CSV</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>Session</th><th>Project</th><th>Last Active</th><th>Duration</th>
        <th>Model</th><th>Turns</th><th>Input</th><th>Output</th><th>Est. Cost</th>
      </tr></thead>
      <tbody id="sessions-body"></tbody>
    </table>
  </div>
  <div class="table-card">
    <div class="table-header">
      <div class="section-title">Cost by Model</div>
      <div class="table-tools">
        <button class="export-btn" onclick="exportModelsCSV()"><span class="icon">&#x2913;</span> Export CSV</button>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>Model</th><th>Turns</th><th>Input</th><th>Output</th>
        <th>Cache Read</th><th>Cache Creation</th><th>Est. Cost</th>
      </tr></thead>
      <tbody id="model-cost-body"></tbody>
    </table>
  </div>
</div>

<div class="cheatsheet-backdrop" id="cheatsheet-backdrop">
  <div class="cheatsheet" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts">
    <h3>Keyboard shortcuts</h3>
    <div class="rows">
      <kbd>/</kbd><div class="desc">Focus session search</div>
      <kbd>1</kbd><div class="desc">Range: last 7 days</div>
      <kbd>2</kbd><div class="desc">Range: last 30 days</div>
      <kbd>3</kbd><div class="desc">Range: last 90 days</div>
      <kbd>4</kbd><div class="desc">Range: all time</div>
      <kbd>R</kbd><div class="desc">Refresh now</div>
      <kbd>?</kbd><div class="desc">Toggle this cheatsheet</div>
      <kbd>Esc</kbd><div class="desc">Close / clear search</div>
    </div>
    <div class="hint">Press <kbd>?</kbd> or <kbd>Esc</kbd> to close</div>
  </div>
</div>

<footer>
  <div class="footer-content">
    <p>Cost estimates based on Anthropic API pricing (<a href="https://claude.com/pricing#api" target="_blank">claude.com/pricing#api</a>) as of April 2026. Only models containing <em>opus</em>, <em>sonnet</em>, or <em>haiku</em> in the name are included in cost calculations. Actual costs for Max/Pro subscribers differ from API pricing.</p>
    <p>
      claudepulse &middot;
      <a href="https://github.com/ColdDesertLab/claudepulse" target="_blank">github.com/ColdDesertLab/claudepulse</a>
      &nbsp;&middot;&nbsp;
      License: MIT
    </p>
  </div>
</footer>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let rawData = null;
let selectedModels = new Set();
let selectedRange = '30d';
let charts = {};
let sessionSearchQuery = '';
let lastFilteredSessions = [];
let lastByModel = [];
let expandedSessionId = null;
let lastFetchAt = 0;
let lastFetchOk = true;
let selectedHour = null;  // { dow: 0-6 (Mon=0..Sun=6), hour: 0-23 } or null

// ── Pricing (Anthropic API, April 2026) ────────────────────────────────────
const PRICING = {
  'claude-opus-4-6':   { input: 6.15,  output: 30.75, cache_write: 7.69, cache_read: 0.61 },
  'claude-opus-4-5':   { input: 6.15,  output: 30.75, cache_write: 7.69, cache_read: 0.61 },
  'claude-sonnet-4-6': { input: 3.69,  output: 18.45, cache_write: 4.61, cache_read: 0.37 },
  'claude-sonnet-4-5': { input: 3.69,  output: 18.45, cache_write: 4.61, cache_read: 0.37 },
  'claude-haiku-4-5':  { input: 1.23,  output:  6.15, cache_write: 1.54, cache_read: 0.12 },
  'claude-haiku-4-6':  { input: 1.23,  output:  6.15, cache_write: 1.54, cache_read: 0.12 },
};

function isBillable(model) {
  if (!model) return false;
  const m = model.toLowerCase();
  return m.includes('opus') || m.includes('sonnet') || m.includes('haiku');
}

function getPricing(model) {
  if (!model) return null;
  if (PRICING[model]) return PRICING[model];
  for (const key of Object.keys(PRICING)) {
    if (model.startsWith(key)) return PRICING[key];
  }
  const m = model.toLowerCase();
  if (m.includes('opus'))   return PRICING['claude-opus-4-6'];
  if (m.includes('sonnet')) return PRICING['claude-sonnet-4-6'];
  if (m.includes('haiku'))  return PRICING['claude-haiku-4-5'];
  return null;
}

function calcCost(model, inp, out, cacheRead, cacheCreation) {
  if (!isBillable(model)) return 0;
  const p = getPricing(model);
  if (!p) return 0;
  return (
    inp           * p.input       / 1e6 +
    out           * p.output      / 1e6 +
    cacheRead     * p.cache_read  / 1e6 +
    cacheCreation * p.cache_write / 1e6
  );
}

// ── Formatting ─────────────────────────────────────────────────────────────
function fmt(n) {
  if (n >= 1e9) return (n/1e9).toFixed(2)+'B';
  if (n >= 1e6) return (n/1e6).toFixed(2)+'M';
  if (n >= 1e3) return (n/1e3).toFixed(1)+'K';
  return n.toLocaleString();
}
function fmtCost(c)    { return '$' + c.toFixed(4); }
function fmtCostBig(c) { return '$' + c.toFixed(2); }
function shortModelName(model) {
  const m = String(model || '');
  const match = m.match(/(opus|sonnet|haiku)-(\d)-(\d)/i);
  if (match) {
    const family = match[1][0].toUpperCase() + match[1].slice(1).toLowerCase();
    return `${family} ${match[2]}.${match[3]}`;
  }
  return m.replace(/^claude-/i, '').replace(/-/g, ' ');
}
function compactProjectLabel(project) {
  const p = String(project || '');
  if (p.length <= 38) return p;
  return `${p.slice(0, 12)}…${p.slice(-22)}`;
}

// ── Chart colors ───────────────────────────────────────────────────────────
// Multi-hue data palette — saturated, high-contrast on dark. Mixes cool + warm
// for real category separation. Brand indigo is reserved for chrome (logo, focus).
const TOKEN_COLORS = {
  input:          '#3b82f6',  // sonnet blue
  output:         '#a78bfa',  // violet
  cache_read:     '#34d399',  // emerald
  cache_creation: '#fbbf24',  // amber
};
// Four brand colors only. If there are more than 4 models, the palette cycles.
const MODEL_COLORS = ['#3b82f6', '#a78bfa', '#34d399', '#fbbf24'];
const TICK_COLOR = '#62666d';
const GRID_COLOR = 'rgba(255,255,255,0.05)';

// ── Time range ─────────────────────────────────────────────────────────────
const RANGE_LABELS = { '7d': 'Last 7 Days', '30d': 'Last 30 Days', '90d': 'Last 90 Days', 'all': 'All Time' };
const RANGE_TICKS  = { '7d': 7, '30d': 15, '90d': 13, 'all': 12 };

function rangeDays(range) {
  return range === '7d' ? 7 : range === '30d' ? 30 : range === '90d' ? 90 : null;
}

function getRangeCutoff(range) {
  const days = rangeDays(range);
  if (days == null) return null;
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

// Returns [startISO, endISO) for the window immediately preceding the current one.
// e.g. for 30d: prior window is the 30d window that ended where the current one began.
function getPriorWindow(range) {
  const days = rangeDays(range);
  if (days == null) return null;
  const end = new Date();
  end.setDate(end.getDate() - days);
  const start = new Date(end);
  start.setDate(start.getDate() - days);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function readURLRange() {
  const p = new URLSearchParams(window.location.search).get('range');
  return ['7d', '30d', '90d', 'all'].includes(p) ? p : '30d';
}

function setRange(range) {
  selectedRange = range;
  document.querySelectorAll('.range-btn').forEach(btn =>
    btn.classList.toggle('active', btn.dataset.range === range)
  );
  updateURL();
  applyFilter();
}

// ── Model filter ───────────────────────────────────────────────────────────
function modelPriority(m) {
  const ml = m.toLowerCase();
  if (ml.includes('opus'))   return 0;
  if (ml.includes('sonnet')) return 1;
  if (ml.includes('haiku'))  return 2;
  return 3;
}

function readURLModels(allModels) {
  const param = new URLSearchParams(window.location.search).get('models');
  if (!param) return new Set(allModels.filter(m => isBillable(m)));
  const fromURL = new Set(param.split(',').map(s => s.trim()).filter(Boolean));
  return new Set(allModels.filter(m => fromURL.has(m)));
}

function isDefaultModelSelection(allModels) {
  const billable = allModels.filter(m => isBillable(m));
  if (selectedModels.size !== billable.length) return false;
  return billable.every(m => selectedModels.has(m));
}

function buildFilterUI(allModels) {
  const sorted = [...allModels].sort((a, b) => {
    const pa = modelPriority(a), pb = modelPriority(b);
    return pa !== pb ? pa - pb : a.localeCompare(b);
  });
  selectedModels = readURLModels(allModels);
  const container = document.getElementById('model-checkboxes');
  container.innerHTML = sorted.map(m => {
    const checked = selectedModels.has(m);
    return `<label class="model-cb-label ${checked ? 'checked' : ''}" data-model="${m}">
      <input type="checkbox" value="${m}" ${checked ? 'checked' : ''} onchange="onModelToggle(this)">
      ${m}
    </label>`;
  }).join('');
}

function onModelToggle(cb) {
  const label = cb.closest('label');
  if (cb.checked) { selectedModels.add(cb.value);    label.classList.add('checked'); }
  else            { selectedModels.delete(cb.value); label.classList.remove('checked'); }
  updateURL();
  applyFilter();
}

function selectAllModels() {
  document.querySelectorAll('#model-checkboxes input').forEach(cb => {
    cb.checked = true; selectedModels.add(cb.value); cb.closest('label').classList.add('checked');
  });
  updateURL(); applyFilter();
}

function clearAllModels() {
  document.querySelectorAll('#model-checkboxes input').forEach(cb => {
    cb.checked = false; selectedModels.delete(cb.value); cb.closest('label').classList.remove('checked');
  });
  updateURL(); applyFilter();
}

// ── URL persistence ────────────────────────────────────────────────────────
function updateURL() {
  const allModels = Array.from(document.querySelectorAll('#model-checkboxes input')).map(cb => cb.value);
  const params = new URLSearchParams();
  if (selectedRange !== '30d') params.set('range', selectedRange);
  if (!isDefaultModelSelection(allModels)) params.set('models', Array.from(selectedModels).join(','));
  const search = params.toString() ? '?' + params.toString() : '';
  history.replaceState(null, '', window.location.pathname + search);
}

// ── Aggregation & filtering ────────────────────────────────────────────────
function applyFilter() {
  if (!rawData) return;

  const cutoff = getRangeCutoff(selectedRange);

  // Filter daily rows by model + date range
  const filteredDaily = rawData.daily_by_model.filter(r =>
    selectedModels.has(r.model) && (!cutoff || r.day >= cutoff)
  );

  // Daily chart: aggregate by day
  const dailyMap = {};
  for (const r of filteredDaily) {
    if (!dailyMap[r.day]) dailyMap[r.day] = { day: r.day, input: 0, output: 0, cache_read: 0, cache_creation: 0 };
    const d = dailyMap[r.day];
    d.input          += r.input;
    d.output         += r.output;
    d.cache_read     += r.cache_read;
    d.cache_creation += r.cache_creation;
  }
  const daily = Object.values(dailyMap).sort((a, b) => a.day.localeCompare(b.day));

  // By model: aggregate tokens + turns from daily data
  const modelMap = {};
  for (const r of filteredDaily) {
    if (!modelMap[r.model]) modelMap[r.model] = { model: r.model, input: 0, output: 0, cache_read: 0, cache_creation: 0, turns: 0, sessions: 0 };
    const m = modelMap[r.model];
    m.input          += r.input;
    m.output         += r.output;
    m.cache_read     += r.cache_read;
    m.cache_creation += r.cache_creation;
    m.turns          += r.turns;
  }

  // Filter sessions by model + date range (+ optional heatmap hour filter)
  const filteredSessions = rawData.sessions_all.filter(s => {
    if (!selectedModels.has(s.model)) return false;
    if (cutoff && s.last_date < cutoff) return false;
    if (selectedHour) {
      // s.last is "YYYY-MM-DD HH:MM"
      const d = new Date((s.last || '').replace(' ', 'T') + 'Z');
      if (isNaN(d)) return false;
      if (d.getUTCDay() !== selectedHour.dow) return false;
      if (d.getUTCHours() !== selectedHour.hour) return false;
    }
    return true;
  });

  // Add session counts into modelMap
  for (const s of filteredSessions) {
    if (modelMap[s.model]) modelMap[s.model].sessions++;
  }

  const byModel = Object.values(modelMap).sort((a, b) => (b.input + b.output) - (a.input + a.output));

  // By project: aggregate from filtered sessions
  const projMap = {};
  for (const s of filteredSessions) {
    if (!projMap[s.project]) projMap[s.project] = { project: s.project, input: 0, output: 0, turns: 0 };
    projMap[s.project].input  += s.input;
    projMap[s.project].output += s.output;
    projMap[s.project].turns  += s.turns;
  }
  const byProject = Object.values(projMap).sort((a, b) => (b.input + b.output) - (a.input + a.output));

  // Totals
  const totals = {
    sessions:       filteredSessions.length,
    turns:          byModel.reduce((s, m) => s + m.turns, 0),
    input:          byModel.reduce((s, m) => s + m.input, 0),
    output:         byModel.reduce((s, m) => s + m.output, 0),
    cache_read:     byModel.reduce((s, m) => s + m.cache_read, 0),
    cache_creation: byModel.reduce((s, m) => s + m.cache_creation, 0),
    cost:           byModel.reduce((s, m) => s + calcCost(m.model, m.input, m.output, m.cache_read, m.cache_creation), 0),
  };

  // Prior window totals (for delta indicators). Null when range === 'all'.
  let priorTotals = null;
  const priorWin = getPriorWindow(selectedRange);
  if (priorWin) {
    const priorDaily = rawData.daily_by_model.filter(r =>
      selectedModels.has(r.model) && r.day >= priorWin.start && r.day < priorWin.end
    );
    const pt = { input: 0, output: 0, cache_read: 0, cache_creation: 0, turns: 0, cost: 0 };
    const pmm = {};
    for (const r of priorDaily) {
      pt.input += r.input; pt.output += r.output;
      pt.cache_read += r.cache_read; pt.cache_creation += r.cache_creation;
      pt.turns += r.turns;
      if (!pmm[r.model]) pmm[r.model] = { input: 0, output: 0, cache_read: 0, cache_creation: 0 };
      const m = pmm[r.model];
      m.input += r.input; m.output += r.output;
      m.cache_read += r.cache_read; m.cache_creation += r.cache_creation;
    }
    for (const [model, m] of Object.entries(pmm)) {
      pt.cost += calcCost(model, m.input, m.output, m.cache_read, m.cache_creation);
    }
    const priorSessions = rawData.sessions_all.filter(s =>
      selectedModels.has(s.model) && s.last_date >= priorWin.start && s.last_date < priorWin.end
    );
    pt.sessions = priorSessions.length;
    priorTotals = pt;
  }

  // Update daily chart title
  document.getElementById('daily-chart-title').textContent = 'Daily Token Usage \u2014 ' + RANGE_LABELS[selectedRange];

  lastFilteredSessions = filteredSessions;
  lastByModel = byModel;

  renderStats(totals, priorTotals);
  renderDailyChart(daily);
  renderModelChart(byModel);
  renderProjectChart(byProject);
  renderEfficiencyChart(byModel);
  renderHeatmap();
  renderSessionsTable();
  renderModelCostTable(byModel);
}

// ── Renderers ──────────────────────────────────────────────────────────────
function deltaPill(curr, prior) {
  if (prior == null) return '';
  if (prior === 0 && curr === 0) return '';
  if (prior === 0) return `<div class="delta up"><span class="arrow">\u2191</span>new</div>`;
  const pct = ((curr - prior) / prior) * 100;
  const abs = Math.abs(pct);
  if (abs < 0.5) return `<div class="delta flat"><span class="arrow">\u2192</span>flat</div>`;
  const cls = pct > 0 ? 'up' : 'down';
  const arrow = pct > 0 ? '\u2191' : '\u2193';
  const rounded = abs >= 100 ? Math.round(abs) : abs.toFixed(1);
  return `<div class="delta ${cls}"><span class="arrow">${arrow}</span>${rounded}%</div>`;
}

function renderStats(t, prior) {
  const rangeLabel = RANGE_LABELS[selectedRange].toLowerCase();
  const days = rangeDays(selectedRange);
  const cacheTotal = t.input + t.cache_read;
  const cacheEff = cacheTotal > 0 ? (t.cache_read / cacheTotal) * 100 : 0;
  const monthlyRunRate = days ? (t.cost / days) * 30 : null;

  const priorCacheTotal = prior ? (prior.input + prior.cache_read) : 0;
  const priorCacheEff = prior && priorCacheTotal > 0 ? (prior.cache_read / priorCacheTotal) * 100 : null;

  const stats = [
    { label: 'Sessions',       value: t.sessions.toLocaleString(), sub: rangeLabel,              delta: deltaPill(t.sessions,   prior && prior.sessions) },
    { label: 'Turns',          value: fmt(t.turns),                sub: rangeLabel,              delta: deltaPill(t.turns,      prior && prior.turns) },
    { label: 'Input Tokens',   value: fmt(t.input),                sub: rangeLabel,              delta: deltaPill(t.input,      prior && prior.input) },
    { label: 'Output Tokens',  value: fmt(t.output),               sub: rangeLabel,              delta: deltaPill(t.output,     prior && prior.output) },
    { label: 'Cache Read',     value: fmt(t.cache_read),           sub: 'from prompt cache',     delta: deltaPill(t.cache_read, prior && prior.cache_read) },
    { label: 'Cache Creation', value: fmt(t.cache_creation),       sub: 'writes to prompt cache',delta: deltaPill(t.cache_creation, prior && prior.cache_creation) },
    { label: 'Cache Efficiency', value: cacheEff.toFixed(1) + '%', sub: 'cache reads / (input + cache reads)',
      delta: (priorCacheEff != null)
        ? deltaPill(Math.round(cacheEff * 100), Math.round(priorCacheEff * 100))
        : '' },
    { label: 'Est. Cost',      value: fmtCostBig(t.cost),          sub: 'API pricing, Apr 2026', delta: deltaPill(t.cost,       prior && prior.cost) },
  ];
  if (monthlyRunRate != null) {
    stats.push({
      label: 'Monthly Run Rate',
      value: fmtCostBig(monthlyRunRate),
      sub: 'projected from ' + rangeLabel,
      delta: '',
    });
  }

  document.getElementById('stats-row').innerHTML = stats.map(s => `
    <div class="stat-card">
      <div class="label">${s.label}</div>
      <div class="value">${s.value}</div>
      ${s.sub ? `<div class="sub">${s.sub}</div>` : ''}
      ${s.delta || ''}
    </div>
  `).join('');
}

function renderDailyChart(daily) {
  const ctx = document.getElementById('chart-daily').getContext('2d');
  if (charts.daily) charts.daily.destroy();
  charts.daily = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: daily.map(d => d.day),
      datasets: [
        { label: 'Input',          data: daily.map(d => d.input),          backgroundColor: TOKEN_COLORS.input,          stack: 'tokens' },
        { label: 'Output',         data: daily.map(d => d.output),         backgroundColor: TOKEN_COLORS.output,         stack: 'tokens' },
        { label: 'Cache Read',     data: daily.map(d => d.cache_read),     backgroundColor: TOKEN_COLORS.cache_read,     stack: 'tokens' },
        { label: 'Cache Creation', data: daily.map(d => d.cache_creation), backgroundColor: TOKEN_COLORS.cache_creation, stack: 'tokens' },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: TICK_COLOR, boxWidth: 12, font: { size: 12 } } } },
      scales: {
        x: { ticks: { color: TICK_COLOR, maxTicksLimit: RANGE_TICKS[selectedRange] }, grid: { color: GRID_COLOR } },
        y: { ticks: { color: TICK_COLOR, callback: v => fmt(v) }, grid: { color: GRID_COLOR } },
      }
    }
  });
}

function renderModelChart(byModel) {
  const ctx = document.getElementById('chart-model').getContext('2d');
  if (charts.model) charts.model.destroy();
  if (!byModel.length) { charts.model = null; return; }
  const fullLabels = byModel.map(m => m.model);
  const shortLabels = fullLabels.map(shortModelName);
  charts.model = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: shortLabels,
      datasets: [{ data: byModel.map(m => m.input + m.output), backgroundColor: byModel.map((_, i) => MODEL_COLORS[i % MODEL_COLORS.length]), borderWidth: 2, borderColor: '#08090a' }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      cutout: '68%',
      plugins: {
        legend: {
          position: 'right',
          labels: { color: '#8a8f98', boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: 'circle', padding: 14, font: { size: 12, weight: '500' } }
        },
        tooltip: {
          callbacks: {
            title: (items) => fullLabels[items[0].dataIndex] || items[0].label,
            label: ctx => ` ${fmt(ctx.raw)} tokens`
          }
        }
      }
    }
  });
}

function renderProjectChart(byProject) {
  const top = byProject.slice(0, 8);
  const ctx = document.getElementById('chart-project').getContext('2d');
  if (charts.project) charts.project.destroy();
  if (!top.length) { charts.project = null; return; }
  const fullLabels = top.map(p => p.project);
  const shortLabel = (project) => compactProjectLabel(project);
  charts.project = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: fullLabels.map(shortLabel),
      datasets: [
        { label: 'Input',  data: top.map(p => p.input),  backgroundColor: TOKEN_COLORS.input },
        { label: 'Output', data: top.map(p => p.output), backgroundColor: TOKEN_COLORS.output },
      ]
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: TICK_COLOR, boxWidth: 12, font: { size: 12 } } },
        tooltip: {
          callbacks: {
            title: (items) => fullLabels[items[0].dataIndex] || items[0].label
          }
        }
      },
      scales: {
        x: { ticks: { color: TICK_COLOR, callback: v => fmt(v) }, grid: { color: GRID_COLOR } },
        y: { ticks: { color: '#d0d6e0', font: { size: 13, weight: '500' } }, grid: { color: GRID_COLOR } },
      }
    }
  });
}

function escHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function sessionDetailHTML(s) {
  const cost = calcCost(s.model, s.input, s.output, s.cache_read, s.cache_creation);
  const p = getPricing(s.model);
  const inCost   = p ? (s.input          * p.input       / 1e6)         : 0;
  const outCost  = p ? (s.output         * p.output      / 1e6)         : 0;
  const crCost   = p ? (s.cache_read     * p.cache_read  / 1e6)         : 0;
  const ccCost   = p ? (s.cache_creation * p.cache_write / 1e6)         : 0;
  const total = s.input + s.output + s.cache_read + s.cache_creation;
  const pct = (v) => total > 0 ? (v / total * 100).toFixed(2) + '%' : '0%';
  const avgPerTurn = s.turns > 0 ? Math.round((s.input + s.output) / s.turns) : 0;
  const costPerTurn = s.turns > 0 ? cost / s.turns : 0;
  return `
    <div class="session-detail">
      <div class="field"><span class="k">Session ID</span><span class="v">${escHtml(s.session_id)}…</span></div>
      <div class="field"><span class="k">Project</span><span class="v">${escHtml(s.project)}</span></div>
      <div class="field"><span class="k">Model</span><span class="v">${escHtml(s.model)}</span></div>
      <div class="field"><span class="k">Last Active</span><span class="v">${escHtml(s.last)}</span></div>
      <div class="field"><span class="k">Duration</span><span class="v">${s.duration_min}m</span></div>
      <div class="field"><span class="k">Turns</span><span class="v">${s.turns}</span></div>
      <div class="field"><span class="k">Avg tokens/turn</span><span class="v">${fmt(avgPerTurn)}</span></div>
      <div class="field"><span class="k">Cost/turn</span><span class="v">${isBillable(s.model) && s.turns > 0 ? fmtCost(costPerTurn) : '—'}</span></div>
      <div class="field"><span class="k">Input</span><span class="v">${fmt(s.input)} · ${pct(s.input)}${isBillable(s.model) ? ' · ' + fmtCost(inCost) : ''}</span></div>
      <div class="field"><span class="k">Output</span><span class="v">${fmt(s.output)} · ${pct(s.output)}${isBillable(s.model) ? ' · ' + fmtCost(outCost) : ''}</span></div>
      <div class="field"><span class="k">Cache Read</span><span class="v">${fmt(s.cache_read)} · ${pct(s.cache_read)}${isBillable(s.model) ? ' · ' + fmtCost(crCost) : ''}</span></div>
      <div class="field"><span class="k">Cache Creation</span><span class="v">${fmt(s.cache_creation)} · ${pct(s.cache_creation)}${isBillable(s.model) ? ' · ' + fmtCost(ccCost) : ''}</span></div>
      <div class="field"><span class="k">Total cost</span><span class="v">${isBillable(s.model) ? fmtCost(cost) : 'n/a'}</span></div>
      <div class="bar">
        <span class="b-input"   style="width:${pct(s.input)}"></span>
        <span class="b-output"  style="width:${pct(s.output)}"></span>
        <span class="b-cread"   style="width:${pct(s.cache_read)}"></span>
        <span class="b-ccreate" style="width:${pct(s.cache_creation)}"></span>
      </div>
    </div>`;
}

function toggleSessionRow(id) {
  expandedSessionId = expandedSessionId === id ? null : id;
  renderSessionsTable();
}

function renderSessionsTable() {
  const q = sessionSearchQuery.trim().toLowerCase();
  const matching = q
    ? lastFilteredSessions.filter(s =>
        (s.project || '').toLowerCase().includes(q) ||
        (s.session_id || '').toLowerCase().includes(q) ||
        (s.model || '').toLowerCase().includes(q))
    : lastFilteredSessions;
  const rows = matching.slice(0, 40);
  const body = document.getElementById('sessions-body');
  if (rows.length === 0) {
    body.innerHTML = `<tr><td colspan="9" class="muted" style="text-align:center;padding:32px 16px">No sessions match${q ? ' "' + escHtml(q) + '"' : ''}.</td></tr>`;
    return;
  }
  body.innerHTML = rows.map(s => {
    const cost = calcCost(s.model, s.input, s.output, s.cache_read, s.cache_creation);
    const costCell = isBillable(s.model)
      ? `<td class="cost">${fmtCost(cost)}</td>`
      : `<td class="cost-na">n/a</td>`;
    const isExpanded = expandedSessionId === s.session_id;
    const mainRow = `<tr class="session-row${isExpanded ? ' expanded' : ''}" data-sid="${escHtml(s.session_id)}">
      <td class="muted" style="font-family:var(--font-mono)">${escHtml(s.session_id)}&hellip;</td>
      <td>${escHtml(s.project)}</td>
      <td class="muted">${escHtml(s.last)}</td>
      <td class="muted">${s.duration_min}m</td>
      <td><span class="model-tag">${escHtml(s.model)}</span></td>
      <td class="num">${s.turns}</td>
      <td class="num">${fmt(s.input)}</td>
      <td class="num">${fmt(s.output)}</td>
      ${costCell}
    </tr>`;
    const detailRow = isExpanded
      ? `<tr class="detail-row"><td colspan="9">${sessionDetailHTML(s)}</td></tr>`
      : '';
    return mainRow + detailRow;
  }).join('');
  // Bind click handlers
  body.querySelectorAll('tr.session-row').forEach(tr => {
    tr.addEventListener('click', () => toggleSessionRow(tr.dataset.sid));
  });
}

// ── Cost efficiency chart ──────────────────────────────────────────────────
function renderEfficiencyChart(byModel) {
  const ctx = document.getElementById('chart-efficiency').getContext('2d');
  if (charts.efficiency) charts.efficiency.destroy();

  // Effective $/1K output tokens = total_cost / (output / 1000).
  // Only billable models with >0 output are comparable.
  const rows = byModel
    .filter(m => isBillable(m.model) && (m.output || 0) > 0)
    .map(m => {
      const cost = calcCost(m.model, m.input, m.output, m.cache_read, m.cache_creation);
      return {
        model: m.model,
        rate: (m.output > 0) ? (cost / m.output) * 1000 : 0,
        cost: cost,
      };
    })
    .sort((a, b) => a.rate - b.rate);  // cheapest first

  if (rows.length === 0) {
    // Draw empty state: a faint message in the canvas
    const canvas = ctx.canvas;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#62666d';
    ctx.font = '12px "JetBrains Mono", ui-monospace, monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('No billable output in this window', canvas.width / 2, canvas.height / 2);
    return;
  }

  charts.efficiency = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: rows.map(r => r.model),
      datasets: [{
        label: '$/1K output',
        data: rows.map(r => r.rate),
        backgroundColor: rows.map((_, i) => MODEL_COLORS[i % MODEL_COLORS.length]),
        borderWidth: 0,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => {
              const row = rows[item.dataIndex];
              return `$${row.rate.toFixed(4)} per 1K output  ·  total ${fmtCostBig(row.cost)}`;
            }
          }
        }
      },
      scales: {
        x: {
          ticks: { color: TICK_COLOR, callback: (v) => '$' + (+v).toFixed(3) },
          grid: { color: GRID_COLOR },
        },
        y: {
          ticks: { color: TICK_COLOR, font: { size: 11 } },
          grid: { color: GRID_COLOR },
        }
      }
    }
  });
}

// ── Heatmap ────────────────────────────────────────────────────────────────
const DOW_LABELS     = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const DOW_LABELS_LONG = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];

function renderHeatmap() {
  if (!rawData || !rawData.hourly_by_model) return;
  const cutoff = getRangeCutoff(selectedRange);
  // 7 rows (native Sun=0..Sat=6) x 24 cols. turns + tokens.
  const turnsGrid  = Array.from({length: 7}, () => Array(24).fill(0));
  const tokensGrid = Array.from({length: 7}, () => Array(24).fill(0));
  let totalTurns = 0;
  for (const r of rawData.hourly_by_model) {
    if (!selectedModels.has(r.model)) continue;
    if (cutoff && r.day < cutoff) continue;
    const dow = new Date(r.day + 'T00:00:00Z').getUTCDay();
    if (Number.isNaN(dow)) continue;
    turnsGrid[dow][r.hour]  += r.turns;
    tokensGrid[dow][r.hour] += r.tokens;
    totalTurns += r.turns;
  }
  // UI order: Mon..Sun
  const uiOrder = [1,2,3,4,5,6,0];
  const ordered = uiOrder.map((i, ui) => ({
    label: DOW_LABELS[i],
    labelLong: DOW_LABELS_LONG[i],
    nativeDow: i,
    uiIdx: ui,
    row: turnsGrid[i],
    tokens: tokensGrid[i],
  }));
  let max = 0;
  for (const { row } of ordered) for (const v of row) if (v > max) max = v;
  const level = (v) => {
    if (v <= 0 || max === 0) return 0;
    const f = v / max;
    if (f <= 0.15) return 1;
    if (f <= 0.35) return 2;
    if (f <= 0.65) return 3;
    return 4;
  };

  const wrap = document.getElementById('heatmap');
  wrap.innerHTML = ordered.map(({ label, row, nativeDow }, ui) => `
    <div class="heatmap-row" data-ui="${ui}">
      <div class="heatmap-label" data-ui="${ui}">${label}</div>
      ${row.map((v, h) => {
        const isSelected = selectedHour && selectedHour.dow === nativeDow && selectedHour.hour === h;
        return `<div class="heatmap-cell${isSelected ? ' is-selected' : ''}" data-level="${level(v)}" data-dow="${nativeDow}" data-ui="${ui}" data-hour="${h}" data-turns="${v}" data-tokens="${ordered[ui].tokens[h]}"></div>`;
      }).join('')}
    </div>
  `).join('');

  const axis = document.getElementById('heatmap-axis');
  const hours = Array.from({length: 24}, (_, h) => h);
  axis.innerHTML = '<span></span>' + hours.map(h => `<span>${h % 3 === 0 ? String(h).padStart(2,'0') : ''}</span>`).join('');

  // ── Summary: peak cell + busiest day ────────────────────────────────────
  let peak = { v: 0, dow: null, hour: null, label: '', tokens: 0 };
  const dayTotals = new Array(7).fill(0);
  ordered.forEach(({ label, row, tokens, nativeDow }) => {
    let dayTotal = 0;
    row.forEach((v, h) => {
      dayTotal += v;
      if (v > peak.v) peak = { v, dow: nativeDow, hour: h, label, tokens: tokens[h] };
    });
    dayTotals[nativeDow] = dayTotal;
  });
  const busiestDowNative = dayTotals.indexOf(Math.max(...dayTotals));
  const summary = document.getElementById('heatmap-summary');
  if (totalTurns === 0) {
    summary.innerHTML = `<span>No activity in this window.</span>`;
  } else {
    const hrStr = (h) => String(h).padStart(2, '0') + ':00';
    const peakStr   = peak.v > 0 ? `<strong>${peak.label} ${hrStr(peak.hour)}</strong> &middot; ${fmt(peak.v)} turns &middot; ${fmt(peak.tokens)} tokens` : '—';
    const busyStr   = `<strong>${DOW_LABELS_LONG[busiestDowNative]}</strong> &middot; ${fmt(dayTotals[busiestDowNative])} turns`;
    const totalStr  = `<strong>${fmt(totalTurns)}</strong> turns total`;
    const clearLink = selectedHour ? `<a class="clear-hour" onclick="clearHourFilter()">clear hour filter</a>` : '';
    summary.innerHTML = `
      <span>Peak: ${peakStr}</span>
      <span>Busiest day: ${busyStr}</span>
      <span>${totalStr}</span>
      ${clearLink}
    `;
  }

  // ── Hover: tooltip + focus + row/label highlight ────────────────────────
  const tooltip = document.getElementById('heatmap-tooltip');
  const cells = wrap.querySelectorAll('.heatmap-cell');
  cells.forEach(cell => {
    cell.addEventListener('mouseenter', (e) => {
      cell.classList.add('is-hover');
      const ui = cell.dataset.ui;
      wrap.querySelector(`.heatmap-label[data-ui="${ui}"]`)?.classList.add('is-hover');
      const turns  = +cell.dataset.turns;
      const tokens = +cell.dataset.tokens;
      const dowNative = +cell.dataset.dow;
      const hour = +cell.dataset.hour;
      const dayLong = DOW_LABELS_LONG[dowNative];
      const hrStr = String(hour).padStart(2, '0') + ':00';
      const nextHrStr = String((hour + 1) % 24).padStart(2, '0') + ':00';
      tooltip.innerHTML = `
        <span class="tt-label">${dayLong} &middot; ${hrStr}–${nextHrStr}</span>
        <div><span class="tt-val">${fmt(turns)}</span> turn${turns === 1 ? '' : 's'}</div>
        <div class="tt-sub">${fmt(tokens)} tokens &middot; click to filter sessions</div>
      `;
      tooltip.classList.add('visible');
      positionHeatmapTooltip(e);
    });
    cell.addEventListener('mousemove', positionHeatmapTooltip);
    cell.addEventListener('mouseleave', () => {
      cell.classList.remove('is-hover');
      wrap.querySelectorAll('.heatmap-label.is-hover').forEach(l => l.classList.remove('is-hover'));
      tooltip.classList.remove('visible');
    });
    cell.addEventListener('click', () => {
      const dow = +cell.dataset.dow;
      const hour = +cell.dataset.hour;
      if (selectedHour && selectedHour.dow === dow && selectedHour.hour === hour) {
        selectedHour = null;
      } else {
        selectedHour = { dow, hour };
      }
      applyFilter();
    });
  });
}

function positionHeatmapTooltip(e) {
  const tt = document.getElementById('heatmap-tooltip');
  tt.style.left = e.clientX + 'px';
  tt.style.top  = e.clientY + 'px';
}

function clearHourFilter() {
  selectedHour = null;
  applyFilter();
}

// ── CSV export ─────────────────────────────────────────────────────────────
function downloadCSV(filename, rows) {
  const esc = (v) => {
    if (v == null) return '';
    const s = String(v);
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const csv = rows.map(r => r.map(esc).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function exportSessionsCSV() {
  const header = ['session_id','project','last_active','duration_min','model','turns','input','output','cache_read','cache_creation','est_cost_usd'];
  const rows = [header];
  for (const s of lastFilteredSessions) {
    const cost = isBillable(s.model) ? calcCost(s.model, s.input, s.output, s.cache_read, s.cache_creation) : '';
    rows.push([s.session_id, s.project, s.last, s.duration_min, s.model, s.turns, s.input, s.output, s.cache_read, s.cache_creation, cost === '' ? '' : cost.toFixed(6)]);
  }
  const stamp = new Date().toISOString().slice(0,10);
  downloadCSV(`claudepulse-sessions-${selectedRange}-${stamp}.csv`, rows);
}

function exportModelsCSV() {
  const header = ['model','turns','input','output','cache_read','cache_creation','est_cost_usd'];
  const rows = [header];
  for (const m of lastByModel) {
    const cost = isBillable(m.model) ? calcCost(m.model, m.input, m.output, m.cache_read, m.cache_creation) : '';
    rows.push([m.model, m.turns, m.input, m.output, m.cache_read, m.cache_creation, cost === '' ? '' : cost.toFixed(6)]);
  }
  const stamp = new Date().toISOString().slice(0,10);
  downloadCSV(`claudepulse-models-${selectedRange}-${stamp}.csv`, rows);
}

// ── Empty state ────────────────────────────────────────────────────────────
function renderEmptyState() {
  const container = document.querySelector('.container');
  container.innerHTML = `
    <div class="empty-state">
      <h2>No usage data yet</h2>
      <p>claudepulse scanned your Claude Code logs but didn't find any token usage to chart. Run a session in Claude Code and come back — data appears here automatically.</p>
      <div class="command-block"><span class="prompt">&gt;</span> claudepulse scan</div>
    </div>
  `;
  document.getElementById('filter-bar').style.display = 'none';
}

function renderModelCostTable(byModel) {
  document.getElementById('model-cost-body').innerHTML = byModel.map(m => {
    const cost = calcCost(m.model, m.input, m.output, m.cache_read, m.cache_creation);
    const costCell = isBillable(m.model)
      ? `<td class="cost">${fmtCost(cost)}</td>`
      : `<td class="cost-na">n/a</td>`;
    return `<tr>
      <td><span class="model-tag">${m.model}</span></td>
      <td class="num">${fmt(m.turns)}</td>
      <td class="num">${fmt(m.input)}</td>
      <td class="num">${fmt(m.output)}</td>
      <td class="num">${fmt(m.cache_read)}</td>
      <td class="num">${fmt(m.cache_creation)}</td>
      ${costCell}
    </tr>`;
  }).join('');
}

// ── Refresh state ──────────────────────────────────────────────────────────
function setRefreshState(state, text) {
  const dot = document.getElementById('pulse-dot');
  const metaText = document.getElementById('meta-text');
  if (dot) {
    dot.classList.remove('stale', 'failed');
    if (state === 'stale')  dot.classList.add('stale');
    if (state === 'failed') dot.classList.add('failed');
  }
  if (metaText && text != null) metaText.textContent = text;
}

function updateStaleness() {
  if (!lastFetchAt) return;
  if (!lastFetchOk) { setRefreshState('failed', 'Last refresh failed — click ↻ to retry'); return; }
  const age = (Date.now() - lastFetchAt) / 1000;
  if (age < 45) setRefreshState('fresh', `Live · updated ${Math.floor(age)}s ago`);
  else          setRefreshState('stale', `Stale · updated ${Math.floor(age)}s ago`);
}

// ── Data loading ───────────────────────────────────────────────────────────
async function loadData() {
  try {
    const resp = await fetch('/api/data');
    const d = await resp.json();
    if (d.error) {
      document.body.innerHTML = '<div style="padding:48px;color:#f7f8f8;background:#08090a;min-height:100vh;font-family:Inter,system-ui,sans-serif;font-size:15px;letter-spacing:-0.165px">' + d.error + '</div>';
      return;
    }
    lastFetchAt = Date.now();
    lastFetchOk = true;
    setRefreshState('fresh', 'Live · updated just now');

    const isFirstLoad = rawData === null;
    rawData = d;

    // Empty-state: no models, no daily rows, no sessions
    const hasData = (d.all_models && d.all_models.length)
      || (d.daily_by_model && d.daily_by_model.length)
      || (d.sessions_all && d.sessions_all.length);
    if (!hasData) {
      if (isFirstLoad) renderEmptyState();
      return;
    }

    if (isFirstLoad) {
      // Restore range from URL, mark active button
      selectedRange = readURLRange();
      document.querySelectorAll('.range-btn').forEach(btn =>
        btn.classList.toggle('active', btn.dataset.range === selectedRange)
      );
      // Build model filter (reads URL for model selection too)
      buildFilterUI(d.all_models);
      // Wire session search
      const searchInput = document.getElementById('session-search');
      if (searchInput) {
        searchInput.addEventListener('input', (e) => {
          sessionSearchQuery = e.target.value || '';
          renderSessionsTable();
        });
      }
      // Wire refresh button
      const refreshBtn = document.getElementById('refresh-btn');
      if (refreshBtn) refreshBtn.addEventListener('click', () => loadData());
      // Keyboard shortcuts
      installKeyboardShortcuts();
      // Sticky shadow on filter bar
      installStickyShadow();
    }

    applyFilter();
  } catch(e) {
    console.error(e);
    lastFetchOk = false;
    setRefreshState('failed', 'Last refresh failed — click ↻ to retry');
  }
}

// ── Keyboard shortcuts ─────────────────────────────────────────────────────
function installKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    const inField = /INPUT|TEXTAREA|SELECT/.test((e.target && e.target.tagName) || '');
    const cheatOpen = document.getElementById('cheatsheet-backdrop').classList.contains('open');

    if (e.key === 'Escape') {
      if (cheatOpen) { toggleCheatsheet(false); e.preventDefault(); return; }
      if (inField && e.target.id === 'session-search') {
        e.target.value = '';
        sessionSearchQuery = '';
        renderSessionsTable();
        e.target.blur();
        e.preventDefault();
      }
      return;
    }
    if (inField) return; // let typing pass through

    if (e.key === '?' || (e.shiftKey && e.key === '/')) { toggleCheatsheet(); e.preventDefault(); return; }
    if (e.key === '/') {
      const s = document.getElementById('session-search');
      if (s) { s.focus(); s.select(); e.preventDefault(); }
      return;
    }
    if (e.key === 'r' || e.key === 'R') { loadData(); e.preventDefault(); return; }
    if (e.key === '1') { setRange('7d');  e.preventDefault(); return; }
    if (e.key === '2') { setRange('30d'); e.preventDefault(); return; }
    if (e.key === '3') { setRange('90d'); e.preventDefault(); return; }
    if (e.key === '4') { setRange('all'); e.preventDefault(); return; }
  });

  // Click backdrop to close cheatsheet
  document.getElementById('cheatsheet-backdrop').addEventListener('click', (e) => {
    if (e.target.id === 'cheatsheet-backdrop') toggleCheatsheet(false);
  });
}

function toggleCheatsheet(force) {
  const el = document.getElementById('cheatsheet-backdrop');
  if (typeof force === 'boolean') el.classList.toggle('open', force);
  else el.classList.toggle('open');
}

// ── Sticky shadow ──────────────────────────────────────────────────────────
function installStickyShadow() {
  const wrap = document.getElementById('filter-bar-wrap');
  if (!wrap) return;
  // Use IntersectionObserver on a sentinel placed just above the wrap
  const sentinel = document.createElement('div');
  sentinel.style.height = '1px';
  wrap.parentNode.insertBefore(sentinel, wrap);
  const io = new IntersectionObserver(([entry]) => {
    wrap.classList.toggle('is-stuck', !entry.isIntersecting);
  }, { threshold: 0 });
  io.observe(sentinel);
}

loadData();
setInterval(loadData, 30000);
setInterval(updateStaleness, 2000);
</script>
</body>
</html>
"""


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))

        elif self.path == "/api/data":
            data = get_dashboard_data()
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404)
            self.end_headers()


def serve(port=8080):
    server = HTTPServer(("localhost", port), DashboardHandler)
    print(f"Dashboard running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    serve()
