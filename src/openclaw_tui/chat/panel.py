"""ChatPanel widget — interactive chat interface for selected sessions."""
from __future__ import annotations

from rich.console import RenderableType
from rich.markup import escape as escape_markup
from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static, RichLog, Input
from textual.message import Message
from textual.suggester import SuggestFromList

from .commands import command_suggestions
from openclaw_tui.models import ChatMessage


class ChatPanel(Vertical):
    """Interactive chat panel — replaces LogPanel in chat mode.

    Default state: shows "Select a session" in header, placeholder in log
    When populated: shows messages with role-based formatting
    """

    DEFAULT_CSS = """
    ChatPanel {
        height: 100%;
        background: #16213E;
        padding: 0 1;
    }
    #chat-header {
        height: 1;
        background: #1A1A2E;
        color: #F5A623;
        text-style: bold;
        padding: 0 1;
        border-bottom: solid #2A2E3D;
    }
    #chat-log {
        height: 1fr;
        border: round #2A2E3D;
        background: #16213E;
        padding: 0 1;
    }
    #chat-status {
        height: 1;
        color: #A8B5A2;
        padding: 0 1;
    }
    #chat-input {
        height: 3;
        border: round #2A2E3D;
        background: #1A1A2E;
        color: #FFF8E7;
    }
    #chat-input:focus {
        border: round #F5A623;
    }
    """

    _SPINNER_FRAMES = ("⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷")
    _SLASH_SUGGESTIONS = command_suggestions()

    class Submit(Message):
        """Message sent when user submits a message in the chat input."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    @staticmethod
    def _safe_markup_text(value: object) -> str:
        """Escape dynamic text before interpolating it into Rich markup."""
        return escape_markup(str(value))

    @staticmethod
    def _render_markdown(value: object) -> Markdown:
        """Render message content with Markdown formatting."""
        return Markdown(str(value), hyperlinks=True)

    def compose(self) -> ComposeResult:
        """Compose the chat panel with header, log, status, and input."""
        yield Static("Select a session", id="chat-header")
        yield RichLog(id="chat-log", wrap=True, highlight=True, markup=True)
        yield Static("[dim #A8B5A2]● connected[/]", id="chat-status")
        yield Input(
            placeholder="Ask your agent, or type /help",
            id="chat-input",
            suggester=SuggestFromList(self._SLASH_SUGGESTIONS, case_sensitive=False),
        )

    def on_mount(self) -> None:
        """Set up message handler on mount."""
        input_widget = self.query_one("#chat-input")
        input_widget.focus()
        self._spinner_index = 0

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission and post a message to the app."""
        if event.input.value:
            self.post_message(self.Submit(event.input.value))
            event.input.value = ""

    def set_header(self, text: str) -> None:
        """Update the header with refined rich formatting."""
        header = self.query_one("#chat-header")
        stripped = text.strip()
        safe_stripped = self._safe_markup_text(stripped)
        if stripped.lower() == "select a session":
            header.update("[dim #A8B5A2]Select a session[/]")
            return

        parts = [part.strip() for part in stripped.split("·")]
        if len(parts) >= 3:
            session_name, agent_id, model = parts[:3]
            selected_session = getattr(self.app, "_selected_session", None)
            total_tokens = getattr(selected_session, "total_tokens", None)
            token_label = f"{total_tokens:,} tokens" if isinstance(total_tokens, int) else session_name
            safe_agent_id = self._safe_markup_text(agent_id)
            safe_model = self._safe_markup_text(model)
            safe_token_label = self._safe_markup_text(token_label)
            header.update(
                f"[bold #F5A623]{safe_agent_id}[/] [dim #7B7F87]•[/] "
                f"[#A8B5A2]{safe_model}[/] [dim #7B7F87]•[/] [#C67B5C]{safe_token_label}[/]"
            )
            return

        header.update(f"[bold #F5A623]{safe_stripped}[/]")

    # Status patterns: (substring_match, display_label) - order matters for specificity
    _BUSY_PATTERNS = (
        ("loading history", "syncing history..."),
        ("waiting for response", "thinking..."),
        ("running shell command", "running shell..."),
        ("sending", "sending..."),
        ("aborting", "aborting..."),
        ("loading", "loading..."),
    )

    def set_status(self, text: str) -> None:
        """Update status with calm idle, alive busy, and clear error states."""
        status = self.query_one("#chat-status")
        lower = text.lower()

        # Error states (priority checks)
        if "connection lost" in lower:
            status.update("[bold #C67B5C]⚠ Connection lost[/]")
            return
        if "error" in lower:
            safe_error = self._safe_markup_text(text.replace("●", "").strip())
            status.update(f"[bold #C67B5C]⚠ {safe_error}[/]")
            return
        if "timeout" in lower:
            status.update("[bold #C67B5C]⚠ Timed out waiting for response[/]")
            return
        if "idle" in lower:
            status.update("[dim #A8B5A2]● connected[/]")
            return

        # Busy states - single pass pattern matching
        for pattern, label in self._BUSY_PATTERNS:
            if pattern in lower:
                frame = self._SPINNER_FRAMES[self._spinner_index % len(self._SPINNER_FRAMES)]
                self._spinner_index += 1
                status.update(f"[bold #F5A623]{frame}[/] [#A8B5A2]{label}[/]")
                return

        safe_text = self._safe_markup_text(text)
        status.update(f"[#A8B5A2]{safe_text}[/]")

    def _write_block(self, lines: list[RenderableType]) -> None:
        """Write a formatted block with one blank spacer line."""
        rich_log = self.query_one("#chat-log")
        for line in lines:
            rich_log.write(line)
        rich_log.write("")

    def append_message(self, msg: ChatMessage) -> None:
        """Render a message to the chat log with role-based formatting.

        Role blocks use subtle framing and spacing for readability.
        """
        safe_timestamp = self._safe_markup_text(msg.timestamp)
        if msg.role == "user":
            self._write_block([
                f"[#F5A623]┌─[/] [bold #F5A623]you[/] [dim #7B7F87]{safe_timestamp}[/]",
                self._render_markdown(msg.content),
            ])
        elif msg.role == "assistant":
            self._write_block([
                f"[#A8B5A2]┌─[/] [bold #A8B5A2]assistant[/] [dim #7B7F87]{safe_timestamp}[/]",
                self._render_markdown(msg.content),
            ])
        elif msg.role == "system":
            safe_content = self._safe_markup_text(msg.content)
            self._write_block([
                f"[dim #7B7F87]├─ SYSTEM {safe_timestamp}[/]",
                f"[dim #A8B5A2]{safe_content}[/]",
            ])
        elif msg.role == "tool":
            safe_content = self._safe_markup_text(msg.content)
            safe_tool_name = self._safe_markup_text(msg.tool_name or "tool")
            self._write_block([
                f"[dim #7B7F87]╭─ ⚙ {safe_tool_name} {safe_timestamp}[/]",
                f"[dim #A8B5A2]╰─ {safe_content}[/]",
            ])
        else:
            safe_content = self._safe_markup_text(msg.content)
            safe_role = self._safe_markup_text(msg.role)
            self._write_block([
                f"[dim #7B7F87]├─ {safe_role} {safe_timestamp}[/]",
                f"[dim #A8B5A2]{safe_content}[/]",
            ])

    def show_messages(self, messages: list[ChatMessage]) -> None:
        """Clear log and render all messages."""
        rich_log = self.query_one("#chat-log")
        rich_log.clear()

        for msg in messages:
            self.append_message(msg)

    def clear_log(self) -> None:
        """Clear the RichLog widget."""
        rich_log = self.query_one("#chat-log")
        rich_log.clear()

    def show_placeholder(self, text: str | None = None) -> None:
        """Show placeholder text in the log.

        Args:
            text: Optional custom placeholder text. Defaults to "Select a session".
        """
        rich_log = self.query_one("#chat-log")
        placeholder = text or "Select a session"
        safe_placeholder = self._safe_markup_text(placeholder)
        rich_log.clear()
        rich_log.write(f"[dim #7B7F87]┌─[/] [#A8B5A2]{safe_placeholder}[/]")
