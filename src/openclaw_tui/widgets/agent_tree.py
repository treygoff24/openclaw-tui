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
    name = session.label or session.display_name
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

    def update_tree(
        self,
        nodes: list[AgentNode],
        now_ms: int,
        *,
        parent_by_key: dict[str, str] | None = None,
        synthetic_sessions: dict[str, SessionInfo] | None = None,
    ) -> None:
        """Rebuild tree from agent nodes. Preserves expansion state of agent groups.

        Args:
            nodes:  List of AgentNode objects to display.
            now_ms: Current time in milliseconds (used to compute session status).
            parent_by_key: Optional session hierarchy map (child -> parent key).
            synthetic_sessions: Optional synthetic SessionInfo entries not present in nodes.
        """
        expanded = self._snapshot_expanded_nodes(self.root)

        self.clear()
        # Ensure root is expanded after clear (clear preserves the state, but be explicit)
        self.root.expand()

        parent_by_key = parent_by_key or {}
        synthetic_sessions = synthetic_sessions or {}

        if not nodes and synthetic_sessions:
            grouped_agents = sorted(
                {session.agent_id for session in synthetic_sessions.values()},
                key=lambda agent_id: (0, "") if agent_id == "main" else (1, agent_id),
            )
            nodes = [AgentNode(agent_id=agent_id, sessions=[]) for agent_id in grouped_agents]
        elif synthetic_sessions:
            # Keep synthetic-only agent IDs visible even when some real agent groups exist.
            existing_agent_ids = {node.agent_id for node in nodes}
            missing_agent_ids = sorted(
                {session.agent_id for session in synthetic_sessions.values()} - existing_agent_ids,
                key=lambda agent_id: (0, "") if agent_id == "main" else (1, agent_id),
            )
            if missing_agent_ids:
                nodes.extend(AgentNode(agent_id=agent_id, sessions=[]) for agent_id in missing_agent_ids)

        if not nodes:
            self.root.add_leaf("No sessions")
            return

        for agent_node in nodes:
            was_expanded = expanded.get(agent_node.agent_id, True)
            group = self.root.add(
                agent_node.agent_id,
                expand=was_expanded,
            )
            by_key: dict[str, SessionInfo] = {session.key: session for session in agent_node.sessions}
            for key, session in synthetic_sessions.items():
                if session.agent_id == agent_node.agent_id and key not in by_key:
                    by_key[key] = session

            child_keys: dict[str, list[str]] = {}
            for child_key, parent_key in parent_by_key.items():
                if child_key in by_key and parent_key in by_key:
                    child_keys.setdefault(parent_key, []).append(child_key)

            position = {session.key: index for index, session in enumerate(agent_node.sessions)}
            for key in synthetic_sessions:
                position.setdefault(key, len(position) + 1000)

            for siblings in child_keys.values():
                siblings.sort(key=lambda key: position.get(key, 10_000))

            roots = [
                key
                for key in by_key
                if key not in parent_by_key or parent_by_key[key] not in by_key
            ]
            roots.sort(key=lambda key: position.get(key, 10_000))

            def add_session_node(parent, session_key: str) -> None:
                session = by_key[session_key]
                label = _session_label(session, now_ms)
                children = child_keys.get(session_key, [])
                if children:
                    node = parent.add(
                        label,
                        data=session,
                        expand=expanded.get(session.key, True),
                    )
                    for child_key in children:
                        add_session_node(node, child_key)
                else:
                    parent.add_leaf(label, data=session)

            for root_key in roots:
                add_session_node(group, root_key)

    @staticmethod
    def _infer_channel_from_key(key: str) -> str:
        parts = key.split(":")
        return parts[2] if len(parts) >= 3 and parts[2] else "webchat"

    @classmethod
    def _synthesize_session(cls, node_data, now_ms: int) -> SessionInfo:
        key = str(getattr(node_data, "key", "unknown"))
        label = str(getattr(node_data, "label", key))
        status = str(getattr(node_data, "status", "active"))
        # Keep status semantics roughly aligned for synthetic entries.
        if status == "active":
            updated_at = now_ms
            aborted = False
        elif status == "failed":
            updated_at = max(0, now_ms - 120_000)
            aborted = True
        else:
            updated_at = max(0, now_ms - 120_000)
            aborted = False
        return SessionInfo(
            key=key,
            kind="chat",
            channel=cls._infer_channel_from_key(key),
            display_name=label,
            label=label,
            updated_at=updated_at,
            session_id=key,
            model="unknown",
            context_tokens=None,
            total_tokens=0,
            aborted_last_run=aborted,
        )

    @staticmethod
    def _snapshot_expanded_nodes(root) -> dict[str, bool]:
        expanded: dict[str, bool] = {}

        def walk(node) -> None:
            data = getattr(node, "data", None)
            key = data.key if isinstance(data, SessionInfo) else node.label.plain
            expanded[key] = node.is_expanded
            for child in node.children:
                walk(child)

        for child in root.children:
            walk(child)
        return expanded

    def update_tree_from_nodes(
        self,
        tree_nodes: list,
        now_ms: int,
        *,
        session_lookup: dict[str, SessionInfo] | None = None,
    ) -> None:
        """Update tree with hierarchical TreeNodeData for subagent view.

        Args:
            tree_nodes: List of TreeNodeData objects with parent-child hierarchy.
            now_ms:     Current time in milliseconds.

        Each TreeNodeData has: key, label, depth, status, runtime_ms, children.
        Completed/failed nodes show their runtime via format_runtime().
        """
        from ..models import TreeNodeData, format_runtime

        expanded = self._snapshot_expanded_nodes(self.root)
        lookup = session_lookup or {}

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

            session = lookup.get(node_data.key) or self._synthesize_session(node_data, now_ms)
            should_expand = expanded.get(session.key, True)

            if node_data.children:
                node = parent.add(label, data=session, expand=should_expand)
                for child in node_data.children:
                    add_node(node, child)
            else:
                parent.add_leaf(label, data=session)

        for tree_node in tree_nodes:
            add_node(self.root, tree_node)
