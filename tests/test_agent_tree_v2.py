"""Tests for AgentTreeWidget v2 — new rich label format with channel icons, relative time, and Hearth palette."""
from __future__ import annotations

import time

import pytest

from openclaw_tui.models import SessionInfo, SessionStatus
from openclaw_tui.widgets.agent_tree import _session_label, _channel_icon


NOW_MS = int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_session(
    key: str = "agent:main:test",
    channel: str = "discord",
    display_name: str = "test-session",
    label: str | None = "main-session",
    model: str = "claude-sonnet-4-6",
    total_tokens: int = 28_000,
    aborted: bool = False,
    active: bool = True,
) -> SessionInfo:
    updated_at = NOW_MS - (5_000 if active else 120_000)
    return SessionInfo(
        key=key,
        kind="agent",
        channel=channel,
        display_name=display_name,
        label=label,
        updated_at=updated_at,
        session_id="sess-abc123",
        model=model,
        context_tokens=None,
        total_tokens=total_tokens,
        aborted_last_run=aborted,
    )


# ---------------------------------------------------------------------------
# Channel icon tests (1–5)
# ---------------------------------------------------------------------------


def test_session_label_includes_channel_icon_discord() -> None:
    """Session with channel='discord' → label contains ⌨."""
    session = make_session(channel="discord", active=True)
    label = _session_label(session, NOW_MS)
    assert "⌨" in label


def test_session_label_includes_channel_icon_cron() -> None:
    """Channel containing 'cron' → label contains ⏱."""
    session = make_session(channel="cron:nightly-consolidation", active=True)
    label = _session_label(session, NOW_MS)
    assert "⏱" in label


def test_session_label_includes_channel_icon_hearth() -> None:
    """Session with channel='hearth' → label contains 🔥."""
    session = make_session(channel="hearth", active=True)
    label = _session_label(session, NOW_MS)
    assert "🔥" in label


def test_session_label_includes_channel_icon_webchat() -> None:
    """Session with channel='webchat' → label contains 🌐."""
    session = make_session(channel="webchat", active=True)
    label = _session_label(session, NOW_MS)
    assert "🌐" in label


def test_session_label_includes_channel_icon_unknown() -> None:
    """Session with unknown channel → label contains '·' (middle dot)."""
    session = make_session(channel="unknown", active=True)
    label = _session_label(session, NOW_MS)
    assert "·" in label


# ---------------------------------------------------------------------------
# Relative time test (6)
# ---------------------------------------------------------------------------


def test_session_label_includes_relative_time() -> None:
    """Recent session (updated < 30s ago) → label contains 'active'."""
    session = make_session(active=True)  # updated_at = NOW_MS - 5_000 (5s ago)
    label = _session_label(session, NOW_MS)
    assert "active" in label


# ---------------------------------------------------------------------------
# Token count test (7)
# ---------------------------------------------------------------------------


def test_session_label_includes_token_count() -> None:
    """27652 tokens → label contains '27K'."""
    session = make_session(total_tokens=27_652, active=True)
    label = _session_label(session, NOW_MS)
    assert "27K" in label


# ---------------------------------------------------------------------------
# Status markup / color tests (8–10)
# ---------------------------------------------------------------------------


def test_session_label_active_status_amber_markup() -> None:
    """Active session → label contains '#F5A623' (amber) or '●' icon."""
    session = make_session(active=True, aborted=False)
    label = _session_label(session, NOW_MS)
    assert "#F5A623" in label or "●" in label


def test_session_label_aborted_status_terracotta() -> None:
    """Aborted session → label contains '#C67B5C' (terracotta) or '⚠' icon."""
    session = make_session(aborted=True, active=False)
    label = _session_label(session, NOW_MS)
    assert "#C67B5C" in label or "⚠" in label


def test_session_label_idle_status_sage() -> None:
    """Idle session (updated > 30s ago) → label contains '#A8B5A2' (sage) or '○' icon."""
    session = make_session(active=False, aborted=False)  # updated 120s ago → IDLE
    label = _session_label(session, NOW_MS)
    assert "#A8B5A2" in label or "○" in label
