"""E6: App integration tests for chat mode."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openclaw_tui.app import AgentDashboard
from openclaw_tui.widgets import AgentTreeWidget, ChatPanel, LogPanel
from openclaw_tui.models import SessionInfo


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
async def test_select_tree_node_opens_chat_mode() -> None:
    """Selecting a tree node and pressing Enter opens chat mode."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        # Configure the mock client from the fixture
        app._client.fetch_history.return_value = []

        # Set up a mock tree node with a session
        session = _make_session()

        # Manually set chat mode by simulating node selection
        app._enter_chat_mode_for_session(session)

        await pilot.pause()

        # Verify chat mode is active
        assert app._chat_mode is True
        assert app._chat_state is not None

        # Verify ChatPanel is visible and LogPanel is hidden
        chat_panel = app.query_one(ChatPanel)
        log_panel = app.query_one(LogPanel)
        assert chat_panel.display is True
        assert log_panel.display is False


@pytest.mark.asyncio
async def test_escape_in_chat_mode_empty_input_returns_to_transcript() -> None:
    """Pressing Escape in chat mode with empty input returns to transcript mode."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        app._client.fetch_history.return_value = []

        session = _make_session()
        app._enter_chat_mode_for_session(session)

        await pilot.pause()

        # Verify we're in chat mode
        assert app._chat_mode is True

        # Simulate empty input and press Escape
        input_widget = app.query_one("#chat-input")
        input_widget.value = ""

        # Press Escape key
        await pilot.press("escape")

        await pilot.pause()

        # Verify we exited chat mode
        assert app._chat_mode is False


@pytest.mark.asyncio
async def test_v_toggle_works_in_chat_mode() -> None:
    """v toggle works in chat mode."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        app._client.fetch_history.return_value = []

        session = _make_session()
        app._enter_chat_mode_for_session(session)

        await pilot.pause()

        # Get initial right panel state
        right_panel = app.query_one("#right-panel")

        # Toggle using action
        app.action_toggle_logs()

        await pilot.pause()

        # Right panel should now be hidden
        assert right_panel.display is False

        # Toggle again
        app.action_toggle_logs()

        await pilot.pause()

        # Right panel should be visible again
        assert right_panel.display is True


@pytest.mark.asyncio
async def test_tree_still_polls_while_in_chat_mode() -> None:
    """Existing tree still polls while in chat mode (mock the client)."""
    app = AgentDashboard()
    fetch_call_count = 0

    def counting_fetch_sessions(*args, **kwargs):
        nonlocal fetch_call_count
        fetch_call_count += 1
        return []

    async with app.run_test() as pilot:
        # Replace the fetch_sessions with our counter
        app._client.fetch_sessions = counting_fetch_sessions

        # First, get into chat mode
        session = _make_session()
        app._enter_chat_mode_for_session(session)

        # Wait for at least one poll to happen
        await pilot.pause()

        # Trigger another poll manually to simulate the interval
        app._trigger_poll()

        await pilot.pause()

        # Verify fetch_sessions was called (poll happened)
        assert fetch_call_count > 0


@pytest.mark.asyncio
async def test_escape_with_non_empty_input_does_not_exit() -> None:
    """Escape in chat mode with non-empty input does NOT exit chat mode."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        app._client.fetch_history.return_value = []

        session = _make_session()
        app._enter_chat_mode_for_session(session)

        await pilot.pause()

        # Verify we're in chat mode
        assert app._chat_mode is True

        # Set non-empty input
        input_widget = app.query_one("#chat-input")
        input_widget.value = "some text"

        # Try to trigger exit (should not exit)
        await pilot.press("escape")

        await pilot.pause()

        # Verify we're still in chat mode
        assert app._chat_mode is True


@pytest.mark.asyncio
async def test_chat_history_loaded_on_session_select() -> None:
    """Chat history is loaded when selecting a session."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        # Return some mock history
        app._client.fetch_history.return_value = [
            {"role": "user", "content": "Hello", "timestamp": "10:00"},
            {"role": "assistant", "content": "Hi there!", "timestamp": "10:01"},
        ]

        session = _make_session()
        app._enter_chat_mode_for_session(session)

        # Let the history load
        await pilot.pause()
        await pilot.pause()

        # Verify fetch_history was called
        assert app._client.fetch_history.called

        # Verify chat state has messages
        assert app._chat_state is not None
        assert len(app._chat_state.messages) == 2


@pytest.mark.asyncio
async def test_empty_chat_history_is_not_treated_as_error() -> None:
    """Empty history should show a normal placeholder and keep status idle."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        app._client.fetch_history.return_value = []
        app._client.last_history_error = None

        session = _make_session()
        app._enter_chat_mode_for_session(session)

        await pilot.pause()
        await pilot.pause()

        assert app._chat_state is not None
        assert app._chat_state.error is None

        status = app.query_one("#chat-status")
        assert "connected" in str(status.content).lower()


@pytest.mark.asyncio
async def test_history_load_error_is_shown_with_details() -> None:
    """History fetch errors should be visible in status/error state."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        app._client.fetch_history.return_value = []
        app._client.last_history_error = "Gateway returned HTTP 422: invalid session key"

        session = _make_session()
        app._enter_chat_mode_for_session(session)

        await pilot.pause()
        await pilot.pause()

        assert app._chat_state is not None
        assert app._chat_state.error == "Gateway returned HTTP 422: invalid session key"

        status = app.query_one("#chat-status")
        rendered = str(status.content).lower()
        assert "invalid session key" in rendered
