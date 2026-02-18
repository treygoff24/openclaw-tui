from __future__ import annotations

import asyncio
import json

import pytest

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
            "payload": {"type": "hello-ok", "protocol": 1},
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
async def test_connect_challenge_does_not_send_fake_device_identity() -> None:
    ws = _FakeWebSocket()

    async def connector(_url: str) -> _FakeWebSocket:
        return ws

    client = GatewayWsClient(
        url="ws://127.0.0.1:2020",
        connect_delay_s=1.0,
        request_timeout_ms=200,
        connector=connector,
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
    assert "device" not in connect_req["params"]

    await ws.push(
        {
            "type": "res",
            "id": connect_req["id"],
            "ok": True,
            "payload": {"type": "hello-ok", "protocol": 3},
        }
    )
    await client.wait_ready(timeout_ms=500)
    await client.stop()
