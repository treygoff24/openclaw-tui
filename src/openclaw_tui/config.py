from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 18789
_DEFAULT_CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"


@dataclass
class GatewayConfig:
    host: str
    port: int
    token: str | None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}"


def load_config(config_path: str | None = None) -> GatewayConfig:
    """Load config from ~/.openclaw/openclaw.json, falling back to env vars.

    Config file fields:
    - gateway.port (int, default 2020)
    - gateway.auth.token (str, optional)

    Env var overrides:
    - OPENCLAW_GATEWAY_HOST (default "127.0.0.1")
    - OPENCLAW_GATEWAY_PORT / CLAWDBOT_GATEWAY_PORT (overrides config file)
    - OPENCLAW_GATEWAY_TOKEN / OPENCLAW_WEBHOOK_TOKEN (overrides config file)

    Returns GatewayConfig. Never raises — uses defaults if config missing.
    """
    path = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH

    port = _DEFAULT_PORT
    token: str | None = None

    if path.exists():
        try:
            data = json.loads(path.read_text())
            gateway_section = data.get("gateway", {})
            port = int(gateway_section.get("port", _DEFAULT_PORT))
            auth_section = gateway_section.get("auth", {})
            token = auth_section.get("token", None)
        except Exception as exc:
            logger.warning("Failed to parse config file %s: %s — using defaults", path, exc)
            port = _DEFAULT_PORT
            token = None
    else:
        logger.info("Config file not found at %s — using defaults", path)

    # Env var overrides
    host = os.environ.get("OPENCLAW_GATEWAY_HOST", _DEFAULT_HOST)

    env_port = os.environ.get("OPENCLAW_GATEWAY_PORT") or os.environ.get("CLAWDBOT_GATEWAY_PORT")
    if env_port is not None:
        try:
            port = int(env_port)
        except ValueError:
            logger.warning("Invalid OPENCLAW_GATEWAY_PORT value %r — using %d", env_port, port)

    env_token = os.environ.get("OPENCLAW_GATEWAY_TOKEN") or os.environ.get("OPENCLAW_WEBHOOK_TOKEN")
    if env_token is not None:
        token = env_token

    return GatewayConfig(host=host, port=port, token=token)
