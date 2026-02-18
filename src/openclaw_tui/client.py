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


def _extract_error_text(data: object) -> str | None:
    """Best-effort extraction of human-readable error text from gateway JSON."""
    if not isinstance(data, dict):
        return None

    candidates: list[object] = [
        data.get("error"),
        data.get("message"),
        data.get("detail"),
    ]

    result = data.get("result")
    if isinstance(result, dict):
        candidates.extend([
            result.get("error"),
            result.get("message"),
            result.get("detail"),
        ])
        details = result.get("details")
        if isinstance(details, dict):
            candidates.extend([
                details.get("error"),
                details.get("message"),
                details.get("detail"),
            ])

    for item in candidates:
        if isinstance(item, str) and item.strip():
            return item.strip()
        if isinstance(item, dict):
            for key in ("message", "error", "detail"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _summarize_message(message: str, max_chars: int = 120) -> str:
    """Return a compact single-line message snippet for error context."""
    compact = " ".join(message.split())
    if not compact:
        return "<empty>"
    if len(compact) <= max_chars:
        return compact
    return f"{compact[: max_chars - 3]}..."


def _extract_response_error_detail(response: httpx.Response, data: object) -> str | None:
    """Extract best available human-readable error detail from response."""
    message = _extract_error_text(data)
    if message:
        return message

    text = response.text.strip()
    if text:
        return text[:300]
    return None


def _extract_history_messages(data: object) -> list[dict]:
    """Extract a messages list from known gateway response shapes."""
    if not isinstance(data, dict):
        raise ValueError("Response body is not an object")

    containers: list[dict] = []

    def add_if_dict(value: object) -> None:
        if isinstance(value, dict):
            containers.append(value)

    add_if_dict(data)
    result = data.get("result")
    add_if_dict(result)

    details = result.get("details") if isinstance(result, dict) else None
    add_if_dict(details)

    for parent in tuple(containers):
        add_if_dict(parent.get("data"))
        add_if_dict(parent.get("output"))
        add_if_dict(parent.get("result"))

    for container in containers:
        for key in ("messages", "history", "items", "events"):
            value = container.get(key)
            if isinstance(value, list):
                return value

    raise ValueError("No messages list found in gateway response")


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
        self._last_history_error: str | None = None

    @property
    def last_history_error(self) -> str | None:
        """Return last fetch_history error message, if any."""
        return self._last_history_error

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
        {"tool": "sessions_list", "args": {"activeMinutes": active_minutes}}

        Maps camelCase JSON fields to snake_case SessionInfo fields.

        Raises ConnectionError if gateway unreachable.
        Raises AuthError if 401/403.
        Returns empty list on unexpected errors (logged as warning).
        """
        client = self._get_client()
        payload = {
            "tool": "sessions_list",
            "args": {"activeMinutes": active_minutes},
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
        payload = {"tool": "sessions_tree", "args": {"depth": depth}}

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

    def send_message(self, session_key: str, message: str) -> dict:
        """Send a message to a session.

        POST /tools/invoke with body:
        {"tool": "sessions_send", "args": {"sessionKey": key, "message": msg}}

        Raises ConnectionError if gateway unreachable.
        Raises AuthError if 401/403.
        Returns the full result dict on success.
        """
        client = self._get_client()
        payloads = [
            {"tool": "sessions_send", "args": {"sessionKey": session_key, "message": message}},
            {"tool": "sessions_send", "args": {"session_key": session_key, "message": message}},
        ]
        fallback_statuses = {400, 404, 422}
        errors: list[str] = []

        for index, payload in enumerate(payloads):
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

            data: object = None
            try:
                data = response.json()
            except ValueError:
                data = None

            if response.status_code != 200:
                message_context = _summarize_message(message)
                detail = (
                    f"Gateway returned HTTP {response.status_code} while sending "
                    f"to session '{session_key}' with message '{message_context}'"
                )
                response_detail = _extract_response_error_detail(response, data)
                if response_detail:
                    detail = f"{detail}: {response_detail}"
                errors.append(detail)

                if index == 0 and response.status_code in fallback_statuses:
                    continue

                logger.warning("send_message failed: %s", detail)
                raise GatewayError("; ".join(errors))

            if data is None:
                detail = (
                    f"Gateway returned invalid JSON while sending "
                    f"to session '{session_key}'"
                )
                logger.warning("send_message invalid JSON response")
                raise GatewayError(detail)

            return data

        raise GatewayError("; ".join(errors) or "Unable to send message")

    def fetch_history(self, session_key: str, limit: int = 30) -> list[dict]:
        """Fetch message history for a session.

        POST /tools/invoke with body:
        {"tool": "sessions_history", "args": {"sessionKey": key, "limit": limit}}

        Returns empty list on any error (connection, auth, parse).
        Sets ``last_history_error`` with details when available.
        Never raises.
        """
        client = self._get_client()
        self._last_history_error = None

        payloads = [
            {"tool": "sessions_history", "args": {"sessionKey": session_key, "limit": limit}},
            {"tool": "sessions_history", "args": {"session_key": session_key, "limit": limit}},
        ]

        errors: list[str] = []
        for index, payload in enumerate(payloads):
            try:
                response = client.post("/tools/invoke", json=payload)
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as exc:
                detail = f"Cannot reach gateway at {self.config.base_url}: {exc}"
                logger.warning("fetch_history connection failed: %s", exc)
                self._last_history_error = detail
                return []

            if response.status_code in (401, 403):
                detail = f"Authentication failed: HTTP {response.status_code}"
                logger.warning("fetch_history auth failed: HTTP %d", response.status_code)
                self._last_history_error = detail
                return []

            data: object = None
            try:
                data = response.json()
            except ValueError:
                data = None

            if response.status_code != 200:
                message = _extract_error_text(data)
                detail = f"Gateway returned HTTP {response.status_code}"
                if message:
                    detail = f"{detail}: {message}"
                errors.append(detail)
                # Retry once with snake_case for possible schema mismatch.
                if index == 0 and response.status_code in (400, 422):
                    continue
                self._last_history_error = "; ".join(errors)
                return []

            try:
                messages = _extract_history_messages(data)
            except ValueError as exc:
                message = _extract_error_text(data)
                detail = message or str(exc)
                logger.warning("fetch_history unexpected response shape: %s", detail)
                errors.append(detail)
                # Retry once with snake_case in case first payload field is invalid.
                if index == 0:
                    continue
                self._last_history_error = "; ".join(errors)
                return []

            if not isinstance(messages, list):
                errors.append("Invalid messages payload from gateway")
                if index == 0:
                    continue
                self._last_history_error = "; ".join(errors)
                return []

            self._last_history_error = None
            return messages

        self._last_history_error = "; ".join(errors) or "Unable to load chat history"
        return []

    def abort_session(self, session_key: str) -> dict:
        """Abort an active session run.

        POST /tools/invoke with body:
        {"tool": "sessions_kill", "args": {"sessionKey": key}}

        Raises ConnectionError if gateway unreachable.
        Raises AuthError if 401/403.
        Returns the full result dict on success.
        """
        client = self._get_client()
        payload = {
            "tool": "sessions_kill",
            "args": {"sessionKey": session_key},
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
            logger.warning("Unexpected gateway status %d", response.status_code)
            raise GatewayError(f"Unexpected status code: {response.status_code}")

        return response.json()

    def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            self._client.close()
            logger.info("Gateway client closed")
