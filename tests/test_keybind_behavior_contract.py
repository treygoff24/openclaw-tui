from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual import events

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
    mock_ws_client.agents_list = AsyncMock(return_value={"agents": []})
    mock_ws_client.models_list = AsyncMock(return_value=[])
    mock_ws_client.status = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr("openclaw_tui.app.GatewayWsClient", MagicMock(return_value=mock_ws_client))
    monkeypatch.setattr("openclaw_tui.app.build_tree", lambda sessions: [])


@pytest.mark.asyncio
async def test_escape_aborts_when_run_is_active() -> None:
    app = AgentDashboard()
    async with app.run_test() as pilot:
        app._enter_chat_mode_for_session(_make_session())
        await pilot.pause()
        assert app._chat_state is not None
        app._chat_state.active_run_id = "run-1"

        app.on_key(events.Key("escape", None))
        await pilot.pause()
        await pilot.pause()

        assert app._ws_client.chat_abort.await_count == 1


@pytest.mark.asyncio
async def test_meta_c_still_copies_info() -> None:
    app = AgentDashboard()
    async with app.run_test() as pilot:
        app._selected_session = _make_session()
        with patch.object(app, "action_copy_info") as copy_action:
            app.on_key(events.Key("meta+c", None))
        copy_action.assert_called_once()


@pytest.mark.asyncio
async def test_ctrl_n_opens_new_session_modal_from_transcript_mode() -> None:
    app = AgentDashboard()
    async with app.run_test() as pilot:
        with patch.object(app, "action_new_session") as open_new:
            app.on_key(events.Key("ctrl+n", None))
        open_new.assert_called_once()


@pytest.mark.asyncio
async def test_ctrl_n_opens_new_session_modal_from_chat_mode() -> None:
    app = AgentDashboard()
    async with app.run_test() as pilot:
        app._enter_chat_mode_for_session(_make_session())
        await pilot.pause()
        with patch.object(app, "action_new_session") as open_new:
            app.on_key(events.Key("ctrl+n", None))
        open_new.assert_called_once()
