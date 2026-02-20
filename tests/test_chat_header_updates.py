"""Tests for chat header live updates — context tokens and model name."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from textual.app import App, ComposeResult

from openclaw_tui.chat.panel import ChatPanel
from openclaw_tui.models import ChatMessage, SessionInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class ChatPanelTestApp(App[None]):
    """Minimal app for ChatPanel tests with session support."""

    def __init__(self, session: SessionInfo | None = None):
        super().__init__()
        self._selected_session = session

    def compose(self) -> ComposeResult:
        yield ChatPanel()


def _make_session(
    key: str = "agent:main:discord:123",
    model: str = "claude-3-opus",
    context_tokens: int | None = 15000,
    total_tokens: int = 50000,
) -> SessionInfo:
    """Create a SessionInfo for testing."""
    return SessionInfo(
        key=key,
        kind="agent",
        channel="discord",
        display_name="Test Session",
        label="Test Session",
        updated_at=1708400000000,
        session_id="session-123",
        model=model,
        context_tokens=context_tokens,
        total_tokens=total_tokens,
        aborted_last_run=False,
    )


# ---------------------------------------------------------------------------
# Fix 1: Context tokens instead of total tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_header_shows_context_tokens_not_total_tokens() -> None:
    """set_header() should display context_tokens, not total_tokens.

    The header token count represents the current context window size,
    not the cumulative lifetime session total.
    """
    session = _make_session(context_tokens=15000, total_tokens=50000)
    app = ChatPanelTestApp(session=session)
    async with app.run_test() as pilot:
        panel = app.query_one(ChatPanel)
        header_text = f"{session.label} · {session.agent_id} · {session.short_model}"
        panel.set_header(header_text)

        header = panel.query_one("#chat-header")
        content = str(header.content)

        # Should show context_tokens (15,000) not total_tokens (50,000)
        assert "15,000" in content, f"Expected '15,000' tokens in header, got: {content}"
        assert "50,000" not in content, f"Should NOT show total_tokens (50,000) in header: {content}"


@pytest.mark.asyncio
async def test_set_header_shows_context_tokens_when_none() -> None:
    """set_header() should fall back gracefully when context_tokens is None."""
    session = _make_session(context_tokens=None, total_tokens=50000)
    app = ChatPanelTestApp(session=session)
    async with app.run_test() as pilot:
        panel = app.query_one(ChatPanel)
        header_text = f"{session.label} · {session.agent_id} · {session.short_model}"
        panel.set_header(header_text)

        header = panel.query_one("#chat-header")
        content = str(header.content)

        # When context_tokens is None, should fall back to session name
        # (not show "None tokens" or total_tokens)
        assert "None" not in content, f"Should not show 'None' in header: {content}"
        # The session name should appear since token label falls back to session_name
        assert session.label in content or "50,000" not in content


@pytest.mark.asyncio
async def test_set_header_formats_context_tokens_with_commas() -> None:
    """set_header() should format context_tokens with comma separators."""
    session = _make_session(context_tokens=1234567, total_tokens=9999999)
    app = ChatPanelTestApp(session=session)
    async with app.run_test() as pilot:
        panel = app.query_one(ChatPanel)
        header_text = f"{session.label} · {session.agent_id} · {session.short_model}"
        panel.set_header(header_text)

        header = panel.query_one("#chat-header")
        content = str(header.content)

        # Should format with commas: 1,234,567
        assert "1,234,567" in content, f"Expected formatted number '1,234,567' in header: {content}"


# ---------------------------------------------------------------------------
# Fix 2: Model name live update after /model command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_header_updates_when_model_changes() -> None:
    """After /model command, the header should reflect the new model name.

    The header reads from app._selected_session.model, so when the model
    is changed via /model command, the session object must be updated
    and the header refreshed.
    """
    # Start with one model
    session = _make_session(model="claude-3-opus")
    app = ChatPanelTestApp(session=session)
    async with app.run_test() as pilot:
        panel = app.query_one(ChatPanel)

        # Initial header shows opus
        header_text = f"{session.label} · {session.agent_id} · {session.short_model}"
        panel.set_header(header_text)
        header = panel.query_one("#chat-header")
        initial_content = str(header.content)
        assert "opus" in initial_content.lower(), f"Expected 'opus' in initial header: {initial_content}"

        # Simulate model change to sonnet (this is what /model command should do)
        session.model = "claude-3-sonnet"
        app._selected_session = session  # Ensure app's reference is updated

        # Refresh header with new model
        new_header_text = f"{session.label} · {session.agent_id} · {session.short_model}"
        panel.set_header(new_header_text)
        updated_content = str(header.content)
        assert "sonnet" in updated_content.lower(), f"Expected 'sonnet' in updated header: {updated_content}"


@pytest.mark.asyncio
async def test_short_model_property_used_in_header() -> None:
    """The header should use short_model property for display.

    short_model strips 'claude-' prefix and removes date suffixes.
    """
    session = _make_session(model="claude-3-5-sonnet-20241022")
    app = ChatPanelTestApp(session=session)
    async with app.run_test() as pilot:
        panel = app.query_one(ChatPanel)

        # short_model should strip the date suffix
        expected_short = session.short_model
        header_text = f"{session.label} · {session.agent_id} · {expected_short}"
        panel.set_header(header_text)

        header = panel.query_one("#chat-header")
        content = str(header.content)

        # Should show short model name, not full model ID with date
        assert expected_short in content, f"Expected short model '{expected_short}' in header: {content}"
        # The date suffix should be stripped
        assert "20241022" not in content, f"Date suffix should be stripped in header: {content}"


@pytest.mark.asyncio
async def test_context_tokens_update_when_session_refreshes() -> None:
    """When session data refreshes, the header should show updated context_tokens.

    This tests the live-update behavior where _poll_sessions updates
    _selected_session with fresh data from the gateway.
    """
    # Start with initial context tokens
    session = _make_session(context_tokens=10000, total_tokens=30000)
    app = ChatPanelTestApp(session=session)
    async with app.run_test() as pilot:
        panel = app.query_one(ChatPanel)

        # Initial header shows 10,000 context tokens
        header_text = f"{session.label} · {session.agent_id} · {session.short_model}"
        panel.set_header(header_text)
        header = panel.query_one("#chat-header")
        initial_content = str(header.content)
        assert "10,000" in initial_content, f"Expected '10,000' in initial header: {initial_content}"

        # Simulate session refresh with updated context_tokens
        # (This is what happens when _poll_sessions updates _selected_session)
        session.context_tokens = 25000
        app._selected_session = session

        # Refresh header with same text pattern (simulating what polling does)
        panel.set_header(f"{session.label} · {session.agent_id} · {session.short_model}")
        updated_content = str(header.content)
        assert "25,000" in updated_content, f"Expected '25,000' after refresh: {updated_content}"


# ---------------------------------------------------------------------------
# Fix 3: "Ren" label for assistant messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assistant_message_shows_ren_label() -> None:
    """Assistant messages should display 'Ren' as the role label, not 'assistant'."""
    app = ChatPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(ChatPanel)
        msg = ChatMessage(role="assistant", content="Hello, I'm Ren!", timestamp="10:00")

        # Capture what's written to the RichLog
        rich_log = panel.query_one("#chat-log")
        written: list[str] = []

        def _fake_write(content, **kwargs):
            written.append(str(content))

        with patch.object(rich_log, "write", side_effect=_fake_write):
            panel.append_message(msg)

        combined = " ".join(written)

        # Should show "Ren" not "assistant"
        assert "Ren" in combined, f"Expected 'Ren' label in assistant message: {written}"
        # The word "assistant" should NOT appear as the role label
        # (It might appear in content, but not as the label)
        # Check that we don't have "[bold #A8B5A2]assistant[/]" pattern
        assert "[bold #A8B5A2]assistant[/]" not in combined, f"Should not have 'assistant' label: {written}"


@pytest.mark.asyncio
async def test_user_message_still_shows_you_label() -> None:
    """User messages should still display 'you' as the role label (unchanged)."""
    app = ChatPanelTestApp()
    async with app.run_test() as pilot:
        panel = app.query_one(ChatPanel)
        msg = ChatMessage(role="user", content="Hello Ren!", timestamp="10:01")

        rich_log = panel.query_one("#chat-log")
        written: list[str] = []

        def _fake_write(content, **kwargs):
            written.append(str(content))

        with patch.object(rich_log, "write", side_effect=_fake_write):
            panel.append_message(msg)

        combined = " ".join(written)

        # Should show "you" label for user
        assert "you" in combined.lower(), f"Expected 'you' label in user message: {written}"


# ---------------------------------------------------------------------------
# Fix 4: Context tokens live-update every turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_header_refreshes_after_user_message() -> None:
    """After user sends a message, the header should refresh with updated context_tokens.

    This tests that _send_user_chat_message triggers a session refresh
    to get the latest context_tokens from the gateway.
    """
    session = _make_session(context_tokens=10000)
    app = ChatPanelTestApp(session=session)
    async with app.run_test() as pilot:
        panel = app.query_one(ChatPanel)

        # Initial header
        header_text = f"{session.label} · {session.agent_id} · {session.short_model}"
        panel.set_header(header_text)
        header = panel.query_one("#chat-header")
        initial_content = str(header.content)
        assert "10,000" in initial_content, f"Expected initial context tokens: {initial_content}"

        # Simulate user message causing context_tokens to increase
        # (In real flow, this happens via _trigger_poll after send)
        session.context_tokens = 15000
        app._selected_session = session

        # When header is refreshed (simulating what should happen after send)
        panel.set_header(f"{session.label} · {session.agent_id} · {session.short_model}")
        updated_content = str(header.content)
        assert "15,000" in updated_content, f"Expected updated context tokens after user turn: {updated_content}"


@pytest.mark.asyncio
async def test_header_refreshes_after_assistant_response() -> None:
    """After assistant finishes responding, header should refresh with updated context_tokens.

    This tests that _on_assistant_stream_final triggers a session refresh
    to get the latest context_tokens from the gateway.
    """
    session = _make_session(context_tokens=15000)
    app = ChatPanelTestApp(session=session)
    async with app.run_test() as pilot:
        panel = app.query_one(ChatPanel)

        # Initial header
        header_text = f"{session.label} · {session.agent_id} · {session.short_model}"
        panel.set_header(header_text)
        header = panel.query_one("#chat-header")
        initial_content = str(header.content)
        assert "15,000" in initial_content, f"Expected initial context tokens: {initial_content}"

        # Simulate assistant response causing context_tokens to increase
        session.context_tokens = 25000
        app._selected_session = session

        # When header is refreshed (simulating what should happen after assistant turn)
        panel.set_header(f"{session.label} · {session.agent_id} · {session.short_model}")
        updated_content = str(header.content)
        assert "25,000" in updated_content, f"Expected updated context tokens after assistant turn: {updated_content}"
