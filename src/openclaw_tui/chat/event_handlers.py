from __future__ import annotations

from collections.abc import Callable

from .runtime_types import RunTrackingState
from .stream_assembler import TuiStreamAssembler


class ChatEventProcessor:
    def __init__(
        self,
        *,
        state: RunTrackingState,
        on_assistant_update: Callable[[str, str], None],
        on_assistant_final: Callable[[str, str], None],
        on_system: Callable[[str], None],
        on_status: Callable[[str], None],
        include_thinking: bool = False,
        on_refresh_history: Callable[[], None] | None = None,
    ) -> None:
        self._state = state
        self._on_assistant_update = on_assistant_update
        self._on_assistant_final = on_assistant_final
        self._on_system = on_system
        self._on_status = on_status
        self._include_thinking = include_thinking
        self._on_refresh_history = on_refresh_history
        self._assembler = TuiStreamAssembler()

    @property
    def state(self) -> RunTrackingState:
        return self._state

    def set_include_thinking(self, include_thinking: bool) -> None:
        self._include_thinking = include_thinking

    def set_session_key(self, session_key: str) -> None:
        self._state.set_session_key(session_key)
        self._assembler = TuiStreamAssembler()

    def note_local_run(self, run_id: str) -> None:
        self._state.note_local_run(run_id)

    def forget_local_run(self, run_id: str | None) -> None:
        self._state.forget_local_run(run_id)

    def handle_chat_event(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return

        session_key = payload.get("sessionKey")
        run_id = payload.get("runId")
        state_name = payload.get("state")
        if not isinstance(session_key, str) or not isinstance(run_id, str) or not isinstance(state_name, str):
            return
        if session_key != self._state.session_key:
            return

        if run_id in self._state.finalized_run_ids and state_name in {"delta", "final"}:
            return

        self._state.note_session_run(run_id)
        if self._state.active_run_id is None:
            self._state.active_run_id = run_id

        if state_name == "delta":
            text = self._assembler.ingest_delta(run_id, payload.get("message"), self._include_thinking)
            if text:
                self._on_assistant_update(text, run_id)
                self._on_status("streaming")
            return

        if state_name == "final":
            final_text = self._assembler.finalize(run_id, payload.get("message"), self._include_thinking)
            if final_text:
                self._on_assistant_final(final_text, run_id)
            self._state.note_finalized_run(run_id)
            self._state.active_run_id = None
            self._on_status("idle")
            if run_id not in self._state.local_run_ids and self._on_refresh_history is not None:
                self._on_refresh_history()
            self._state.forget_local_run(run_id)
            return

        if state_name == "aborted":
            self._on_system("run aborted")
            self._assembler.drop(run_id)
            self._state.note_finalized_run(run_id)
            self._state.active_run_id = None
            self._state.forget_local_run(run_id)
            self._on_status("aborted")
            return

        if state_name == "error":
            error_message = payload.get("errorMessage")
            msg = error_message if isinstance(error_message, str) and error_message else "unknown"
            self._on_system(f"run error: {msg}")
            self._assembler.drop(run_id)
            self._state.note_finalized_run(run_id)
            self._state.active_run_id = None
            self._state.forget_local_run(run_id)
            self._on_status("error")

    def handle_agent_event(self, payload: object, *, verbose_level: str = "off") -> None:
        if not isinstance(payload, dict):
            return
        run_id = payload.get("runId")
        stream = payload.get("stream")
        data = payload.get("data")
        if not isinstance(run_id, str) or not isinstance(stream, str):
            return

        is_known = (
            run_id == self._state.active_run_id
            or run_id in self._state.session_run_ids
            or run_id in self._state.finalized_run_ids
        )
        if not is_known:
            return

        if stream == "lifecycle" and isinstance(data, dict):
            phase = data.get("phase")
            if phase == "start":
                self._on_status("running")
            elif phase == "end":
                self._on_status("idle")
            elif phase == "error":
                self._on_status("error")
            return

        if stream == "tool" and verbose_level != "off":
            self._on_status("running")
