from __future__ import annotations

import time
import pytest

from openclaw_tui.models import SessionInfo, TreeNodeData, format_runtime


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


# === TreeNodeData Tests ===

class TestTreeNodeData:
    def test_tree_node_data_has_required_fields(self):
        """Can create TreeNodeData with key, label, depth, status, runtime_ms"""
        node = TreeNodeData(
            key="agent:main",
            label="Main Agent",
            depth=0,
            status="active",
            runtime_ms=15000
        )
        assert node.key == "agent:main"
        assert node.label == "Main Agent"
        assert node.depth == 0
        assert node.status == "active"
        assert node.runtime_ms == 15000

    def test_tree_node_data_children_default_empty(self):
        """children defaults to empty list"""
        node = TreeNodeData(
            key="agent:main",
            label="Main Agent",
            depth=0,
            status="active",
            runtime_ms=1000
        )
        assert node.children == []

    def test_tree_node_data_nested_children(self):
        """Can nest TreeNodeData in children"""
        child = TreeNodeData(
            key="agent:main:sub",
            label="Sub Agent",
            depth=1,
            status="completed",
            runtime_ms=5000
        )
        parent = TreeNodeData(
            key="agent:main",
            label="Main Agent",
            depth=0,
            status="active",
            runtime_ms=10000,
            children=[child]
        )
        assert len(parent.children) == 1
        assert parent.children[0].key == "agent:main:sub"
        assert parent.children[0].depth == 1

    def test_tree_node_data_status_values(self):
        """status field accepts 'active', 'completed', 'failed' strings"""
        active_node = TreeNodeData(key="1", label="a", depth=0, status="active", runtime_ms=0)
        completed_node = TreeNodeData(key="2", label="b", depth=0, status="completed", runtime_ms=0)
        failed_node = TreeNodeData(key="3", label="c", depth=0, status="failed", runtime_ms=0)
        
        assert active_node.status == "active"
        assert completed_node.status == "completed"
        assert failed_node.status == "failed"


# === SessionInfo.transcript_path Tests ===

class TestSessionInfoTranscriptPath:
    def test_session_info_has_transcript_path_field(self):
        """SessionInfo can be created with transcript_path=None (default)"""
        session = make_session()
        assert hasattr(session, 'transcript_path')
        assert session.transcript_path is None

    def test_session_info_transcript_path_accepts_string(self):
        """transcript_path accepts a string path"""
        session = make_session(transcript_path="/path/to/transcript.json")
        assert session.transcript_path == "/path/to/transcript.json"

    def test_session_info_existing_fields_unchanged(self):
        """all existing SessionInfo fields still work"""
        now = int(time.time() * 1000)
        session = make_session(
            key="agent:test:test",
            kind="subagent",
            channel="discord",
            display_name="Test Agent",
            label="test-label",
            updated_at=now,
            session_id="xyz-789",
            model="claude-sonnet-4-5",
            context_tokens=200000,
            total_tokens=5000,
            aborted_last_run=True,
            transcript_path=None
        )
        
        assert session.key == "agent:test:test"
        assert session.kind == "subagent"
        assert session.channel == "discord"
        assert session.display_name == "Test Agent"
        assert session.label == "test-label"
        assert session.updated_at == now
        assert session.session_id == "xyz-789"
        assert session.model == "claude-sonnet-4-5"
        assert session.context_tokens == 200000
        assert session.total_tokens == 5000
        assert session.aborted_last_run is True
        assert session.transcript_path is None


# === format_runtime Tests ===

class TestFormatRuntime:
    def test_format_runtime_seconds(self):
        """1000ms → '1s'"""
        assert format_runtime(1000) == "1s"

    def test_format_runtime_minutes(self):
        """199554ms → '3m20s'"""
        assert format_runtime(199554) == "3m20s"

    def test_format_runtime_hours(self):
        """3661000ms → '1h1m'"""
        assert format_runtime(3661000) == "1h1m"

    def test_format_runtime_zero(self):
        """0ms → '0s'"""
        assert format_runtime(0) == "0s"