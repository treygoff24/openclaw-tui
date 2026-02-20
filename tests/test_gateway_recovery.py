"""E8: App integration tests for gateway auto-recovery."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual import events

from openclaw_tui.app import AgentDashboard
from openclaw_tui.widgets import ChatPanel, SummaryBar
from openclaw_tui.models import SessionInfo


def _mock_load_config():
    from openclaw_tui.config import GatewayConfig
    return GatewayConfig(host="localhost", port=9876, token=None)

def _make_mock_client():
    mock_client = MagicMock()
    mock_client.fetch_sessions.return_value = []
    mock_client.fetch_tree.return_value = []
    mock_client.fetch_history.return_value = []
    mock_client.close.return_value = None
    return mock_client


@pytest.fixture(autouse=True)
def _mock_gateway(monkeypatch):
    monkeypatch.setattr("openclaw_tui.app.load_config", _mock_load_config)


@pytest.mark.asyncio
async def test_reconnect_loop_triggered_on_disconnect(monkeypatch) -> None:
    """Test that when disconnected, the app shows 'reconnecting...' and spawns worker."""
    mock_client = _make_mock_client()
    monkeypatch.setattr("openclaw_tui.app.GatewayClient", lambda _: mock_client)

    app = AgentDashboard()
    # Mock ws connect so it immediately finishes
    app._connect_ws_gateway = AsyncMock()

    async with app.run_test() as pilot:
        await pilot.pause(0.1)

        # Force chat mode to test UI updates
        app._chat_mode = True
        app._selected_session = SessionInfo(
            key="agent:main:123",
            kind="chat",
            channel="webchat",
            display_name="Test Session",
            label=None,
            updated_at=123,
            session_id="123",
            model="test-model",
            context_tokens=None,
            total_tokens=0,
            aborted_last_run=False,
            transcript_path=None,
        )

        # Trigger disconnect event
        app._on_gateway_disconnected("test error")
        await pilot.pause(0.1)

        # Check UI states
        bar = app.query_one(SummaryBar)
        assert "Gateway offline. Reconnecting" in bar._display_text

        chat_panel = app.query_one(ChatPanel)
        status_widget = chat_panel.query_one("#chat-status")
        assert "reconnecting" in str(status_widget.render()).lower()

        # The worker should have cleared old client and be waiting
        assert app._ws_client is None

        # Clean up worker to prevent infinite loop
        app.workers.cancel_group(app, "chat_gateway_reconnect")


@pytest.mark.asyncio
async def test_offline_message_queue(monkeypatch) -> None:
    """Test that messages sent while disconnected are queued."""
    mock_client = _make_mock_client()
    monkeypatch.setattr("openclaw_tui.app.GatewayClient", lambda _: mock_client)

    app = AgentDashboard()
    # Make ensure_ws_client fail consistently to simulate offline
    app._ensure_ws_client = AsyncMock(side_effect=RuntimeError("disconnected"))

    async with app.run_test() as pilot:
        await pilot.pause(0.1)

        app._chat_mode = True
        from openclaw_tui.chat import ChatState
        app._chat_state = ChatState(session_key="test-key", agent_id="main", session_info=MagicMock())

        # Attempt to send message
        await app._send_chat_message("test-key", "hello world")
        
        # Should be queued
        assert hasattr(app, "_offline_message_queue")
        assert len(app._offline_message_queue) == 1
        queued = app._offline_message_queue[0]
        assert queued[0] == "test-key"
        assert queued[1] == "hello world"
        
        chat_panel = app.query_one(ChatPanel)
        status_widget = chat_panel.query_one("#chat-status")
        assert "queued" in str(status_widget.render()).lower()
