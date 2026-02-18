"""LogPanel widget — right-side transcript viewer for selected sessions."""
from __future__ import annotations

from textual.widgets import RichLog


class LogPanel(RichLog):
    """Right-side panel showing transcript messages for selected session.

    Default state: shows placeholder text "Select a session to view logs"
    When populated: shows messages as "[HH:MM] role: content"
    """

    DEFAULT_CSS = """
    LogPanel {
        border-left: solid $accent;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("markup", True)
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        """Show placeholder text when widget is first mounted."""
        self.show_placeholder()

    def show_transcript(self, messages: list) -> None:
        """Clear log and write formatted messages.

        Each message has: .timestamp (str, "HH:MM"), .role (str), .content (str)
        Format: "[HH:MM] role: content"
        Color coding via Rich markup:
        - user: [bold cyan]user[/]: content
        - assistant: [bold green]assistant[/]: content
        - tool: [dim]tool: content[/]
        """
        self.clear()
        if not messages:
            self.write("[dim]No messages found[/dim]")
            return
        for msg in messages:
            if msg.role == "user":
                self.write(f"[bold cyan][{msg.timestamp}] user:[/bold cyan] {msg.content}")
            elif msg.role == "assistant":
                self.write(f"[bold green][{msg.timestamp}] assistant:[/bold green] {msg.content}")
            else:
                self.write(f"[dim][{msg.timestamp}] {msg.role}: {msg.content}[/dim]")

    def show_placeholder(self) -> None:
        """Show placeholder text."""
        self.clear()
        self.write("[dim]Select a session to view logs[/dim]")

    def show_error(self, message: str) -> None:
        """Show error message."""
        self.clear()
        self.write(f"[bold red]Error:[/bold red] {message}")
