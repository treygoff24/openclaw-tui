from __future__ import annotations

import pytest

from openclaw_tui.models import ChatMessage


class TestChatMessageCreation:
    def test_create_chat_message_with_all_fields(self):
        """Can create ChatMessage with role, content, timestamp, tool_name"""
        msg = ChatMessage(
            role="user",
            content="Hello",
            timestamp="10:30",
            tool_name="web_search"
        )
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.timestamp == "10:30"
        assert msg.tool_name == "web_search"

    def test_chat_message_defaults_tool_name_to_none(self):
        """tool_name defaults to None when not provided"""
        msg = ChatMessage(role="user", content="Hello", timestamp="10:30")
        assert msg.tool_name is None

    def test_chat_message_with_tool_role_and_tool_name(self):
        """ChatMessage with tool role should accept tool_name"""
        msg = ChatMessage(
            role="tool",
            content="Search results...",
            timestamp="10:32",
            tool_name="web_search"
        )
        assert msg.role == "tool"
        assert msg.tool_name == "web_search"

    def test_chat_message_accepts_assistant_role(self):
        """ChatMessage accepts 'assistant' role"""
        msg = ChatMessage(role="assistant", content="Response", timestamp="10:35")
        assert msg.role == "assistant"

    def test_chat_message_accepts_system_role(self):
        """ChatMessage accepts 'system' role"""
        msg = ChatMessage(role="system", content="System prompt", timestamp="10:00")
        assert msg.role == "system"