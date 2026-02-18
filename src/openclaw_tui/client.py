from __future__ import annotations

import logging

import httpx

from .config import GatewayConfig
from .models import SessionInfo, TreeNodeData

logger = logging.getLogger(__name__)


def _parse_tree_node(raw: dict) -> TreeNodeData:
    """Parse a raw tree node dict into a TreeNodeData object recursively."""
    children = [_parse_tree_node(c) for c in raw.get("children", [])]
    return TreeNodeData(
        key=raw["key"],
        label=raw.get("label", raw["key"]),
        depth=raw.get("depth", 0),
        status=raw.get("status", "unknown"),
        runtime_ms=raw.get("runtimeMs", 0),
        children=children,
    )


class GatewayError(Exception):
    """Base error for gateway communication."""
    pass


class AuthError(GatewayError):
    """Authentication failed (401/403)."""
    pass


class GatewayClient:
    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self._client: httpx.Client | None = None

    def _get_client(self) -> httpx.Client:
        """Get or create reusable HTTP client."""
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {}
            if self.config.token:
                headers["Authorization"] = f"Bearer {self.config.token}"
            self._client = httpx.Client(
                base_url=self.config.base_url,
                headers=headers,
                timeout=5.0,
            )
            logger.info("Gateway client created for %s", self.config.base_url)
        return self._client

    def fetch_sessions(self, active_minutes: int = 1440) -> list[SessionInfo]:
        """Fetch sessions from gateway.

        POST /tools/invoke with body:
        {"tool": "sessions_list", "input": {"activeMinutes": active_minutes}}

        Maps camelCase JSON fields to snake_case SessionInfo fields.

        Raises ConnectionError if gateway unreachable.
        Raises AuthError if 401/403.
        Returns empty list on unexpected errors (logged as warning).
        """
        client = self._get_client()
        payload = {
            "tool": "sessions_list",
            "input": {"activeMinutes": active_minutes},
        }

        try:
            response = client.post("/tools/invoke", json=payload)
        except httpx.ConnectError as exc:
            logger.warning("Gateway connection failed: %s", exc)
            raise ConnectionError(f"Cannot reach gateway at {self.config.base_url}: {exc}") from exc
        except httpx.TimeoutException as exc:
            logger.warning("Gateway request timed out: %s", exc)
            raise ConnectionError(f"Gateway request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            logger.warning("Gateway request error: %s", exc)
            raise ConnectionError(f"Gateway request error: {exc}") from exc

        if response.status_code in (401, 403):
            logger.warning("Gateway auth failed: HTTP %d", response.status_code)
            raise AuthError(f"Authentication failed: HTTP {response.status_code}")

        if response.status_code != 200:
            logger.warning("Unexpected gateway status %d — returning empty list", response.status_code)
            return []

        try:
            data = response.json()
            raw_sessions = data["result"]["details"]["sessions"]
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Unexpected gateway response shape: %s — returning empty list", exc)
            return []

        sessions: list[SessionInfo] = []
        for raw in raw_sessions:
            try:
                session = SessionInfo(
                    key=raw["key"],
                    kind=raw.get("kind", "other"),
                    channel=raw.get("channel", "unknown"),
                    display_name=raw.get("displayName", raw["key"]),
                    label=raw.get("label"),
                    updated_at=raw.get("updatedAt", 0),
                    session_id=raw.get("sessionId", ""),
                    model=raw.get("model", "unknown"),
                    context_tokens=raw.get("contextTokens"),
                    total_tokens=raw.get("totalTokens", 0),
                    aborted_last_run=raw.get("abortedLastRun", False),
                    transcript_path=raw.get("transcriptPath"),
                )
                sessions.append(session)
            except (KeyError, TypeError) as exc:
                logger.warning("Skipping malformed session record: %s", exc)

        logger.debug("Fetched %d sessions from gateway", len(sessions))
        return sessions

    def fetch_tree(self, depth: int = 5) -> list[TreeNodeData]:
        """Fetch sessions_tree and return hierarchical TreeNodeData list.

        Returns empty list on any error (connection, auth, parse).
        Never raises.
        """
        client = self._get_client()
        payload = {"tool": "sessions_tree", "input": {"depth": depth}}

        try:
            response = client.post("/tools/invoke", json=payload)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as exc:
            logger.warning("fetch_tree connection failed: %s", exc)
            return []

        if response.status_code in (401, 403):
            logger.warning("fetch_tree auth failed: HTTP %d", response.status_code)
            return []

        if response.status_code != 200:
            return []

        try:
            data = response.json()
            raw_tree = data["result"]["details"]["tree"]
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("fetch_tree unexpected response shape: %s", exc)
            return []

        return [_parse_tree_node(node) for node in raw_tree]

    def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            self._client.close()
            logger.info("Gateway client closed")
