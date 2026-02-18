from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from openclaw_tui.app import AgentDashboard
from openclaw_tui.models import SessionInfo


def _mock_load_config():
    from openclaw_tui.config import GatewayConfig

    return GatewayConfig(host="localhost", port=9876, token=None)


def _make_session() -> SessionInfo:
    return SessionInfo(
        key="agent:main:test:abc123",
        kind="chat",
        channel="webchat",
        display_name="Test Session",
        label="Test",
        updated_at=1700000000000,
        session_id="session-123",
        model="claude-sonnet-4-20250514",
        context_tokens=1000,
        total_tokens=2000,
        aborted_last_run=False,
        transcript_path=None,
    )


@pytest.fixture(autouse=True)
def _mock_gateway(monkeypatch):
    monkeypatch.setattr("openclaw_tui.app.load_config", _mock_load_config)

    mock_client = MagicMock()
    mock_client.fetch_sessions.return_value = []
    mock_client.fetch_tree.return_value = []
    mock_client.send_message.return_value = {}
    mock_client.close.return_value = None
    monkeypatch.setattr("openclaw_tui.app.GatewayClient", MagicMock(return_value=mock_client))

    mock_ws_client = MagicMock()
    mock_ws_client.start = AsyncMock()
    mock_ws_client.wait_ready = AsyncMock()
    mock_ws_client.stop = AsyncMock()
    mock_ws_client.chat_history = AsyncMock(return_value={"messages": []})
    mock_ws_client.send_chat = AsyncMock(return_value={"runId": "run-test"})
    mock_ws_client.chat_abort = AsyncMock(return_value={"ok": True, "aborted": True})
    mock_ws_client.sessions_list = AsyncMock(return_value={"sessions": []})
    mock_ws_client.sessions_patch = AsyncMock(return_value={})
    mock_ws_client.sessions_reset = AsyncMock(return_value={})
    mock_ws_client.agents_list = AsyncMock(return_value={"agents": []})
    mock_ws_client.models_list = AsyncMock(return_value={"models": []})
    mock_ws_client.status = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("openclaw_tui.app.GatewayWsClient", MagicMock(return_value=mock_ws_client))
    monkeypatch.setattr("openclaw_tui.app.build_tree", lambda sessions: [])


@pytest.mark.asyncio
async def test_send_uses_websocket_chat_send_not_sessions_send() -> None:
    app = AgentDashboard()

    async with app.run_test() as pilot:
        session = _make_session()
        app._enter_chat_mode_for_session(session)
        await pilot.pause()
        app._send_user_chat_message("hello parity")
        await pilot.pause()
        await pilot.pause()

        assert app._ws_client.send_chat.await_count == 1
        assert app._client.send_message.call_count == 0
        kwargs = app._ws_client.send_chat.await_args.kwargs
        assert kwargs["message"] == "hello parity"
        assert kwargs["session_key"] == session.key


@pytest.mark.asyncio
async def test_unknown_slash_is_forwarded_to_gateway_chat_send() -> None:
    app = AgentDashboard()

    async with app.run_test() as pilot:
        session = _make_session()
        app._enter_chat_mode_for_session(session)
        await pilot.pause()

        app._run_chat_command("/context")
        await pilot.pause()
        await pilot.pause()

        assert app._ws_client.send_chat.await_count == 1
        kwargs = app._ws_client.send_chat.await_args.kwargs
        assert kwargs["message"] == "/context"


@pytest.mark.asyncio
async def test_abort_command_uses_active_run_id() -> None:
    app = AgentDashboard()

    async with app.run_test() as pilot:
        session = _make_session()
        app._enter_chat_mode_for_session(session)
        await pilot.pause()
        assert app._chat_state is not None
        app._chat_state.active_run_id = "run-123"
        app._run_chat_command("/abort")
        await pilot.pause()
        await pilot.pause()

        assert app._ws_client.chat_abort.await_count == 1
        kwargs = app._ws_client.chat_abort.await_args.kwargs
        assert kwargs["run_id"] == "run-123"
