"""Tests for SummaryBar v2 - redesigned with Hearth-colored icons."""
from __future__ import annotations

import time

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer

from openclaw_tui.models import AgentNode, SessionInfo, SessionStatus
from openclaw_tui.widgets import AgentTreeWidget, SummaryBar


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

NOW_MS = int(time.time() * 1000)


def make_session(
    key: str = "agent:main:test",
    kind: str = "agent",
    display_name: str = "test-session",
    label: str | None = None,
    model: str = "claude-opus-4-6",
    total_tokens: int = 27_652,
    context_tokens: int | None = None,
    aborted: bool = False,
    active: bool = True,
) -> SessionInfo:
    updated_at = NOW_MS - (5_000 if active else 120_000)
    return SessionInfo(
        key=key,
        kind=kind,
        channel="webchat",
        display_name=display_name,
        label=label,
        updated_at=updated_at,
        session_id="sess-abc123",
        model=model,
        context_tokens=context_tokens,
        total_tokens=total_tokens,
        aborted_last_run=aborted,
    )


class WidgetTestApp(App[None]):
    """Minimal host app for widget tests."""

    def compose(self) -> ComposeResult:
        yield Header()
        yield AgentTreeWidget("Agents")
        yield SummaryBar("⚡ Connecting...")
        yield Footer()


# ---------------------------------------------------------------------------
# SummaryBar v2 tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_bar_shows_active_count() -> None:
    """update_summary displays active session count with amber ● icon."""
    app = WidgetTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(SummaryBar)

        session = make_session(key="a:main:s1", active=True)
        nodes = [AgentNode(agent_id="main", sessions=[session])]
        bar.update_summary(nodes, NOW_MS)
        await pilot.pause()

        text = bar._display_text
        # Check for the amber ● icon and count
        assert "●" in text
        assert "1 active" in text.lower()


@pytest.mark.asyncio
async def test_summary_bar_shows_idle_count() -> None:
    """update_summary displays idle session count with ○ icon."""
    app = WidgetTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(SummaryBar)

        session = make_session(key="a:main:s1", active=False)
        nodes = [AgentNode(agent_id="main", sessions=[session])]
        bar.update_summary(nodes, NOW_MS)
        await pilot.pause()

        text = bar._display_text
        assert "○" in text
        assert "1 idle" in text.lower()


@pytest.mark.asyncio
async def test_summary_bar_shows_aborted_count() -> None:
    """update_summary displays aborted session count with ⚠ icon."""
    app = WidgetTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(SummaryBar)

        session = make_session(key="a:main:s1", aborted=True)
        nodes = [AgentNode(agent_id="main", sessions=[session])]
        bar.update_summary(nodes, NOW_MS)
        await pilot.pause()

        text = bar._display_text
        assert "⚠" in text
        assert "1 aborted" in text.lower()


@pytest.mark.asyncio
async def test_summary_bar_shows_total() -> None:
    """update_summary displays total session count."""
    app = WidgetTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(SummaryBar)

        # 3 sessions total
        sessions = [
            make_session(key="a:main:s1", active=True),
            make_session(key="a:main:s2", active=False),
            make_session(key="a:main:s3", aborted=True),
        ]
        nodes = [AgentNode(agent_id="main", sessions=sessions)]
        bar.update_summary(nodes, NOW_MS)
        await pilot.pause()

        text = bar._display_text
        assert "3 total" in text.lower()


@pytest.mark.asyncio
async def test_summary_bar_update_with_tree_stats() -> None:
    """update_with_tree_stats method displays running/done/total format."""
    app = WidgetTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(SummaryBar)

        bar.update_with_tree_stats(active=2, completed=5, total=7)
        await pilot.pause()

        text = bar._display_text
        assert "2 running" in text.lower()
        assert "5 done" in text.lower()
        assert "7 total" in text.lower()


@pytest.mark.asyncio
async def test_summary_bar_error_shows_terracotta_icon() -> None:
    """set_error displays terracotta-colored ⚠ icon."""
    app = WidgetTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(SummaryBar)
        bar.set_error("Gateway unreachable")
        await pilot.pause()

        text = bar._display_text
        # Should have ⚠ in terracotta color (C67B5C)
        assert "⚠" in text
        assert "Gateway unreachable" in text


@pytest.mark.asyncio
async def test_summary_bar_initial_connecting_text() -> None:
    """Initial state contains connecting indicator."""
    app = WidgetTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(SummaryBar)
        # Default init shows "⚡ Connecting..."
        assert "⚡" in bar._display_text or "Connecting" in bar._display_text