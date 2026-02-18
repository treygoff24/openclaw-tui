from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

OPENCLAW_DIR = Path.home() / ".openclaw"


@dataclass
class TranscriptMessage:
    timestamp: str  # HH:MM format for display (extracted from ISO timestamp)
    role: str       # "user", "assistant", "tool"
    content: str    # Text content, truncated


def _extract_timestamp(iso_ts: str) -> str:
    """Extract HH:MM from an ISO timestamp string."""
    try:
        # ISO format: 2024-01-15T14:30:00.000Z or similar
        # Find the T separator
        t_idx = iso_ts.find("T")
        if t_idx >= 0:
            time_part = iso_ts[t_idx + 1:]
            return time_part[:5]  # HH:MM
        # Fallback: try splitting on space
        parts = iso_ts.split(" ")
        if len(parts) >= 2:
            return parts[1][:5]
    except Exception:
        pass
    return "??:??"


def _extract_content(content_raw: object, max_len: int) -> str:
    """Extract text content from a message content field."""
    if isinstance(content_raw, str):
        return content_raw[:max_len]

    if isinstance(content_raw, list):
        # Find the first useful block
        for block in content_raw:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                text = block.get("text", "")
                return text[:max_len]
            elif block_type == "toolCall":
                name = block.get("name", "") or block.get("tool", "") or "unknown"
                return f"[tool: {name}]"
            elif block_type == "toolResult":
                # Show first max_len chars of the result content
                result = block.get("content", "")
                if isinstance(result, str):
                    return result[:max_len]
                elif isinstance(result, list):
                    # Nested content blocks
                    for sub in result:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            return sub.get("text", "")[:max_len]
                return str(result)[:max_len]
        # No recognised block found
        return ""

    return str(content_raw)[:max_len]


_ROLE_MAP: dict[str, str] = {
    "user": "user",
    "assistant": "assistant",
    "toolResult": "tool",
}


def read_transcript(
    session_id: str,
    agent_id: str,
    limit: int = 20,
    max_content_len: int = 200,
) -> list[TranscriptMessage]:
    """Read last `limit` messages from a session transcript.

    File location: ~/.openclaw/agents/<agent_id>/sessions/<session_id>.jsonl
    """
    path = OPENCLAW_DIR / "agents" / agent_id / "sessions" / f"{session_id}.jsonl"

    if not path.exists():
        logger.warning("Transcript file not found: %s", path)
        return []

    messages: list[TranscriptMessage] = []

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Failed to read transcript %s: %s", path, exc)
        return []

    for lineno, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.debug("Skipping malformed JSON at line %d of %s: %s", lineno, path, exc)
            continue

        if not isinstance(record, dict):
            logger.debug("Skipping non-dict record at line %d of %s", lineno, path)
            continue

        if record.get("type") != "message":
            continue

        msg = record.get("message")
        if not isinstance(msg, dict):
            logger.debug("Skipping record with missing/invalid 'message' at line %d", lineno)
            continue

        raw_role = msg.get("role", "")
        role = _ROLE_MAP.get(raw_role, raw_role)

        iso_ts = record.get("timestamp", "")
        timestamp = _extract_timestamp(iso_ts)

        try:
            content = _extract_content(msg.get("content", ""), max_content_len)
        except Exception as exc:
            logger.debug("Error extracting content at line %d: %s", lineno, exc)
            content = ""

        messages.append(TranscriptMessage(timestamp=timestamp, role=role, content=content))

    return messages[-limit:]
