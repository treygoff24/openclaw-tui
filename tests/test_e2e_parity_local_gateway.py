from __future__ import annotations

import os

import pytest

from openclaw_tui.gateway.ws_client import GatewayWsClient


@pytest.mark.asyncio
async def test_local_gateway_chat_send_round_trip_smoke() -> None:
    """Optional E2E parity check against a real local gateway.

    Enable by setting OPENCLAW_E2E_WS_URL and OPENCLAW_E2E_SESSION_KEY.
    """
    ws_url = os.environ.get("OPENCLAW_E2E_WS_URL")
    session_key = os.environ.get("OPENCLAW_E2E_SESSION_KEY")
    token = os.environ.get("OPENCLAW_E2E_TOKEN")
    if not ws_url or not session_key:
        pytest.skip("set OPENCLAW_E2E_WS_URL and OPENCLAW_E2E_SESSION_KEY for local parity e2e")

    client = GatewayWsClient(url=ws_url, token=token)
    await client.start()
    await client.wait_ready()
    await client.send_chat(session_key=session_key, message="e2e parity smoke", run_id="e2e-smoke-1")
    history = await client.chat_history(session_key, limit=20)
    await client.stop()

    messages = history.get("messages", []) if isinstance(history, dict) else []
    assert isinstance(messages, list)
