# 🌘 OpenClaw Agent Dashboard

A Hearth-inspired live terminal dashboard for monitoring OpenClaw agent sessions in real-time.

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Features

- **Live agent session tree** — Polls every 2 seconds
- **WebSocket chat parity transport** — Uses gateway `chat.send/chat.history/chat.abort`
- **Hearth-inspired dark theme** — Amber #F5A623 accent, deep navy #1A1A2E background
- **Relative timestamps** — "active", "3m ago", "2h ago"
- **Channel icons** — ⌨ discord, ⏱ cron, 🔥 hearth, 🌐 webchat
- **Session transcript viewer** — View messages with metadata
- **Parent-child agent hierarchy** — Via sessions_tree API
- **Clipboard support** — macOS (pbcopy) + Linux (xclip/xsel)

## Requirements

- Python 3.12+
- OpenClaw gateway running locally
- `~/.openclaw/openclaw.json` with `gateway.port` and `gateway.auth.token`

## Installation (macOS)

```bash
git clone https://github.com/treygoff24/openclaw-tui
cd openclaw-tui
uv venv .venv
uv pip install -e .
uv run python -m openclaw_tui
```

## Configuration

Auto-reads `~/.openclaw/openclaw.json` — no manual config needed.

```json
{
  "gateway": {
    "port": 2020,
    "auth": {
      "token": "your-gateway-token"
    }
  }
}
```

## Keybindings

| Key | Action |
|-----|--------|
| q | Quit |
| r | Refresh now |
| cmd+c | Copy session info / transcript |
| ctrl+c | Double-press to quit |
| esc | Abort active run (if running), otherwise leave chat when input is empty |
| ctrl+l | Open/list models |
| ctrl+g | Open/list agents |
| ctrl+p | Open/list sessions |
| ctrl+t | Toggle thinking visibility and refresh history |

## Color Palette

- **Background:** #1A1A2E (deep moon)
- **Accent:** #F5A623 (amber glow)
- **Text:** #FFF8E7 (warm white)

---

Forked from [mattmascolo/openclaw-tui](https://github.com/mattmascolo/openclaw-tui)
