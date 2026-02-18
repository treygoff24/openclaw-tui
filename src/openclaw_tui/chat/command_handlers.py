from __future__ import annotations

from collections.abc import Awaitable, Callable

from .commands import ALIASES, COMMANDS
from .runtime_types import CommandResult


KNOWN_COMMANDS = {ALIASES.get(name, name) for name in COMMANDS}


def _parse_slash_command(raw: str) -> tuple[str, str]:
    stripped = raw[1:].strip()
    if not stripped:
        return "", ""
    parts = stripped.split(None, 1)
    name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    return ALIASES.get(name, name), args


class ChatCommandHandlers:
    def __init__(
        self,
        *,
        client: object,
        state: object,
        on_send_text: Callable[[str], None],
        on_system: Callable[[str], None],
        on_known_command: Callable[[str, str], Awaitable[CommandResult] | CommandResult] | None,
    ) -> None:
        self._client = client
        self._state = state
        self._on_send_text = on_send_text
        self._on_system = on_system
        self._on_known_command = on_known_command

    async def handle(self, raw: str) -> bool:
        if not raw.startswith("/"):
            return False
        name, args = _parse_slash_command(raw)
        if not name:
            return True

        if name == "abort":
            await self._handle_abort()
            return True

        if name in KNOWN_COMMANDS and self._on_known_command is not None:
            result = self._on_known_command(name, args)
            if isinstance(result, CommandResult):
                return result.handled
            awaited = await result
            return awaited.handled

        # Built-in parity: unknown slash commands are forwarded to chat.send.
        self._on_send_text(raw)
        return True

    async def _handle_abort(self) -> None:
        session_key = getattr(self._state, "current_session_key", "")
        run_id = getattr(self._state, "active_run_id", None)
        if not session_key:
            self._on_system("abort failed: no active session")
            return
        chat_abort = getattr(self._client, "chat_abort", None)
        if not callable(chat_abort):
            self._on_system("abort failed: chat transport unavailable")
            return
        try:
            await chat_abort(session_key, run_id=run_id)
        except Exception as exc:  # noqa: BLE001
            self._on_system(f"abort failed: {exc}")
