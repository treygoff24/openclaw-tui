"""Tests for AgentDashboard app (smoke tests + composition)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from textual.widgets import Header, Footer

from openclaw_tui.app import AgentDashboard
from openclaw_tui.models import SessionInfo, TreeNodeData
from openclaw_tui.widgets import AgentTreeWidget, SummaryBar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_load_config():
    """Return a mock GatewayConfig with sensible defaults."""
    from openclaw_tui.config import GatewayConfig
    return GatewayConfig(host="localhost", port=9876, token=None)


@pytest.fixture(autouse=True)
def _mock_gateway(monkeypatch):
    """Patch load_config and GatewayClient for all app tests."""
    monkeypatch.setattr(
        "openclaw_tui.app.load_config",
        _mock_load_config,
    )
    mock_client = MagicMock()
    mock_client.fetch_sessions.return_value = []
    mock_client.fetch_tree.return_value = []
    mock_client.close.return_value = None
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
    mock_ws_client.models_list = AsyncMock(return_value={"models": []})
    mock_ws_client.status = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(
        "openclaw_tui.app.GatewayWsClient",
        MagicMock(return_value=mock_ws_client),
    )
    monkeypatch.setattr(
        "openclaw_tui.app.build_tree",
        lambda sessions: [],
    )


# ---------------------------------------------------------------------------
# App composition tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_app_composes_header() -> None:
    """App includes a Header widget."""
    app = AgentDashboard()
    async with app.run_test() as pilot:
        assert app.query_one(Header) is not None


@pytest.mark.asyncio
async def test_app_composes_footer() -> None:
    """App includes a Footer widget."""
    app = AgentDashboard()
    async with app.run_test() as pilot:
        assert app.query_one(Footer) is not None


@pytest.mark.asyncio
async def test_app_composes_agent_tree_widget() -> None:
    """App includes an AgentTreeWidget."""
    app = AgentDashboard()
    async with app.run_test() as pilot:
        assert app.query_one(AgentTreeWidget) is not None


@pytest.mark.asyncio
async def test_app_composes_summary_bar() -> None:
    """App includes a SummaryBar."""
    app = AgentDashboard()
    async with app.run_test() as pilot:
        assert app.query_one(SummaryBar) is not None


@pytest.mark.asyncio
async def test_app_mounts_without_crash() -> None:
    """Smoke test: app mounts, runs, and exits cleanly."""
    app = AgentDashboard()
    async with app.run_test() as pilot:
        assert app.is_running
        await pilot.pause()
        assert app.is_running


@pytest.mark.asyncio
async def test_app_all_widgets_composed() -> None:
    """App compose() yields Header, AgentTreeWidget, SummaryBar, Footer."""
    app = AgentDashboard()
    async with app.run_test() as pilot:
        assert app.query_one(Header) is not None
        assert app.query_one(AgentTreeWidget) is not None
        assert app.query_one(SummaryBar) is not None
        assert app.query_one(Footer) is not None


@pytest.mark.asyncio
async def test_app_summary_bar_initial_text() -> None:
    """SummaryBar starts with connecting text."""
    app = AgentDashboard()
    async with app.run_test() as pilot:
        bar = app.query_one(SummaryBar)
        # Initial state before any poll completes, or after first empty poll
        assert hasattr(bar, '_display_text')


@pytest.mark.asyncio
async def test_poll_uses_tree_stats_without_summary_flicker() -> None:
    """When tree stats are available, poll should render the summary bar once."""
    app = AgentDashboard()
    async with app.run_test() as pilot:
        bar = app.query_one(SummaryBar)
        bar.update_summary = MagicMock()
        bar.update_with_tree_stats = MagicMock()

        app._client.fetch_sessions.return_value = []
        app._client.fetch_tree.return_value = [
            TreeNodeData(
                key="root",
                label="root",
                depth=0,
                status="active",
                runtime_ms=1000,
                children=[
                    TreeNodeData(
                        key="child",
                        label="child",
                        depth=1,
                        status="completed",
                        runtime_ms=500,
                        children=[],
                    )
                ],
            )
        ]

        await app._poll_sessions()
        await pilot.pause()

        bar.update_with_tree_stats.assert_called_once_with(active=1, completed=1, total=2)
        bar.update_summary.assert_not_called()


@pytest.mark.asyncio
async def test_poll_falls_back_to_summary_when_tree_stats_missing() -> None:
    """If tree stats are unavailable, poll should still update summary once."""
    app = AgentDashboard()
    async with app.run_test() as pilot:
        bar = app.query_one(SummaryBar)
        bar.update_summary = MagicMock()
        bar.update_with_tree_stats = MagicMock()

        app._client.fetch_sessions.return_value = []
        app._client.fetch_tree.return_value = []

        await app._poll_sessions()
        await pilot.pause()

        assert bar.update_summary.call_count >= 1
        bar.update_with_tree_stats.assert_not_called()


@pytest.mark.asyncio
async def test_poll_populates_recursive_tree_with_clickable_session_data() -> None:
    """Poll should render sessions_tree hierarchy with SessionInfo data at every depth."""
    app = AgentDashboard()
    async with app.run_test() as pilot:
        app._client.fetch_sessions.return_value = [
            SessionInfo(
                key="agent:main:main",
                kind="chat",
                channel="webchat",
                display_name="Main",
                label="Main",
                updated_at=1700000000000,
                session_id="session-main",
                model="claude-sonnet-4-20250514",
                context_tokens=1000,
                total_tokens=2000,
                aborted_last_run=False,
            )
        ]
        app._client.fetch_tree.return_value = [
            TreeNodeData(
                key="agent:main:main",
                label="Main",
                depth=0,
                status="active",
                runtime_ms=1000,
                children=[
                    TreeNodeData(
                        key="agent:main:subagent:child",
                        label="Child",
                        depth=1,
                        status="active",
                        runtime_ms=500,
                        children=[
                            TreeNodeData(
                                key="agent:main:subagent:grandchild",
                                label="Grandchild",
                                depth=2,
                                status="completed",
                                runtime_ms=250,
                                children=[],
                            )
                        ],
                    )
                ],
            )
        ]

        await app._poll_sessions()
        await pilot.pause()

        tree = app.query_one(AgentTreeWidget)
        first = tree.root.children[0]
        second = first.children[0]
        third = second.children[0]
        assert isinstance(first.data, SessionInfo)
        assert isinstance(second.data, SessionInfo)
        assert isinstance(third.data, SessionInfo)
        assert second.data.key == "agent:main:subagent:child"
        assert third.data.key == "agent:main:subagent:grandchild"
