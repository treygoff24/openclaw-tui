from __future__ import annotations

from openclaw_tui.chat.event_handlers import ChatEventProcessor
from openclaw_tui.chat.runtime_types import RunTrackingState


def test_chat_event_processor_handles_delta_final_and_status() -> None:
    state = RunTrackingState(session_key="agent:main:main")
    updates: list[tuple[str, str]] = []
    finals: list[tuple[str, str]] = []
    systems: list[str] = []
    statuses: list[str] = []
    processor = ChatEventProcessor(
        state=state,
        on_assistant_update=lambda text, run_id: updates.append((text, run_id)),
        on_assistant_final=lambda text, run_id: finals.append((text, run_id)),
        on_system=systems.append,
        on_status=statuses.append,
    )

    processor.handle_chat_event(
        {
            "runId": "run-1",
            "sessionKey": "agent:main:main",
            "seq": 1,
            "state": "delta",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
        }
    )
    processor.handle_chat_event(
        {
            "runId": "run-1",
            "sessionKey": "agent:main:main",
            "seq": 2,
            "state": "final",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "hello!"}]},
        }
    )

    assert updates == [("hello", "run-1")]
    assert finals == [("hello!", "run-1")]
    assert systems == []
    assert statuses == ["streaming", "idle"]


def test_chat_event_processor_refreshes_for_remote_final() -> None:
    refreshed: list[str] = []
    state = RunTrackingState(session_key="agent:main:main")
    processor = ChatEventProcessor(
        state=state,
        on_assistant_update=lambda _text, _run_id: None,
        on_assistant_final=lambda _text, _run_id: None,
        on_system=lambda _text: None,
        on_status=lambda _status: None,
        on_refresh_history=lambda: refreshed.append("refresh"),
    )

    processor.note_local_run("local-run")
    processor.handle_chat_event(
        {
            "runId": "remote-run",
            "sessionKey": "agent:main:main",
            "seq": 1,
            "state": "final",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        }
    )

    assert refreshed == ["refresh"]
