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
    mock_ws_client.agents_list = AsyncMock(return_value={"agents": [{"id": "main"}]})
    mock_ws_client.models_list = AsyncMock(
        return_value=[{"provider": "anthropic", "id": "claude-opus-4-6"}]
    )
    mock_ws_client.status = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("openclaw_tui.app.GatewayWsClient", MagicMock(return_value=mock_ws_client))
    monkeypatch.setattr("openclaw_tui.app.build_tree", lambda sessions: [])


@pytest.mark.asyncio
async def test_usage_command_defaults_to_tokens_mode() -> None:
    app = AgentDashboard()
    async with app.run_test() as pilot:
        app._enter_chat_mode_for_session(_make_session())
        await pilot.pause()
        app._run_chat_command("/usage")
        await pilot.pause()
        await pilot.pause()

        kwargs = app._ws_client.sessions_patch.await_args.kwargs
        assert kwargs["responseUsage"] == "tokens"


@pytest.mark.asyncio
async def test_session_command_normalizes_non_agent_key() -> None:
    app = AgentDashboard()
    async with app.run_test() as pilot:
        app._enter_chat_mode_for_session(_make_session())
        await pilot.pause()
        app._run_chat_command("/session main")
        await pilot.pause()
        await pilot.pause()
        assert app._chat_state is not None
        assert app._chat_state.session_key == "agent:main:main"
