"""Entry point: python -m openclaw_tui"""
from __future__ import annotations

from .app import AgentDashboard


def main() -> None:
    """Launch the OpenClaw TUI dashboard."""
    app = AgentDashboard()
    app.run()


if __name__ == "__main__":
    main()
