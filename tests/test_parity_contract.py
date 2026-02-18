from __future__ import annotations

import json
from pathlib import Path

import pytest

from openclaw_tui.chat.command_handlers import ChatCommandHandlers
from openclaw_tui.chat.event_handlers import ChatEventProcessor
from openclaw_tui.chat.runtime_types import RunTrackingState
from openclaw_tui.chat.stream_assembler import TuiStreamAssembler


FIXTURE = Path(__file__).parent / "fixtures" / "gateway_chat_events.json"


class _StubWsClient:
    def __init__(self) -> None:
        self.abort_calls: list[tuple[str, str | None]] = []

    async def chat_abort(self, session_key: str, run_id: str | None = None) -> dict:
        self.abort_calls.append((session_key, run_id))
        return {"ok": True, "aborted": True}


class _State:
    def __init__(self) -> None:
        self.current_session_key = "agent:main:main"
        self.active_run_id = "run-abc"


@pytest.mark.asyncio
async def test_unknown_slash_command_is_forwarded_as_chat_text() -> None:
    sent: list[str] = []
    handlers = ChatCommandHandlers(
        client=_StubWsClient(),
        state=_State(),
        on_send_text=sent.append,
        on_system=lambda _text: None,
        on_known_command=None,
    )

    handled = await handlers.handle("/context")

    assert handled is True
    assert sent == ["/context"]


@pytest.mark.asyncio
async def test_abort_uses_active_run_id() -> None:
    client = _StubWsClient()
    state = _State()
    handlers = ChatCommandHandlers(
        client=client,
        state=state,
        on_send_text=lambda _text: None,
        on_system=lambda _text: None,
        on_known_command=None,
    )

    handled = await handlers.handle("/abort")

    assert handled is True
    assert client.abort_calls == [("agent:main:main", "run-abc")]


def test_stream_assembler_delta_then_final() -> None:
    payload = json.loads(FIXTURE.read_text())
    events = payload["events"]
    run_id = payload["run_id"]
    assembler = TuiStreamAssembler()

    first = assembler.ingest_delta(run_id, events[0]["payload"]["message"], include_thinking=False)
    second = assembler.ingest_delta(run_id, events[1]["payload"]["message"], include_thinking=False)
    final = assembler.finalize(run_id, events[2]["payload"]["message"], include_thinking=False)

    assert first == "hello"
    assert second == "hello there"
    assert final == "hello there!"


def test_session_switch_ignores_stale_events() -> None:
    state = RunTrackingState(session_key="agent:main:main")
    updates: list[str] = []
    processor = ChatEventProcessor(
        state=state,
        on_assistant_update=lambda text, _run_id: updates.append(text),
        on_assistant_final=lambda _text, _run_id: None,
        on_system=lambda _text: None,
        on_status=lambda _status: None,
    )

    processor.handle_chat_event(
        {
            "runId": "run-1",
            "sessionKey": "agent:main:main",
            "seq": 1,
            "state": "delta",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "first"}]},
        }
    )
    processor.set_session_key("agent:main:other")
    processor.handle_chat_event(
        {
            "runId": "run-1",
            "sessionKey": "agent:main:main",
            "seq": 2,
            "state": "delta",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "stale"}]},
        }
    )

    assert updates == ["first"]
