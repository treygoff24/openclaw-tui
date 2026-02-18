# OpenClaw TUI Dashboard

Live terminal dashboard showing OpenClaw agent sessions, their tree structure, and summary stats.

```
┌─ Agents ───────────────────────────────────────────────┐
│ ▼ main                                                 │
│   ○ openclaw-tui (opus-4-6) 27K tokens                │
│   ○ Cron: Nightly Consolidation (opus-4-6) 28K tokens │
│   ○ discord:#general (opus-4-6) 19K tokens            │
│ ▼ sonnet-worker                                        │
│   ● forge-builder-tui (sonnet-4-5) 50K tokens         │
│   ○ forge-builder-data (sonnet-4-5) 37K tokens        │
│ ▼ social                                               │
│   ○ discord:#lab (sonnet-4-5) 37K tokens              │
├────────────────────────────────────────────────────────┤
│ Active: 1  Idle: 8  Aborted: 0  Total: 9              │
└────────────────────────────────────────────────────────┘
```

## Install

```bash
cd ~/.openclaw/workspace/openclaw-tui
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Run

```bash
source ~/.openclaw/workspace/openclaw-tui/.venv/bin/activate
python -m openclaw_tui
```

Or if installed globally:

```bash
openclaw-tui
```

## Keybindings

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Force refresh |
| `Ctrl+C` | Quit |

## Configuration

Auto-reads from `~/.openclaw/openclaw.json`:
- `gateway.port` — gateway port (default: 2020)
- `gateway.auth.token` — bearer token for auth

Environment variable overrides:
- `OPENCLAW_GATEWAY_HOST` — gateway host (default: 127.0.0.1)
- `OPENCLAW_GATEWAY_PORT` — gateway port
- `OPENCLAW_WEBHOOK_TOKEN` — auth token

## Status Icons

| Icon | Meaning |
|------|---------|
| ● | Active (updated within 30s) |
| ○ | Idle (no recent updates) |
| ⚠ | Aborted (last run was aborted) |

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## v2 Roadmap

- [ ] Log tailing per selected agent
- [ ] Combined log feed for depth-1 children
- [ ] Cost estimation in summary bar
- [ ] Configurable poll interval
- [ ] Color themes
