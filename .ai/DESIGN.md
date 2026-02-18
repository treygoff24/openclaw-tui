# Design: OpenClaw TUI Dashboard

Live terminal dashboard showing agent sessions, their tree structure, and summary stats.

## Brief

**Job to be done:** Matt can glance at a terminal and see all running OpenClaw agents, their status, model, token usage, and relationships — updated live.

**Appetite:** 2-3 hours. Ship tree + summary at 2h. Log tailing is v2.

**Constraints:**
- **Language/Runtime:** Python 3.12+, Textual TUI framework
- **Deployment:** Local CLI tool, run from terminal
- **Integration points:** OpenClaw gateway HTTP API (`/tools/invoke`) on localhost
- **Performance:** Poll every 2s, render <100ms. Dashboard is read-only.
- **Security sensitivity:** Low — local-only, reads gateway auth token from config file

**Success criteria:**
- [ ] Running `python -m openclaw_tui` shows a live-updating agent tree
- [ ] Tree groups sessions by agent ID with status icons (●/○/⚠)
- [ ] Summary bar shows counts: active, idle, aborted, total sessions
- [ ] Auth token auto-loaded from `~/.openclaw/openclaw.json`
- [ ] Graceful handling when gateway is unreachable

---

## Architecture Overview

```
┌──────────────┐     HTTP/JSON      ┌──────────────────┐
│   OpenClaw   │◄──── poll 2s ──────│  TUI Dashboard   │
│   Gateway    │                    │                  │
│  :18789      │────── sessions ───►│  config.py       │
└──────────────┘     list response  │  client.py       │
                                    │  models.py       │
                                    │  app.py          │
                                    │  widgets/        │
                                    └──────────────────┘
```

### Components

| Component | Responsibility | Exposes | Consumes |
|-----------|---------------|---------|----------|
| `models.py` | Shared data types | `SessionInfo`, `AgentNode`, status enums | Nothing |
| `config.py` | Load gateway connection config | `GatewayConfig`, `load_config()` | `~/.openclaw/openclaw.json` |
| `client.py` | HTTP polling of gateway API | `fetch_sessions()` | `GatewayConfig` |
| `tree.py` | Build tree from flat session list | `build_tree()` | `SessionInfo` list |
| `widgets/agent_tree.py` | Textual Tree widget for agents | `AgentTreeWidget` | `AgentNode` list |
| `widgets/summary_bar.py` | Summary stats footer | `SummaryBar` | `AgentNode` list |
| `app.py` | Main Textual app, polling loop, layout | `AgentDashboard` | All above |

---

## Interface Contracts

### models.py

```python
from dataclasses import dataclass, field
from enum import Enum

class SessionStatus(Enum):
    ACTIVE = "active"      # updated within last 30s
    IDLE = "idle"          # updated >30s ago
    ABORTED = "aborted"    # abortedLastRun == True

STATUS_ICONS = {
    SessionStatus.ACTIVE: "●",
    SessionStatus.IDLE: "○",
    SessionStatus.ABORTED: "⚠",
}

STATUS_STYLES = {
    SessionStatus.ACTIVE: "green",
    SessionStatus.IDLE: "dim",
    SessionStatus.ABORTED: "yellow",
}

@dataclass
class SessionInfo:
    key: str
    kind: str                    # "other", "group"
    channel: str                 # "webchat", "discord", "unknown"
    display_name: str
    label: str | None
    updated_at: int              # epoch milliseconds
    session_id: str
    model: str
    context_tokens: int | None
    total_tokens: int
    aborted_last_run: bool

    def status(self, now_ms: int) -> SessionStatus:
        """Derive status from aborted flag and recency of update."""
        if self.aborted_last_run:
            return SessionStatus.ABORTED
        if (now_ms - self.updated_at) < 30_000:
            return SessionStatus.ACTIVE
        return SessionStatus.IDLE

@dataclass
class AgentNode:
    agent_id: str               # e.g. "main", "sonnet-worker", "social"
    sessions: list[SessionInfo] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        """Human-friendly agent name."""
        return self.agent_id
```

### config.py

```python
from dataclasses import dataclass

@dataclass
class GatewayConfig:
    host: str       # default "127.0.0.1"
    port: int       # from openclaw.json gateway.port, default 2020
    token: str | None  # from gateway.auth.token, None if no auth

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

def load_config(config_path: str | None = None) -> GatewayConfig:
    """Load gateway config from ~/.openclaw/openclaw.json.
    
    Falls back to env vars OPENCLAW_GATEWAY_HOST, OPENCLAW_GATEWAY_PORT,
    OPENCLAW_WEBHOOK_TOKEN if config file missing.
    
    Raises FileNotFoundError only if no config source is available.
    """
    ...
```

### client.py

```python
from .config import GatewayConfig
from .models import SessionInfo

class GatewayClient:
    def __init__(self, config: GatewayConfig):
        self.config = config
        self._session: httpx.Client | None = None  # reuse connection

    def fetch_sessions(self, active_minutes: int = 1440) -> list[SessionInfo]:
        """Poll sessions_list via /tools/invoke.
        
        Returns list of SessionInfo on success.
        Raises ConnectionError if gateway unreachable.
        Raises AuthError if 401/403.
        Returns empty list on other errors (logged).
        """
        ...

    def close(self):
        """Close HTTP session."""
        ...
```

### tree.py

```python
from .models import SessionInfo, AgentNode

def build_tree(sessions: list[SessionInfo]) -> list[AgentNode]:
    """Group sessions by agent ID extracted from session key.
    
    Session key format: agent:<agent_id>:<context>
    Groups all sessions sharing the same agent_id under one AgentNode.
    Returns list sorted: "main" first, then alphabetical.
    """
    ...
```

### widgets/agent_tree.py

```python
from textual.widgets import Tree

class AgentTreeWidget(Tree):
    """Tree widget showing agent hierarchy with live status updates."""

    def update_tree(self, nodes: list[AgentNode], now_ms: int) -> None:
        """Rebuild tree content from agent nodes.
        Preserves expansion state across updates.
        """
        ...
```

### widgets/summary_bar.py

```python
from textual.widgets import Static

class SummaryBar(Static):
    """Footer showing aggregate session counts."""

    def update_summary(self, nodes: list[AgentNode], now_ms: int) -> None:
        """Update summary text: Active: N  Idle: N  Aborted: N  Total: N"""
        ...
```

### app.py

```python
from textual.app import App

class AgentDashboard(App):
    """Main TUI application."""

    TITLE = "OpenClaw Agent Dashboard"
    CSS = """..."""  # layout CSS

    def compose(self) -> ComposeResult:
        """Layout: Header, AgentTreeWidget (main area), SummaryBar (footer)."""
        ...

    def on_mount(self) -> None:
        """Start polling loop (2s interval)."""
        ...

    async def poll_sessions(self) -> None:
        """Fetch sessions, build tree, update widgets."""
        ...
```

---

## Data Models

See `models.py` interface contract above. The gateway returns:

```json
{
  "ok": true,
  "result": {
    "details": {
      "count": 9,
      "sessions": [
        {
          "key": "agent:main:main",
          "kind": "other",
          "channel": "webchat",
          "displayName": "openclaw-tui",
          "label": null,
          "updatedAt": 1771379198943,
          "sessionId": "a56de194-...",
          "model": "claude-opus-4-6",
          "contextTokens": 150000,
          "totalTokens": 27652,
          "abortedLastRun": false
        }
      ]
    }
  }
}
```

Key parsing: `"agent:main:main".split(":", 2)` → `["agent", "main", "main"]` → agent_id = index 1.

---

## Conventions

- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants
- **Error handling:** Raise typed exceptions (`ConnectionError`, `AuthError`) for recoverable errors. Never silently swallow. Log warnings for non-critical failures.
- **Logging:** Use `logging` stdlib. `INFO` for connection events, `DEBUG` for poll results, `WARNING` for transient failures.
- **Imports:** stdlib → third-party (`textual`, `httpx`) → local, separated by blank lines
- **Return values:** Always typed. Use dataclasses for structured data, never bare dicts in public interfaces.
- **HTTP client:** `httpx` (sync client, connection reuse). NOT `requests` — httpx is lighter and supports connection pooling natively.
- **Type hints:** Required on all public functions. Use `from __future__ import annotations` for modern syntax.

---

## Architecture Decision Records

### ADR-1: httpx over requests

- **Decision:** Use `httpx` for HTTP client
- **Context:** Need a sync HTTP client with connection reuse for polling
- **Alternatives:** `requests` (heavier, no native connection pooling), `urllib3` (too low-level), `aiohttp` (async — Textual uses its own async loop)
- **Consequences:** Lighter dependency. Sync client works fine with Textual's `set_interval` running in a worker thread.

### ADR-2: Flat agent grouping (not hierarchical tree)

- **Decision:** Group sessions by agent_id as flat groups, not inferred parent-child hierarchy
- **Context:** Session keys don't encode spawn relationships. `agent:sonnet-worker:subagent:UUID` doesn't tell us which agent spawned it. `sessions_tree` tool doesn't exist.
- **Alternatives:** Infer parent-child from session keys (fragile, assumptions break), require sessions_tree (doesn't exist)
- **Consequences:** Simple, correct, extensible. Can add true hierarchy later if sessions_tree is added to OpenClaw.

### ADR-3: 30-second active threshold

- **Decision:** Sessions updated within last 30 seconds are "active", otherwise "idle"
- **Context:** No explicit status field in API response. Need to derive status from available data.
- **Alternatives:** 10s (too aggressive — poll itself takes time), 60s (too lenient), use totalTokens delta (complex, requires tracking previous state)
- **Consequences:** Simple heuristic. May show false "active" for 30s after session actually completes. Acceptable for a dashboard.

### ADR-4: Sync httpx in Textual worker

- **Decision:** Use sync httpx client called from a Textual `@work` decorator method
- **Context:** Textual is async but httpx sync is simpler and Textual provides `run_worker()` / `@work` for running sync code off the event loop
- **Consequences:** Avoids async complexity. Textual handles threading. Clean separation between IO and UI.

---

## Acceptance Criteria

- [ ] `python -m openclaw_tui` launches a full-screen TUI
- [ ] Tree shows agents grouped by ID: main, sonnet-worker, social, etc.
- [ ] Each session shows: status icon, display name or label, model, token count
- [ ] Summary bar shows: Active: N  Idle: N  Aborted: N  Total: N
- [ ] Tree updates live every 2 seconds without flicker
- [ ] Gateway unreachable → shows "Connection error" in summary, doesn't crash
- [ ] Auth token loaded from `~/.openclaw/openclaw.json` automatically
- [ ] `q` or `Ctrl+C` exits cleanly
- [ ] Works with 0 sessions (empty state handled)
