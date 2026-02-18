"""AgentDashboard — main Textual TUI application with live polling."""
from __future__ import annotations

import asyncio
import inspect
import logging
import time

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.theme import Theme
from textual.widgets import Header, Footer, Tree
from textual.worker import Worker, WorkerState

from .widgets import AgentTreeWidget, SummaryBar, LogPanel
from .config import GatewayConfig, load_config
from .client import GatewayClient, GatewayError
from .tree import build_tree
from . import transcript
from .transcript import read_transcript
from .utils.clipboard import copy_to_clipboard

logger = logging.getLogger(__name__)


class AgentDashboard(App[None]):
    """Main TUI application with live-updating agent tree.

    Polls the OpenClaw gateway every 2 seconds, groups sessions into an
    agent tree, and displays them with a live summary footer.
    """

    TITLE = "🌘 OpenClaw"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("c", "copy_info", "Copy Info"),
        ("v", "toggle_logs", "View Logs"),
        ("e", "expand_all", "Expand All"),
    ]

    CSS = """
Screen {
    background: #1A1A2E;
}
Header {
    background: #16213E;
    color: #F5A623;
    text-style: bold;
}
#main-content {
    height: 1fr;
}
AgentTreeWidget {
    width: 2fr;
    border: solid $accent;
    background: #1A1A2E;
}
LogPanel {
    width: 3fr;
    border-left: solid $accent;
    background: #16213E;
}
SummaryBar {
    height: 3;
    background: #16213E;
    color: $foreground;
    padding: 0 2;
    dock: bottom;
}
Footer {
    background: #16213E;
    color: #A8B5A2;
}
"""

    def compose(self) -> ComposeResult:
        """Layout: Header → Horizontal(AgentTreeWidget + LogPanel) → SummaryBar → Footer."""
        yield Header()
        with Horizontal(id="main-content"):
            yield AgentTreeWidget("Agents")
            yield LogPanel()
        yield SummaryBar("⚡ Connecting...")
        yield Footer()

    def on_mount(self) -> None:
        """Load config, create client, start 2 s polling interval."""
        logger.info("AgentDashboard mounted — starting poll loop")
        self._config = load_config()
        self._client = GatewayClient(self._config)
        self._selected_session: SessionInfo | None = None
        self.register_theme(Theme(
            name="hearth",
            primary="#F5A623",
            background="#1A1A2E",
            surface="#16213E",
            accent="#F5A623",
            warning="#FFD93D",
            error="#C67B5C",
            success="#4ADE80",
            secondary="#4A90D9",
            foreground="#FFF8E7",
            panel="#16213E",
        ))
        self.theme = "hearth"
        self.set_interval(2.0, self._trigger_poll)
        self._trigger_poll()  # immediate first poll

    def _trigger_poll(self) -> None:
        """Trigger an exclusive worker to poll the gateway."""
        self.run_worker(self._poll_sessions, exclusive=True)

    async def _poll_sessions(self) -> None:
        """Worker coroutine: fetch sessions, build tree, update widgets.

        Runs ``fetch_sessions`` (sync httpx call) in a thread via
        ``asyncio.to_thread`` so the TUI event loop stays responsive.
        On any error, updates the SummaryBar with an error message instead
        of crashing.
        """
        now_ms = int(time.time() * 1000)
        try:
            sessions = await asyncio.to_thread(self._client.fetch_sessions)
            nodes = build_tree(sessions)
            tree = self.query_one(AgentTreeWidget)
            bar = self.query_one(SummaryBar)
            tree.update_tree(nodes, now_ms)
            bar.update_summary(nodes, now_ms)
            try:
                tree_nodes = await asyncio.to_thread(self._client.fetch_tree)
                if tree_nodes:
                    active = 0
                    completed = 0
                    total = 0
                    stack = list(tree_nodes)
                    while stack:
                        tree_node = stack.pop()
                        total += 1
                        if tree_node.status == "active":
                            active += 1
                        elif tree_node.status == "completed":
                            completed += 1
                        stack.extend(tree_node.children)
                    bar.update_with_tree_stats(active=active, completed=completed, total=total)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Tree stats update skipped: %s", exc)
            logger.info("Poll OK — %d sessions across %d agents", len(sessions), len(nodes))
        except (GatewayError, ConnectionError) as exc:
            logger.warning("Gateway poll failed: %s", exc)
            self._show_poll_error(str(exc) or "Gateway unreachable")
        except Exception as exc:  # noqa: BLE001 — never crash the TUI
            logger.warning("Unexpected poll error: %s", exc)
            self._show_poll_error(str(exc) or "Unknown error")

    def _show_poll_error(self, message: str) -> None:
        """Update SummaryBar with error message (safe — never raises)."""
        try:
            bar = self.query_one(SummaryBar)
            bar.set_error(message)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not update SummaryBar: %s", exc)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """When a session node is selected, show its transcript."""
        node_data = event.node.data  # This is the SessionInfo object (set in AgentTreeWidget)
        if node_data is None:
            return  # Agent group header, not a session
        self._selected_session = node_data
        log_panel = self.query_one(LogPanel)
        try:
            transcript_path = getattr(node_data, "transcript_path", None)
            messages = []
            if transcript_path:
                read_from_path = getattr(transcript, "read_transcript_from_path", None)
                if callable(read_from_path):
                    try:
                        messages = read_from_path(transcript_path=transcript_path)
                    except TypeError:
                        messages = read_from_path(transcript_path)
                else:
                    kwargs = {
                        "session_id": node_data.session_id,
                        "agent_id": node_data.agent_id,
                    }
                    if "transcript_path" in inspect.signature(read_transcript).parameters:
                        kwargs["transcript_path"] = transcript_path
                    messages = read_transcript(**kwargs)
            else:
                messages = read_transcript(
                    session_id=node_data.session_id,
                    agent_id=node_data.agent_id,
                )
            log_panel.show_transcript(messages, session_info=node_data)
        except Exception as exc:  # noqa: BLE001 — never crash the TUI
            logger.warning(
                "Failed to load transcript for %s: %s",
                getattr(node_data, "session_id", "unknown"),
                exc,
            )
            log_panel.show_error(str(exc) or "Failed to load transcript")

    def action_copy_info(self) -> None:
        """Copy selected session info to clipboard."""
        session = getattr(self, "_selected_session", None)
        if session is None:
            self.notify("No session selected", severity="warning")
            return
        info_lines = [
            f"Agent: {session.agent_id}",
            f"Session: {session.key}",
            f"Name: {session.label or session.display_name}",
            f"Model: {session.model}",
            f"Tokens: {session.total_tokens}",
            f"Session ID: {session.session_id}",
        ]
        info_text = "\n".join(info_lines)
        try:
            copied = copy_to_clipboard(info_text)
        except Exception:  # noqa: BLE001
            copied = False

        if copied:
            self.notify(f"Copied: {session.label or session.display_name}")
        else:
            self.notify("Failed to copy session info to clipboard", severity="error")

    def action_toggle_logs(self) -> None:
        """Toggle the log panel visibility. Tree expands to full width when hidden."""
        log_panel = self.query_one(LogPanel)
        tree = self.query_one(AgentTreeWidget)
        if log_panel.display:
            log_panel.display = False
            tree.styles.width = "100%"
        else:
            log_panel.display = True
            tree.styles.width = "2fr"

    def action_expand_all(self) -> None:
        """Expand all agent group nodes in the tree."""
        tree = self.query_one(AgentTreeWidget)
        for group in tree.root.children:
            group.expand()

    def action_refresh(self) -> None:
        """Manual refresh triggered by 'r' key."""
        logger.info("Manual refresh triggered")
        self._trigger_poll()

    def on_unmount(self) -> None:
        """Clean up HTTP client on exit."""
        if hasattr(self, "_client"):
            logger.info("Closing gateway client")
            self._client.close()
