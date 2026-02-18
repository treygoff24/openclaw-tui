# Design: v2 — Log Panel

Patch (Structural) — adds a log panel to the TUI dashboard showing transcript messages for the selected session.

## Brief

**Job to be done:** Matt can select a session in the tree and see its recent messages in a side panel.

**Appetite:** 30-45 minutes.

**Success criteria:**
- [ ] Selecting a session (Enter/click) shows its last ~20 messages in a right-side panel
- [ ] Messages show timestamp, role, and content (truncated)
- [ ] Panel updates when a different session is selected
- [ ] Panel shows "Select a session to view logs" when nothing selected
- [ ] Handles missing transcript files gracefully

---

## Changes

### New: `src/openclaw_tui/transcript.py`

Reads JSONL transcript files and extracts human-readable messages.

```python
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class TranscriptMessage:
    timestamp: str          # ISO format, e.g. "2026-02-18T01:44:10"
    role: str               # "user", "assistant", "tool"
    content: str            # Truncated text content
    
def read_transcript(session_id: str, agent_id: str, limit: int = 20) -> list[TranscriptMessage]:
    """Read last `limit` messages from a session's transcript file.
    
    File location: ~/.openclaw/agents/<agent_id>/sessions/<session_id>.jsonl
    
    Only includes type="message" lines. Extracts text from content blocks.
    For toolCall blocks: shows "[tool: <name>]".
    For toolResult blocks: shows first 80 chars of result.
    
    Returns empty list if file not found or unreadable.
    """
    ...
```

### New: `src/openclaw_tui/widgets/log_panel.py`

```python
from textual.widgets import RichLog

class LogPanel(RichLog):
    """Right-side panel showing transcript messages for selected session.
    
    Shows "Select a session to view logs" as placeholder.
    When a session is selected, displays last N messages with:
    [HH:MM] role: content (truncated to ~120 chars per line)
    """
    
    def show_transcript(self, messages: list[TranscriptMessage]) -> None:
        """Clear and display messages."""
        ...
    
    def show_placeholder(self) -> None:
        """Show 'Select a session to view logs'."""
        ...
    
    def show_error(self, message: str) -> None:
        """Show error (e.g., file not found)."""
        ...
```

### Modified: `src/openclaw_tui/models.py`

Add `agent_id` property to `SessionInfo` (parsed from key).

```python
@property
def agent_id(self) -> str:
    """Extract agent_id from key. 'agent:main:cron:UUID' → 'main'."""
    parts = self.key.split(":", 2)
    return parts[1] if len(parts) >= 2 else "unknown"
```

### Modified: `src/openclaw_tui/widgets/agent_tree.py`

Emit a message/event when a session node is selected (Enter/click).

### Modified: `src/openclaw_tui/app.py`

- Layout: horizontal split — tree (left, 40%) + log panel (right, 60%)
- Handle session selection → read transcript → update log panel
- SummaryBar stays at bottom spanning full width

### Modified: `src/openclaw_tui/widgets/__init__.py`

Export `LogPanel`.

---

## Conventions

Same as v1. Additionally:
- `RichLog` for the log panel (Textual's scrollable log widget — supports Rich markup)
- Read transcript files with stdlib only (json, pathlib) — no new deps
- Tail optimization: read file, take last N message lines. Don't parse entire file if huge.

---

## ADR-5: RichLog over Static for log panel

- **Decision:** Use `RichLog` widget instead of `Static`
- **Context:** Need scrollable, appendable text area for messages
- **Alternatives:** `Static` (no scroll), `TextArea` (editable, overkill), `ListView` (item-based)
- **Consequences:** RichLog supports `write()` with Rich markup, auto-scrolls, efficient for append-only display

## ADR-6: Read transcript from disk, not HTTP

- **Decision:** Read `.jsonl` files directly from `~/.openclaw/agents/<agentId>/sessions/<sessionId>.jsonl`
- **Context:** `sessions_history` HTTP endpoint is broken. API `transcriptPath` field points to wrong directory.
- **Alternatives:** Fix sessions_history (can't, it's an OpenClaw bug), use transcriptPath (wrong path)
- **Consequences:** Works immediately, no API dependency. Tightly coupled to file layout — if OpenClaw changes transcript location, we break. Acceptable for a local tool.
