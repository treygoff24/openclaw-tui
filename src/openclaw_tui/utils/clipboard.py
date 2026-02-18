import subprocess
import sys


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard using platform-specific command fallbacks."""
    for command in _copy_commands_for_platform():
        if _copy_via_subprocess(command, text):
            return True
    return False


def read_from_clipboard() -> str | None:
    """Read text from clipboard using platform-specific command fallbacks."""
    for command in _read_commands_for_platform():
        output = _read_via_subprocess(command)
        if output is not None:
            return output
    return None


def _copy_commands_for_platform() -> list[list[str]]:
    if sys.platform == "darwin":
        return [["pbcopy"]]
    if sys.platform.startswith(("win32", "cygwin", "msys")):
        return [
            ["clip"],
            ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
        ]
    if sys.platform.startswith("linux"):
        return [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "-i"],
            ["clip.exe"],
        ]
    return []


def _read_commands_for_platform() -> list[list[str]]:
    if sys.platform == "darwin":
        return [["pbpaste"]]
    if sys.platform.startswith(("win32", "cygwin", "msys")):
        return [
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
        ]
    if sys.platform.startswith("linux"):
        return [
            ["wl-paste", "--no-newline"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["xsel", "--clipboard", "-o"],
            ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        ]
    return []


def _copy_via_subprocess(cmd: list[str], text: str) -> bool:
    """Run subprocess with input text. Returns False on failure."""
    try:
        result = subprocess.run(
            cmd,
            input=text,
            text=True,
            check=True,
            capture_output=True,
        )
        return result.returncode == 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _read_via_subprocess(cmd: list[str]) -> str | None:
    """Run subprocess and return clipboard text or None on failure."""
    try:
        result = subprocess.run(
            cmd,
            text=True,
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout
