from __future__ import annotations

from .models import AgentNode, SessionInfo


def build_tree(sessions: list[SessionInfo]) -> list[AgentNode]:
    """Group sessions by agent_id extracted from session key.

    Key format: agent:<agent_id>:<context>
    e.g. "agent:main:main"                     → agent_id="main"
         "agent:sonnet-worker:subagent:uuid"   → agent_id="sonnet-worker"

    Returns list of AgentNode, sorted: "main" first, then alphabetical.
    Empty sessions list → empty result.
    Malformed keys (not starting with "agent:") → grouped under "unknown".
    """
    if not sessions:
        return []

    # Use dict to preserve insertion order within each group
    nodes: dict[str, AgentNode] = {}

    for session in sessions:
        parts = session.key.split(":", 2)
        if len(parts) >= 2 and parts[0] == "agent":
            agent_id = parts[1]
        else:
            agent_id = "unknown"

        if agent_id not in nodes:
            nodes[agent_id] = AgentNode(agent_id=agent_id)
        nodes[agent_id].sessions.append(session)

    # Sort: "main" first, then alphabetical for the rest
    def sort_key(agent_id: str) -> tuple[int, str]:
        return (0, "") if agent_id == "main" else (1, agent_id)

    sorted_nodes = sorted(nodes.values(), key=lambda n: sort_key(n.agent_id))
    return sorted_nodes
