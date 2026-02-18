"""Tests for LogPanel v2 redesign - metadata header and role icons."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult

from openclaw_tui.widgets.log_panel import LogPanel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class LogPanelTestApp(App[None]):
    """Minimal app for LogPanel tests."""

    def compose(self) -> ComposeResult:
        yield LogPanel()


class FakeMessage:
    """Stand-in for TranscriptMessage in tests."""

    def __init__(self, role: str, content: str, timestamp: str = "10:00") -> None:
        self.role = role
        self.content = content
        self.timestamp = timestamp


class FakeSessionInfo:
    """Stand-in for SessionInfo in tests."""

    def __init__(
        self,
        key: str = "agent:main:discord:123",
        updated_at: int = 1700000000000,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self.key = key
        self.updated_at = updated_at
        self.model = model

    @property
    def short_model(self) -> str:
        name = self.model.replace("claude-", "")
        parts = name.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 8:
            name = parts[0]
        return name

    @property
    def agent_id(self) -> str:
        """Extract agent_id from key. 'agent:main:cron:UUID' → 'main'."""
        parts = self.key.split(":", 2)
        return parts[1] if len(parts) >= 2 else "unknown"


def _capture_writes(panel: LogPanel, fn) -> list[str]:
    """Call fn() while intercepting all LogPanel.write() calls.

    Returns a list of string representations of each write argument.
    """
    written: list[str] = []

    def _fake_write(content, **kwargs):
        written.append(str(content))

    with patch.object(panel, "write", side_effect=_fake_write):
        fn()

    return written


# ---------------------------------------------------------------------------
# Tests for v2 features
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_show_transcript_with_metadata_writes_header() -> None:
    """When show_transcript is called with session_info kwarg, first line contains agent: and model:."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        session_info = FakeSessionInfo(key="agent:main:discord:123", model="claude-sonnet-4-20250514")
        messages = [FakeMessage("user", "Hello", "10:00")]

        # Mock relative_time to return predictable output
        with patch("openclaw_tui.widgets.log_panel.relative_time", return_value="5m ago"):
            written = _capture_writes(panel, lambda: panel.show_transcript(messages, session_info=session_info))

        combined = " ".join(written)
        assert "agent:" in combined.lower(), f"Expected 'agent:' in header: {written}"
        assert "model:" in combined.lower(), f"Expected 'model:' in header: {written}"


@pytest.mark.asyncio
async def test_show_transcript_user_role_uses_circle_icon() -> None:
    """User message line contains circle icon ◉."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        messages = [FakeMessage("user", "Hello world", "10:00")]

        written = _capture_writes(panel, lambda: panel.show_transcript(messages))
        combined = " ".join(written)

        assert "◉" in combined, f"Expected ◉ circle icon for user role: {written}"


@pytest.mark.asyncio
async def test_show_transcript_assistant_role_uses_diamond_icon() -> None:
    """Assistant message line contains diamond icon ◆."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        messages = [FakeMessage("assistant", "Hi there", "10:00")]

        written = _capture_writes(panel, lambda: panel.show_transcript(messages))
        combined = " ".join(written)

        assert "◆" in combined, f"Expected ◆ diamond icon for assistant role: {written}"


@pytest.mark.asyncio
async def test_show_transcript_tool_role_uses_dot_icon() -> None:
    """Tool (non user/assistant) message line contains dot icon ·."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        messages = [FakeMessage("tool", "[tool: bash]", "10:00")]

        written = _capture_writes(panel, lambda: panel.show_transcript(messages))
        combined = " ".join(written)

        assert "·" in combined, f"Expected · dot icon for tool role: {written}"


@pytest.mark.asyncio
async def test_show_placeholder_shows_moon_emoji() -> None:
    """Placeholder text contains moon emoji 🌘."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        written = _capture_writes(panel, panel.show_placeholder)
        combined = " ".join(written)

        assert "🌘" in combined, f"Expected 🌘 moon emoji in placeholder: {written}"


@pytest.mark.asyncio
async def test_show_transcript_empty_messages_with_metadata() -> None:
    """No messages but session_info provided shows 'No messages' NOT placeholder."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        session_info = FakeSessionInfo(key="agent:main:discord:123", model="claude-sonnet-4-20250514")

        with patch("openclaw_tui.widgets.log_panel.relative_time", return_value="5m ago"):
            written = _capture_writes(panel, lambda: panel.show_transcript([], session_info=session_info))

        combined = " ".join(written)
        # Should NOT show the placeholder moon emoji
        assert "🌘" not in combined, f"Should NOT show placeholder when session_info provided: {written}"
        # Should show "No messages" instead
        assert "No messages" in combined, f"Expected 'No messages' text: {written}"


@pytest.mark.asyncio
async def test_show_transcript_backward_compat_no_session_info() -> None:
    """Calling show_transcript(messages) without session_info still works (backward compat)."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        # Old call signature - just messages, no session_info
        messages = [
            FakeMessage("user", "Hello", "09:00"),
            FakeMessage("assistant", "Hi there", "09:01"),
        ]

        # Should not raise any errors
        written = _capture_writes(panel, lambda: panel.show_transcript(messages))

        combined = " ".join(written)
        assert "Hello" in combined, f"User message content missing: {written}"
        assert "Hi there" in combined, f"Assistant message content missing: {written}"