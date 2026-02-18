import subprocess
import sys


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard. macOS: pbcopy. Linux: xclip then xsel. Returns True on success."""
    if sys.platform == "darwin":
        return _copy_via_subprocess(["pbcopy"], text)
    elif sys.platform == "linux":
        # Try xclip first, fall back to xsel
        if _copy_via_subprocess(["xclip", "-selection", "clipboard"], text):
            return True
        # xclip failed, try xsel
        return _copy_via_subprocess(["xsel", "--clipboard", "-i"], text)
    else:
        # Unsupported platform
        return False


def _copy_via_subprocess(cmd: list[str], text: str) -> bool:
    """Run subprocess with input text. Returns False on failure."""
    try:
        result = subprocess.run(cmd, input=text, check=True, capture_output=True)
        return result.returncode == 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False