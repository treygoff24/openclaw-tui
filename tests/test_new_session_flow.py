from __future__ import annotations

import re

from openclaw_tui.chat.new_session_flow import (
    build_new_main_session_key,
    normalize_model_choices,
    parse_newsession_args,
)


def test_build_new_main_session_key_uses_main_chat_prefix_and_utc_stamp() -> None:
    key = build_new_main_session_key(now_ms=1735732800000, rand="a1b2c3d4")
    assert key.startswith("agent:main:chat:")
    assert key == "agent:main:chat:20250101120000-a1b2c3d4"


def test_build_new_main_session_key_sanitizes_random_segment() -> None:
    key = build_new_main_session_key(now_ms=1735732800000, rand="A1..b2/!?")
    assert re.fullmatch(r"agent:main:chat:20250101120000-[a-z0-9]{8}", key)


def test_parse_newsession_args_empty() -> None:
    model, label, error = parse_newsession_args("")
    assert model is None
    assert label is None
    assert error is None


def test_parse_newsession_args_model_only() -> None:
    model, label, error = parse_newsession_args("anthropic/claude-opus-4-6")
    assert model == "anthropic/claude-opus-4-6"
    assert label is None
    assert error is None


def test_parse_newsession_args_model_and_label() -> None:
    model, label, error = parse_newsession_args("anthropic/claude-opus-4-6 sprint planning")
    assert model == "anthropic/claude-opus-4-6"
    assert label == "sprint planning"
    assert error is None


def test_parse_newsession_args_rejects_non_provider_model_format() -> None:
    model, label, error = parse_newsession_args("claude-opus-4-6")
    assert model is None
    assert label is None
    assert isinstance(error, str)
    assert "provider/model" in error


def test_normalize_model_choices_accepts_list_payload() -> None:
    models = normalize_model_choices(
        [
            {"provider": "anthropic", "id": "claude-opus-4-6", "name": "Opus"},
            {"provider": "openai", "id": "gpt-5.2"},
        ]
    )
    assert [choice.ref for choice in models] == ["anthropic/claude-opus-4-6", "openai/gpt-5.2"]


def test_normalize_model_choices_accepts_dict_models_payload() -> None:
    models = normalize_model_choices(
        {"models": [{"provider": "anthropic", "id": "claude-sonnet-4-6"}]}
    )
    assert [choice.ref for choice in models] == ["anthropic/claude-sonnet-4-6"]

