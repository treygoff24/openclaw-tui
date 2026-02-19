"""Tests for the LogPanel widget."""
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
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_panel_shows_placeholder_initially() -> None:
    """LogPanel.show_placeholder() writes the placeholder text."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)
        written = _capture_writes(panel, panel.show_placeholder)

        assert any("Select a session" in w for w in written), (
            f"Expected placeholder text in writes: {written}"
        )


@pytest.mark.asyncio
async def test_log_panel_show_transcript_formats_messages() -> None:
    """show_transcript() writes formatted message lines."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        msgs = [
            FakeMessage("user", "Hello world", "09:00"),
            FakeMessage("assistant", "Hi there", "09:01"),
        ]

        written = _capture_writes(panel, lambda: panel.show_transcript(msgs))
        combined = " ".join(written)

        assert "Hello world" in combined, f"User message content missing: {written}"
        assert "Hi there" in combined, f"Assistant message content missing: {written}"
        assert "09:00" in combined, f"User timestamp missing: {written}"
        assert "09:01" in combined, f"Assistant timestamp missing: {written}"


@pytest.mark.asyncio
async def test_log_panel_show_transcript_empty_shows_no_messages() -> None:
    """show_transcript() with empty list shows 'No messages found'."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        written = _capture_writes(panel, lambda: panel.show_transcript([]))

        assert any("No messages found" in w for w in written), (
            f"Expected 'No messages found' in writes: {written}"
        )


@pytest.mark.asyncio
async def test_log_panel_show_error_displays_error_text() -> None:
    """show_error() writes an error message containing the provided text."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        written = _capture_writes(panel, lambda: panel.show_error("Something went wrong"))
        combined = " ".join(written)

        assert "Something went wrong" in combined, f"Error text missing: {written}"
        assert "Error" in combined, f"'Error' label missing: {written}"


@pytest.mark.asyncio
async def test_log_panel_user_messages_have_cyan_styling() -> None:
    """User messages are formatted with [bold cyan] Rich markup."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        msgs = [FakeMessage("user", "Hello", "10:00")]
        written = _capture_writes(panel, lambda: panel.show_transcript(msgs))
        combined = " ".join(written)

        assert "bold cyan" in combined, f"[bold cyan] markup missing: {written}"
        assert "Hello" in combined, f"Message content missing: {written}"


@pytest.mark.asyncio
async def test_log_panel_assistant_messages_have_green_styling() -> None:
    """Assistant messages are formatted with [bold green] Rich markup."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        msgs = [FakeMessage("assistant", "Hi there", "10:00")]
        written = _capture_writes(panel, lambda: panel.show_transcript(msgs))
        combined = " ".join(written)

        assert "bold green" in combined, f"[bold green] markup missing: {written}"
        assert "Hi there" in combined, f"Message content missing: {written}"


@pytest.mark.asyncio
async def test_log_panel_tool_messages_have_dim_styling() -> None:
    """Tool (non user/assistant) messages are formatted with [dim] Rich markup."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        msgs = [FakeMessage("tool", "[tool: bash]", "10:00")]
        written = _capture_writes(panel, lambda: panel.show_transcript(msgs))
        combined = " ".join(written)

        assert "dim" in combined, f"[dim] markup missing: {written}"
        assert "[tool: bash]" in combined, f"Tool content missing: {written}"


@pytest.mark.asyncio
async def test_log_panel_escapes_markup_like_message_content() -> None:
    """Transcript content with Rich-like closing tags should be escaped."""
    app = LogPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(LogPanel)

        msgs = [FakeMessage("tool", "from docs [/concepts/session-pruning]", "10:00")]
        written = _capture_writes(panel, lambda: panel.show_transcript(msgs))
        combined = " ".join(written)

        assert "\\[/concepts/session-pruning]" in combined, f"Expected escaped closing tag in: {written}"
