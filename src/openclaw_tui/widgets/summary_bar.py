"""SummaryBar — footer Static widget showing aggregate session counts."""
from __future__ import annotations

from textual.timer import Timer
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
    _RUNNING_FRAMES = ("◐", "◓", "◑", "◒")

    DEFAULT_CSS = """
    SummaryBar {
        height: 3;
        background: #16213E;
        color: #FFF8E7;
        border-top: solid #2A2E3D;
        padding: 0 2;
    }
    """

    def __init__(self, content: str = "⚡ Connecting...", **kwargs: object) -> None:
        """Initialise the widget and capture the initial display text.

        Args:
            content: Initial text to display (default: connecting indicator).
            **kwargs: Forwarded to :class:`textual.widgets.Static`.
        """
        super().__init__(content, **kwargs)
        self._display_text: str = str(content)
        self._running_frame_index = 0
        self._latest_tree_stats: tuple[int, int, int] | None = None
        self._running_anim_timer: Timer | None = None

    def on_mount(self) -> None:
        """Animate running indicator while active sessions exist."""
        self._running_anim_timer = self.set_interval(0.18, self._animate_running_indicator)

    def on_unmount(self) -> None:
        """Stop animation timer when widget is removed."""
        if self._running_anim_timer is not None:
            self._running_anim_timer.stop()
            self._running_anim_timer = None

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
        self._latest_tree_stats = (active, completed, total)
        text = self._render_tree_stats(active, completed, total)
        self._display_text = text
        self.update(text)

    def _animate_running_indicator(self) -> None:
        """Refresh animated glyph while sessions are running."""
        if self._latest_tree_stats is None:
            return
        active, completed, total = self._latest_tree_stats
        if active <= 0:
            return
        self._display_text = self._render_tree_stats(active, completed, total)
        self.update(self._display_text)

    def _render_tree_stats(self, active: int, completed: int, total: int) -> str:
        """Render running/done/total summary text."""
        if active > 0:
            frame = self._RUNNING_FRAMES[self._running_frame_index % len(self._RUNNING_FRAMES)]
            self._running_frame_index += 1
        else:
            frame = "◌"
        return (
            f"[bold #F5A623]{frame}[/] {active} running  "
            f"[dim #A8B5A2]✓[/] {completed} done  "
            f"[dim #7B7F87]│[/] [dim]{total} total[/]"
        )

    def set_error(self, message: str) -> None:
        """Display an error state in the summary bar.

        Args:
            message: Human-readable error description.
        """
        text = f"[bold #C67B5C]⚠[/] {message}"
        self._display_text = text
        self.update(text)
