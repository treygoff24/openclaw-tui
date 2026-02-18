"""AgentTreeWidget — Textual Tree widget displaying agents and their sessions."""
from __future__ import annotations

from textual.widgets import Tree

from ..models import AgentNode, SessionInfo, SessionStatus, STATUS_ICONS, STATUS_STYLES


def _format_tokens(count: int) -> str:
    """Format token count as human-readable string.

    Examples:
        0       → "0"
        27652   → "27K"
        1200000 → "1.2M"
    """
    if count == 0:
        return "0"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count // 1_000}K"
    return str(count)


# ---------------------------------------------------------------------------
# Channel icons
# ---------------------------------------------------------------------------

_CHANNEL_ICONS: dict[str, str] = {
    "discord": "⌨",
    "cron": "⏱",
    "hearth": "🔥",
    "webchat": "🌐",
}


def _channel_icon(channel: str) -> str:
    """Return the icon for a channel. Exact match first, then substring match.

    Handles channel names like 'cron:nightly-job' by substring matching 'cron'.
    Unknown channels fall back to '·' (middle dot).
    """
    # Exact match
    if channel in _CHANNEL_ICONS:
        return _CHANNEL_ICONS[channel]
    # Substring match (e.g., "cron:job-name" matches "cron")
    for key, icon in _CHANNEL_ICONS.items():
        if key in channel:
            return icon
    return "·"


# ---------------------------------------------------------------------------
# Status markup (Hearth palette)
# ---------------------------------------------------------------------------

_STATUS_MARKUP: dict[SessionStatus, str] = {
    SessionStatus.ACTIVE: "[bold #F5A623]●[/]",
    SessionStatus.IDLE: "[dim #A8B5A2]○[/]",
    SessionStatus.ABORTED: "[bold #C67B5C]⚠[/]",
}


def _session_label(session: SessionInfo, now_ms: int) -> str:
    """Build the display label for a session leaf node.

    Format: "● main-session (sonnet-4-6) ⌨ • 28K • 3m ago"

    Uses Rich markup for status colors (Hearth palette):
    - Active:  amber  #F5A623
    - Idle:    sage   #A8B5A2
    - Aborted: terracotta #C67B5C
    """
    from ..utils.time import relative_time

    status = session.status(now_ms)
    icon = _STATUS_MARKUP[status]
    name = session.label if session.label is not None else session.display_name
    model = session.short_model
    tokens = _format_tokens(session.total_tokens)
    chan = _channel_icon(session.channel)
    rel = relative_time(session.updated_at, now_ms)
    return f"{icon} {name} ({model}) {chan} • {tokens} • {rel}"


class AgentTreeWidget(Tree[SessionInfo]):
    """Tree widget displaying agents and their sessions.

    Top-level nodes: agent IDs (e.g., "main", "sonnet-worker")
    Children: individual sessions with status icon, label/name, model, tokens

    Format per session line (Rich markup, Hearth palette):
        "● my-session (opus-4-6) 🌐 • 27K • active"
        "○ cron-job (sonnet-4-5) ⏱ • 30K • 5m ago"
        "⚠ subagent:abc123 (minimax) · • 0 • 2h ago"
    """

    def on_mount(self) -> None:
        """Hide root node; ensure it is expanded so children are visible."""
        self.show_root = False
        self.root.expand()

    def update_tree(self, nodes: list[AgentNode], now_ms: int) -> None:
        """Rebuild tree from agent nodes. Preserves expansion state of agent groups.

        Args:
            nodes:  List of AgentNode objects to display.
            now_ms: Current time in milliseconds (used to compute session status).
        """
        # Snapshot current expansion state keyed by agent_id label text
        expanded: dict[str, bool] = {}
        for child in self.root.children:
            expanded[child.label.plain] = child.is_expanded

        self.clear()
        # Ensure root is expanded after clear (clear preserves the state, but be explicit)
        self.root.expand()

        if not nodes:
            self.root.add_leaf("No sessions")
            return

        for agent_node in nodes:
            was_expanded = expanded.get(agent_node.agent_id, True)
            group = self.root.add(
                agent_node.agent_id,
                expand=was_expanded,
            )
            for session in agent_node.sessions:
                label = _session_label(session, now_ms)
                group.add_leaf(label, data=session)

    def update_tree_from_nodes(self, tree_nodes: list, now_ms: int) -> None:
        """Update tree with hierarchical TreeNodeData for subagent view.

        Args:
            tree_nodes: List of TreeNodeData objects with parent-child hierarchy.
            now_ms:     Current time in milliseconds.

        Each TreeNodeData has: key, label, depth, status, runtime_ms, children.
        Completed/failed nodes show their runtime via format_runtime().
        """
        from ..models import TreeNodeData, format_runtime

        self.clear()
        self.root.expand()

        if not tree_nodes:
            self.root.add_leaf("No sessions")
            return

        _STATUS_NODE_ICONS: dict[str, str] = {
            "active": "[bold #F5A623]●[/]",
            "completed": "[dim #A8B5A2]✓[/]",
            "failed": "[bold #C67B5C]⚠[/]",
        }

        def add_node(parent, node_data: TreeNodeData) -> None:
            icon = _STATUS_NODE_ICONS.get(node_data.status, "[dim]○[/]")
            runtime = format_runtime(node_data.runtime_ms) if node_data.runtime_ms > 0 else ""
            label = f"{icon} {node_data.label}"
            if runtime:
                label += f" [{runtime}]"

            if node_data.children:
                node = parent.add(label)
                node.expand()
                for child in node_data.children:
                    add_node(node, child)
            else:
                parent.add_leaf(label, data=node_data)

        for tree_node in tree_nodes:
            add_node(self.root, tree_node)
