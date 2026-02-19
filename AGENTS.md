# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `src/openclaw_tui/`. Entry points are `__main__.py` and `app.py`, with feature modules split by concern (for example `chat.py`, `gateway.py`, `sessions.py`, `tree.py`, `transcript.py`, and `widgets/` for UI components). Tests live in `tests/`. Project metadata and dependencies are managed in `pyproject.toml`, and `uv.lock` pins resolved versions.

## Build, Test, and Development Commands
Use `uv` for local setup and execution.

- `uv venv .venv` creates the virtual environment.
- `uv pip install -e .[dev]` installs the package in editable mode plus dev tools.
- `uv run python -m openclaw_tui` runs the TUI app module directly.
- `uv run openclaw-tui` runs the console script defined in `pyproject.toml`.
- `uv run pytest` runs the full test suite.
- `uv run pytest tests/test_file.py -k "case_name"` runs targeted tests during iteration.

## Coding Style & Naming Conventions
This is a Python project (`>=3.12`). Follow PEP 8 defaults: 4-space indentation, clear type hints where useful, and small focused modules. Use `snake_case` for files/functions/variables, `PascalCase` for classes, and keep UI/widget names descriptive (for example `session_list.py`, `chat_view.py`). Prefer explicit imports and avoid cross-module circular dependencies.

## Testing Guidelines
Tests use `pytest` with `pytest-asyncio` available for async flows. Place tests under `tests/` and name files `test_*.py`. Mirror source module names where practical (for example `src/openclaw_tui/chat.py` -> `tests/test_chat.py`). Add regression tests for bug fixes and cover success + failure paths for gateway/session/chat behaviors.

## Commit & Pull Request Guidelines
Recent history shows concise, imperative commit subjects, with optional conventional prefixes when helpful:

- `feat(tui): add new-session model picker flow`
- `fix: merge partial sessions_tree with full session list in left panel`
- `Render assistant/user chat bodies as Markdown`

Keep commits scoped to one logical change. PRs should include a short summary, test evidence (`uv run pytest` output), related issue/context, and screenshots or terminal captures for visible TUI behavior changes.
