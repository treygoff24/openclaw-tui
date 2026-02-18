import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


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


def read_image_to_temp_file_from_clipboard() -> Path | None:
    """Read image bytes from clipboard, persist to cache, and return file path."""
    for command in _read_image_commands_for_platform():
        data = _read_bytes_via_subprocess(command)
        if not data:
            continue
        extension = _detect_image_extension(data)
        if extension is None:
            continue
        return _write_clipboard_image(data, extension)
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


def _read_image_commands_for_platform() -> list[list[str]]:
    if sys.platform == "darwin":
        return [["pngpaste", "-"]]
    if sys.platform.startswith("linux"):
        return [
            ["wl-paste", "--no-newline", "--type", "image/png"],
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            ["xsel", "--clipboard", "--output", "--mime-type", "image/png"],
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


def _read_bytes_via_subprocess(cmd: list[str]) -> bytes | None:
    """Run subprocess and return stdout bytes or None on failure."""
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout


def _detect_image_extension(data: bytes) -> str | None:
    """Best-effort image extension detection via file signatures."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"BM"):
        return "bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    return None


def _write_clipboard_image(data: bytes, extension: str) -> Path:
    """Persist clipboard image bytes and opportunistically prune stale files."""
    cache_dir = Path.home() / ".cache" / "openclaw_tui" / "clipboard"
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_old_clipboard_images(cache_dir)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_path = cache_dir / f"paste-{timestamp}-{uuid4().hex[:8]}.{extension}"
    output_path.write_bytes(data)
    return output_path


def _cleanup_old_clipboard_images(cache_dir: Path) -> None:
    """Keep cache bounded; remove files older than 7 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    for file_path in cache_dir.glob("paste-*.*"):
        try:
            modified = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
            if modified < cutoff:
                file_path.unlink()
        except OSError:
            continue
