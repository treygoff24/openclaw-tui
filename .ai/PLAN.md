# Implementation Plan: OpenClaw TUI Dashboard

## Prerequisites & Dependencies

### External Dependencies

| Package | Version | Purpose | Verified? |
|---------|---------|---------|-----------|
| textual | >=3.0 | TUI framework | ☐ |
| httpx | >=0.27 | HTTP client for gateway polling | ☐ |

### Environment Requirements

- Python 3.12+
- Access to OpenClaw gateway on localhost (default port 18789)
- `~/.openclaw/openclaw.json` for auth token

### Test Framework

- **Framework:** pytest
- **Run command:** `cd ~/.openclaw/workspace/openclaw-tui && python -m pytest tests/ -v`

---

## Walking Skeleton

**Path:** Load config → fetch sessions from gateway → print count to terminal in a Textual app

**Files created:**
- `pyproject.toml` — project config + deps
- `src/openclaw_tui/__init__.py`
- `src/openclaw_tui/__main__.py` — entry point
- `src/openclaw_tui/models.py` — data types (stub)
- `src/openclaw_tui/config.py` — config loader (stub)
- `src/openclaw_tui/client.py` — gateway client (stub)
- `src/openclaw_tui/app.py` — minimal Textual app showing "Loading..."
- `tests/__init__.py`

**Validates:**
- Textual app launches and renders
- httpx can reach gateway and parse response
- Project structure is correct

---

## Work Units

### System Summary

OpenClaw TUI Dashboard: a live terminal dashboard that polls the OpenClaw gateway's sessions_list endpoint every 2 seconds, groups sessions into an agent tree, and displays them with status icons and a summary bar. Built with Python + Textual + httpx. Project location: `~/.openclaw/workspace/openclaw-tui/`.

---

### WU-1: Data Layer (config + client + tree builder + models)

**Owner:** Builder 1
**Files:** `src/openclaw_tui/models.py`, `src/openclaw_tui/config.py`, `src/openclaw_tui/client.py`, `src/openclaw_tui/tree.py`, `tests/test_models.py`, `tests/test_config.py`, `tests/test_client.py`, `tests/test_tree.py`
**Depends on:** Walking skeleton (project structure exists)

#### Big Picture
OpenClaw TUI Dashboard: a live terminal dashboard that polls the OpenClaw gateway's sessions_list endpoint every 2 seconds, groups sessions into an agent tree, and displays them with status icons and a summary bar. Built with Python + Textual + httpx. Project location: `~/.openclaw/workspace/openclaw-tui/`.

#### Task
Build the complete data layer: data models, config loading, HTTP client for gateway polling, and tree builder that groups flat sessions by agent ID. This is everything below the UI — the TUI widgets will consume these interfaces.

#### Interface Contract (you implement)

```python
# src/openclaw_tui/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum

class SessionStatus(Enum):
    ACTIVE = "active"
    IDLE = "idle"
    ABORTED = "aborted"

STATUS_ICONS: dict[SessionStatus, str] = {
    SessionStatus.ACTIVE: "●",
    SessionStatus.IDLE: "○",
    SessionStatus.ABORTED: "⚠",
}

STATUS_STYLES: dict[SessionStatus, str] = {
    SessionStatus.ACTIVE: "green",
    SessionStatus.IDLE: "dim",
    SessionStatus.ABORTED: "yellow",
}

@dataclass
class SessionInfo:
    key: str
    kind: str
    channel: str
    display_name: str
    label: str | None
    updated_at: int              # epoch milliseconds
    session_id: str
    model: str
    context_tokens: int | None
    total_tokens: int
    aborted_last_run: bool

    def status(self, now_ms: int) -> SessionStatus:
        """Derive status. aborted_last_run=True → ABORTED, updated <30s ago → ACTIVE, else IDLE."""
        if self.aborted_last_run:
            return SessionStatus.ABORTED
        if (now_ms - self.updated_at) < 30_000:
            return SessionStatus.ACTIVE
        return SessionStatus.IDLE

    @property
    def short_model(self) -> str:
        """Shorten model name: 'claude-opus-4-6' → 'opus-4-6', 'claude-sonnet-4-5-20250929' → 'sonnet-4-5'."""
        name = self.model
        name = name.replace("claude-", "")
        # Strip date suffix like -20250929
        parts = name.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 8:
            name = parts[0]
        return name

    @property
    def context_label(self) -> str:
        """Human-readable context from key. 'agent:main:cron:UUID' → 'cron:UUID'."""
        parts = self.key.split(":", 2)
        return parts[2] if len(parts) >= 3 else self.key

@dataclass
class AgentNode:
    agent_id: str
    sessions: list[SessionInfo] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.agent_id
```

```python
# src/openclaw_tui/config.py
from __future__ import annotations
from dataclasses import dataclass
import json
import os
from pathlib import Path

@dataclass
class GatewayConfig:
    host: str
    port: int
    token: str | None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

def load_config(config_path: str | None = None) -> GatewayConfig:
    """Load config from ~/.openclaw/openclaw.json, falling back to env vars.
    
    Config file fields:
    - gateway.port (int, default 2020)
    - gateway.auth.token (str, optional)
    
    Env var overrides:
    - OPENCLAW_GATEWAY_HOST (default "127.0.0.1")
    - OPENCLAW_GATEWAY_PORT (overrides config file)
    - OPENCLAW_WEBHOOK_TOKEN (overrides config file)
    
    Returns GatewayConfig. Never raises — uses defaults if config missing.
    """
    ...
```

```python
# src/openclaw_tui/client.py
from __future__ import annotations
import httpx
from .config import GatewayConfig
from .models import SessionInfo

class GatewayError(Exception):
    """Base error for gateway communication."""
    pass

class AuthError(GatewayError):
    """Authentication failed (401/403)."""
    pass

class GatewayClient:
    def __init__(self, config: GatewayConfig):
        self.config = config
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create reusable HTTP client."""
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.config.token:
                headers["Authorization"] = f"Bearer {self.config.token}"
            self._client = httpx.Client(
                base_url=self.config.base_url,
                headers=headers,
                timeout=5.0,
            )
        return self._client

    def fetch_sessions(self, active_minutes: int = 1440) -> list[SessionInfo]:
        """Fetch sessions from gateway.
        
        POST /tools/invoke with tool=sessions_list.
        Parse response.result.details.sessions into SessionInfo list.
        
        Raises ConnectionError if gateway unreachable.
        Raises AuthError if 401/403.
        Returns empty list on unexpected errors (logged).
        """
        ...

    def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            self._client.close()
```

```python
# src/openclaw_tui/tree.py
from __future__ import annotations
from .models import SessionInfo, AgentNode

def build_tree(sessions: list[SessionInfo]) -> list[AgentNode]:
    """Group sessions by agent_id extracted from session key.
    
    Key format: agent:<agent_id>:<context>
    e.g. "agent:main:main" → agent_id="main"
         "agent:sonnet-worker:subagent:uuid" → agent_id="sonnet-worker"
    
    Returns list of AgentNode, sorted: "main" first, then alphabetical.
    Empty sessions list → empty result.
    Malformed keys (not starting with "agent:") → grouped under "unknown".
    """
    ...
```

#### Dependencies (you consume)
None — this is the foundation layer. Uses only stdlib + httpx.

#### Conventions
- `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants
- Error handling: raise typed exceptions (`ConnectionError`, `AuthError`). Never silently swallow. Log warnings for transient failures.
- Logging: `logging` stdlib. `INFO` for connection events, `DEBUG` for poll data, `WARNING` for failures.
- Imports: stdlib → third-party (`httpx`) → local, blank line separated
- Type hints on all public functions. `from __future__ import annotations` at top of every file.
- Use `@dataclass` for data structures, never bare dicts in public interfaces.
- HTTP: use `httpx.Client` (sync), not `requests`.

#### Tests Required
**models.py:**
- `SessionInfo.status()` returns ABORTED when `aborted_last_run=True` regardless of timing
- `SessionInfo.status()` returns ACTIVE when updated <30s ago
- `SessionInfo.status()` returns IDLE when updated >30s ago
- `SessionInfo.short_model` strips "claude-" prefix
- `SessionInfo.short_model` strips date suffix
- `SessionInfo.context_label` extracts context from key

**config.py:**
- `load_config()` reads port and token from a valid config file (use tmp file)
- `load_config()` falls back to defaults when file missing
- `load_config()` respects env var overrides

**client.py:**
- `fetch_sessions()` parses valid gateway response into SessionInfo list
- `fetch_sessions()` raises AuthError on 401 response
- `fetch_sessions()` raises ConnectionError on network failure
- `fetch_sessions()` returns empty list on unexpected error
- Use `httpx.MockTransport` or `respx` for HTTP mocking (prefer `httpx.MockTransport` to avoid extra deps)

**tree.py:**
- `build_tree()` with empty list returns empty list
- `build_tree()` groups sessions by agent_id
- `build_tree()` puts "main" agent first
- `build_tree()` sorts remaining agents alphabetically
- `build_tree()` handles malformed keys (no "agent:" prefix) → "unknown" group

#### Definition of Done
- [ ] All interface functions implemented with correct signatures
- [ ] All required tests pass (`pytest tests/ -v`)
- [ ] No bare dicts — all data flows through dataclasses
- [ ] Config loads from real `~/.openclaw/openclaw.json` format
- [ ] HTTP client uses connection reuse via httpx.Client

---

### WU-2: TUI Layer (widgets + app + polling)

**Owner:** Builder 2
**Files:** `src/openclaw_tui/widgets/__init__.py`, `src/openclaw_tui/widgets/agent_tree.py`, `src/openclaw_tui/widgets/summary_bar.py`, `src/openclaw_tui/app.py`, `src/openclaw_tui/__main__.py`, `tests/test_widgets.py`, `tests/test_app.py`
**Depends on:** WU-1 types (models.py — provided in interface contract below)

#### Big Picture
OpenClaw TUI Dashboard: a live terminal dashboard that polls the OpenClaw gateway's sessions_list endpoint every 2 seconds, groups sessions into an agent tree, and displays them with status icons and a summary bar. Built with Python + Textual + httpx. Project location: `~/.openclaw/workspace/openclaw-tui/`.

#### Task
Build the Textual TUI application: agent tree widget, summary bar widget, main app with polling loop and layout. The data layer (models, config, client, tree builder) is built separately — you consume their interfaces as defined below.

#### Interface Contract (you implement)

```python
# src/openclaw_tui/widgets/__init__.py
from .agent_tree import AgentTreeWidget
from .summary_bar import SummaryBar

__all__ = ["AgentTreeWidget", "SummaryBar"]
```

```python
# src/openclaw_tui/widgets/agent_tree.py
from __future__ import annotations
from textual.widgets import Tree
from ..models import AgentNode, SessionInfo, SessionStatus, STATUS_ICONS, STATUS_STYLES

class AgentTreeWidget(Tree[SessionInfo]):
    """Tree widget displaying agents and their sessions.
    
    Top-level nodes: agent IDs (e.g., "main", "sonnet-worker")
    Children: individual sessions with status icon, label/name, model, tokens
    
    Format per session line:
    "● my-session (opus-4-6) 27K tokens"
    "○ cron: Nightly (sonnet-4-5) 30K tokens"
    "⚠ subagent:abc123 (minimax) 0 tokens"
    """

    def update_tree(self, nodes: list[AgentNode], now_ms: int) -> None:
        """Rebuild tree from agent nodes. Preserves expansion state of agent groups."""
        ...
```

```python
# src/openclaw_tui/widgets/summary_bar.py
from __future__ import annotations
from textual.widgets import Static
from ..models import AgentNode, SessionStatus

class SummaryBar(Static):
    """Footer widget showing aggregate counts.
    
    Displays: "Active: 3  Idle: 5  Aborted: 1  Total: 9"
    Shows "⚡ Connecting..." when no data received yet.
    Shows "❌ Gateway unreachable" on connection error.
    """

    def update_summary(self, nodes: list[AgentNode], now_ms: int) -> None:
        """Count sessions by status, update display."""
        ...

    def set_error(self, message: str) -> None:
        """Display error state in summary bar."""
        ...
```

```python
# src/openclaw_tui/app.py
from __future__ import annotations
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer
from .widgets import AgentTreeWidget, SummaryBar
from .config import GatewayConfig, load_config
from .client import GatewayClient
from .tree import build_tree

class AgentDashboard(App[None]):
    """Main TUI application with live-updating agent tree."""

    TITLE = "OpenClaw Agent Dashboard"
    BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh")]

    CSS = """
    AgentTreeWidget {
        height: 1fr;
    }
    SummaryBar {
        height: 3;
        background: $surface;
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        """Layout: Header → AgentTreeWidget → SummaryBar → Footer."""
        yield Header()
        yield AgentTreeWidget("Agents")
        yield SummaryBar("⚡ Connecting...")
        yield Footer()

    def on_mount(self) -> None:
        """Load config, create client, start 2s polling interval."""
        ...

    def action_refresh(self) -> None:
        """Manual refresh triggered by 'r' key."""
        ...

    async def poll_sessions(self) -> None:
        """Worker: fetch sessions, build tree, update widgets. Handles errors gracefully."""
        ...

    def on_unmount(self) -> None:
        """Clean up HTTP client."""
        ...
```

```python
# src/openclaw_tui/__main__.py
"""Entry point: python -m openclaw_tui"""
from .app import AgentDashboard

def main():
    app = AgentDashboard()
    app.run()

if __name__ == "__main__":
    main()
```

#### Dependencies (you consume)

These types come from WU-1 (models.py). Use them as-is — DO NOT redefine them. Import from `openclaw_tui.models`.

```python
# From models.py — you consume these, do NOT redefine
class SessionStatus(Enum):
    ACTIVE = "active"
    IDLE = "idle"
    ABORTED = "aborted"

STATUS_ICONS: dict[SessionStatus, str] = {
    SessionStatus.ACTIVE: "●", SessionStatus.IDLE: "○", SessionStatus.ABORTED: "⚠",
}
STATUS_STYLES: dict[SessionStatus, str] = {
    SessionStatus.ACTIVE: "green", SessionStatus.IDLE: "dim", SessionStatus.ABORTED: "yellow",
}

@dataclass
class SessionInfo:
    key: str; kind: str; channel: str; display_name: str; label: str | None
    updated_at: int; session_id: str; model: str; context_tokens: int | None
    total_tokens: int; aborted_last_run: bool
    def status(self, now_ms: int) -> SessionStatus: ...
    @property
    def short_model(self) -> str: ...
    @property
    def context_label(self) -> str: ...

@dataclass
class AgentNode:
    agent_id: str
    sessions: list[SessionInfo] = field(default_factory=list)
    @property
    def display_name(self) -> str: ...

# From config.py:
def load_config(config_path: str | None = None) -> GatewayConfig: ...

# From client.py:
class GatewayClient:
    def __init__(self, config: GatewayConfig): ...
    def fetch_sessions(self, active_minutes: int = 1440) -> list[SessionInfo]: ...
    def close(self) -> None: ...
class GatewayError(Exception): ...
class AuthError(GatewayError): ...

# From tree.py:
def build_tree(sessions: list[SessionInfo]) -> list[AgentNode]: ...
```

#### Conventions
- `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants
- Error handling: catch `GatewayError`/`ConnectionError` in poll loop, display in SummaryBar. Never crash the TUI on transient errors.
- Logging: `logging` stdlib. `INFO` for lifecycle events, `WARNING` for poll errors.
- Imports: stdlib → third-party (`textual`) → local, blank line separated
- Type hints on all public functions. `from __future__ import annotations` at top of every file.
- Textual CSS: inline in `CSS` class var, not separate file.
- Token display: format as "27K" for thousands, "1.2M" for millions, "0" for zero.

#### Tests Required
**widgets/agent_tree.py:**
- Widget renders agent group headers
- Widget renders session lines with status icons
- Widget handles empty node list (shows "No sessions")

**widgets/summary_bar.py:**
- Shows correct counts for mixed statuses
- Shows "⚡ Connecting..." initially
- Shows error message via set_error()

**app.py:**
- App composes all widgets (Header, AgentTreeWidget, SummaryBar, Footer)
- App mounts without crash (smoke test using textual's testing tools: `async with app.run_test()`)

Note: For Textual widget tests, use `from textual.testing import *` — Textual provides built-in test harness. Use `app.run_test()` context manager.

#### Definition of Done
- [ ] All widgets render correctly with sample data
- [ ] Polling loop fetches and updates every 2 seconds
- [ ] Gateway errors shown in SummaryBar, no crash
- [ ] `q` and `Ctrl+C` exit cleanly
- [ ] Empty state (0 sessions) handled gracefully
- [ ] Token counts formatted as "27K" / "1.2M" / "0"
- [ ] All required tests pass

---

## File Ownership

| File | Owner |
|------|-------|
| `pyproject.toml` | Walking Skeleton |
| `src/openclaw_tui/__init__.py` | Walking Skeleton |
| `src/openclaw_tui/__main__.py` | WU-2 |
| `src/openclaw_tui/models.py` | WU-1 |
| `src/openclaw_tui/config.py` | WU-1 |
| `src/openclaw_tui/client.py` | WU-1 |
| `src/openclaw_tui/tree.py` | WU-1 |
| `src/openclaw_tui/widgets/__init__.py` | WU-2 |
| `src/openclaw_tui/widgets/agent_tree.py` | WU-2 |
| `src/openclaw_tui/widgets/summary_bar.py` | WU-2 |
| `src/openclaw_tui/app.py` | WU-2 |
| `tests/test_models.py` | WU-1 |
| `tests/test_config.py` | WU-1 |
| `tests/test_client.py` | WU-1 |
| `tests/test_tree.py` | WU-1 |
| `tests/test_widgets.py` | WU-2 |
| `tests/test_app.py` | WU-2 |

---

## Integration Order

1. **Walking Skeleton** — pyproject.toml, package structure, minimal Textual app, install deps
2. **WU-1 (Data Layer)** + **WU-2 (TUI Layer)** — build in parallel (WU-2 uses stubs for data layer during development, final wiring uses real imports)
3. **Integration** — wire data layer into TUI app, run full test suite, verify live against gateway
4. **Polish** — test with real gateway, fix any rendering issues

### Stubbing Strategy

WU-2 can build against the interface contracts without WU-1 being complete:
- Import types from `openclaw_tui.models` (WU-1 builds models first, or WU-2 can create test fixtures matching the interface)
- For widget tests, create sample `AgentNode` / `SessionInfo` objects directly
- For app smoke tests, mock `GatewayClient.fetch_sessions()` to return sample data

---

## Parallel Build Groups

- **Group 1 (parallel):** WU-1, WU-2
- **Group 2 (serial):** Integration + polish
