"""E8: App integration tests for gateway auto-recovery."""
from __future__ import annotations

import asyncio
from functools import partial
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


def _make_session_info() -> SessionInfo:
    return SessionInfo(
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


@pytest.fixture(autouse=True)
def _mock_gateway(monkeypatch):
    monkeypatch.setattr("openclaw_tui.app.load_config", _mock_load_config)


@pytest.mark.asyncio
async def test_reconnect_loop_triggered_on_disconnect(monkeypatch) -> None:
    """Disconnect event shows reconnecting status and spawns reconnect worker."""
    mock_client = _make_mock_client()
    monkeypatch.setattr("openclaw_tui.app.GatewayClient", lambda _: mock_client)

    app = AgentDashboard()
    app._connect_ws_gateway = AsyncMock()

    async with app.run_test() as pilot:
        await pilot.pause(0.1)

        app._chat_mode = True
        app._selected_session = _make_session_info()

        app._on_gateway_disconnected("test error")
        await pilot.pause(0.1)

        bar = app.query_one(SummaryBar)
        assert "Gateway offline. Reconnecting" in bar._display_text

        chat_panel = app.query_one(ChatPanel)
        status_widget = chat_panel.query_one("#chat-status")
        assert "reconnecting" in str(status_widget.render()).lower()

        assert app._ws_client is None

        app.workers.cancel_group(app, "chat_gateway_reconnect")


@pytest.mark.asyncio
async def test_offline_message_queue(monkeypatch) -> None:
    """Messages sent while disconnected are queued."""
    mock_client = _make_mock_client()
    monkeypatch.setattr("openclaw_tui.app.GatewayClient", lambda _: mock_client)

    app = AgentDashboard()
    app._ensure_ws_client = AsyncMock(side_effect=RuntimeError("disconnected"))

    async with app.run_test() as pilot:
        await pilot.pause(0.1)

        app._chat_mode = True
        from openclaw_tui.chat import ChatState
        app._chat_state = ChatState(session_key="test-key", agent_id="main", session_info=MagicMock())

        await app._send_chat_message("test-key", "hello world")

        assert len(app._offline_message_queue) == 1
        queued = app._offline_message_queue[0]
        assert queued[0] == "test-key"
        assert queued[1] == "hello world"

        chat_panel = app.query_one(ChatPanel)
        status_widget = chat_panel.query_one("#chat-status")
        assert "queued" in str(status_widget.render()).lower()


@pytest.mark.asyncio
async def test_is_busy_reset_after_offline_queue(monkeypatch) -> None:
    """is_busy must be reset to False when a message is queued offline."""
    mock_client = _make_mock_client()
    monkeypatch.setattr("openclaw_tui.app.GatewayClient", lambda _: mock_client)

    app = AgentDashboard()
    app._ensure_ws_client = AsyncMock(side_effect=RuntimeError("disconnected"))

    async with app.run_test() as pilot:
        await pilot.pause(0.1)

        app._chat_mode = True
        from openclaw_tui.chat import ChatState
        app._chat_state = ChatState(
            session_key="test-key", agent_id="main", session_info=MagicMock()
        )
        app._chat_state.is_busy = True

        await app._send_chat_message("test-key", "hello")

        assert app._chat_state.is_busy is False, (
            "is_busy must be cleared so the user can send further messages"
        )
        assert len(app._offline_message_queue) == 1


@pytest.mark.asyncio
async def test_queue_replay_requeues_on_failure(monkeypatch) -> None:
    """Failed sends during queue replay are re-queued, not dropped."""
    mock_client = _make_mock_client()
    monkeypatch.setattr("openclaw_tui.app.GatewayClient", lambda _: mock_client)

    app = AgentDashboard()

    async with app.run_test() as pilot:
        await pilot.pause(0.1)

        # Simulate a ws_client whose send_chat always fails
        fake_ws = MagicMock()
        fake_ws.send_chat = AsyncMock(side_effect=ConnectionError("gone"))
        app._ws_client = fake_ws

        queue = [
            ("key-1", "msg-1", [], "run-1", None),
            ("key-2", "msg-2", [], "run-2", None),
        ]

        await app._drain_offline_queue(queue)

        # Both messages should be re-queued
        assert len(app._offline_message_queue) == 2
        assert app._offline_message_queue[0][0] == "key-1"
        assert app._offline_message_queue[1][0] == "key-2"


@pytest.mark.asyncio
async def test_queue_replay_partial_failure(monkeypatch) -> None:
    """If first message succeeds and second fails, only the failed one is re-queued."""
    mock_client = _make_mock_client()
    monkeypatch.setattr("openclaw_tui.app.GatewayClient", lambda _: mock_client)

    app = AgentDashboard()

    async with app.run_test() as pilot:
        await pilot.pause(0.1)

        call_count = 0

        async def _send_chat_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ConnectionError("dropped")

        fake_ws = MagicMock()
        fake_ws.send_chat = AsyncMock(side_effect=_send_chat_side_effect)
        app._ws_client = fake_ws

        queue = [
            ("key-1", "msg-1", [], "run-1", None),
            ("key-2", "msg-2", [], "run-2", None),
        ]

        await app._drain_offline_queue(queue)

        # Only the second message should be re-queued
        assert len(app._offline_message_queue) == 1
        assert app._offline_message_queue[0][0] == "key-2"


@pytest.mark.asyncio
async def test_offline_queue_initialized_at_mount(monkeypatch) -> None:
    """_offline_message_queue exists from mount, no hasattr needed."""
    mock_client = _make_mock_client()
    monkeypatch.setattr("openclaw_tui.app.GatewayClient", lambda _: mock_client)

    app = AgentDashboard()

    async with app.run_test() as pilot:
        await pilot.pause(0.1)

        assert hasattr(app, "_offline_message_queue")
        assert app._offline_message_queue == []


@pytest.mark.asyncio
async def test_exit_chat_mode_clears_queue(monkeypatch) -> None:
    """Exiting chat mode clears any queued offline messages."""
    mock_client = _make_mock_client()
    monkeypatch.setattr("openclaw_tui.app.GatewayClient", lambda _: mock_client)

    app = AgentDashboard()

    async with app.run_test() as pilot:
        await pilot.pause(0.1)

        app._chat_mode = True
        from openclaw_tui.chat import ChatState
        app._chat_state = ChatState(
            session_key="test-key", agent_id="main", session_info=MagicMock()
        )
        app._offline_message_queue = [
            ("test-key", "stale msg", [], "run-stale", None),
        ]

        app._exit_chat_mode()

        assert app._offline_message_queue == []


@pytest.mark.asyncio
async def test_unrelated_runtime_error_not_caught(monkeypatch) -> None:
    """RuntimeError without connection keywords should not be caught as offline."""
    mock_client = _make_mock_client()
    monkeypatch.setattr("openclaw_tui.app.GatewayClient", lambda _: mock_client)

    app = AgentDashboard()
    app._ensure_ws_client = AsyncMock(side_effect=RuntimeError("some other bug"))

    async with app.run_test() as pilot:
        await pilot.pause(0.1)

        app._chat_mode = True
        from openclaw_tui.chat import ChatState
        app._chat_state = ChatState(
            session_key="test-key", agent_id="main", session_info=MagicMock()
        )

        with pytest.raises(RuntimeError, match="some other bug"):
            await app._send_chat_message("test-key", "hello")

        # Nothing should be queued for an unrelated error
        assert len(app._offline_message_queue) == 0


@pytest.mark.asyncio
async def test_drain_stops_when_client_goes_none(monkeypatch) -> None:
    """If ws_client becomes None mid-drain, remaining messages are re-queued."""
    mock_client = _make_mock_client()
    monkeypatch.setattr("openclaw_tui.app.GatewayClient", lambda _: mock_client)

    app = AgentDashboard()

    async with app.run_test() as pilot:
        await pilot.pause(0.1)

        call_count = 0

        async def _send_then_disconnect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                app._ws_client = None  # simulate mid-drain disconnect

        fake_ws = MagicMock()
        fake_ws.send_chat = AsyncMock(side_effect=_send_then_disconnect)
        app._ws_client = fake_ws

        queue = [
            ("key-1", "msg-1", [], "run-1", None),
            ("key-2", "msg-2", [], "run-2", None),
            ("key-3", "msg-3", [], "run-3", None),
        ]

        await app._drain_offline_queue(queue)

        # First message sent, but ws_client set to None after.
        # Remaining 2 messages should be re-queued.
        assert len(app._offline_message_queue) == 2
        assert app._offline_message_queue[0][0] == "key-2"
        assert app._offline_message_queue[1][0] == "key-3"
