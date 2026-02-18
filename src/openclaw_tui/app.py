"""AgentDashboard — main Textual TUI application with live polling."""
from __future__ import annotations

import asyncio
from datetime import datetime
from functools import partial
import inspect
import logging
import subprocess
import time

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.theme import Theme
from textual.widgets import Footer, Header, Tree

from .chat import ChatState
from .chat.commands import ParsedInput, format_help, parse_input
from .client import GatewayClient, GatewayError
from .config import load_config
from .models import ChatMessage, SessionInfo
from .tree import build_tree
from .transcript import read_transcript
from .utils.clipboard import copy_to_clipboard, read_from_clipboard
from .widgets import AgentTreeWidget, ChatPanel, LogPanel, SummaryBar
from . import transcript

logger = logging.getLogger(__name__)


class AgentDashboard(App[None]):
    """Main TUI application with live-updating agent tree.

    Polls the OpenClaw gateway every 2 seconds, groups sessions into an
    agent tree, and displays them with a live summary footer.
    """

    TITLE = "🌘 OpenClaw"
    CTRL_C_QUIT_CONFIRM_TIMEOUT_SECONDS = 2.0
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("meta+c", "copy_info", "Copy Info"),
        ("v", "toggle_logs", "View Logs"),
        ("e", "expand_all", "Expand All"),
    ]

    CSS = """
Screen {
    background: #1A1A2E;
    color: #FFF8E7;
}
Header {
    background: #1A1A2E;
    color: #F5A623;
    text-style: bold;
    border-bottom: solid #2A2E3D;
}
#main-content {
    height: 1fr;
    padding: 1 1 0 1;
}
#right-panel {
    width: 3fr;
    border-left: solid #2A2E3D;
    background: #16213E;
    padding: 0 0 1 1;
}
AgentTreeWidget {
    width: 2fr;
    border: round #2A2E3D;
    background: #16213E;
    padding: 0 1;
}
LogPanel {
    background: #16213E;
}
ChatPanel {
    background: #16213E;
}
SummaryBar {
    height: 3;
    background: #16213E;
    color: #FFF8E7;
    border-top: solid #2A2E3D;
    padding: 0 2;
    dock: bottom;
}
Footer {
    background: #1A1A2E;
    color: #A8B5A2;
    border-top: solid #2A2E3D;
}
"""

    def compose(self) -> ComposeResult:
        """Layout: Header → Horizontal(AgentTreeWidget + LogPanel) → SummaryBar → Footer."""
        yield Header()
        with Horizontal(id="main-content"):
            yield AgentTreeWidget("Agents")
            with Vertical(id="right-panel"):
                yield LogPanel()
                chat_panel = ChatPanel()
                chat_panel.display = False
                yield chat_panel
        yield SummaryBar("⚡ Connecting...")
        yield Footer()

    def on_mount(self) -> None:
        """Load config, create client, start 2 s polling interval."""
        logger.info("AgentDashboard mounted — starting poll loop")
        self._config = load_config()
        self._client = GatewayClient(self._config)
        self._selected_session: SessionInfo | None = None
        self._chat_mode: bool = False
        self._chat_state: ChatState | None = None
        self._last_ctrl_c_press_at: float | None = None
        self.register_theme(Theme(
            name="hearth",
            primary="#F5A623",
            background="#1A1A2E",
            surface="#16213E",
            accent="#F5A623",
            warning="#FFD93D",
            error="#C67B5C",
            success="#4ADE80",
            secondary="#4A90D9",
            foreground="#FFF8E7",
            panel="#16213E",
        ))
        self.theme = "hearth"
        self.set_interval(2.0, self._trigger_poll)
        self._trigger_poll()  # immediate first poll

    def _trigger_poll(self) -> None:
        """Trigger an exclusive worker to poll the gateway."""
        self.run_worker(self._poll_sessions, exclusive=True, group="session_poll")

    async def _poll_sessions(self) -> None:
        """Worker coroutine: fetch sessions, build tree, update widgets.

        Runs ``fetch_sessions`` (sync httpx call) in a thread via
        ``asyncio.to_thread`` so the TUI event loop stays responsive.
        On any error, updates the SummaryBar with an error message instead
        of crashing.
        """
        now_ms = int(time.time() * 1000)
        try:
            sessions = await asyncio.to_thread(self._client.fetch_sessions)
            nodes = build_tree(sessions)
            tree = self.query_one(AgentTreeWidget)
            bar = self.query_one(SummaryBar)
            tree.update_tree(nodes, now_ms)
            try:
                tree_nodes = await asyncio.to_thread(self._client.fetch_tree)
                if tree_nodes:
                    active = 0
                    completed = 0
                    total = 0
                    stack = list(tree_nodes)
                    while stack:
                        tree_node = stack.pop()
                        total += 1
                        if tree_node.status == "active":
                            active += 1
                        elif tree_node.status == "completed":
                            completed += 1
                        stack.extend(tree_node.children)
                    bar.update_with_tree_stats(active=active, completed=completed, total=total)
                else:
                    bar.update_summary(nodes, now_ms)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Tree stats update skipped: %s", exc)
                bar.update_summary(nodes, now_ms)
            logger.info("Poll OK — %d sessions across %d agents", len(sessions), len(nodes))
        except (GatewayError, ConnectionError) as exc:
            logger.warning("Gateway poll failed: %s", exc)
            self._show_poll_error(str(exc) or "Gateway unreachable")
        except Exception as exc:  # noqa: BLE001 — never crash the TUI
            logger.warning("Unexpected poll error: %s", exc)
            self._show_poll_error(str(exc) or "Unknown error")

    def _show_poll_error(self, message: str) -> None:
        """Update SummaryBar with error message (safe — never raises)."""
        try:
            bar = self.query_one(SummaryBar)
            bar.set_error(message)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not update SummaryBar: %s", exc)

    def _show_transcript_for_session(self, session: SessionInfo) -> None:
        """Load and display transcript for a session in LogPanel."""
        log_panel = self.query_one(LogPanel)
        try:
            transcript_path = getattr(session, "transcript_path", None)
            messages = []
            if transcript_path:
                read_from_path = getattr(transcript, "read_transcript_from_path", None)
                if callable(read_from_path):
                    try:
                        messages = read_from_path(transcript_path=transcript_path)
                    except TypeError:
                        messages = read_from_path(transcript_path)
                else:
                    kwargs = {
                        "session_id": session.session_id,
                        "agent_id": session.agent_id,
                    }
                    if "transcript_path" in inspect.signature(read_transcript).parameters:
                        kwargs["transcript_path"] = transcript_path
                    messages = read_transcript(**kwargs)
            else:
                messages = read_transcript(
                    session_id=session.session_id,
                    agent_id=session.agent_id,
                )
            log_panel.show_transcript(messages, session_info=session)
        except Exception as exc:  # noqa: BLE001 — never crash the TUI
            logger.warning(
                "Failed to load transcript for %s: %s",
                getattr(session, "session_id", "unknown"),
                exc,
            )
            log_panel.show_error(str(exc) or "Failed to load transcript")

    def _enter_chat_mode_for_session(self, session: SessionInfo, history_limit: int = 30) -> None:
        """Enter chat mode and load session history into ChatPanel."""
        self._selected_session = session
        self._chat_mode = True
        self._chat_state = ChatState(
            session_key=session.key,
            agent_id=session.agent_id,
            session_info=session,
        )
        self.workers.cancel_group(self, "chat_poll")
        self.query_one(LogPanel).display = False

        chat_panel = self.query_one(ChatPanel)
        chat_panel.display = True
        chat_panel.set_header(
            f"{session.label or session.display_name} · {session.agent_id} · {session.short_model}"
        )
        chat_panel.set_status("● loading history...")
        chat_panel.show_placeholder("Loading chat history...")
        chat_panel.query_one("#chat-input").focus()

        self.run_worker(
            partial(self._load_chat_history, session.key, history_limit),
            exclusive=True,
            group="chat_history",
        )

    def _exit_chat_mode(self) -> None:
        """Exit chat mode and return to transcript view."""
        self.workers.cancel_group(self, "chat_poll")
        self.workers.cancel_group(self, "chat_history")

        chat_panel = self.query_one(ChatPanel)
        chat_panel.display = False
        chat_panel.set_header("Select a session")
        chat_panel.set_status("● idle")
        chat_panel.clear_log()

        log_panel = self.query_one(LogPanel)
        log_panel.display = True

        self._chat_mode = False
        self._chat_state = None
        if self._selected_session is not None:
            self._show_transcript_for_session(self._selected_session)
        else:
            log_panel.show_placeholder()

    @staticmethod
    def _now_hhmm() -> str:
        return datetime.now().strftime("%H:%M")

    @staticmethod
    def _format_error_status(detail: str | None) -> str:
        """Format a compact user-facing error status string."""
        clean = " ".join((detail or "").split())
        if not clean:
            return "● error"
        if len(clean) > 90:
            clean = f"{clean[:87].rstrip()}..."
        return f"● error: {clean}"

    @staticmethod
    def _coerce_chat_content(content: object) -> str:
        """Convert gateway content payloads into plain text."""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            if isinstance(content.get("text"), str):
                return content["text"]
            return str(content)
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, str):
                    chunks.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                if isinstance(item.get("text"), str):
                    chunks.append(item["text"])
                    continue
                nested_content = item.get("content")
                if isinstance(nested_content, str):
                    chunks.append(nested_content)
            if chunks:
                return "\n".join(chunks)
        return str(content)

    @classmethod
    def _to_chat_message(cls, raw: object) -> ChatMessage:
        """Map gateway history record to ChatMessage."""
        if not isinstance(raw, dict):
            return ChatMessage(
                role="system",
                content=cls._coerce_chat_content(raw),
                timestamp="??:??",
            )

        role_raw = str(raw.get("role", "system"))
        role = "tool" if role_raw == "toolResult" else role_raw
        if role not in {"user", "assistant", "system", "tool"}:
            role = "system"

        timestamp_raw = raw.get("timestamp")
        timestamp = "??:??"
        try:
            if isinstance(timestamp_raw, (int, float)):
                epoch = float(timestamp_raw)
                if epoch > 1_000_000_000_000:
                    epoch /= 1000.0
                timestamp = datetime.fromtimestamp(epoch).strftime("%H:%M")
            elif isinstance(timestamp_raw, str):
                if "T" in timestamp_raw:
                    timestamp = timestamp_raw.split("T", 1)[1][:5]
                elif " " in timestamp_raw:
                    timestamp = timestamp_raw.split(" ", 1)[1][:5]
                else:
                    timestamp = timestamp_raw[:5]
        except Exception:  # noqa: BLE001
            timestamp = "??:??"

        tool_name = raw.get("tool_name") or raw.get("toolName") or raw.get("name")
        raw_content = raw.get("content")
        return ChatMessage(
            role=role,
            content=cls._coerce_chat_content(raw_content) if raw_content is not None else "",
            timestamp=timestamp,
            tool_name=tool_name if isinstance(tool_name, str) else None,
        )

    def _append_system_message(self, content: str) -> None:
        """Append a local system message to the current chat log/state."""
        if not self._chat_mode or self._chat_state is None:
            return
        message = ChatMessage(role="system", content=content, timestamp=self._now_hhmm())
        self.query_one(ChatPanel).append_message(message)
        self._chat_state.messages.append(message)
        self._chat_state.last_message_count = len(self._chat_state.messages)

    async def _load_chat_history(self, session_key: str, limit: int = 30) -> None:
        """Fetch history for a chat session and render it."""
        state = self._chat_state
        if state is None:
            return

        chat_panel = self.query_one(ChatPanel)
        chat_panel.set_status("● loading history...")

        try:
            raw_messages = await asyncio.to_thread(self._client.fetch_history, session_key, limit)
        except ConnectionError as exc:
            if self._chat_state is None or self._chat_state.session_key != session_key:
                return
            detail = str(exc) or "Connection lost while loading history"
            self._chat_state.error = detail
            self._chat_state.is_busy = False
            chat_panel.show_placeholder(f"Failed to load history: {detail}")
            chat_panel.set_status(self._format_error_status(detail))
            return
        except Exception as exc:  # noqa: BLE001
            if self._chat_state is None or self._chat_state.session_key != session_key:
                return
            detail = str(exc) or "Unknown error while loading history"
            self._chat_state.error = detail
            self._chat_state.is_busy = False
            chat_panel.show_placeholder(f"Failed to load history: {detail}")
            chat_panel.set_status(self._format_error_status(detail))
            return

        if self._chat_state is None or self._chat_state.session_key != session_key:
            return

        history_error = getattr(self._client, "last_history_error", None)
        if isinstance(history_error, str) and history_error.strip():
            detail = history_error.strip()
            self._chat_state.error = detail
            self._chat_state.is_busy = False
            chat_panel.show_placeholder(f"Failed to load history: {detail}")
            chat_panel.set_status(self._format_error_status(detail))
            return

        messages = [self._to_chat_message(msg) for msg in raw_messages]
        self._chat_state.messages = messages
        self._chat_state.last_message_count = len(messages)
        self._chat_state.is_busy = False
        self._chat_state.error = None

        if messages:
            chat_panel.show_messages(messages)
        else:
            # Empty history placeholder
            chat_panel.show_placeholder("No messages yet. Start typing!")
        chat_panel.set_status("● idle")

    def _start_chat_poll_worker(self) -> None:
        """Start polling for new chat messages."""
        self.workers.cancel_group(self, "chat_poll")
        self.run_worker(self._poll_chat_updates, exclusive=True, group="chat_poll")

    async def _poll_chat_updates(self) -> None:
        """Poll history and append new messages until response arrives or timeout."""
        if self._chat_state is None:
            return

        session_key = self._chat_state.session_key
        start_time = time.monotonic()
        chat_panel = self.query_one(ChatPanel)

        while (time.monotonic() - start_time) < 180:
            await asyncio.sleep(0.75)
            if self._chat_state is None or self._chat_state.session_key != session_key:
                return

            try:
                limit = max(self._chat_state.last_message_count + 20, 50)
                raw_messages = await asyncio.to_thread(self._client.fetch_history, session_key, limit)
            except ConnectionError as exc:
                logger.warning("Chat poll connection lost for %s: %s", session_key, exc)
                if self._chat_state is not None and self._chat_state.session_key == session_key:
                    self._chat_state.error = "Connection lost"
                    self._chat_state.is_busy = False
                    chat_panel.set_status("● Connection lost")
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("Chat poll failed for %s: %s", session_key, exc)
                if self._chat_state is not None and self._chat_state.session_key == session_key:
                    self._chat_state.error = str(exc)
                    self._chat_state.is_busy = False
                    chat_panel.set_status(self._format_error_status(str(exc)))
                return

            if self._chat_state is None or self._chat_state.session_key != session_key:
                return

            history_error = getattr(self._client, "last_history_error", None)
            if isinstance(history_error, str) and history_error.strip():
                detail = history_error.strip()
                self._chat_state.error = detail
                self._chat_state.is_busy = False
                chat_panel.set_status(self._format_error_status(detail))
                return

            messages = [self._to_chat_message(msg) for msg in raw_messages]
            if len(messages) <= self._chat_state.last_message_count:
                continue

            previous_count = self._chat_state.last_message_count
            new_messages = messages[previous_count:]
            for message in new_messages:
                chat_panel.append_message(message)

            self._chat_state.messages = messages
            self._chat_state.last_message_count = len(messages)

            if any(message.role != "user" for message in new_messages):
                self._chat_state.is_busy = False
                chat_panel.set_status("● idle")
                return

        if self._chat_state is not None and self._chat_state.session_key == session_key:
            self._chat_state.is_busy = False
            chat_panel.set_status("● timeout")
            self._append_system_message("Timed out waiting for response.")

    def _run_chat_command(self, parsed: ParsedInput) -> None:
        """Handle slash commands in chat mode."""
        if self._chat_state is None:
            return

        if parsed.name == "help":
            self._append_system_message(format_help())
            return

        if parsed.name == "status":
            session = self._chat_state.session_info
            status_text = (
                f"Agent: {session.agent_id}\n"
                f"Session: {session.key}\n"
                f"Name: {session.label or session.display_name}\n"
                f"Model: {session.model}\n"
                f"Tokens: {session.total_tokens}"
            )
            self._append_system_message(status_text)
            return

        if parsed.name == "abort":
            self.workers.cancel_group(self, "chat_poll")
            if self._chat_state is not None:
                self._chat_state.is_busy = False
            self.query_one(ChatPanel).set_status("● aborting...")
            self._append_system_message("Aborted")
            self.run_worker(
                partial(self._abort_chat_session, self._chat_state.session_key),
                exclusive=True,
                group="chat_abort",
            )
            return

        if parsed.name == "back":
            self._exit_chat_mode()
            return

        if parsed.name == "history":
            limit = 30
            if parsed.args:
                try:
                    limit = max(1, int(parsed.args.strip()))
                except ValueError:
                    self._append_system_message("Usage: /history [n]")
                    return
            self.run_worker(
                partial(self._load_chat_history, self._chat_state.session_key, limit),
                exclusive=True,
                group="chat_history",
            )
            return

        if parsed.name == "clear":
            chat_panel = self.query_one(ChatPanel)
            chat_panel.clear_log()
            self._chat_state.messages = []
            self._chat_state.last_message_count = 0
            chat_panel.set_status("● idle")
            return

        unknown = parsed.name or "(empty)"
        self._append_system_message(f"Unknown command: /{unknown}\nTry /help")

    def _run_bang_command(self, command_text: str) -> None:
        """Execute a shell command and post output as a system message."""
        command = command_text.strip()
        if not command:
            self._append_system_message("Usage: !<shell command>")
            return

        self.query_one(ChatPanel).set_status("● running shell command...")
        self.run_worker(
            partial(self._run_shell_command_worker, command),
            exclusive=True,
            group="chat_shell",
        )

    @staticmethod
    def _run_shell_command(command: str) -> str:
        """Run a shell command and return combined stdout/stderr."""
        try:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f"$ {command}\n(command timed out after 30s)"
        except Exception as exc:  # noqa: BLE001
            return f"$ {command}\n(error: {exc})"

        output_parts = [f"$ {command}"]
        if completed.stdout:
            output_parts.append(completed.stdout.rstrip())
        if completed.stderr:
            output_parts.append(completed.stderr.rstrip())
        output_parts.append(f"(exit: {completed.returncode})")

        output = "\n".join(part for part in output_parts if part)
        return output[:4000]

    async def _run_shell_command_worker(self, command: str) -> None:
        """Worker wrapper for executing shell commands off-thread."""
        output = await asyncio.to_thread(self._run_shell_command, command)
        if not self._chat_mode or self._chat_state is None:
            return
        self._append_system_message(output)
        self.query_one(ChatPanel).set_status("● idle")

    async def _abort_chat_session(self, session_key: str) -> None:
        """Call gateway abort and report result in chat panel."""
        try:
            await asyncio.to_thread(self._client.abort_session, session_key)
        except Exception as exc:  # noqa: BLE001
            self._append_system_message(f"Abort failed: {exc}")
            self.query_one(ChatPanel).set_status(self._format_error_status(str(exc)))
            if self._chat_state is not None and self._chat_state.session_key == session_key:
                self._chat_state.error = str(exc)
            return

        if self._chat_state is not None and self._chat_state.session_key == session_key:
            self._chat_state.is_busy = False
            self._chat_state.error = None
        self._append_system_message("Abort requested.")
        self.query_one(ChatPanel).set_status("● idle")

    async def _send_chat_message(self, session_key: str, message: str) -> None:
        """Send a user message to gateway then start response polling."""
        try:
            await asyncio.to_thread(self._client.send_message, session_key, message)
        except ConnectionError as exc:
            logger.warning("send_message connection lost for %s: %s", session_key, exc)
            if self._chat_state is not None and self._chat_state.session_key == session_key:
                self._chat_state.is_busy = False
                self._chat_state.error = "Connection lost"
                self._append_system_message(f"Send failed: {exc}")
                self.query_one(ChatPanel).set_status("⚠ Connection lost")
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("send_message failed for %s: %s", session_key, exc)
            if self._chat_state is not None and self._chat_state.session_key == session_key:
                self._chat_state.is_busy = False
                self._chat_state.error = str(exc)
                self._append_system_message(f"Send failed: {exc}")
                self.query_one(ChatPanel).set_status(self._format_error_status(str(exc)))
            return

        if self._chat_state is None or self._chat_state.session_key != session_key:
            return

        self._chat_state.error = None
        self.query_one(ChatPanel).set_status("● waiting for response...")
        self._start_chat_poll_worker()

    def _send_user_chat_message(self, content: str) -> None:
        """Append local user message and dispatch send worker."""
        if self._chat_state is None:
            return

        user_message = ChatMessage(role="user", content=content, timestamp=self._now_hhmm())
        self.query_one(ChatPanel).append_message(user_message)

        self._chat_state.messages.append(user_message)
        self._chat_state.last_message_count = len(self._chat_state.messages)
        self._chat_state.is_busy = True
        self._chat_state.error = None

        self.query_one(ChatPanel).set_status("● sending...")
        self.run_worker(
            partial(self._send_chat_message, self._chat_state.session_key, content),
            exclusive=True,
            group="chat_send",
        )

    def _chat_input_widget(self):
        """Return the chat input widget if mounted, else None."""
        try:
            return self.query_one("#chat-input")
        except Exception:  # noqa: BLE001
            return None

    def _insert_text_into_chat_input(self, text: str) -> bool:
        """Insert text at chat input cursor and focus the input."""
        if not self._chat_mode or not text:
            return False
        input_widget = self._chat_input_widget()
        if input_widget is None:
            return False
        input_widget.focus()
        try:
            input_widget.insert_text_at_cursor(text)
        except Exception:  # noqa: BLE001
            current = getattr(input_widget, "value", "")
            input_widget.value = f"{current}{text}"
        return True

    def _paste_from_system_clipboard(self) -> bool:
        """Fallback paste path for terminals without bracketed paste support."""
        text = read_from_clipboard()
        if text is None:
            return False
        return self._insert_text_into_chat_input(text)

    def on_chat_panel_submit(self, event: ChatPanel.Submit) -> None:
        """Handle chat input submission (commands, shell, or regular message)."""
        if not self._chat_mode or self._chat_state is None:
            return

        text = event.text.strip()
        if not text:
            return

        parsed = parse_input(text)
        if parsed.kind == "command":
            self._run_chat_command(parsed)
            return
        if parsed.kind == "bang":
            self._run_bang_command(parsed.name)
            return

        self._send_user_chat_message(text)

    def on_paste(self, event: events.Paste) -> None:
        """Route pasted text into chat input while in chat mode."""
        if not self._chat_mode or not event.text:
            return
        if self._insert_text_into_chat_input(event.text):
            event.stop()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Enter or switch chat mode when selecting a session node."""
        node_data = event.node.data  # This is the SessionInfo object (set in AgentTreeWidget)
        if not isinstance(node_data, SessionInfo):
            return  # Agent group header, not a session

        # Session switch while busy: cancel current poll worker before loading new session
        if self._chat_mode and self._chat_state is not None:
            if self._chat_state.is_busy:
                self.workers.cancel_group(self, "chat_poll")
            if self._chat_state.session_key == node_data.key:
                return
            self._enter_chat_mode_for_session(node_data)
            return

        self._enter_chat_mode_for_session(node_data)

    def action_copy_info(self) -> None:
        """Copy chat transcript (in chat mode) or selected session info to clipboard."""
        session = getattr(self, "_selected_session", None)
        if session is None:
            self.notify("No session selected", severity="warning")
            return

        if self._chat_mode and self._chat_state is not None and self._chat_state.messages:
            transcript_lines: list[str] = []
            for msg in self._chat_state.messages:
                role = msg.role
                if msg.tool_name:
                    role = f"{role} ({msg.tool_name})"
                transcript_lines.append(f"[{msg.timestamp}] {role}: {msg.content}")
            copy_text = "\n".join(transcript_lines)
        else:
            info_lines = [
                f"Agent: {session.agent_id}",
                f"Session: {session.key}",
                f"Name: {session.label or session.display_name}",
                f"Model: {session.model}",
                f"Tokens: {session.total_tokens}",
                f"Session ID: {session.session_id}",
            ]
            copy_text = "\n".join(info_lines)

        try:
            copied = copy_to_clipboard(copy_text)
        except Exception:  # noqa: BLE001
            copied = False

        if copied:
            if self._chat_mode and self._chat_state is not None and self._chat_state.messages:
                self.notify("Copied chat transcript")
            else:
                self.notify(f"Copied: {session.label or session.display_name}")
        else:
            self.notify("Failed to copy to clipboard", severity="error")

    def action_toggle_logs(self) -> None:
        """Toggle right panel visibility. Tree expands to full width when hidden."""
        right_panel = self.query_one("#right-panel", Vertical)
        tree = self.query_one(AgentTreeWidget)
        if right_panel.display:
            right_panel.display = False
            tree.styles.width = "100%"
        else:
            right_panel.display = True
            tree.styles.width = "2fr"

    def action_expand_all(self) -> None:
        """Expand all agent group nodes in the tree."""
        tree = self.query_one(AgentTreeWidget)
        for group in tree.root.children:
            group.expand()

    def action_refresh(self) -> None:
        """Manual refresh triggered by 'r' key."""
        logger.info("Manual refresh triggered")
        self._trigger_poll()

    def _handle_ctrl_c_quit(self) -> None:
        """Require double Ctrl+C within timeout before quitting the app."""
        now = time.monotonic()
        last_press = self._last_ctrl_c_press_at
        timeout = self.CTRL_C_QUIT_CONFIRM_TIMEOUT_SECONDS

        if last_press is not None and (now - last_press) <= timeout:
            self._last_ctrl_c_press_at = None
            self.exit()
            return

        self._last_ctrl_c_press_at = now
        timeout_seconds = int(timeout)
        self.notify(
            f"Press Ctrl+C again within {timeout_seconds}s to quit",
            severity="warning",
        )

    def on_key(self, event: events.Key) -> None:
        """Escape in chat mode exits back to transcript if input is empty."""
        if self._chat_mode and event.key in {"ctrl+v", "meta+v", "shift+insert"}:
            if self._paste_from_system_clipboard():
                event.prevent_default()
                event.stop()
                return

        if event.key == "meta+c":
            self.action_copy_info()
            event.prevent_default()
            event.stop()
            return

        if event.key == "ctrl+c":
            self._handle_ctrl_c_quit()
            event.prevent_default()
            event.stop()
            return

        if event.key != "escape" or not self._chat_mode:
            return

        input_widget = self._chat_input_widget()
        if input_widget is None:
            return
        if getattr(input_widget, "value", "").strip():
            return

        self._exit_chat_mode()
        event.stop()

    def on_unmount(self) -> None:
        """Clean up HTTP client on exit."""
        if hasattr(self, "_client"):
            logger.info("Closing gateway client")
            self._client.close()
