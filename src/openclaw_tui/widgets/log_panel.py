"""LogPanel widget — right-side transcript viewer for selected sessions."""
from __future__ import annotations

import time
from typing import Any

from textual.widgets import RichLog

from openclaw_tui.utils.time import relative_time


class LogPanel(RichLog):
    """Right-side panel showing transcript messages for selected session.

    Default state: shows placeholder text "Select a session to view logs"
    When populated: shows messages as "[HH:MM] role: content"
    """

    DEFAULT_CSS = """
    LogPanel {
        height: 1fr;
        border: round #2A2E3D;
        background: #16213E;
        padding: 0 1;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("markup", True)
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        """Show placeholder text when widget is first mounted."""
        self.show_placeholder()

    def show_transcript(self, messages: list, session_info: Any = None) -> None:
        """Clear log and write formatted messages.

        Each message has: .timestamp (str, "HH:MM"), .role (str), .content (str)
        Format: "[HH:MM] role: content"
        Color coding via Rich markup:
        - user: [bold cyan]◉ user:[/bold cyan] content
        - assistant: [bold green]◆ asst:[/bold green] content
        - tool: [#A8B5A2 dim]· role: content[/]

        If session_info is provided, writes a metadata header first with agent, model, and last update time.
        """
        self.clear()

        # Show metadata header if session_info provided
        if session_info is not None:
            now_ms = int(time.time() * 1000)
            rel = relative_time(session_info.updated_at, now_ms)
            agent_id = session_info.agent_id
            model = session_info.short_model
            tokens = getattr(session_info, "total_tokens", None)
            token_chunk = (
                f"  [dim #7B7F87]•[/] [bold #C67B5C]{tokens:,} tokens[/]"
                if isinstance(tokens, int)
                else ""
            )
            self.write(
                f"[bold #F5A623]agent:[/] {agent_id}  [dim #7B7F87]•[/] "
                f"[bold #F5A623]model:[/] {model}{token_chunk}  [dim #7B7F87]•[/] "
                f"[bold #F5A623]last:[/] {rel}"
            )
            self.write("[#7B7F87 dim]" + "─" * 52 + "[/]")
            self.write("")

        if not messages:
            self.write("[dim]No messages found[/dim]")
            return

        for msg in messages:
            if msg.role == "user":
                self.write(
                    f"[#F5A623][{msg.timestamp}][/] [#F5A623]┌─[/] "
                    f"[bold cyan]◉ user:[/bold cyan] {msg.content}"
                )
                self.write("[#F5A623]└─[/]")
            elif msg.role == "assistant":
                self.write(
                    f"[#F5A623][{msg.timestamp}][/] [#A8B5A2]┌─[/] "
                    f"[bold green]◆ asst:[/bold green] {msg.content}"
                )
                self.write("[#A8B5A2]└─[/]")
            else:
                self.write(f"[#A8B5A2 dim][{msg.timestamp}] [dim]╭─ · {msg.role}[/]")
                self.write(f"[#A8B5A2 dim]╰─ {msg.content}[/]")
            self.write("")

    def show_placeholder(self) -> None:
        """Show placeholder text."""
        self.clear()
        self.write("[#7B7F87 dim]┌─[/] [#A8B5A2 dim]🌘 Select a session to view its transcript[/]")

    def show_error(self, message: str) -> None:
        """Show error message."""
        self.clear()
        self.write(f"[bold #C67B5C]⚠ Error:[/bold #C67B5C] {message}")
