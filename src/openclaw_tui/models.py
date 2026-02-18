from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass
class ChatMessage:
    role: str  # "user", "assistant", "system", "tool"
    content: str
    timestamp: str  # HH:MM display format
    tool_name: str | None = None  # for tool messages


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
    updated_at: int
    session_id: str
    model: str
    context_tokens: int | None
    total_tokens: int
    aborted_last_run: bool
    transcript_path: str | None = None

    def status(self, now_ms: int) -> SessionStatus:
        if self.aborted_last_run:
            return SessionStatus.ABORTED
        if (now_ms - self.updated_at) < 30_000:
            return SessionStatus.ACTIVE
        return SessionStatus.IDLE

    @property
    def short_model(self) -> str:
        name = self.model.replace("claude-", "")
        parts = name.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 8:
            name = parts[0]
        return name

    @property
    def context_label(self) -> str:
        parts = self.key.split(":", 2)
        return parts[2] if len(parts) >= 3 else self.key

    @property
    def agent_id(self) -> str:
        """Extract agent_id from key. 'agent:main:cron:UUID' → 'main'."""
        parts = self.key.split(":", 2)
        return parts[1] if len(parts) >= 2 else "unknown"


@dataclass
class TreeNodeData:
    key: str
    label: str
    depth: int
    status: str  # "active" | "completed" | "failed"
    runtime_ms: int
    children: list[TreeNodeData] = field(default_factory=list)


def format_runtime(ms: int) -> str:
    """Format runtime in ms to human-readable. 1000→'1s', 61000→'1m1s', 3661000→'1h1m'"""
    if ms == 0:
        return "0s"
    
    # Use ceiling for total seconds (handles cases like 199554ms → 200s)
    total_seconds = (ms + 999) // 1_000
    
    hours = total_seconds // 3_600
    remainder = total_seconds % 3_600
    minutes = remainder // 60
    seconds = remainder % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    # Only show seconds if no hours (matches "1h1m" case where seconds are hidden)
    if seconds > 0 and hours == 0:
        parts.append(f"{seconds}s")
    
    return "".join(parts)


@dataclass
class AgentNode:
    agent_id: str
    sessions: list[SessionInfo] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.agent_id
