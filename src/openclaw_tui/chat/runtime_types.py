from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ChatStateName = Literal["delta", "final", "aborted", "error"]


@dataclass
class ChatEvent:
    run_id: str
    session_key: str
    seq: int
    state: ChatStateName
    message: object | None = None
    error_message: str | None = None


@dataclass
class AgentEvent:
    run_id: str
    stream: str
    data: dict[str, object] | None = None


@dataclass
class SessionInfoSnapshot:
    thinking_level: str | None = None
    verbose_level: str | None = None
    reasoning_level: str | None = None
    model: str | None = None
    model_provider: str | None = None
    context_tokens: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    response_usage: str | None = None
    updated_at: int | None = None
    display_name: str | None = None


@dataclass
class CommandResult:
    ok: bool
    handled: bool = True
    message: str | None = None


@dataclass
class RunTrackingState:
    session_key: str
    active_run_id: str | None = None
    local_run_ids: set[str] = field(default_factory=set)
    finalized_run_ids: set[str] = field(default_factory=set)
    session_run_ids: set[str] = field(default_factory=set)

    _MAX_LOCAL: int = 200
    _MAX_FINALIZED: int = 200

    def set_session_key(self, session_key: str) -> None:
        if session_key == self.session_key:
            return
        self.session_key = session_key
        self.active_run_id = None
        self.local_run_ids.clear()
        self.finalized_run_ids.clear()
        self.session_run_ids.clear()

    def note_local_run(self, run_id: str) -> None:
        if not run_id:
            return
        self.local_run_ids.add(run_id)
        self._trim(self.local_run_ids, self._MAX_LOCAL)

    def forget_local_run(self, run_id: str | None) -> None:
        if not run_id:
            return
        self.local_run_ids.discard(run_id)

    def note_session_run(self, run_id: str) -> None:
        if not run_id:
            return
        self.session_run_ids.add(run_id)
        self._trim(self.session_run_ids, self._MAX_LOCAL)

    def note_finalized_run(self, run_id: str) -> None:
        if not run_id:
            return
        self.finalized_run_ids.add(run_id)
        self.session_run_ids.discard(run_id)
        self._trim(self.finalized_run_ids, self._MAX_FINALIZED)

    @staticmethod
    def _trim(values: set[str], max_size: int) -> None:
        if len(values) <= max_size:
            return
        while len(values) > max_size:
            values.pop()
