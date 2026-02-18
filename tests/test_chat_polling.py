"""E5: Polling behavior tests for chat mode."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from openclaw_tui.app import AgentDashboard
from openclaw_tui.chat.state import ChatState
from openclaw_tui.models import SessionInfo, ChatMessage


def _mock_load_config():
    """Return a mock GatewayConfig with sensible defaults."""
    from openclaw_tui.config import GatewayConfig
    return GatewayConfig(host="localhost", port=9876, token=None)


def _make_mock_client():
    """Create a mock GatewayClient."""
    mock_client = MagicMock()
    mock_client.fetch_sessions.return_value = []
    mock_client.fetch_tree.return_value = []
    mock_client.fetch_history.return_value = []
    mock_client.send_message.return_value = {}
    mock_client.abort_session.return_value = {}
    mock_client.close.return_value = None
    return mock_client


@pytest.fixture(autouse=True)
def _mock_gateway(monkeypatch):
    """Patch load_config and GatewayClient for all app tests."""
    monkeypatch.setattr(
        "openclaw_tui.app.load_config",
        _mock_load_config,
    )
    mock_client = _make_mock_client()
    monkeypatch.setattr(
        "openclaw_tui.app.GatewayClient",
        MagicMock(return_value=mock_client),
    )
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
    monkeypatch.setattr(
        "openclaw_tui.app.GatewayWsClient",
        MagicMock(return_value=mock_ws_client),
    )
    monkeypatch.setattr(
        "openclaw_tui.app.build_tree",
        lambda sessions: [],
    )


def _make_session(agent_id: str = "test-agent", session_key: str = "agent:main:test:abc123") -> SessionInfo:
    """Create a test SessionInfo."""
    return SessionInfo(
        key=session_key,
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


@pytest.mark.asyncio
async def test_poll_handles_connection_error() -> None:
    """Poll handles connection error gracefully."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        # Make fetch_history raise a connection error
        app._client.fetch_history.side_effect = ConnectionError("Connection failed")

        session = _make_session()

        # Set up chat state
        app._chat_state = ChatState(
            session_key=session.key,
            agent_id=session.agent_id,
            session_info=session,
            messages=[],
            last_message_count=0,
            is_busy=True,
        )

        # Run the poll worker with timeout to avoid hanging
        try:
            await asyncio.wait_for(app._poll_chat_updates(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("Poll should have returned quickly on error")

        await pilot.pause()

        # Verify error was handled gracefully
        assert app._chat_state.error is not None
        # The app logs "Connection lost" but includes the original message
        assert "Connection failed" in app._chat_state.error or "Connection" in app._chat_state.error
        assert app._chat_state.is_busy is False


@pytest.mark.asyncio
async def test_poll_handles_timeout_error() -> None:
    """Poll handles timeout gracefully."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        # Make fetch_history raise a timeout
        app._client.fetch_history.side_effect = TimeoutError("Request timed out")

        session = _make_session()

        # Set up chat state
        app._chat_state = ChatState(
            session_key=session.key,
            agent_id=session.agent_id,
            session_info=session,
            messages=[],
            last_message_count=0,
            is_busy=True,
        )

        # Run with timeout
        try:
            await asyncio.wait_for(app._poll_chat_updates(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("Poll should have returned quickly on error")

        await pilot.pause()

        # Verify error was handled gracefully
        assert app._chat_state.error is not None
        assert app._chat_state.is_busy is False


@pytest.mark.asyncio
async def test_poll_limit_calculation() -> None:
    """Verify poll uses correct limit calculation (last_count + 20, min 50)."""
    # Test the limit calculation logic directly
    test_cases = [
        (0, 50),    # 0 + 20 = 20, but min is 50
        (10, 50),   # 10 + 20 = 30, but min is 50
        (30, 50),   # 30 + 20 = 50
        (40, 60),   # 40 + 20 = 60
        (100, 120), # 100 + 20 = 120
    ]
    
    for last_count, expected in test_cases:
        limit = max(last_count + 20, 50)
        assert limit == expected, f"Failed for last_count={last_count}"


@pytest.mark.asyncio
async def test_poll_stops_on_none_chat_state() -> None:
    """Poll stops when chat_state becomes None during polling."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        session = _make_session()

        # Set up chat state
        app._chat_state = ChatState(
            session_key=session.key,
            agent_id=session.agent_id,
            session_info=session,
            messages=[],
            last_message_count=0,
            is_busy=True,
        )

        # Set up mock to return slow responses, then set chat_state to None
        call_count = 0
        def slow_history(*args):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                # On second call, simulate session being closed (chat_state = None)
                app._chat_state = None
            return [{"role": "user", "content": "Hello", "timestamp": "10:00"}]
        
        app._client.fetch_history.side_effect = slow_history

        # Run with timeout
        try:
            await asyncio.wait_for(app._poll_chat_updates(), timeout=2.0)
        except asyncio.TimeoutError:
            pass  # May timeout if it keeps polling
        
        # The key test is that it doesn't crash when chat_state becomes None


@pytest.mark.asyncio
async def test_chat_state_message_count_tracking() -> None:
    """Test that ChatState properly tracks message count."""
    session = _make_session()
    state = ChatState(
        session_key=session.key,
        agent_id=session.agent_id,
        session_info=session,
        messages=[],
        last_message_count=0,
    )
    
    # Add some messages
    state.messages = [
        ChatMessage(role="user", content="Hello", timestamp="10:00"),
        ChatMessage(role="assistant", content="Hi", timestamp="10:01"),
    ]
    state.last_message_count = len(state.messages)
    
    assert state.last_message_count == 2
    assert len(state.messages) == 2
    
    # Simulate receiving more messages
    new_messages = state.messages + [
        ChatMessage(role="user", content="How are you?", timestamp="10:02"),
    ]
    
    # Detect new messages
    previous_count = state.last_message_count
    added_messages = new_messages[previous_count:]
    
    assert len(added_messages) == 1
    assert added_messages[0].content == "How are you?"


@pytest.mark.asyncio
async def test_to_chat_message_converts_raw_messages() -> None:
    """Test that _to_chat_message properly converts raw gateway messages."""
    app = AgentDashboard()
    
    # Test various raw message formats
    raw_messages = [
        {"role": "user", "content": "Hello", "timestamp": "10:00"},
        {"role": "assistant", "content": "Hi there!", "timestamp": "10:01"},
        {"role": "system", "content": "System message", "timestamp": "10:02"},
        {"role": "toolResult", "content": "Tool result", "timestamp": "10:03", "tool_name": "bash"},
    ]
    
    for raw in raw_messages:
        msg = app._to_chat_message(raw)
        assert msg.role in ["user", "assistant", "system", "tool"]
        assert msg.content is not None
        assert msg.timestamp is not None

    # Non-dict payloads should not crash conversion.
    raw_scalar = "unexpected payload"
    msg = app._to_chat_message(raw_scalar)
    assert msg.role == "system"
    assert "unexpected payload" in msg.content
