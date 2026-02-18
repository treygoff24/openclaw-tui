from __future__ import annotations

import time
import pytest

from openclaw_tui.models import SessionInfo, AgentNode, SessionStatus, STATUS_ICONS, STATUS_STYLES


def make_session(**kwargs) -> SessionInfo:
    defaults = dict(
        key="agent:main:main",
        kind="other",
        channel="webchat",
        display_name="test-agent",
        label=None,
        updated_at=int(time.time() * 1000),
        session_id="abc-123",
        model="claude-opus-4-6",
        context_tokens=150000,
        total_tokens=1000,
        aborted_last_run=False,
    )
    defaults.update(kwargs)
    return SessionInfo(**defaults)


class TestSessionInfoStatus:
    def test_aborted_when_aborted_last_run(self):
        now_ms = int(time.time() * 1000)
        # Even updated just now, aborted_last_run=True → ABORTED
        session = make_session(aborted_last_run=True, updated_at=now_ms)
        assert session.status(now_ms) == SessionStatus.ABORTED

    def test_active_when_updated_less_than_30s_ago(self):
        now_ms = int(time.time() * 1000)
        updated_at = now_ms - 10_000  # 10 seconds ago
        session = make_session(aborted_last_run=False, updated_at=updated_at)
        assert session.status(now_ms) == SessionStatus.ACTIVE

    def test_idle_when_updated_more_than_30s_ago(self):
        now_ms = int(time.time() * 1000)
        updated_at = now_ms - 60_000  # 60 seconds ago
        session = make_session(aborted_last_run=False, updated_at=updated_at)
        assert session.status(now_ms) == SessionStatus.IDLE

    def test_aborted_takes_priority_over_active_timing(self):
        """aborted_last_run=True should trump recency."""
        now_ms = int(time.time() * 1000)
        updated_at = now_ms - 5_000  # 5 seconds ago (would be ACTIVE)
        session = make_session(aborted_last_run=True, updated_at=updated_at)
        assert session.status(now_ms) == SessionStatus.ABORTED

    def test_boundary_exactly_30s_is_idle(self):
        now_ms = int(time.time() * 1000)
        updated_at = now_ms - 30_000  # exactly 30s ago — not *less* than 30s
        session = make_session(aborted_last_run=False, updated_at=updated_at)
        assert session.status(now_ms) == SessionStatus.IDLE


class TestSessionInfoShortModel:
    def test_strips_claude_prefix(self):
        session = make_session(model="claude-opus-4-6")
        assert session.short_model == "opus-4-6"

    def test_strips_date_suffix(self):
        session = make_session(model="claude-sonnet-4-5-20250929")
        assert session.short_model == "sonnet-4-5"

    def test_no_claude_prefix_unchanged(self):
        session = make_session(model="opus-4-6")
        assert session.short_model == "opus-4-6"

    def test_date_suffix_must_be_8_digits(self):
        # A suffix that's not 8 digits should NOT be stripped
        session = make_session(model="claude-haiku-123")
        assert session.short_model == "haiku-123"

    def test_strips_both_prefix_and_date(self):
        session = make_session(model="claude-haiku-4-5-20251001")
        assert session.short_model == "haiku-4-5"


class TestSessionInfoContextLabel:
    def test_extracts_context_from_standard_key(self):
        session = make_session(key="agent:main:main")
        assert session.context_label == "main"

    def test_extracts_nested_context(self):
        session = make_session(key="agent:main:cron:some-uuid-here")
        assert session.context_label == "cron:some-uuid-here"

    def test_subagent_context(self):
        session = make_session(key="agent:sonnet-worker:subagent:88db67f5-5cd6-4a2e-b4c3-452897f9a207")
        assert session.context_label == "subagent:88db67f5-5cd6-4a2e-b4c3-452897f9a207"

    def test_malformed_key_returns_key(self):
        session = make_session(key="no-colons-here")
        assert session.context_label == "no-colons-here"

    def test_two_part_key_returns_key(self):
        session = make_session(key="agent:main")
        assert session.context_label == "agent:main"


class TestStatusConstants:
    def test_status_icons_defined(self):
        assert STATUS_ICONS[SessionStatus.ACTIVE] == "●"
        assert STATUS_ICONS[SessionStatus.IDLE] == "○"
        assert STATUS_ICONS[SessionStatus.ABORTED] == "⚠"

    def test_status_styles_defined(self):
        assert STATUS_STYLES[SessionStatus.ACTIVE] == "green"
        assert STATUS_STYLES[SessionStatus.IDLE] == "dim"
        assert STATUS_STYLES[SessionStatus.ABORTED] == "yellow"


class TestSessionInfoAgentId:
    def test_extracts_main_from_agent_main_main(self):
        session = make_session(key="agent:main:main")
        assert session.agent_id == "main"

    def test_extracts_sonnet_worker_from_subagent_key(self):
        session = make_session(key="agent:sonnet-worker:subagent:some-uuid")
        assert session.agent_id == "sonnet-worker"

    def test_returns_unknown_for_malformed_key(self):
        session = make_session(key="no-colons-here")
        assert session.agent_id == "unknown"


class TestAgentNode:
    def test_display_name_returns_agent_id(self):
        node = AgentNode(agent_id="main")
        assert node.display_name == "main"

    def test_sessions_default_empty(self):
        node = AgentNode(agent_id="main")
        assert node.sessions == []

    def test_sessions_can_be_set(self):
        session = make_session()
        node = AgentNode(agent_id="main", sessions=[session])
        assert len(node.sessions) == 1
