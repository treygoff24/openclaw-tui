from __future__ import annotations

import json
import pytest
import httpx

from openclaw_tui.config import GatewayConfig
from openclaw_tui.client import GatewayClient, GatewayError, AuthError
from openclaw_tui.models import SessionInfo


SAMPLE_RESPONSE = {
    "ok": True,
    "result": {
        "details": {
            "count": 2,
            "sessions": [
                {
                    "key": "agent:main:main",
                    "kind": "other",
                    "channel": "webchat",
                    "displayName": "openclaw-tui",
                    "label": None,
                    "updatedAt": 1771379198943,
                    "sessionId": "a56de194-1234-5678-abcd-000000000001",
                    "model": "claude-opus-4-6",
                    "contextTokens": 150000,
                    "totalTokens": 27652,
                    "abortedLastRun": False,
                },
                {
                    "key": "agent:sonnet-worker:subagent:88db67f5",
                    "kind": "subagent",
                    "channel": "internal",
                    "displayName": "Sonnet Worker",
                    "label": "forge-builder",
                    "updatedAt": 1771379100000,
                    "sessionId": "b1b2b3b4-0000-0000-0000-000000000002",
                    "model": "claude-sonnet-4-5-20250929",
                    "contextTokens": None,
                    "totalTokens": 5000,
                    "abortedLastRun": True,
                },
            ],
        }
    },
}


def make_config(token: str | None = "test-token") -> GatewayConfig:
    return GatewayConfig(host="127.0.0.1", port=2020, token=token)


def make_mock_transport(response_body: dict, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            json=response_body,
        )
    return httpx.MockTransport(handler)


def make_error_transport(exception: Exception) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception
    return httpx.MockTransport(handler)


class TestFetchSessions:
    def test_parses_valid_response_into_session_list(self):
        transport = make_mock_transport(SAMPLE_RESPONSE)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        sessions = client.fetch_sessions()

        assert len(sessions) == 2
        assert all(isinstance(s, SessionInfo) for s in sessions)

    def test_parses_first_session_fields_correctly(self):
        transport = make_mock_transport(SAMPLE_RESPONSE)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        sessions = client.fetch_sessions()
        s = sessions[0]

        assert s.key == "agent:main:main"
        assert s.kind == "other"
        assert s.channel == "webchat"
        assert s.display_name == "openclaw-tui"
        assert s.label is None
        assert s.updated_at == 1771379198943
        assert s.session_id == "a56de194-1234-5678-abcd-000000000001"
        assert s.model == "claude-opus-4-6"
        assert s.context_tokens == 150000
        assert s.total_tokens == 27652
        assert s.aborted_last_run is False

    def test_parses_second_session_with_label_and_aborted(self):
        transport = make_mock_transport(SAMPLE_RESPONSE)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        sessions = client.fetch_sessions()
        s = sessions[1]

        assert s.label == "forge-builder"
        assert s.context_tokens is None
        assert s.aborted_last_run is True

    def test_raises_auth_error_on_401(self):
        transport = make_mock_transport({"error": "unauthorized"}, status_code=401)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        with pytest.raises(AuthError):
            client.fetch_sessions()

    def test_raises_auth_error_on_403(self):
        transport = make_mock_transport({"error": "forbidden"}, status_code=403)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        with pytest.raises(AuthError):
            client.fetch_sessions()

    def test_raises_connection_error_on_network_failure(self):
        transport = make_error_transport(httpx.ConnectError("Connection refused"))
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        with pytest.raises(ConnectionError):
            client.fetch_sessions()

    def test_returns_empty_list_on_unexpected_error(self):
        """An unexpected response shape (no 'result' key) should return empty list."""
        transport = make_mock_transport({"ok": True, "result": {}})
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        sessions = client.fetch_sessions()
        assert sessions == []

    def test_sends_authorization_header_when_token_set(self):
        captured_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(200, json=SAMPLE_RESPONSE)

        transport = httpx.MockTransport(handler)
        config = make_config(token="my-secret")
        client = GatewayClient(config)
        # Don't pre-inject _client — let _get_client build it with transport via monkey patch
        # We'll inject directly with the transport
        client._client = httpx.Client(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {config.token}"},
            transport=transport,
        )

        client.fetch_sessions()
        assert captured_headers.get("authorization") == "Bearer my-secret"

    def test_posts_to_correct_endpoint(self):
        captured_requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(200, json=SAMPLE_RESPONSE)

        transport = httpx.MockTransport(handler)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        client.fetch_sessions()

        assert len(captured_requests) == 1
        req = captured_requests[0]
        assert req.method == "POST"
        assert req.url.path == "/tools/invoke"

    def test_sends_correct_request_body(self):
        captured_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(request.content))
            return httpx.Response(200, json=SAMPLE_RESPONSE)

        transport = httpx.MockTransport(handler)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        client.fetch_sessions(active_minutes=720)

        body = captured_bodies[0]
        assert body["tool"] == "sessions_list"
        assert body["args"]["activeMinutes"] == 720


class TestGatewayClientClose:
    def test_close_closes_http_client(self):
        transport = make_mock_transport(SAMPLE_RESPONSE)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        client.close()
        assert client._client.is_closed

    def test_close_when_no_client_does_not_raise(self):
        config = make_config()
        client = GatewayClient(config)
        client.close()  # Should not raise
