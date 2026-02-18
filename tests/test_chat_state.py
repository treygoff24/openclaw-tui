from unittest.mock import MagicMock
from openclaw_tui.chat.state import ChatState
from openclaw_tui.models import SessionInfo


def make_session_info(key: str = "agent:main:main:abc123") -> SessionInfo:
    """Helper to create a SessionInfo for testing."""
    return SessionInfo(
        key=key,
        kind="chat",
        channel="test",
        display_name="Test Session",
        label="test-label",
        updated_at=1_700_000_000_000,
        session_id="sess-123",
        model="claude-sonnet-4-20250501",
        context_tokens=1000,
        total_tokens=2000,
        aborted_last_run=False,
    )


class TestChatStateCreation:
    """Test ChatState creation with required fields."""

    def test_create_with_required_fields(self):
        """Test ChatState can be created with session_key, agent_id, session_info."""
        session_info = make_session_info()
        state = ChatState(
            session_key="agent:main:main:abc123",
            agent_id="main",
            session_info=session_info,
        )
        assert state.session_key == "agent:main:main:abc123"
        assert state.agent_id == "main"
        assert state.session_info == session_info


class TestChatStateDefaults:
    """Test ChatState default values."""

    def test_messages_defaults_to_empty_list(self):
        """Test messages defaults to empty list."""
        session_info = make_session_info()
        state = ChatState(
            session_key="agent:main:main:abc123",
            agent_id="main",
            session_info=session_info,
        )
        assert state.messages == []
        assert isinstance(state.messages, list)

    def test_is_busy_defaults_to_false(self):
        """Test is_busy defaults to False."""
        session_info = make_session_info()
        state = ChatState(
            session_key="agent:main:main:abc123",
            agent_id="main",
            session_info=session_info,
        )
        assert state.is_busy is False

    def test_last_message_count_defaults_to_zero(self):
        """Test last_message_count defaults to 0."""
        session_info = make_session_info()
        state = ChatState(
            session_key="agent:main:main:abc123",
            agent_id="main",
            session_info=session_info,
        )
        assert state.last_message_count == 0

    def test_error_defaults_to_none(self):
        """Test error defaults to None."""
        session_info = make_session_info()
        state = ChatState(
            session_key="agent:main:main:abc123",
            agent_id="main",
            session_info=session_info,
        )
        assert state.error is None


class TestChatStateTransitions:
    """Test ChatState state transitions."""

    def test_idle_to_busy(self):
        """Test transition from idle to busy."""
        session_info = make_session_info()
        state = ChatState(
            session_key="agent:main:main:abc123",
            agent_id="main",
            session_info=session_info,
        )
        # Initially idle
        assert state.is_busy is False

        # Transition to busy
        state.is_busy = True
        assert state.is_busy is True

    def test_busy_to_idle(self):
        """Test transition from busy to idle with message count increment."""
        session_info = make_session_info()
        state = ChatState(
            session_key="agent:main:main:abc123",
            agent_id="main",
            session_info=session_info,
            messages=[],
            is_busy=True,
            last_message_count=0,
        )
        # Busy state
        assert state.is_busy is True

        # Transition to idle
        state.is_busy = False
        state.last_message_count = len(state.messages)
        assert state.is_busy is False
        assert state.last_message_count == 0  # No messages yet

    def test_busy_to_error(self):
        """Test transition from busy to error state."""
        session_info = make_session_info()
        state = ChatState(
            session_key="agent:main:main:abc123",
            agent_id="main",
            session_info=session_info,
            is_busy=True,
        )
        # Busy state
        assert state.is_busy is True
        assert state.error is None

        # Transition to error
        state.is_busy = False
        state.error = "some error"
        assert state.is_busy is False
        assert state.error == "some error"


class TestChatStateListIndependence:
    """Test that ChatState instances don't share mutable state."""

    def test_messages_list_independence(self):
        """Test two ChatState instances don't share the messages list."""
        session_info1 = make_session_info(key="agent:main:main:abc123")
        session_info2 = make_session_info(key="agent:main:main:def456")

        state1 = ChatState(
            session_key="agent:main:main:abc123",
            agent_id="main",
            session_info=session_info1,
        )
        state2 = ChatState(
            session_key="agent:main:main:def456",
            agent_id="main",
            session_info=session_info2,
        )

        # Modify one instance's messages
        state1.messages.append("test message")

        # Verify the other instance is not affected
        assert state2.messages == []
        assert state1.messages != state2.messages