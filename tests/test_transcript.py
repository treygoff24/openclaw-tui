from __future__ import annotations

import json
from pathlib import Path

import pytest

from openclaw_tui.transcript import TranscriptMessage, read_transcript


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_jsonl(tmp_path: Path, agent_id: str, session_id: str, lines: list[dict]) -> Path:
    """Write a JSONL transcript file and return its path."""
    session_dir = tmp_path / "agents" / agent_id / "sessions"
    session_dir.mkdir(parents=True)
    file_path = session_dir / f"{session_id}.jsonl"
    file_path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return file_path


def msg_line(role: str, content, timestamp: str = "2024-01-15T14:30:00.000Z") -> dict:
    return {
        "type": "message",
        "timestamp": timestamp,
        "message": {"role": role, "content": content},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReadTranscriptMissingFile:
    def test_returns_empty_list_when_file_not_found(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)
        result = read_transcript("nonexistent-session", "main")
        assert result == []


class TestReadTranscriptFiltering:
    def test_only_message_lines_returned(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)

        lines = [
            {"type": "session", "data": "some session info"},
            msg_line("user", "hello"),
            {"type": "custom", "whatever": 42},
            msg_line("assistant", "world"),
        ]
        make_jsonl(tmp_path, "main", "sess1", lines)

        result = read_transcript("sess1", "main")
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[1].role == "assistant"


class TestReadTranscriptRoleMapping:
    def test_user_role(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)
        make_jsonl(tmp_path, "main", "sess", [msg_line("user", "hi")])
        result = read_transcript("sess", "main")
        assert result[0].role == "user"

    def test_assistant_role(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)
        make_jsonl(tmp_path, "main", "sess", [msg_line("assistant", "hi back")])
        result = read_transcript("sess", "main")
        assert result[0].role == "assistant"

    def test_tool_result_role_mapped_to_tool(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)
        make_jsonl(tmp_path, "main", "sess", [msg_line("toolResult", "some result")])
        result = read_transcript("sess", "main")
        assert result[0].role == "tool"


class TestReadTranscriptStringContent:
    def test_string_content_used_directly(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)
        make_jsonl(tmp_path, "main", "sess", [msg_line("user", "Hello, world!")])
        result = read_transcript("sess", "main")
        assert result[0].content == "Hello, world!"


class TestReadTranscriptListContent:
    def test_extracts_text_from_text_block(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)
        content = [{"type": "text", "text": "Block text here"}]
        make_jsonl(tmp_path, "main", "sess", [msg_line("assistant", content)])
        result = read_transcript("sess", "main")
        assert result[0].content == "Block text here"

    def test_formats_tool_call_block(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)
        content = [{"type": "toolCall", "name": "exec"}]
        make_jsonl(tmp_path, "main", "sess", [msg_line("assistant", content)])
        result = read_transcript("sess", "main")
        assert result[0].content == "[tool: exec]"


class TestReadTranscriptLimit:
    def test_respects_limit_parameter(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)

        lines = [msg_line("user", f"message {i}") for i in range(30)]
        make_jsonl(tmp_path, "main", "sess", lines)

        result = read_transcript("sess", "main", limit=5)
        assert len(result) == 5

    def test_returns_last_n_messages(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)

        lines = [msg_line("user", f"message {i}") for i in range(10)]
        make_jsonl(tmp_path, "main", "sess", lines)

        result = read_transcript("sess", "main", limit=3)
        assert len(result) == 3
        assert result[0].content == "message 7"
        assert result[1].content == "message 8"
        assert result[2].content == "message 9"


class TestReadTranscriptTruncation:
    def test_truncates_content_to_max_content_len(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)
        long_text = "x" * 500
        make_jsonl(tmp_path, "main", "sess", [msg_line("user", long_text)])
        result = read_transcript("sess", "main", max_content_len=50)
        assert len(result[0].content) == 50
        assert result[0].content == "x" * 50


class TestReadTranscriptTimestamp:
    def test_extracts_hhmm_from_iso_timestamp(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)
        line = msg_line("user", "hi", timestamp="2024-03-22T09:45:30.123Z")
        make_jsonl(tmp_path, "main", "sess", [line])
        result = read_transcript("sess", "main")
        assert result[0].timestamp == "09:45"


class TestReadTranscriptMalformedLines:
    def test_skips_invalid_json_lines(self, tmp_path, monkeypatch):
        import openclaw_tui.transcript as t
        monkeypatch.setattr(t, "OPENCLAW_DIR", tmp_path)

        session_dir = tmp_path / "agents" / "main" / "sessions"
        session_dir.mkdir(parents=True)
        file_path = session_dir / "sess.jsonl"
        # Mix of valid and invalid JSON
        file_path.write_text(
            '{"type": "message", "timestamp": "2024-01-01T10:00:00Z", "message": {"role": "user", "content": "good"}}\n'
            "NOT VALID JSON AT ALL\n"
            '{"type": "message", "timestamp": "2024-01-01T11:00:00Z", "message": {"role": "assistant", "content": "also good"}}\n',
            encoding="utf-8",
        )

        result = read_transcript("sess", "main")
        assert len(result) == 2
        assert result[0].content == "good"
        assert result[1].content == "also good"
