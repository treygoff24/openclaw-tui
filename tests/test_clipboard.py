from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch
from pathlib import Path

from openclaw_tui.utils.clipboard import (
    copy_to_clipboard,
    read_from_clipboard,
    read_image_to_temp_file_from_clipboard,
)


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
        assert call_args[1]["text"] is True
        assert call_args[1]["check"] is True
        assert result is True

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_linux_wayland_prefers_wl_copy(self, mock_run, mock_sys):
        """On Linux, should try wl-copy before legacy X11 tools."""
        mock_sys.platform = "linux"
        mock_run.return_value = MagicMock(returncode=0)
        result = copy_to_clipboard("test text")
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["wl-copy"]
        assert call_args[1]["input"] == "test text"
        assert call_args[1]["text"] is True
        assert call_args[1]["check"] is True
        assert result is True

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_linux_falls_back_to_xclip_when_wl_copy_fails(self, mock_run, mock_sys):
        """On Linux, wl-copy failure should fall back to xclip."""
        mock_sys.platform = "linux"
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, ["wl-copy"]),
            MagicMock(returncode=0),
        ]
        result = copy_to_clipboard("test text")
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[0][0][0] == ["wl-copy"]
        assert mock_run.call_args_list[1][0][0] == ["xclip", "-selection", "clipboard"]
        assert result is True

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_linux_returns_false_when_all_copy_tools_fail(self, mock_run, mock_sys):
        """When no clipboard tool available, should return False without raising."""
        mock_sys.platform = "linux"
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, ["wl-copy"]),
            subprocess.CalledProcessError(1, ["xclip"]),
            subprocess.CalledProcessError(1, ["xsel"]),
            subprocess.CalledProcessError(1, ["clip.exe"]),
        ]
        result = copy_to_clipboard("test text")
        assert mock_run.call_count == 4
        assert result is False

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_windows_uses_clip_command(self, mock_run, mock_sys):
        """On Windows, should use clip command."""
        mock_sys.platform = "win32"
        mock_run.return_value = MagicMock(returncode=0)
        result = copy_to_clipboard("test text")
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["clip"]
        assert result is True


class TestReadFromClipboard:
    """Tests for cross-platform clipboard read functionality."""

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_macos_uses_pbpaste(self, mock_run, mock_sys):
        mock_sys.platform = "darwin"
        mock_run.return_value = MagicMock(returncode=0, stdout="hello")
        result = read_from_clipboard()
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["pbpaste"]
        assert result == "hello"

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_linux_falls_back_to_xclip_for_read(self, mock_run, mock_sys):
        mock_sys.platform = "linux"
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, ["wl-paste"]),
            MagicMock(returncode=0, stdout="from-xclip"),
        ]
        result = read_from_clipboard()
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[0][0][0] == ["wl-paste", "--no-newline"]
        assert mock_run.call_args_list[1][0][0] == ["xclip", "-selection", "clipboard", "-o"]
        assert result == "from-xclip"

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_windows_uses_powershell_get_clipboard(self, mock_run, mock_sys):
        mock_sys.platform = "win32"
        mock_run.return_value = MagicMock(returncode=0, stdout="clip-text")
        result = read_from_clipboard()
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-Clipboard -Raw",
        ]
        assert result == "clip-text"

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_read_returns_none_when_all_commands_fail(self, mock_run, mock_sys):
        mock_sys.platform = "linux"
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, ["wl-paste"]),
            subprocess.CalledProcessError(1, ["xclip"]),
            subprocess.CalledProcessError(1, ["xsel"]),
            subprocess.CalledProcessError(1, ["powershell.exe"]),
        ]
        result = read_from_clipboard()
        assert result is None


class TestReadImageFromClipboard:
    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard._write_clipboard_image")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_macos_pngpaste_is_used_for_image_clipboard(self, mock_run, mock_write, mock_sys):
        mock_sys.platform = "darwin"
        png_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        mock_run.return_value = MagicMock(returncode=0, stdout=png_data)
        expected_path = Path("/tmp/paste-123.png")
        mock_write.return_value = expected_path

        result = read_image_to_temp_file_from_clipboard()

        assert result == expected_path
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["pngpaste", "-"]
        mock_write.assert_called_once()

    @patch("openclaw_tui.utils.clipboard.sys")
    @patch("openclaw_tui.utils.clipboard.subprocess.run")
    def test_image_read_returns_none_when_no_commands_succeed(self, mock_run, mock_sys):
        mock_sys.platform = "linux"
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, ["wl-paste"]),
            subprocess.CalledProcessError(1, ["xclip"]),
            subprocess.CalledProcessError(1, ["xsel"]),
        ]

        result = read_image_to_temp_file_from_clipboard()

        assert result is None
