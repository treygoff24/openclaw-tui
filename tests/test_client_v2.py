from __future__ import annotations

import json
import pytest
import httpx

from openclaw_tui.config import GatewayConfig
from openclaw_tui.client import GatewayClient
from openclaw_tui.models import SessionInfo, TreeNodeData


# Sample sessions response WITH transcriptPath
SESSIONS_WITH_TRANSCRIPT = {
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
                    "transcriptPath": "/transcripts/session-a56de194.json",
                },
                {
                    "key": "agent:minimax:subagent:88db67f5",
                    "kind": "subagent",
                    "channel": "internal",
                    "displayName": "Minimax Worker",
                    "label": "task-worker",
                    "updatedAt": 1771379100000,
                    "sessionId": "b1b2b3b4-0000-0000-0000-000000000002",
                    "model": "minimax-m2p5",
                    "contextTokens": None,
                    "totalTokens": 5000,
                    "abortedLastRun": False,
                    # No transcriptPath field
                },
            ],
        }
    },
}


# Sample tree response
TREE_RESPONSE = {
    "ok": True,
    "result": {
        "details": {
            "active": 1,
            "completed": 2,
            "total": 3,
            "tree": [
                {
                    "key": "agent:glm:subagent:uuid1",
                    "label": "parent-task",
                    "depth": 1,
                    "status": "completed",
                    "runtimeMs": 199554,
                    "children": [
                        {
                            "key": "agent:minimax:subagent:uuid2",
                            "label": "child-task",
                            "depth": 2,
                            "status": "active",
                            "runtimeMs": 5000,
                            "children": []
                        }
                    ]
                }
            ]
        }
    }
}


# Tree response with nested grandchildren
TREE_RESPONSE_DEEP = {
    "ok": True,
    "result": {
        "details": {
            "active": 1,
            "completed": 1,
            "total": 3,
            "tree": [
                {
                    "key": "agent:main:main",
                    "label": "root-task",
                    "depth": 0,
                    "status": "completed",
                    "runtimeMs": 100000,
                    "children": [
                        {
                            "key": "agent:glm:subagent:child1",
                            "label": "level-1",
                            "depth": 1,
                            "status": "completed",
                            "runtimeMs": 50000,
                            "children": [
                                {
                                    "key": "agent:minimax:subagent:grandchild",
                                    "label": "level-2",
                                    "depth": 2,
                                    "status": "active",
                                    "runtimeMs": 10000,
                                    "children": []
                                }
                            ]
                        }
                    ]
                }
            ]
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


class TestFetchTree:
    def test_fetch_tree_returns_list_of_tree_node_data(self):
        transport = make_mock_transport(TREE_RESPONSE)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_tree()

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], TreeNodeData)

    def test_fetch_tree_parses_key_label_depth_status_runtime(self):
        transport = make_mock_transport(TREE_RESPONSE)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_tree()
        node = result[0]

        assert node.key == "agent:glm:subagent:uuid1"
        assert node.label == "parent-task"
        assert node.depth == 1
        assert node.status == "completed"
        assert node.runtime_ms == 199554

    def test_fetch_tree_parses_children_recursively(self):
        transport = make_mock_transport(TREE_RESPONSE)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_tree()
        parent = result[0]

        assert len(parent.children) == 1
        child = parent.children[0]
        assert child.key == "agent:minimax:subagent:uuid2"
        assert child.label == "child-task"
        assert child.depth == 2
        assert child.status == "active"
        assert child.runtime_ms == 5000

    def test_fetch_tree_returns_empty_list_on_connection_error(self):
        transport = make_error_transport(httpx.ConnectError("Connection refused"))
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_tree()
        assert result == []

    def test_fetch_tree_returns_empty_list_on_auth_error(self):
        transport = make_mock_transport({"error": "unauthorized"}, status_code=401)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_tree()
        assert result == []

    def test_fetch_tree_returns_empty_list_on_unexpected_response_shape(self):
        # Missing 'result' key
        transport = make_mock_transport({"ok": True})
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_tree()
        assert result == []

    def test_fetch_tree_sends_correct_tool_name(self):
        captured_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(request.content))
            return httpx.Response(200, json=TREE_RESPONSE)

        transport = httpx.MockTransport(handler)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        client.fetch_tree()

        body = captured_bodies[0]
        assert body["tool"] == "sessions_tree"

    def test_fetch_tree_sends_correct_depth(self):
        captured_bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_bodies.append(json.loads(request.content))
            return httpx.Response(200, json=TREE_RESPONSE)

        transport = httpx.MockTransport(handler)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        client.fetch_tree(depth=10)

        body = captured_bodies[0]
        assert body["args"]["depth"] == 10

    def test_fetch_tree_deep_nesting(self):
        transport = make_mock_transport(TREE_RESPONSE_DEEP)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        result = client.fetch_tree()
        
        # Check root
        root = result[0]
        assert root.label == "root-task"
        
        # Check child
        child = root.children[0]
        assert child.label == "level-1"
        
        # Check grandchild
        grandchild = child.children[0]
        assert grandchild.label == "level-2"
        assert grandchild.depth == 2


class TestFetchSessionsTranscriptPath:
    def test_fetch_sessions_extracts_transcript_path(self):
        transport = make_mock_transport(SESSIONS_WITH_TRANSCRIPT)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        sessions = client.fetch_sessions()

        # First session has transcriptPath
        assert sessions[0].transcript_path == "/transcripts/session-a56de194.json"

    def test_fetch_sessions_transcript_path_defaults_to_none(self):
        transport = make_mock_transport(SESSIONS_WITH_TRANSCRIPT)
        config = make_config()
        client = GatewayClient(config)
        client._client = httpx.Client(
            base_url=config.base_url,
            transport=transport,
        )

        sessions = client.fetch_sessions()

        # Second session does NOT have transcriptPath field
        assert sessions[1].transcript_path is None
