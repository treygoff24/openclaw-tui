from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any


_RANDOM_SEGMENT_LEN = 8
_RANDOM_SEGMENT_FALLBACK = "00000000"
_MODEL_REF_RE = re.compile(r"^[^/\s]+/[^/\s]+$")


@dataclass(frozen=True, slots=True)
class ModelChoice:
    provider: str
    model_id: str
    name: str | None = None

    @property
    def ref(self) -> str:
        return f"{self.provider}/{self.model_id}"


def build_new_main_session_key(now_ms: int, rand: str) -> str:
    """Build a canonical main-agent session key with a UTC timestamp."""
    timestamp = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    random_segment = _sanitize_random_segment(rand)
    return f"agent:main:chat:{timestamp}-{random_segment}"


def parse_newsession_args(args: str) -> tuple[str | None, str | None, str | None]:
    """Parse `/newsession` args into model ref + optional label."""
    raw = args.strip()
    if not raw:
        return None, None, None

    parts = raw.split(None, 1)
    model_ref = parts[0].strip()
    if not _MODEL_REF_RE.fullmatch(model_ref):
        return None, None, "Usage: /newsession <provider/model> [label]"

    label = parts[1].strip() if len(parts) > 1 else None
    if label == "":
        label = None
    return model_ref, label, None


def normalize_model_choices(raw_models: Any) -> list[ModelChoice]:
    """Normalize model payloads into a clean list of selectable choices."""
    payload: list[dict[str, Any]]
    if isinstance(raw_models, dict):
        models = raw_models.get("models")
        payload = models if isinstance(models, list) else []
    elif isinstance(raw_models, list):
        payload = raw_models
    else:
        payload = []

    normalized: list[ModelChoice] = []
    seen_refs: set[str] = set()
    for row in payload:
        if not isinstance(row, dict):
            continue
        provider = row.get("provider")
        model_id = row.get("id")
        if not isinstance(provider, str) or not isinstance(model_id, str):
            continue
        provider = provider.strip()
        model_id = model_id.strip()
        if not provider or not model_id:
            continue
        choice = ModelChoice(
            provider=provider,
            model_id=model_id,
            name=row.get("name") if isinstance(row.get("name"), str) else None,
        )
        if choice.ref in seen_refs:
            continue
        seen_refs.add(choice.ref)
        normalized.append(choice)
    return normalized


def _sanitize_random_segment(raw: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]", "", raw.lower())
    if not cleaned:
        return _RANDOM_SEGMENT_FALLBACK
    cleaned = cleaned[:_RANDOM_SEGMENT_LEN]
    if len(cleaned) < _RANDOM_SEGMENT_LEN:
        cleaned = f"{cleaned}{_RANDOM_SEGMENT_FALLBACK}"[:_RANDOM_SEGMENT_LEN]
    return cleaned

