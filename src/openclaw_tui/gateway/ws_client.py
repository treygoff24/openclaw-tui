from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import uuid4

from websockets.asyncio.client import connect as ws_connect

logger = logging.getLogger(__name__)

# Keep in sync with OpenClaw gateway protocol/schema version.
PROTOCOL_VERSION = 3
DEFAULT_TIMEOUT_MS = 30_000
DEFAULT_CONNECT_DELAY_S = 0.75
TOOL_EVENTS_CAP = "tool-events"


class GatewayWsRequestTimeoutError(TimeoutError):
    def __init__(self, method: str, request_id: str, timeout_ms: int) -> None:
        super().__init__(f"gateway request timed out after {timeout_ms}ms: {method}")
        self.method = method
        self.request_id = request_id
        self.timeout_ms = timeout_ms


@dataclass
class _PendingRequest:
    method: str
    future: asyncio.Future[Any]
    expect_final: bool


class GatewayWsClient:
    def __init__(
        self,
        *,
        url: str,
        token: str | None = None,
        password: str | None = None,
        client_display_name: str = "openclaw-tui",
        client_version: str = "dev",
        platform: str = "python",
        request_timeout_ms: int = DEFAULT_TIMEOUT_MS,
        connect_delay_s: float = DEFAULT_CONNECT_DELAY_S,
        connector: Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.password = password
        self.client_display_name = client_display_name
        self.client_version = client_version
        self.platform = platform
        self.request_timeout_ms = max(1, int(request_timeout_ms))
        self.connect_delay_s = max(0.0, float(connect_delay_s))
        self._connector = connector or self._default_connector

        self._ws: Any | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._connect_task: asyncio.Task[None] | None = None
        self._pending: dict[str, _PendingRequest] = {}
        self._ready = asyncio.Event()
        self._closed = False
        self._connect_nonce: str | None = None
        self._connect_sent = False
        self._connect_error: str | None = None
        self._connect_failed = asyncio.Event()
        self._last_seq: int | None = None

        self.hello: dict[str, Any] | None = None
        self.on_event: Callable[[dict[str, Any]], None] | None = None
        self.on_connected: Callable[[], None] | None = None
        self.on_disconnected: Callable[[str], None] | None = None
        self.on_gap: Callable[[dict[str, int]], None] | None = None

    async def _default_connector(self, url: str) -> Any:
        return await ws_connect(url, max_size=25 * 1024 * 1024)

    async def start(self) -> None:
        if self._ws is not None:
            return
        self._closed = False
        self._connect_error = None
        self._connect_failed.clear()
        self._ws = await self._connector(self.url)
        self._reader_task = asyncio.create_task(self._read_loop())
        self._queue_connect()

    async def stop(self) -> None:
        self._closed = True
        if self._connect_task is not None:
            self._connect_task.cancel()
            self._connect_task = None
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        self._ready.clear()
        self._connect_failed.clear()
        self._connect_error = None
        self._fail_pending(RuntimeError("gateway client stopped"))

    async def wait_ready(self, timeout_ms: int | None = None) -> None:
        timeout_s = (timeout_ms if timeout_ms is not None else self.request_timeout_ms) / 1000.0
        ready_task = asyncio.create_task(self._ready.wait())
        failed_task = asyncio.create_task(self._connect_failed.wait())
        try:
            done, pending = await asyncio.wait(
                {ready_task, failed_task},
                timeout=timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for pending_task in pending:
                pending_task.cancel()
            if ready_task in done and self._ready.is_set():
                return
            if failed_task in done and self._connect_failed.is_set():
                raise RuntimeError(self._connect_error or "gateway connect failed")
            raise TimeoutError()
        finally:
            if not ready_task.done():
                ready_task.cancel()
            if not failed_task.done():
                failed_task.cancel()

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout_ms: int | None = None,
        expect_final: bool = False,
    ) -> Any:
        ws = self._ws
        if ws is None:
            raise RuntimeError("gateway not connected")

        request_id = str(uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = _PendingRequest(
            method=method,
            future=future,
            expect_final=expect_final,
        )
        frame = {
            "type": "req",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        await ws.send(json.dumps(frame))

        resolved_timeout_ms = max(1, int(timeout_ms or self.request_timeout_ms))
        try:
            return await asyncio.wait_for(future, timeout=resolved_timeout_ms / 1000.0)
        except asyncio.TimeoutError as exc:
            pending = self._pending.pop(request_id, None)
            if pending is not None and not pending.future.done():
                pending.future.set_exception(
                    GatewayWsRequestTimeoutError(method, request_id, resolved_timeout_ms)
                )
            raise GatewayWsRequestTimeoutError(method, request_id, resolved_timeout_ms) from exc

    async def send_chat(
        self,
        *,
        session_key: str,
        message: str,
        thinking: str | None = None,
        deliver: bool = False,
        timeout_ms: int | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        used_run_id = run_id or str(uuid4())
        payload = {
            "sessionKey": session_key,
            "message": message,
            "thinking": thinking,
            "deliver": deliver,
            "timeoutMs": timeout_ms,
            "idempotencyKey": used_run_id,
        }
        await self.request("chat.send", payload)
        return {"runId": used_run_id}

    async def chat_history(self, session_key: str, limit: int = 200) -> dict[str, Any]:
        return await self.request("chat.history", {"sessionKey": session_key, "limit": limit})

    async def chat_abort(self, session_key: str, run_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"sessionKey": session_key}
        if run_id:
            payload["runId"] = run_id
        return await self.request("chat.abort", payload)

    async def sessions_list(self, **kwargs: Any) -> dict[str, Any]:
        return await self.request("sessions.list", kwargs)

    async def sessions_patch(self, **kwargs: Any) -> dict[str, Any]:
        return await self.request("sessions.patch", kwargs)

    async def sessions_reset(self, key: str) -> dict[str, Any]:
        return await self.request("sessions.reset", {"key": key})

    async def agents_list(self) -> dict[str, Any]:
        return await self.request("agents.list", {})

    async def models_list(self) -> list[dict[str, Any]]:
        response = await self.request("models.list", {})
        models = response.get("models") if isinstance(response, dict) else None
        return models if isinstance(models, list) else []

    async def status(self) -> Any:
        return await self.request("status", {})

    def _queue_connect(self, *, delay_s: float | None = None) -> None:
        if self._connect_task is not None:
            self._connect_task.cancel()
        self._connect_task = asyncio.create_task(
            self._connect_after_delay(self.connect_delay_s if delay_s is None else delay_s)
        )

    async def _connect_after_delay(self, delay_s: float) -> None:
        try:
            await asyncio.sleep(max(0.0, float(delay_s)))
            if self._closed:
                return
            await self._send_connect()
        except Exception as exc:  # noqa: BLE001
            logger.debug("gateway connect failed: %s", exc)
            self._connect_sent = False
            self._connect_error = str(exc)
            self._connect_failed.set()
            if self.on_disconnected is not None:
                self.on_disconnected(str(exc))

    async def _send_connect(self) -> None:
        if self._connect_sent:
            return
        self._connect_sent = True
        auth: dict[str, str] | None = None
        if self.token or self.password:
            auth = {}
            if self.token:
                auth["token"] = self.token
            if self.password:
                auth["password"] = self.password

        params = {
            "minProtocol": PROTOCOL_VERSION,
            "maxProtocol": PROTOCOL_VERSION,
            "client": {
                "id": "gateway-client",
                "displayName": self.client_display_name,
                "version": self.client_version,
                "platform": self.platform,
                "mode": "ui",
                "instanceId": str(uuid4()),
            },
            "caps": [TOOL_EVENTS_CAP],
            "auth": auth,
            "role": "operator",
            "scopes": ["operator.read", "operator.admin"],
        }

        hello = await self.request("connect", params)
        if isinstance(hello, dict):
            self.hello = hello
        self._connect_error = None
        self._connect_failed.clear()
        self._ready.set()
        if self.on_connected is not None:
            self.on_connected()

    async def _read_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        reason = "closed"
        try:
            async for raw in ws:
                self._handle_frame(raw)
        except asyncio.CancelledError:
            reason = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001
            reason = str(exc)
            logger.debug("gateway ws read loop ended: %s", exc)
        finally:
            self._ready.clear()
            self._connect_sent = False
            self._connect_nonce = None
            self._ws = None
            if not self._closed and not self._ready.is_set():
                self._connect_error = reason
                self._connect_failed.set()
            self._fail_pending(RuntimeError(f"gateway disconnected: {reason}"))
            if not self._closed and self.on_disconnected is not None:
                self.on_disconnected(reason)

    def _handle_frame(self, raw: str) -> None:
        try:
            frame = json.loads(raw)
        except Exception:  # noqa: BLE001
            return
        if not isinstance(frame, dict):
            return

        frame_type = frame.get("type")
        if frame_type == "event":
            self._handle_event_frame(frame)
            return
        if frame_type == "res":
            self._handle_response_frame(frame)

    def _handle_event_frame(self, frame: dict[str, Any]) -> None:
        event = frame.get("event")
        payload = frame.get("payload")
        if event == "connect.challenge" and isinstance(payload, dict):
            nonce = payload.get("nonce")
            if isinstance(nonce, str) and nonce:
                self._connect_nonce = nonce
            if not self._connect_sent:
                self._queue_connect(delay_s=0.0)
            return

        seq = frame.get("seq")
        if isinstance(seq, int):
            if self._last_seq is not None and seq > (self._last_seq + 1) and self.on_gap is not None:
                self.on_gap({"expected": self._last_seq + 1, "received": seq})
            self._last_seq = seq

        if self.on_event is not None:
            self.on_event(
                {
                    "event": event,
                    "payload": payload,
                    "seq": seq,
                }
            )

    def _handle_response_frame(self, frame: dict[str, Any]) -> None:
        request_id = frame.get("id")
        if not isinstance(request_id, str):
            return
        pending = self._pending.get(request_id)
        if pending is None:
            return

        payload = frame.get("payload")
        if (
            pending.expect_final
            and isinstance(payload, dict)
            and payload.get("status") == "accepted"
        ):
            return

        self._pending.pop(request_id, None)
        ok = bool(frame.get("ok"))
        if ok:
            if not pending.future.done():
                pending.future.set_result(payload)
            return

        message = "unknown error"
        error = frame.get("error")
        if isinstance(error, dict):
            error_message = error.get("message")
            if isinstance(error_message, str) and error_message:
                message = error_message
        if not pending.future.done():
            pending.future.set_exception(RuntimeError(message))

    def _fail_pending(self, exc: Exception) -> None:
        for request_id, pending in list(self._pending.items()):
            self._pending.pop(request_id, None)
            if not pending.future.done():
                pending.future.set_exception(exc)
