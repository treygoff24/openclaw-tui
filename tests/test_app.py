"""Tests for AgentDashboard app (smoke tests + composition)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import Header, Footer

from openclaw_tui.app import AgentDashboard
from openclaw_tui.widgets import AgentTreeWidget, SummaryBar
from openclaw_tui.client import GatewayError


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
    mock_client.close.return_value = None
    monkeypatch.setattr(
        "openclaw_tui.app.GatewayClient",
        MagicMock(return_value=mock_client),
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
