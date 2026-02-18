"""SummaryBar — footer Static widget showing aggregate session counts."""
from __future__ import annotations

from textual.widgets import Static

from ..models import AgentNode, SessionStatus


class SummaryBar(Static):
    """Footer widget showing aggregate session counts.

    Displays: "Active: 3  Idle: 5  Aborted: 1  Total: 9"
    Shows "⚡ Connecting..." when no data has been received yet.
    Shows "❌ Gateway unreachable" on connection error.

    The current display text is always stored in ``_display_text`` for easy
    introspection in tests.
    """

    def __init__(self, content: str = "⚡ Connecting...", **kwargs: object) -> None:
        """Initialise the widget and capture the initial display text.

        Args:
            content: Initial text to display (default: connecting indicator).
            **kwargs: Forwarded to :class:`textual.widgets.Static`.
        """
        super().__init__(content, **kwargs)
        self._display_text: str = str(content)

    def update_summary(self, nodes: list[AgentNode], now_ms: int) -> None:
        """Count sessions by status across all nodes and update display text.

        Args:
            nodes:  List of AgentNode objects to summarise.
            now_ms: Current time in milliseconds (used to compute session status).
        """
        counts: dict[SessionStatus, int] = {s: 0 for s in SessionStatus}
        for agent_node in nodes:
            for session in agent_node.sessions:
                counts[session.status(now_ms)] += 1

        total = sum(counts.values())
        text = (
            f"[bold #F5A623]●[/] {counts[SessionStatus.ACTIVE]} active  "
            f"[dim #A8B5A2]○[/] {counts[SessionStatus.IDLE]} idle  "
            f"[bold #C67B5C]⚠[/] {counts[SessionStatus.ABORTED]} aborted  "
            f"│ [dim]{total} total[/dim]"
        )
        self._display_text = text
        self.update(text)

    def update_with_tree_stats(self, active: int, completed: int, total: int) -> None:
        """Update with data from sessions_tree endpoint.

        Args:
            active:    Number of running sessions.
            completed: Number of completed sessions.
            total:     Total number of sessions.
        """
        text = (
            f"[bold #F5A623]▶[/] {active} running  "
            f"[dim #A8B5A2]✓[/] {completed} done  "
            f"│ {total} total"
        )
        self._display_text = text
        self.update(text)

    def set_error(self, message: str) -> None:
        """Display an error state in the summary bar.

        Args:
            message: Human-readable error description.
        """
        text = f"[bold #C67B5C]⚠[/] {message}"
        self._display_text = text
        self.update(text)
