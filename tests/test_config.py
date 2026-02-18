from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from openclaw_tui.config import GatewayConfig, load_config


class TestGatewayConfig:
    def test_base_url_format(self):
        cfg = GatewayConfig(host="127.0.0.1", port=2020, token=None)
        assert cfg.base_url == "http://127.0.0.1:2020"

    def test_base_url_with_custom_port(self):
        cfg = GatewayConfig(host="localhost", port=18789, token="tok")
        assert cfg.base_url == "http://localhost:18789"


_ENV_VARS = ("OPENCLAW_GATEWAY_HOST", "OPENCLAW_GATEWAY_PORT", "OPENCLAW_WEBHOOK_TOKEN")


def clear_env(monkeypatch) -> None:
    """Remove all OpenClaw env vars so tests get clean defaults."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


class TestLoadConfig:
    def test_reads_port_and_token_from_config_file(self, tmp_path, monkeypatch):
        clear_env(monkeypatch)
        config_data = {
            "gateway": {
                "port": 9999,
                "auth": {
                    "token": "my-secret-token"
                }
            }
        }
        config_file = tmp_path / "openclaw.json"
        config_file.write_text(json.dumps(config_data))

        cfg = load_config(config_path=str(config_file))

        assert cfg.port == 9999
        assert cfg.token == "my-secret-token"

    def test_reads_port_without_token(self, tmp_path, monkeypatch):
        clear_env(monkeypatch)
        config_data = {
            "gateway": {
                "port": 7777
            }
        }
        config_file = tmp_path / "openclaw.json"
        config_file.write_text(json.dumps(config_data))

        cfg = load_config(config_path=str(config_file))

        assert cfg.port == 7777
        assert cfg.token is None

    def test_falls_back_to_defaults_when_file_missing(self, tmp_path, monkeypatch):
        clear_env(monkeypatch)
        missing_path = str(tmp_path / "nonexistent.json")

        cfg = load_config(config_path=missing_path)

        assert cfg.host == "127.0.0.1"
        assert cfg.port == 2020
        assert cfg.token is None

    def test_default_host_is_loopback(self, tmp_path, monkeypatch):
        clear_env(monkeypatch)
        config_data = {"gateway": {"port": 1234}}
        config_file = tmp_path / "openclaw.json"
        config_file.write_text(json.dumps(config_data))

        cfg = load_config(config_path=str(config_file))

        assert cfg.host == "127.0.0.1"

    def test_env_var_overrides_host(self, tmp_path, monkeypatch):
        clear_env(monkeypatch)
        config_file = tmp_path / "openclaw.json"
        config_file.write_text(json.dumps({"gateway": {"port": 2020}}))
        monkeypatch.setenv("OPENCLAW_GATEWAY_HOST", "192.168.1.10")

        cfg = load_config(config_path=str(config_file))

        assert cfg.host == "192.168.1.10"

    def test_env_var_overrides_port(self, tmp_path, monkeypatch):
        clear_env(monkeypatch)
        config_data = {"gateway": {"port": 2020, "auth": {"token": "tok"}}}
        config_file = tmp_path / "openclaw.json"
        config_file.write_text(json.dumps(config_data))
        monkeypatch.setenv("OPENCLAW_GATEWAY_PORT", "5555")

        cfg = load_config(config_path=str(config_file))

        assert cfg.port == 5555

    def test_env_var_overrides_token(self, tmp_path, monkeypatch):
        clear_env(monkeypatch)
        config_data = {"gateway": {"port": 2020, "auth": {"token": "file-token"}}}
        config_file = tmp_path / "openclaw.json"
        config_file.write_text(json.dumps(config_data))
        monkeypatch.setenv("OPENCLAW_WEBHOOK_TOKEN", "env-token")

        cfg = load_config(config_path=str(config_file))

        assert cfg.token == "env-token"

    def test_malformed_json_falls_back_to_defaults(self, tmp_path, monkeypatch):
        clear_env(monkeypatch)
        config_file = tmp_path / "openclaw.json"
        config_file.write_text("{ invalid json }")

        cfg = load_config(config_path=str(config_file))

        assert cfg.host == "127.0.0.1"
        assert cfg.port == 2020

    def test_env_overrides_apply_even_with_missing_file(self, tmp_path, monkeypatch):
        clear_env(monkeypatch)
        missing_path = str(tmp_path / "nonexistent.json")
        monkeypatch.setenv("OPENCLAW_GATEWAY_PORT", "8888")
        monkeypatch.setenv("OPENCLAW_WEBHOOK_TOKEN", "env-only-token")

        cfg = load_config(config_path=missing_path)

        assert cfg.port == 8888
        assert cfg.token == "env-only-token"
