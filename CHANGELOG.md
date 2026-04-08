# Changelog

All notable changes to claudepulse will be documented here.

## [1.0.2] - 2026-04-08

### Added
- **Keyboard shortcuts** — `/` focuses session search, `1/2/3/4` switches range, `R` refreshes, `?` opens a shortcut cheatsheet overlay, `Esc` closes modals / clears search.
- **Sticky filter bar** — the Models / Range controls now stick to the top of the viewport on scroll, with a subtle shadow appearing when stuck.
- **Expandable session rows** — click any row in Recent Sessions to reveal an inline detail panel with per-component token share, per-turn averages, cost breakdown, and a stacked mini-bar.
- **Live refresh indicator** — pulsing green dot in the header meta area with "Live · updated Ns ago" text. Goes amber when stale (>45s) and red on fetch failure. A manual `↻` refresh button sits next to it.
- **Chart legend toggling** — click items in any Chart.js legend to hide/show that dataset. Especially useful to isolate input/output when cache dominates.

### Design
- All features use the existing four-color brand palette (blue / violet / emerald / amber) — zero new hues.
- Dashboard is now a true dark-mode operator UI: keyboard-driven, glanceable refresh state, drill-into-session.

### Features (full set carried from v1.0.0)
- Linear-inspired dark UI, Inter Variable 510, indigo-violet chrome accent.
- Multi-hue data palette for charts and heatmap.
- Stat cards with period-over-period delta indicators.
- Cache Efficiency card (`cache_read / (input + cache_read)`).
- Monthly Run Rate projection.
- Activity heatmap (7×24 day-of-week × hour-of-day).
- Session search + CSV export on both data tables.
- Empty state card on first-run with no data.
- Incremental scanner, pure Python stdlib.
- `install.sh` one-liner + auto-updating launcher.
- GitHub Actions release workflow with PyPI Trusted Publishing.

### License
- MIT, © 2026 ColdDesertLab.
