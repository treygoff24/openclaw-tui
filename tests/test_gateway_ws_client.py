from __future__ import annotations

import asyncio
import json

import pytest

from openclaw_tui.gateway.device_auth import DeviceIdentity
from openclaw_tui.gateway.ws_client import GatewayWsClient, GatewayWsRequestTimeoutError


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent_frames: list[dict] = []
        self._incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self.closed = False

    async def send(self, raw: str) -> None:
        self.sent_frames.append(json.loads(raw))

    async def close(self) -> None:
        self.closed = True
        await self._incoming.put(None)

    def __aiter__(self) -> _FakeWebSocket:
        return self

    async def __anext__(self) -> str:
        value = await self._incoming.get()
        if value is None:
            raise StopAsyncIteration
        return value

    async def push(self, frame: dict) -> None:
        await self._incoming.put(json.dumps(frame))


async def _ready_client() -> tuple[GatewayWsClient, _FakeWebSocket]:
    ws = _FakeWebSocket()

    async def connector(_url: str) -> _FakeWebSocket:
        return ws

    client = GatewayWsClient(
        url="ws://127.0.0.1:2020",
        connect_delay_s=0.0,
        request_timeout_ms=200,
        connector=connector,
        device_auth=False,
    )
    await client.start()
    for _ in range(20):
        if ws.sent_frames:
            break
        await asyncio.sleep(0.01)
    assert ws.sent_frames, "connect frame was not sent"

    connect_req = ws.sent_frames[-1]
    await ws.push(
        {
            "type": "res",
            "id": connect_req["id"],
            "ok": True,
            "payload": {"type": "hello-ok", "protocol": 3},
        }
    )
    await client.wait_ready(timeout_ms=500)
    return client, ws


@pytest.mark.asyncio
async def test_connect_success_sends_gateway_client_identity() -> None:
    client, ws = await _ready_client()
    connect_req = ws.sent_frames[0]
    params = connect_req["params"]
    assert connect_req["method"] == "connect"
    assert params["client"]["id"] == "gateway-client"
    assert params["client"]["mode"] == "ui"
    assert params["caps"] == ["tool-events"]
    await client.stop()


@pytest.mark.asyncio
async def test_request_timeout_raises_descriptive_error() -> None:
    client, ws = await _ready_client()

    with pytest.raises(GatewayWsRequestTimeoutError) as exc_info:
        await client.request("status", {}, timeout_ms=20)

    assert "status" in str(exc_info.value)
    assert exc_info.value.method == "status"
    await ws.close()
    await client.stop()


@pytest.mark.asyncio
async def test_request_response_matching_resolves_call() -> None:
    client, ws = await _ready_client()
    request_task = asyncio.create_task(client.request("status", {}))
    await asyncio.sleep(0)
    status_req = ws.sent_frames[-1]
    await ws.push(
        {
            "type": "res",
            "id": status_req["id"],
            "ok": True,
            "payload": {"ok": True, "uptime": 123},
        }
    )
    result = await request_task
    assert result["uptime"] == 123
    await client.stop()


@pytest.mark.asyncio
async def test_send_chat_includes_inline_attachments_payload() -> None:
    client, ws = await _ready_client()
    send_task = asyncio.create_task(
        client.send_chat(
            session_key="agent:main:main",
            message="what is in this image?",
            attachments=[{"type": "image", "mimeType": "image/png", "content": "ZmFrZQ=="}],
            run_id="run-inline-1",
        )
    )
    await asyncio.sleep(0)
    send_req = ws.sent_frames[-1]
    await ws.push(
        {
            "type": "res",
            "id": send_req["id"],
            "ok": True,
            "payload": {"ok": True},
        }
    )

    result = await send_task

    assert send_req["method"] == "chat.send"
    assert send_req["params"]["sessionKey"] == "agent:main:main"
    assert send_req["params"]["message"] == "what is in this image?"
    assert send_req["params"]["attachments"] == [
        {"type": "image", "mimeType": "image/png", "content": "ZmFrZQ=="}
    ]
    assert result["runId"] == "run-inline-1"
    await client.stop()


@pytest.mark.asyncio
async def test_gap_callback_receives_expected_and_received_seq() -> None:
    client, ws = await _ready_client()
    gaps: list[dict[str, int]] = []
    client.on_gap = gaps.append

    await ws.push({"type": "event", "event": "chat", "seq": 5, "payload": {}})
    await ws.push({"type": "event", "event": "chat", "seq": 7, "payload": {}})
    await asyncio.sleep(0.01)

    assert gaps == [{"expected": 6, "received": 7}]
    await client.stop()


@pytest.mark.asyncio
async def test_connect_challenge_includes_signed_device_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _FakeWebSocket()
    stored: list[dict] = []

    async def connector(_url: str) -> _FakeWebSocket:
        return ws

    monkeypatch.setattr(
        "openclaw_tui.gateway.ws_client.public_key_raw_base64url_from_pem",
        lambda _pem: "pub-raw",
    )
    monkeypatch.setattr(
        "openclaw_tui.gateway.ws_client.sign_device_payload",
        lambda _pem, _payload: "sig-raw",
    )
    monkeypatch.setattr(
        "openclaw_tui.gateway.ws_client.load_device_auth_token",
        lambda **_kwargs: {"token": "device-token"},
    )
    monkeypatch.setattr(
        "openclaw_tui.gateway.ws_client.store_device_auth_token",
        lambda **kwargs: stored.append(kwargs),
    )

    client = GatewayWsClient(
        url="ws://127.0.0.1:2020",
        connect_delay_s=1.0,
        request_timeout_ms=200,
        connector=connector,
        token="shared-token",
        device_identity=DeviceIdentity(
            device_id="device-123",
            public_key_pem="fake-pub",
            private_key_pem="fake-priv",
        ),
    )
    await client.start()
    await ws.push({"type": "event", "event": "connect.challenge", "payload": {"nonce": "abc"}})

    for _ in range(20):
        if ws.sent_frames:
            break
        await asyncio.sleep(0.01)
    assert ws.sent_frames, "connect frame was not sent after challenge"

    connect_req = ws.sent_frames[-1]
    assert connect_req["method"] == "connect"
    assert connect_req["params"]["auth"]["token"] == "device-token"
    assert connect_req["params"]["device"]["id"] == "device-123"
    assert connect_req["params"]["device"]["publicKey"] == "pub-raw"
    assert connect_req["params"]["device"]["signature"] == "sig-raw"
    assert connect_req["params"]["device"]["nonce"] == "abc"

    await ws.push(
        {
            "type": "res",
            "id": connect_req["id"],
            "ok": True,
            "payload": {
                "type": "hello-ok",
                "protocol": 3,
                "auth": {
                    "deviceToken": "new-device-token",
                    "role": "operator",
                    "scopes": ["operator.admin"],
                },
            },
        }
    )
    await client.wait_ready(timeout_ms=500)
    assert stored and stored[-1]["token"] == "new-device-token"
    await client.stop()
