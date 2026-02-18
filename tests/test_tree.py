from __future__ import annotations

import time
import pytest

from openclaw_tui.models import SessionInfo, AgentNode
from openclaw_tui.tree import build_tree


def make_session(key: str, **kwargs) -> SessionInfo:
    defaults = dict(
        key=key,
        kind="other",
        channel="webchat",
        display_name="agent",
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


class TestBuildTree:
    def test_empty_input_returns_empty_list(self):
        result = build_tree([])
        assert result == []

    def test_groups_sessions_by_agent_id(self):
        sessions = [
            make_session("agent:main:main"),
            make_session("agent:main:subagent:uuid-1"),
            make_session("agent:sonnet-worker:subagent:uuid-2"),
        ]

        result = build_tree(sessions)

        agent_ids = [node.agent_id for node in result]
        assert "main" in agent_ids
        assert "sonnet-worker" in agent_ids

        main_node = next(n for n in result if n.agent_id == "main")
        assert len(main_node.sessions) == 2

        sonnet_node = next(n for n in result if n.agent_id == "sonnet-worker")
        assert len(sonnet_node.sessions) == 1

    def test_main_agent_first(self):
        sessions = [
            make_session("agent:zebra-worker:main"),
            make_session("agent:alpha-worker:main"),
            make_session("agent:main:main"),
        ]

        result = build_tree(sessions)

        assert result[0].agent_id == "main"

    def test_remaining_agents_sorted_alphabetically(self):
        sessions = [
            make_session("agent:zebra-worker:main"),
            make_session("agent:alpha-worker:main"),
            make_session("agent:main:main"),
            make_session("agent:beta-worker:main"),
        ]

        result = build_tree(sessions)

        non_main = [n.agent_id for n in result[1:]]
        assert non_main == sorted(non_main)
        assert non_main == ["alpha-worker", "beta-worker", "zebra-worker"]

    def test_malformed_key_grouped_under_unknown(self):
        sessions = [
            make_session("no-colon-prefix"),
            make_session("also-malformed"),
        ]

        result = build_tree(sessions)

        assert len(result) == 1
        assert result[0].agent_id == "unknown"
        assert len(result[0].sessions) == 2

    def test_mixed_valid_and_malformed_keys(self):
        sessions = [
            make_session("agent:main:main"),
            make_session("bad-key-no-prefix"),
        ]

        result = build_tree(sessions)

        agent_ids = [n.agent_id for n in result]
        assert "main" in agent_ids
        assert "unknown" in agent_ids

    def test_main_before_unknown(self):
        """'main' should sort before 'unknown'."""
        sessions = [
            make_session("bad-key"),
            make_session("agent:main:main"),
        ]

        result = build_tree(sessions)

        assert result[0].agent_id == "main"

    def test_returns_list_of_agent_nodes(self):
        sessions = [make_session("agent:main:main")]

        result = build_tree(sessions)

        assert isinstance(result, list)
        assert all(isinstance(n, AgentNode) for n in result)

    def test_single_session_single_node(self):
        sessions = [make_session("agent:main:main")]

        result = build_tree(sessions)

        assert len(result) == 1
        assert result[0].agent_id == "main"
        assert len(result[0].sessions) == 1

    def test_sessions_within_node_preserve_order(self):
        """Sessions within an agent node should preserve insertion order."""
        sessions = [
            make_session("agent:main:main"),
            make_session("agent:main:subagent:aaa"),
            make_session("agent:main:subagent:bbb"),
        ]

        result = build_tree(sessions)

        main_sessions = result[0].sessions
        assert main_sessions[0].key == "agent:main:main"
        assert main_sessions[1].key == "agent:main:subagent:aaa"
        assert main_sessions[2].key == "agent:main:subagent:bbb"
