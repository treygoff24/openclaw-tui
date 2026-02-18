"""Slash command parser and registry for OpenClaw TUI."""
from dataclasses import dataclass


@dataclass
class ParsedInput:
    kind: str  # "command", "bang", "message"
    name: str  # command name (lowercase) or bang command text or empty
    args: str  # remaining args after command name
    raw: str   # original input


COMMANDS = {
    "help": "Show available commands",
    "commands": "List slash commands",
    "status": "Show gateway status",
    "agent": "Switch agent (or list when omitted)",
    "agents": "List agents",
    "session": "Switch session (or list when omitted)",
    "sessions": "List sessions",
    "model": "Set model (or list when omitted)",
    "models": "List models",
    "think": "Set thinking level",
    "verbose": "Set verbose on/off",
    "reasoning": "Set reasoning on/off",
    "usage": "Set usage footer mode",
    "elevated": "Set elevated mode",
    "elev": "Alias for /elevated",
    "activation": "Set activation mode",
    "newsession": "Create fresh main session (picker or direct)",
    "ns": "Alias for /newsession",
    "new": "Reset current session",
    "reset": "Reset current session",
    "settings": "Open settings",
    "abort": "Abort active run",
    "back": "Return to transcript mode",
    "history": "Reload message history [n]",
    "clear": "Clear chat display",
    "exit": "Exit the app",
    "quit": "Exit the app",
}

ALIASES = {
    "ns": "newsession",
}


def parse_input(raw: str) -> ParsedInput:
    """Parse raw input into a structured ParsedInput.
    
    Args:
        raw: The raw user input string.
        
    Returns:
        ParsedInput with kind, name, args, and raw fields.
    """
    if not raw:
        return ParsedInput(kind="message", name="", args="", raw=raw)
    
    if raw.startswith("/"):
        # Strip the leading slash
        content = raw[1:]
        
        # If content starts with whitespace, command name is empty and 
        # the rest is args
        if content and content[0].isspace():
            return ParsedInput(kind="command", name="", args=content.lstrip(), raw=raw)
        
        # Split on whitespace - first token is command name, rest is args
        parts = content.split(None, 1)
        
        # First token is command name (lowercased), rest is args
        name = parts[0].lower() if parts else ""
        name = ALIASES.get(name, name)
        args = parts[1] if len(parts) > 1 else ""
        
        return ParsedInput(kind="command", name=name, args=args, raw=raw)
    
    if raw.startswith("!"):
        # Bang command - everything after ! is the shell command
        return ParsedInput(kind="bang", name=raw[1:], args="", raw=raw)
    
    # Regular message
    return ParsedInput(kind="message", name="", args="", raw=raw)


def format_help() -> str:
    """Return a polished, grouped help panel with aligned commands."""
    width = max(len(name) for name in COMMANDS)

    def row(name: str, desc: str) -> str:
        return f"  [bold #F5A623]/{name:<{width}}[/]  [#A8B5A2]{desc}[/]"

    lines = [
        "[bold #F5A623]Slash Commands[/]",
        "[dim #7B7F87]────────────────────────────────[/]",
    ]
    for name, description in COMMANDS.items():
        lines.append(row(name, description))
    lines.extend(
        [
            "",
            "[bold #F5A623]Shell[/]",
            "[dim #7B7F87]────────────────────────────────[/]",
            "  [bold #C67B5C]!<command>[/]  [#A8B5A2]Run a local shell command[/]",
        ]
    )
    return "\n".join(lines)
