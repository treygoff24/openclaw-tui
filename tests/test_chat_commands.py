"""Tests for chat commands parser."""
import pytest
from openclaw_tui.chat.commands import format_command_hint, format_help, parse_input, ParsedInput


class TestParseInput:
    def test_slash_help(self):
        result = parse_input("/help")
        assert result.kind == "command"
        assert result.name == "help"
        assert result.args == ""
        assert result.raw == "/help"

    def test_slash_history_with_args(self):
        result = parse_input("/history 50")
        assert result.kind == "command"
        assert result.name == "history"
        assert result.args == "50"

    def test_slash_command_case_insensitive(self):
        result = parse_input("/HELP")
        assert result.kind == "command"
        assert result.name == "help"
        assert result.args == ""

    def test_slash_unknown_command(self):
        result = parse_input("/unknown")
        assert result.kind == "command"
        assert result.name == "unknown"
        assert result.args == ""

    def test_slash_newsession(self):
        result = parse_input("/newsession")
        assert result.kind == "command"
        assert result.name == "newsession"
        assert result.args == ""

    def test_slash_ns_alias_maps_to_newsession(self):
        result = parse_input("/ns")
        assert result.kind == "command"
        assert result.name == "newsession"
        assert result.args == ""

    def test_slash_newsession_with_model_and_label_args(self):
        result = parse_input("/newsession anthropic/claude-opus-4-6 sprint planning")
        assert result.kind == "command"
        assert result.name == "newsession"
        assert result.args == "anthropic/claude-opus-4-6 sprint planning"

    def test_bang_command(self):
        result = parse_input("!ls -la")
        assert result.kind == "bang"
        assert result.name == "ls -la"
        assert result.args == ""
        assert result.raw == "!ls -la"

    def test_regular_message(self):
        result = parse_input("hello world")
        assert result.kind == "message"
        assert result.name == ""
        assert result.args == ""
        assert result.raw == "hello world"

    def test_empty_string(self):
        result = parse_input("")
        assert result.kind == "message"
        assert result.name == ""
        assert result.args == ""
        assert result.raw == ""

    def test_slash_alone(self):
        result = parse_input("/")
        assert result.kind == "command"
        assert result.name == ""
        assert result.args == ""

    def test_slash_with_space(self):
        result = parse_input("/ help")
        assert result.kind == "command"
        assert result.name == ""
        assert result.args == "help"


class TestFormatHelp:
    def test_contains_all_command_names(self):
        result = format_help()
        assert "help" in result
        assert "status" in result
        assert "abort" in result
        assert "newsession" in result
        assert "back" in result
        assert "history" in result
        assert "clear" in result


class TestFormatCommandHint:
    def test_returns_none_for_non_command(self):
        assert format_command_hint("hello") is None

    def test_returns_usage_for_known_command(self):
        hint = format_command_hint("/history 20")
        assert hint == "Usage: /history [n]"

    def test_returns_match_preview_for_partial_command(self):
        hint = format_command_hint("/mo")
        assert hint is not None
        assert "/model" in hint
        assert "/models" in hint
