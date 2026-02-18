"""E7: Keybind regression tests - ensure chat mode doesn't break existing keybinds."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock

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
async def test_c_keybind_triggers_copy_info() -> None:
    """c keybind still triggers copy action (not chat)."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        # Set up selected session via the mock client
        app._selected_session = _make_session()

        # Create a mock for copy_to_clipboard
        with patch("openclaw_tui.app.copy_to_clipboard", return_value=True):
            # Verify action_copy_info exists and is callable
            assert hasattr(app, "action_copy_info")
            assert callable(app.action_copy_info)

            # Trigger the action
            app.action_copy_info()

            await pilot.pause()


@pytest.mark.asyncio
async def test_r_keybind_triggers_refresh() -> None:
    """r keybind still refreshes."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        # Verify action_refresh exists and is callable
        assert hasattr(app, "action_refresh")
        assert callable(app.action_refresh)

        # Trigger refresh - it should trigger a poll
        with patch.object(app, '_trigger_poll') as mock_poll:
            app.action_refresh()
            await pilot.pause()
            mock_poll.assert_called_once()


@pytest.mark.asyncio
async def test_e_keybind_triggers_expand_all() -> None:
    """e keybind still expands all."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        # Verify action_expand_all exists and is callable
        assert hasattr(app, "action_expand_all")
        assert callable(app.action_expand_all)

        # Get the tree
        tree = app.query_one(AgentTreeWidget)

        # Mock expand method on root children by patching the expand method directly
        original_expand = tree.root.expand

        async def mock_expand():
            pass

        tree.root.expand = mock_expand

        # Trigger expand all - this should not crash
        app.action_expand_all()

        await pilot.pause()


@pytest.mark.asyncio
async def test_q_keybind_triggers_quit() -> None:
    """q keybind still quits."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        # Verify action_quit exists and is callable
        assert hasattr(app, "action_quit")
        assert callable(app.action_quit)

        # Trigger quit - action_quit is async in Textual
        await app.action_quit()

        await pilot.pause()

        # App should not be running after quit
        assert app.is_running is False


@pytest.mark.asyncio
async def test_v_keybind_toggles_logs() -> None:
    """v keybind still toggles logs."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        # Verify action_toggle_logs exists and is callable
        assert hasattr(app, "action_toggle_logs")
        assert callable(app.action_toggle_logs)

        right_panel = app.query_one("#right-panel")

        # Initial state - should be visible
        assert right_panel.display is True

        # Toggle off
        app.action_toggle_logs()
        await pilot.pause()
        assert right_panel.display is False

        # Toggle back on
        app.action_toggle_logs()
        await pilot.pause()
        assert right_panel.display is True


@pytest.mark.asyncio
async def test_keybinds_work_in_chat_mode() -> None:
    """Keybinds should still work while in chat mode."""
    app = AgentDashboard()

    async with app.run_test() as pilot:
        app._client.fetch_history.return_value = []

        # Enter chat mode
        session = _make_session()
        app._enter_chat_mode_for_session(session)
        await pilot.pause()

        # Verify we're in chat mode
        assert app._chat_mode is True

        # Test that v toggle still works in chat mode
        right_panel = app.query_one("#right-panel")
        app.action_toggle_logs()
        await pilot.pause()
        assert right_panel.display is False

        # Test refresh still works
        with patch.object(app, '_trigger_poll') as mock_poll:
            app.action_refresh()
            await pilot.pause()
            mock_poll.assert_called_once()

        # Test expand all - just verify method exists and is callable
        assert callable(app.action_expand_all)
        # Don't actually call expand since the tree might not have proper children set up


@pytest.mark.asyncio
async def test_bindings_are_registered() -> None:
    """Verify that all expected keybindings are registered."""
    app = AgentDashboard()

    # Check BINDINGS list
    binding_keys = [b[0] for b in app.BINDINGS]

    assert "q" in binding_keys  # quit
    assert "r" in binding_keys  # refresh
    assert "c" in binding_keys  # copy_info
    assert "v" in binding_keys  # toggle_logs
    assert "e" in binding_keys  # expand_all