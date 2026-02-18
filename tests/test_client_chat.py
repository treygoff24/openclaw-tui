from __future__ import annotations

import json
import pytest
import httpx

from openclaw_tui.config import GatewayConfig
from openclaw_tui.client import GatewayClient, GatewayError, AuthError


# Sample response for send_message
SEND_MESSAGE_RESPONSE = {
    "ok": True,
    "result": {
        "details": {
            "success": True,
            "message": "Message sent to session"
        }
    }
}

# Sample response for fetch_history
FETCH_HISTORY_RESPONSE = {
    "ok": True,
    "result": {
        "details": {
            "messages": [
                {
                    "key": "msg-1",
                    "role": "user",
                    "content": "Hello",
                    "timestamp": 1771379198943
                },
                {
                    "key": "msg-2",
                    "role": "assistant",
                    "content": "Hi there!",
                    "timestamp": 1771379200000
                },
                {
                    "key": "msg-3",
                    "role": "user",
                    "content": "How are you?",
                    "timestamp": 1771379205000
                }
            ]
        }
    }
}

FETCH_HISTORY_ALT_SHAPE_RESPONSE = {
    "ok": True,
    "result": {
        "details": {
            "history": [
                {
                    "key": "msg-1",
                    "role": "assistant",
                    "content": "Alt shape works",
                    "timestamp": 1771379200000,
                }
            ]
        }
    },
}

# Sample response for abort_session
ABORT_SESSION_RESPONSE = {
    "ok": True,
    "result": {
        "details": {
            "success": True,
            "aborted": True
        }
    }
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


class TestSendMessage:
    def test_send_message_success(self):
        transport = make_mock_transport(SEND_MESSAGE_RESPONSE)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.send_message("agent:main:main", "Hello world")

        assert result["ok"] is True
        assert result["result"]["details"]["success"] is True

    def test_send_message_sends_correct_payload(self):
        captured_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(request.content))
            return httpx.Response(200, json=SEND_MESSAGE_RESPONSE)

        transport = httpx.MockTransport(handler)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        client.send_message("agent:minimax:subagent:abc123", "Test message")

        body = captured_bodies[0]
        assert body["tool"] == "sessions_send"
        assert body["args"]["sessionKey"] == "agent:minimax:subagent:abc123"
        assert body["args"]["message"] == "Test message"

    def test_send_message_raises_auth_error_on_401(self):
        transport = make_mock_transport({"error": "unauthorized"}, status_code=401)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        with pytest.raises(AuthError):
            client.send_message("agent:main:main", "Hello")

    def test_send_message_raises_auth_error_on_403(self):
        transport = make_mock_transport({"error": "forbidden"}, status_code=403)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        with pytest.raises(AuthError):
            client.send_message("agent:main:main", "Hello")

    def test_send_message_raises_connection_error_on_network_failure(self):
        transport = make_error_transport(httpx.ConnectError("Connection refused"))
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        with pytest.raises(ConnectionError):
            client.send_message("agent:main:main", "Hello")


class TestFetchHistory:
    def test_fetch_history_success(self):
        transport = make_mock_transport(FETCH_HISTORY_RESPONSE)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_history("agent:main:main")

        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["key"] == "msg-1"
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"

    def test_fetch_history_with_custom_limit(self):
        captured_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(request.content))
            return httpx.Response(200, json=FETCH_HISTORY_RESPONSE)

        transport = httpx.MockTransport(handler)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        client.fetch_history("agent:main:main", limit=10)

        body = captured_bodies[0]
        assert body["tool"] == "sessions_history"
        assert body["args"]["sessionKey"] == "agent:main:main"
        assert body["args"]["limit"] == 10

    def test_fetch_history_default_limit(self):
        captured_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(request.content))
            return httpx.Response(200, json=FETCH_HISTORY_RESPONSE)

        transport = httpx.MockTransport(handler)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        client.fetch_history("agent:main:main")

        body = captured_bodies[0]
        assert body["args"]["limit"] == 30

    def test_fetch_history_returns_empty_list_on_connection_error(self):
        transport = make_error_transport(httpx.ConnectError("Connection refused"))
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_history("agent:main:main")
        assert result == []

    def test_fetch_history_returns_empty_list_on_auth_error(self):
        transport = make_mock_transport({"error": "unauthorized"}, status_code=401)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_history("agent:main:main")
        assert result == []

    def test_fetch_history_returns_empty_list_on_unexpected_response_shape(self):
        transport = make_mock_transport({"ok": True})
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_history("agent:main:main")
        assert result == []

    def test_fetch_history_supports_alternate_history_field(self):
        transport = make_mock_transport(FETCH_HISTORY_ALT_SHAPE_RESPONSE)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_history("agent:main:main")
        assert len(result) == 1
        assert result[0]["content"] == "Alt shape works"
        assert client.last_history_error is None

    def test_fetch_history_retries_with_snake_case_session_key(self):
        captured_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            captured_bodies.append(body)
            if len(captured_bodies) == 1:
                return httpx.Response(
                    422,
                    json={"error": "Invalid input: expected session_key"},
                )
            return httpx.Response(200, json=FETCH_HISTORY_RESPONSE)

        transport = httpx.MockTransport(handler)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_history("agent:main:main")

        assert len(result) == 3
        assert captured_bodies[0]["args"]["sessionKey"] == "agent:main:main"
        assert captured_bodies[1]["args"]["session_key"] == "agent:main:main"
        assert client.last_history_error is None

    def test_fetch_history_sets_descriptive_error(self):
        transport = make_mock_transport(
            {"error": "Session not found for session_key"},
            status_code=404,
        )
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_history("agent:main:missing")
        assert result == []
        assert client.last_history_error == "Gateway returned HTTP 404: Session not found for session_key"


class TestAbortSession:
    def test_abort_session_success(self):
        transport = make_mock_transport(ABORT_SESSION_RESPONSE)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.abort_session("agent:minimax:subagent:abc123")

        assert result["ok"] is True
        assert result["result"]["details"]["success"] is True
        assert result["result"]["details"]["aborted"] is True

    def test_abort_session_sends_correct_payload(self):
        captured_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(request.content))
            return httpx.Response(200, json=ABORT_SESSION_RESPONSE)

        transport = httpx.MockTransport(handler)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        client.abort_session("agent:minimax:subagent:xyz789")

        body = captured_bodies[0]
        assert body["tool"] == "sessions_kill"
        assert body["args"]["sessionKey"] == "agent:minimax:subagent:xyz789"

    def test_abort_session_raises_auth_error_on_401(self):
        transport = make_mock_transport({"error": "unauthorized"}, status_code=401)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        with pytest.raises(AuthError):
            client.abort_session("agent:main:main")

    def test_abort_session_raises_auth_error_on_403(self):
        transport = make_mock_transport({"error": "forbidden"}, status_code=403)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        with pytest.raises(AuthError):
            client.abort_session("agent:main:main")

    def test_abort_session_raises_connection_error_on_network_failure(self):
        transport = make_error_transport(httpx.ConnectError("Connection refused"))
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        with pytest.raises(ConnectionError):
            client.abort_session("agent:main:main")
