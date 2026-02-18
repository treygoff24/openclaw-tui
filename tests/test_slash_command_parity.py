from __future__ import annotations

import pytest

from openclaw_tui.chat.command_handlers import ChatCommandHandlers
from openclaw_tui.chat.commands import parse_input
from openclaw_tui.chat.runtime_types import CommandResult


class _StubClient:
    def __init__(self) -> None:
        self.abort_calls: list[tuple[str, str | None]] = []

    async def chat_abort(self, session_key: str, run_id: str | None = None) -> dict:
        self.abort_calls.append((session_key, run_id))
        return {"ok": True}


class _StubState:
    current_session_key = "agent:main:main"
    active_run_id = "run-1"


def test_parse_input_is_case_insensitive_for_commands() -> None:
    parsed = parse_input("/MODELS")
    assert parsed.kind == "command"
    assert parsed.name == "models"


@pytest.mark.asyncio
async def test_elev_alias_maps_to_elevated_known_handler() -> None:
    seen: list[tuple[str, str]] = []
    handlers = ChatCommandHandlers(
        client=_StubClient(),
        state=_StubState(),
        on_send_text=lambda _text: None,
        on_system=lambda _text: None,
        on_known_command=lambda name, args: (
            seen.append((name, args)),
            CommandResult(ok=True),
        )[1],
    )

    await handlers.handle("/ELEV on")

    assert seen == [("elevated", "on")]


@pytest.mark.asyncio
async def test_unknown_command_is_forwarded() -> None:
    sent: list[str] = []
    handlers = ChatCommandHandlers(
        client=_StubClient(),
        state=_StubState(),
        on_send_text=sent.append,
        on_system=lambda _text: None,
        on_known_command=lambda _name, _args: None,
    )

    await handlers.handle("/context")

    assert sent == ["/context"]
