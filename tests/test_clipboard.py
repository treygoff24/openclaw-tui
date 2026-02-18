from __future__ import annotations

from unittest.mock import patch, MagicMock
import subprocess

import pytest

from openclaw_tui.utils.clipboard import copy_to_clipboard


class TestCopyToClipboard:
    """Tests for cross-platform clipboard copy functionality."""

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_macos_uses_pbcopy(self, mock_run, mock_sys):
        """On macOS, should use pbcopy with stdin."""
        mock_sys.platform = "darwin"
        mock_run.return_value = MagicMock(returncode=0)
        result = copy_to_clipboard("test text")
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["pbcopy"]
        assert call_args[1]["input"] == "test text"
        assert call_args[1]["check"] is True
        assert result is True

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_linux_uses_xclip_when_available(self, mock_run, mock_sys):
        """On Linux, should try xclip first."""
        mock_sys.platform = "linux"
        mock_run.return_value = MagicMock(returncode=0)
        result = copy_to_clipboard("test text")
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["xclip", "-selection", "clipboard"]
        assert call_args[1]["input"] == "test text"
        assert call_args[1]["check"] is True
        assert result is True

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_linux_falls_back_to_xsel_when_xclip_fails(self, mock_run, mock_sys):
        """On Linux, should fall back to xsel if xclip fails."""
        mock_sys.platform = "linux"
        # First call (xclip) fails, second call (xsel) succeeds
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, ["xclip"]),
            MagicMock(returncode=0),
        ]
        result = copy_to_clipboard("test text")
        assert mock_run.call_count == 2
        # First call should be xclip
        assert mock_run.call_args_list[0][0][0] == ["xclip", "-selection", "clipboard"]
        # Second call should be xsel
        assert mock_run.call_args_list[1][0][0] == ["xsel", "--clipboard", "-i"]
        assert result is True

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_returns_false_when_no_clipboard_tool_available(self, mock_run, mock_sys):
        """When no clipboard tool available, should return False without raising."""
        mock_sys.platform = "linux"
        # Both xclip and xsel fail
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, ["xclip"]),
            subprocess.CalledProcessError(1, ["xsel"]),
        ]
        result = copy_to_clipboard("test text")
        assert mock_run.call_count == 2
        assert result is False

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_returns_false_on_failure(self, mock_run, mock_sys):
        """Should return False when subprocess fails."""
        mock_sys.platform = "darwin"
        mock_run.side_effect = subprocess.CalledProcessError(1, ["pbcopy"])
        result = copy_to_clipboard("test text")
        assert result is False