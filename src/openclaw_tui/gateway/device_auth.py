from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    public_key_pem: str
    private_key_pem: str


def resolve_state_dir() -> Path:
    openclaw_home = os.environ.get("OPENCLAW_HOME", "").strip()
    if openclaw_home:
        return Path(os.path.expanduser(openclaw_home))
    return Path.home() / ".openclaw"


def _identity_dir() -> Path:
    return resolve_state_dir() / "identity"


def _device_identity_path() -> Path:
    return _identity_dir() / "device.json"


def _device_auth_path() -> Path:
    return _identity_dir() / "device-auth.json"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _public_key_raw_from_pem(public_key_pem: str) -> bytes:
    key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    return key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _device_id_from_public_key(public_key_pem: str) -> str:
    return hashlib.sha256(_public_key_raw_from_pem(public_key_pem)).hexdigest()


def public_key_raw_base64url_from_pem(public_key_pem: str) -> str:
    return _b64url_encode(_public_key_raw_from_pem(public_key_pem))


def sign_device_payload(private_key_pem: str, payload: str) -> str:
    key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    signature = key.sign(payload.encode("utf-8"))
    return _b64url_encode(signature)


def build_device_auth_payload(
    *,
    device_id: str,
    client_id: str,
    client_mode: str,
    role: str,
    scopes: list[str],
    signed_at_ms: int,
    token: str | None,
    nonce: str | None,
) -> str:
    version = "v2" if nonce else "v1"
    fields = [
        version,
        device_id,
        client_id,
        client_mode,
        role,
        ",".join(scopes),
        str(signed_at_ms),
        token or "",
    ]
    if version == "v2":
        fields.append(nonce or "")
    return "|".join(fields)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{json.dumps(payload, indent=2)}\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_or_create_device_identity() -> DeviceIdentity:
    path = _device_identity_path()
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("version") == 1
                and isinstance(payload.get("deviceId"), str)
                and isinstance(payload.get("publicKeyPem"), str)
                and isinstance(payload.get("privateKeyPem"), str)
            ):
                derived_id = _device_id_from_public_key(payload["publicKeyPem"])
                if derived_id != payload["deviceId"]:
                    payload["deviceId"] = derived_id
                    _write_json(path, payload)
                return DeviceIdentity(
                    device_id=derived_id,
                    public_key_pem=payload["publicKeyPem"],
                    private_key_pem=payload["privateKeyPem"],
                )
    except Exception:
        pass

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_key_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    device_id = _device_id_from_public_key(public_key_pem)
    payload = {
        "version": 1,
        "deviceId": device_id,
        "publicKeyPem": public_key_pem,
        "privateKeyPem": private_key_pem,
        "createdAtMs": int(time.time() * 1000),
    }
    _write_json(path, payload)
    return DeviceIdentity(
        device_id=device_id,
        public_key_pem=public_key_pem,
        private_key_pem=private_key_pem,
    )


def load_device_auth_token(*, device_id: str, role: str) -> dict[str, Any] | None:
    path = _device_auth_path()
    try:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != 1 or payload.get("deviceId") != device_id:
            return None
        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            return None
        entry = tokens.get(role)
        if not isinstance(entry, dict) or not isinstance(entry.get("token"), str):
            return None
        return entry
    except Exception:
        return None


def store_device_auth_token(
    *,
    device_id: str,
    role: str,
    token: str,
    scopes: list[str] | None,
) -> None:
    path = _device_auth_path()
    payload: dict[str, Any] = {
        "version": 1,
        "deviceId": device_id,
        "tokens": {},
    }
    try:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if (
                isinstance(existing, dict)
                and existing.get("version") == 1
                and existing.get("deviceId") == device_id
                and isinstance(existing.get("tokens"), dict)
            ):
                payload["tokens"] = dict(existing["tokens"])
    except Exception:
        pass

    normalized_scopes = sorted({scope.strip() for scope in (scopes or []) if scope.strip()})
    payload["tokens"][role] = {
        "token": token,
        "role": role,
        "scopes": normalized_scopes,
        "updatedAtMs": int(time.time() * 1000),
    }
    _write_json(path, payload)


def clear_device_auth_token(*, device_id: str, role: str) -> None:
    path = _device_auth_path()
    try:
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != 1 or payload.get("deviceId") != device_id:
            return
        tokens = payload.get("tokens")
        if not isinstance(tokens, dict) or role not in tokens:
            return
        tokens = dict(tokens)
        tokens.pop(role, None)
        payload["tokens"] = tokens
        _write_json(path, payload)
    except Exception:
        return
