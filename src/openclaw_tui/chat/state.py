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
    active_run_id: str | None = None
    local_run_ids: set[str] = field(default_factory=set)
    finalized_run_ids: set[str] = field(default_factory=set)
    stream_message_index_by_run: dict[str, int] = field(default_factory=dict)
    thinking_level: str | None = None
    verbose_level: str = "off"

    @property
    def current_session_key(self) -> str:
        return self.session_key

    @current_session_key.setter
    def current_session_key(self, value: str) -> None:
        self.session_key = value
