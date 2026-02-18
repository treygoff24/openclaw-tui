from dataclasses import dataclass, field

from openclaw_tui.models import ChatMessage, SessionInfo


@dataclass
class ChatState:
    session_key: str
    agent_id: str
    session_info: SessionInfo
    messages: list[ChatMessage] = field(default_factory=list)
    is_busy: bool = False
    last_message_count: int = 0
    error: str | None = None