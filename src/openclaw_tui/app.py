"""AgentDashboard — main Textual TUI application with live polling."""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime
from functools import partial
import inspect
import logging
import mimetypes
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.theme import Theme
from textual.widgets import Footer, Header, Input, Tree

from .chat import ChatState
from .chat.commands import format_command_hint, format_help, parse_input
from .chat.command_handlers import ChatCommandHandlers
from .chat.new_session_flow import (
    build_new_main_session_key,
    normalize_model_choices,
    parse_newsession_args,
)
from .chat.event_handlers import ChatEventProcessor
from .chat.runtime_types import CommandResult, RunTrackingState
from .client import GatewayClient, GatewayError
from .config import load_config
from .gateway import GatewayWsClient
from .models import AgentNode, ChatMessage, SessionInfo, TreeNodeData
from .tree import build_tree
from .transcript import read_transcript
from .utils.clipboard import copy_to_clipboard, read_from_clipboard, read_image_to_temp_file_from_clipboard
from .widgets import AgentTreeWidget, ChatPanel, LogPanel, NewSessionModal, SummaryBar
from . import transcript

logger = logging.getLogger(__name__)

_IMAGE_TOKEN_PATTERN = re.compile(r"(?P<path>(?:~|/)\S+)")
_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


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
        ("ctrl+n", "new_session", "New Session"),
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
    padding: 0 0 0 1;
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
        self._ws_client: GatewayWsClient | None = None
        self._ws_connect_lock = asyncio.Lock()
        self._ws_connect_error: str | None = None
        self._chat_events: ChatEventProcessor | None = None
        self._run_tracking: RunTrackingState | None = None
        self._chat_commands = ChatCommandHandlers(
            client=self,
            state=self,
            on_send_text=self._send_user_chat_message,
            on_system=self._append_system_message,
            on_known_command=self._run_known_chat_command,
        )
        self._selected_session: SessionInfo | None = None
        self._chat_mode: bool = False
        self._chat_state: ChatState | None = None
        self._offline_message_queue: list[tuple[str, str, list[dict[str, str]], str, str | None]] = []
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
        self.run_worker(self._connect_ws_gateway, exclusive=True, group="chat_gateway_connect")
        self.set_interval(2.0, self._trigger_poll)
        self._trigger_poll()  # immediate first poll

    def _trigger_poll(self) -> None:
        """Trigger an exclusive worker to poll the gateway."""
        self.run_worker(self._poll_sessions, exclusive=True, group="session_poll")

    @property
    def current_session_key(self) -> str:
        if self._chat_state is None:
            return ""
        return self._chat_state.session_key

    @property
    def active_run_id(self) -> str | None:
        if self._chat_state is None:
            return None
        return self._chat_state.active_run_id

    async def chat_abort(self, session_key: str, run_id: str | None = None) -> dict:
        ws_client = await self._ensure_ws_client()
        return await ws_client.chat_abort(session_key, run_id=run_id)

    async def _connect_ws_gateway(self) -> None:
        """Connect to gateway WebSocket for chat parity transport."""
        async with self._ws_connect_lock:
            if self._ws_client is not None:
                return
            ws_client = GatewayWsClient(
                url=self._config.ws_url,
                token=self._config.token,
                client_display_name="openclaw-tui",
                client_version="0.1.0",
                platform="python",
            )
            ws_client.on_event = self._on_gateway_event
            ws_client.on_disconnected = self._on_gateway_disconnected
            ws_client.on_gap = self._on_gateway_gap
            try:
                await ws_client.start()
                await ws_client.wait_ready()
                self._ws_client = ws_client
                self._ws_connect_error = None
                logger.info("Chat WebSocket connected: %s", self._config.ws_url)
            except Exception as exc:  # noqa: BLE001
                self._ws_connect_error = str(exc)
                try:
                    await ws_client.stop()
                except Exception:  # noqa: BLE001
                    pass
                logger.warning("Chat WebSocket failed: %s", exc)
                self._show_poll_error(f"Chat websocket unavailable: {exc}")

    async def _ensure_ws_client(self) -> GatewayWsClient:
        ws_client = self._ws_client
        if ws_client is not None:
            return ws_client
        await self._connect_ws_gateway()
        ws_client = self._ws_client
        if ws_client is not None:
            return ws_client
        detail = f": {self._ws_connect_error}" if self._ws_connect_error else ""
        raise RuntimeError(f"chat websocket unavailable{detail}")

    def _on_gateway_event(self, evt: dict) -> None:
        if self._chat_mode is False or self._chat_events is None:
            return
        event_type = evt.get("event")
        payload = evt.get("payload")
        if event_type == "chat":
            self._chat_events.handle_chat_event(payload)
            if self._chat_state is not None and self._run_tracking is not None:
                self._chat_state.active_run_id = self._run_tracking.active_run_id
                self._chat_state.local_run_ids = set(self._run_tracking.local_run_ids)
                self._chat_state.finalized_run_ids = set(self._run_tracking.finalized_run_ids)
            return
        if event_type == "agent":
            verbose = "off"
            if self._chat_state is not None and self._chat_state.verbose_level:
                verbose = self._chat_state.verbose_level
            self._chat_events.handle_agent_event(payload, verbose_level=verbose)

    def _on_gateway_disconnected(self, reason: str) -> None:
        try:
            bar = self.query_one(SummaryBar)
            bar.set_error("Gateway offline. Reconnecting...")
        except Exception:  # noqa: BLE001
            pass

        if self._chat_mode:
            try:
                panel = self.query_one(ChatPanel)
                panel.set_status("● reconnecting...")
            except Exception:  # noqa: BLE001
                pass

        self.workers.cancel_group(self, "chat_gateway_connect")
        self.workers.cancel_group(self, "chat_gateway_reconnect")
        self.run_worker(self._reconnect_ws_gateway, exclusive=True, group="chat_gateway_reconnect")

    async def _reconnect_ws_gateway(self) -> None:
        """Background worker to exponentially backoff and reconnect to the gateway."""
        delay = 1.0
        max_delay = 10.0

        async with self._ws_connect_lock:
            old_client = self._ws_client
            self._ws_client = None
            if old_client is not None:
                try:
                    await old_client.stop()
                except Exception:  # noqa: BLE001
                    pass

        while self._ws_client is None:
            if not self.is_running:
                return

            if self._chat_mode:
                try:
                    self.query_one(ChatPanel).set_status(f"● reconnecting in {delay:.1f}s...")
                except Exception:  # noqa: BLE001
                    pass

            await asyncio.sleep(delay)

            if not self.is_running:
                return

            if self._chat_mode:
                try:
                    self.query_one(ChatPanel).set_status("● reconnecting...")
                except Exception:  # noqa: BLE001
                    pass

            await self._connect_ws_gateway()

            if self._ws_client is not None:
                if self._chat_mode:
                    try:
                        self.query_one(ChatPanel).set_status("● connected")
                    except Exception:  # noqa: BLE001
                        pass

                self._trigger_poll()

                if self._chat_state is not None:
                    self.run_worker(
                        partial(self._load_chat_history, self._chat_state.session_key, 200),
                        exclusive=True,
                        group="chat_history",
                    )

                self._replay_offline_queue()
                break

            delay = min(delay * 1.5, max_delay)

    def _replay_offline_queue(self) -> None:
        """Replay queued offline messages after reconnect.

        Failed sends are re-queued so no messages are silently lost.
        """
        if not self._offline_message_queue or self._ws_client is None:
            return
        queue = self._offline_message_queue
        self._offline_message_queue = []
        self.run_worker(
            partial(self._drain_offline_queue, queue),
            exclusive=True,
            group="chat_queue_replay",
        )

    async def _drain_offline_queue(
        self,
        queue: list[tuple[str, str, list[dict[str, str]], str, str | None]],
    ) -> None:
        """Send queued messages, re-queuing any that fail."""
        for queued in queue:
            if self._ws_client is None:
                self._offline_message_queue.extend(queue[queue.index(queued):])
                return
            try:
                await self._ws_client.send_chat(
                    session_key=queued[0],
                    message=queued[1],
                    attachments=queued[2],
                    run_id=queued[3],
                    thinking=queued[4],
                    deliver=False,
                    timeout_ms=30_000,
                )
            except Exception:  # noqa: BLE001
                logger.warning("Re-queuing failed offline message for session %s", queued[0])
                self._offline_message_queue.append(queued)

    def _on_gateway_gap(self, info: dict[str, int]) -> None:
        if not self._chat_mode or self._chat_state is None:
            return
        self.query_one(ChatPanel).set_status(
            f"● error: event gap expected {info['expected']} got {info['received']}"
        )
        self.run_worker(
            partial(self._load_chat_history, self._chat_state.session_key, 200),
            exclusive=True,
            group="chat_history",
        )

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
            if sessions and not nodes:
                nodes = self._group_sessions_fallback(sessions)
            session_lookup = {session.key: session for session in sessions}
            tree = self.query_one(AgentTreeWidget)
            bar = self.query_one(SummaryBar)
            try:
                tree_nodes = await asyncio.to_thread(self._client.fetch_tree)
                if tree_nodes:
                    parent_by_key, keyed_tree_nodes = self._collect_tree_relationships(tree_nodes)
                    synthetic_sessions = {
                        key: AgentTreeWidget._synthesize_session(node_data, now_ms)
                        for key, node_data in keyed_tree_nodes.items()
                        if key not in session_lookup
                    }
                    tree.update_tree(
                        nodes,
                        now_ms,
                        parent_by_key=parent_by_key,
                        synthetic_sessions=synthetic_sessions,
                    )
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
                    tree.update_tree(nodes, now_ms)
                    bar.update_summary(nodes, now_ms)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Tree stats update skipped: %s", exc)
                tree.update_tree(nodes, now_ms)
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

    @staticmethod
    def _collect_tree_relationships(
        tree_nodes: list[TreeNodeData],
    ) -> tuple[dict[str, str], dict[str, TreeNodeData]]:
        """Walk tree nodes and collect parent-child relationships.

        Recursively traverses the tree structure to build two lookup dictionaries:
        one mapping each node key to its parent's key, and another mapping each
        key to its TreeNodeData object.

        Args:
            tree_nodes: List of root TreeNodeData objects to traverse.

        Returns:
            A tuple of (parent_by_key, keyed_tree_nodes):
            - parent_by_key: Dict mapping child keys to their parent keys.
            - keyed_tree_nodes: Dict mapping all keys to their TreeNodeData.
        """
        parent_by_key: dict[str, str] = {}
        keyed_tree_nodes: dict[str, TreeNodeData] = {}

        def walk(node_data: TreeNodeData, parent_key: str | None) -> None:
            key = str(node_data.key)
            if key:
                keyed_tree_nodes[key] = node_data
                if parent_key and parent_key != key:
                    parent_by_key[key] = parent_key
                next_parent = key
            else:
                next_parent = parent_key
            for child in node_data.children:
                walk(child, next_parent)

        for node in tree_nodes:
            walk(node, None)
        return parent_by_key, keyed_tree_nodes

    @staticmethod
    def _group_sessions_fallback(sessions: list[SessionInfo]) -> list[AgentNode]:
        """Group sessions by agent_id as a fallback when tree data is unavailable.

        Creates AgentNode objects from a flat list of sessions, grouping them
        by their agent_id. Results are sorted with "main" agent first, followed
        by others alphabetically.

        Args:
            sessions: Flat list of SessionInfo objects to group.

        Returns:
            List of AgentNode objects, each containing its grouped sessions.
        """
        grouped: dict[str, list[SessionInfo]] = {}
        for session in sessions:
            grouped.setdefault(session.agent_id, []).append(session)
        sorted_agent_ids = sorted(
            grouped.keys(),
            key=lambda agent_id: (0, "") if agent_id == "main" else (1, agent_id),
        )
        return [AgentNode(agent_id=agent_id, sessions=grouped[agent_id]) for agent_id in sorted_agent_ids]

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
        self._reset_chat_runtime_for_session(session.key)
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
        self.workers.cancel_group(self, "chat_history")
        self._offline_message_queue.clear()

        chat_panel = self.query_one(ChatPanel)
        chat_panel.display = False
        chat_panel.set_header("Select a session")
        chat_panel.set_status("● idle")
        chat_panel.clear_log()

        log_panel = self.query_one(LogPanel)
        log_panel.display = True

        self._chat_mode = False
        self._chat_events = None
        self._run_tracking = None
        self._chat_state = None
        if self._selected_session is not None:
            self._show_transcript_for_session(self._selected_session)
        else:
            log_panel.show_placeholder()

    def action_new_session(self) -> None:
        """Open the new-session modal and create a fresh main-agent chat session."""
        self.run_worker(
            self._open_new_session_modal,
            exclusive=True,
            group="new_session_modal",
        )

    async def _open_new_session_modal(self) -> None:
        try:
            ws_client = await self._ensure_ws_client()
            model_choices = normalize_model_choices(await ws_client.models_list())
        except Exception as exc:  # noqa: BLE001
            self._show_new_session_error(f"Model list failed: {exc}")
            return

        if not model_choices:
            self._show_new_session_error("No models available")
            return

        allowed_models = {choice.ref for choice in model_choices}

        def _on_result(result: tuple[str, str | None] | None) -> None:
            if result is None:
                return
            model_ref, label = result
            self.run_worker(
                partial(
                    self._create_new_main_session,
                    model_ref,
                    label,
                    allowed_models=allowed_models,
                ),
                exclusive=True,
                group="new_session_create",
            )

        self.push_screen(NewSessionModal(models=model_choices), callback=_on_result)

    async def _create_new_main_session(
        self,
        model: str,
        label: str | None,
        *,
        allowed_models: set[str] | None = None,
    ) -> bool:
        if allowed_models is not None and model not in allowed_models:
            self._show_new_session_error(f"Model not available: {model}")
            return False

        created_key = build_new_main_session_key(
            now_ms=int(time.time() * 1000),
            rand=uuid4().hex[:8],
        )
        patch_kwargs: dict[str, object] = {"key": created_key, "model": model}
        if label is not None:
            patch_kwargs["label"] = label

        try:
            ws_client = await self._ensure_ws_client()
            result = await ws_client.sessions_patch(**patch_kwargs)
        except Exception as exc:  # noqa: BLE001
            self._show_new_session_error(f"New session failed: {exc}")
            return False

        resolved_key = created_key
        if isinstance(result, dict):
            candidate = result.get("key")
            if isinstance(candidate, str) and candidate.strip():
                resolved_key = candidate.strip()

        session_info = self._build_provisional_session_info_for_new_key(
            session_key=resolved_key,
            model=model,
            label=label,
        )
        self._enter_chat_mode_for_session(session_info, history_limit=200)
        self._trigger_poll()
        return True

    def _build_provisional_session_info_for_new_key(
        self,
        *,
        session_key: str,
        model: str,
        label: str | None,
    ) -> SessionInfo:
        now_ms = int(time.time() * 1000)
        key_tail = session_key.rsplit(":", 1)[-1]
        display_name = (label or "").strip() or key_tail or "new-session"
        return SessionInfo(
            key=session_key,
            kind="chat",
            channel="webchat",
            display_name=display_name,
            label=label.strip() if isinstance(label, str) and label.strip() else None,
            updated_at=now_ms,
            session_id=key_tail,
            model=model,
            context_tokens=None,
            total_tokens=0,
            aborted_last_run=False,
            transcript_path=None,
        )

    def _show_new_session_error(self, text: str) -> None:
        if self._chat_mode and self._chat_state is not None:
            self._append_system_message(text)
            self._chat_state.error = text
            self.query_one(ChatPanel).set_status(self._format_error_status(text))
            return
        self.notify(text, severity="error")

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

    def _on_chat_status(self, status: str) -> None:
        if self._chat_state is None:
            return
        if status in {"idle", "error", "aborted"}:
            self._chat_state.is_busy = False
        self.query_one(ChatPanel).set_status(f"● {status}")

    def _on_assistant_stream_update(self, text: str, run_id: str) -> None:
        if self._chat_state is None:
            return
        state = self._chat_state
        idx = state.stream_message_index_by_run.get(run_id)
        if idx is None:
            message = ChatMessage(role="assistant", content=text, timestamp=self._now_hhmm())
            state.messages.append(message)
            state.stream_message_index_by_run[run_id] = len(state.messages) - 1
        else:
            state.messages[idx].content = text
        state.last_message_count = len(state.messages)
        self.query_one(ChatPanel).show_messages(state.messages)

    def _on_assistant_stream_final(self, text: str, run_id: str) -> None:
        if self._chat_state is None:
            return
        state = self._chat_state
        idx = state.stream_message_index_by_run.pop(run_id, None)
        if idx is None:
            state.messages.append(ChatMessage(role="assistant", content=text, timestamp=self._now_hhmm()))
        else:
            state.messages[idx].content = text
        state.last_message_count = len(state.messages)
        state.active_run_id = None
        self.query_one(ChatPanel).show_messages(state.messages)

    def _reset_chat_runtime_for_session(self, session_key: str) -> None:
        self._run_tracking = RunTrackingState(session_key=session_key)
        self._chat_events = ChatEventProcessor(
            state=self._run_tracking,
            on_assistant_update=self._on_assistant_stream_update,
            on_assistant_final=self._on_assistant_stream_final,
            on_system=self._append_system_message,
            on_status=self._on_chat_status,
            include_thinking=bool(self._chat_state and self._chat_state.thinking_level),
            on_refresh_history=self._refresh_history_if_active,
        )

    def _refresh_history_if_active(self) -> None:
        if self._chat_state is None:
            return
        self.run_worker(
            partial(self._load_chat_history, self._chat_state.session_key, 200),
            exclusive=True,
            group="chat_history",
        )

    async def _load_chat_history(self, session_key: str, limit: int = 30) -> None:
        """Fetch history for a chat session and render it."""
        state = self._chat_state
        if state is None:
            return

        chat_panel = self.query_one(ChatPanel)
        chat_panel.set_status("● loading history...")

        try:
            ws_client = await self._ensure_ws_client()
            history = await ws_client.chat_history(session_key, limit=limit)
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

        messages = [self._to_chat_message(msg) for msg in history.get("messages", [])]
        self._chat_state.messages = messages
        self._chat_state.last_message_count = len(messages)
        self._chat_state.stream_message_index_by_run.clear()
        self._chat_state.thinking_level = history.get("thinkingLevel")
        self._chat_state.verbose_level = history.get("verboseLevel") or "off"
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

    def _run_chat_command(self, raw: str) -> None:
        """Handle slash commands in chat mode using parity command router."""
        if self._chat_state is None:
            return
        self.run_worker(
            partial(self._run_chat_command_async, raw),
            exclusive=True,
            group="chat_command",
        )

    async def _run_chat_command_async(self, raw: str) -> None:
        try:
            await self._chat_commands.handle(raw)
        except Exception as exc:  # noqa: BLE001
            self._append_system_message(f"Command failed: {exc}")

    async def _run_known_chat_command(self, name: str, args: str) -> CommandResult:
        if self._chat_state is None:
            return CommandResult(ok=False, message="No active chat session")
        ws_client: GatewayWsClient | None = None
        if name == "help":
            self._append_system_message(format_help())
            return CommandResult(ok=True)

        if name == "commands":
            self._append_system_message(format_help())
            return CommandResult(ok=True)

        if name == "status":
            session = self._chat_state.session_info
            status_text = (
                f"Agent: {session.agent_id}\n"
                f"Session: {self._chat_state.session_key}\n"
                f"Name: {session.label or session.display_name}\n"
                f"Model: {session.model}\n"
                f"Tokens: {session.total_tokens}"
            )
            self._append_system_message(status_text)
            return CommandResult(ok=True)

        if name == "back":
            self._exit_chat_mode()
            return CommandResult(ok=True)

        if name == "history":
            limit = 30
            if args:
                try:
                    limit = max(1, int(args.strip()))
                except ValueError:
                    self._append_system_message("Usage: /history [n]")
                    return CommandResult(ok=False)
            await self._load_chat_history(self._chat_state.session_key, limit)
            return CommandResult(ok=True)

        if name == "clear":
            chat_panel = self.query_one(ChatPanel)
            chat_panel.clear_log()
            self._chat_state.messages = []
            self._chat_state.last_message_count = 0
            chat_panel.set_status("● idle")
            return CommandResult(ok=True)

        if name in {"exit", "quit"}:
            self.exit()
            return CommandResult(ok=True)

        ws_client = await self._ensure_ws_client()

        if name == "newsession":
            model, label, error = parse_newsession_args(args)
            if error is not None:
                self._append_system_message(error)
                return CommandResult(ok=False)
            if model is None:
                self.action_new_session()
                return CommandResult(ok=True)
            ok = await self._create_new_main_session(model, label)
            return CommandResult(ok=ok)

        if name in {"new", "reset"}:
            await ws_client.sessions_reset(self._chat_state.session_key)
            await self._load_chat_history(self._chat_state.session_key, 200)
            return CommandResult(ok=True)

        if name in {"models", "model"} and not args:
            models = await ws_client.models_list()
            if not models:
                self._append_system_message("no models available")
                return CommandResult(ok=True)
            lines = ["models:"]
            for model in models[:20]:
                provider = model.get("provider", "unknown")
                model_id = model.get("id", "")
                lines.append(f"- {provider}/{model_id}")
            self._append_system_message("\n".join(lines))
            return CommandResult(ok=True)

        if name == "model" and args:
            await ws_client.sessions_patch(key=self._chat_state.session_key, model=args.strip())
            self._append_system_message(f"model set to {args.strip()}")
            return CommandResult(ok=True)

        if name in {"agents", "agent"} and not args:
            result = await ws_client.agents_list()
            agents = result.get("agents", [])
            if not agents:
                self._append_system_message("no agents found")
                return CommandResult(ok=True)
            lines = ["agents:"]
            for agent in agents:
                lines.append(f"- {agent.get('id', 'unknown')}")
            self._append_system_message("\n".join(lines))
            return CommandResult(ok=True)

        if name == "agent" and args:
            target_agent = args.strip()
            sessions = await ws_client.sessions_list(
                includeGlobal=False,
                includeUnknown=False,
                agentId=target_agent,
            )
            entries = sessions.get("sessions", [])
            main_match = next(
                (entry for entry in entries if isinstance(entry, dict) and str(entry.get("key", "")).endswith(":main")),
                None,
            )
            chosen = main_match or (entries[0] if entries else None)
            if not isinstance(chosen, dict) or not isinstance(chosen.get("key"), str):
                self._append_system_message(f"agent not found: {target_agent}")
                return CommandResult(ok=False)
            await self._switch_chat_session(chosen["key"])
            return CommandResult(ok=True)

        if name in {"sessions", "session"} and not args:
            result = await ws_client.sessions_list(
                includeGlobal=False,
                includeUnknown=False,
                includeDerivedTitles=True,
                includeLastMessage=True,
                agentId=self._chat_state.agent_id,
            )
            entries = result.get("sessions", [])
            if not entries:
                self._append_system_message("no sessions found")
                return CommandResult(ok=True)
            lines = ["sessions:"]
            for entry in entries[:25]:
                key = entry.get("key", "")
                title = entry.get("derivedTitle") or entry.get("displayName") or key
                lines.append(f"- {title} ({key})")
            self._append_system_message("\n".join(lines))
            return CommandResult(ok=True)

        if name == "session" and args:
            await self._switch_chat_session(args.strip())
            return CommandResult(ok=True)

        if name == "usage":
            choice = args.strip().lower() if args else "tokens"
            if choice not in {"off", "tokens", "full"}:
                self._append_system_message("usage: /usage <off|tokens|full>")
                return CommandResult(ok=False)
            await ws_client.sessions_patch(
                key=self._chat_state.session_key,
                responseUsage=None if choice == "off" else choice,
            )
            self._append_system_message(f"usage footer: {choice}")
            return CommandResult(ok=True)

        if name == "think":
            if not args:
                self._append_system_message("usage: /think <level>")
                return CommandResult(ok=False)
            await ws_client.sessions_patch(
                key=self._chat_state.session_key,
                thinkingLevel=args.strip(),
            )
            self._append_system_message(f"thinking set to {args.strip()}")
            return CommandResult(ok=True)

        if name == "verbose":
            if not args:
                self._append_system_message("usage: /verbose <on|off>")
                return CommandResult(ok=False)
            await ws_client.sessions_patch(
                key=self._chat_state.session_key,
                verboseLevel=args.strip(),
            )
            self._chat_state.verbose_level = args.strip()
            self._append_system_message(f"verbose set to {args.strip()}")
            return CommandResult(ok=True)

        if name == "reasoning":
            if not args:
                self._append_system_message("usage: /reasoning <on|off>")
                return CommandResult(ok=False)
            await ws_client.sessions_patch(
                key=self._chat_state.session_key,
                reasoningLevel=args.strip(),
            )
            self._append_system_message(f"reasoning set to {args.strip()}")
            return CommandResult(ok=True)

        if name in {"elevated", "activation", "settings"}:
            self._append_system_message(f"/{name} acknowledged")
            return CommandResult(ok=True)

        return CommandResult(ok=False, handled=False)

    async def _switch_chat_session(self, session_key: str) -> None:
        if self._chat_state is None:
            return
        normalized = session_key.strip()
        if normalized and normalized not in {"global", "unknown"} and not normalized.startswith("agent:"):
            normalized = f"agent:{self._chat_state.agent_id}:{normalized}"
        self._chat_state.current_session_key = normalized
        self._chat_state.active_run_id = None
        self._chat_state.stream_message_index_by_run.clear()
        self._reset_chat_runtime_for_session(normalized)
        self.query_one(ChatPanel).set_header(
            f"{normalized} · {self._chat_state.agent_id} · {self._chat_state.session_info.short_model}"
        )
        await self._load_chat_history(normalized, 200)

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
            ws_client = await self._ensure_ws_client()
            run_id = self._chat_state.active_run_id if self._chat_state is not None else None
            await ws_client.chat_abort(session_key, run_id=run_id)
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
        """Send a user message to gateway via websocket transport."""
        run_id = str(uuid4())
        outbound_message, attachments = self._extract_inline_image_attachments(message)

        if self._chat_state is not None:
            self._chat_state.active_run_id = run_id
            self._chat_state.local_run_ids.add(run_id)
        if self._run_tracking is not None:
            self._run_tracking.active_run_id = run_id
            self._run_tracking.note_local_run(run_id)

        try:
            ws_client = await self._ensure_ws_client()
            await ws_client.send_chat(
                session_key=session_key,
                message=outbound_message,
                thinking=self._chat_state.thinking_level if self._chat_state is not None else None,
                deliver=False,
                timeout_ms=30_000,
                run_id=run_id,
                attachments=attachments,
            )
        except (ConnectionError, RuntimeError) as exc:
            if isinstance(exc, RuntimeError) and "unavailable" not in str(exc) and "disconnected" not in str(exc) and "not connected" not in str(exc):
                raise
            logger.warning("send_message connection lost/offline for %s: %s", session_key, exc)

            thinking = self._chat_state.thinking_level if self._chat_state is not None else None
            self._offline_message_queue.append(
                (session_key, outbound_message, attachments, run_id, thinking)
            )

            self._append_system_message("Gateway offline. Message queued for reconnect.")
            if self._chat_state is not None and self._chat_state.session_key == session_key:
                self._chat_state.is_busy = False
                self.query_one(ChatPanel).set_status("● queued (offline)")
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

    @staticmethod
    def _normalize_image_token_path(token: str) -> Path | None:
        """Parse and normalize a candidate image path token."""
        cleaned = token.strip().strip("'\"()[]{}<>,;")
        if not cleaned or not (cleaned.startswith("/") or cleaned.startswith("~")):
            return None
        path = Path(cleaned).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return None
        if not resolved.is_file():
            return None
        if resolved.suffix.lower() not in _IMAGE_MIME_BY_SUFFIX:
            return None
        allowed_root = (Path.home() / ".openclaw" / "media").resolve()
        try:
            resolved.relative_to(allowed_root)
        except ValueError:
            return None
        return resolved

    def _extract_inline_image_attachments(self, message: str) -> tuple[str, list[dict[str, str]]]:
        """Extract image file path tokens and convert them into inline attachments."""
        attachments: list[dict[str, str]] = []
        kept_tokens: list[str] = []

        for raw_token in message.split():
            match = _IMAGE_TOKEN_PATTERN.fullmatch(raw_token)
            path_token = match.group("path") if match else raw_token
            resolved = self._normalize_image_token_path(path_token)
            if resolved is None:
                kept_tokens.append(raw_token)
                continue
            try:
                image_bytes = resolved.read_bytes()
            except OSError:
                kept_tokens.append(raw_token)
                continue
            guessed_mime = _IMAGE_MIME_BY_SUFFIX.get(resolved.suffix.lower()) or mimetypes.guess_type(
                str(resolved)
            )[0]
            mime_type = guessed_mime or "image/png"
            attachments.append(
                {
                    "type": "image",
                    "mimeType": mime_type,
                    "content": base64.b64encode(image_bytes).decode("ascii"),
                }
            )

        cleaned_message = " ".join(kept_tokens).strip()
        if attachments and not cleaned_message:
            # Preserve compatibility if the user pasted only an image path.
            cleaned_message = message
        return cleaned_message or message, attachments

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

    def _paste_image_from_system_clipboard(self) -> bool:
        """Paste an image by staging clipboard bytes to a local file path."""
        image_path = read_image_to_temp_file_from_clipboard()
        if image_path is None:
            return False
        inserted = self._insert_text_into_chat_input(f"{image_path} ")
        if inserted:
            self.query_one(ChatPanel).set_status("● pasted image from clipboard")
        return inserted

    def on_chat_panel_submit(self, event: ChatPanel.Submit) -> None:
        """Handle chat input submission (commands, shell, or regular message)."""
        if not self._chat_mode or self._chat_state is None:
            return

        text = event.text.strip()
        if not text:
            return

        parsed = parse_input(text)
        if parsed.kind == "command":
            self._run_chat_command(parsed.raw)
            return
        if parsed.kind == "bang":
            self._run_bang_command(parsed.name)
            return

        self._send_user_chat_message(text)

    def on_paste(self, event: events.Paste) -> None:
        """Route pasted text into chat input while in chat mode."""
        if not self._chat_mode:
            return
        if event.text and self._insert_text_into_chat_input(event.text):
            event.stop()
            return
        # Some terminals emit paste events with empty text for image paste.
        if self._paste_image_from_system_clipboard():
            event.stop()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Show lightweight slash-command hints while typing in chat input."""
        if not self._chat_mode or event.input.id != "chat-input":
            return
        if self._chat_state is None:
            return
        if self._chat_state.is_busy:
            return

        try:
            chat_panel = self.query_one(ChatPanel)
        except Exception:  # noqa: BLE001
            return
        hint = format_command_hint(event.value)
        if hint:
            chat_panel.set_status(f"● {hint}")
            return

        if self._chat_state.error:
            chat_panel.set_status(self._format_error_status(self._chat_state.error))
            return
        chat_panel.set_status("● idle")

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
        if self._chat_mode and event.key in {"ctrl+v", "meta+v", "alt+v", "shift+insert"}:
            if self._paste_from_system_clipboard():
                event.prevent_default()
                event.stop()
                return
            if self._paste_image_from_system_clipboard():
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

        if event.key == "ctrl+n":
            self.action_new_session()
            event.prevent_default()
            event.stop()
            return

        if self._chat_mode and event.key == "ctrl+l":
            self._run_chat_command("/models")
            event.prevent_default()
            event.stop()
            return

        if self._chat_mode and event.key == "ctrl+g":
            self._run_chat_command("/agents")
            event.prevent_default()
            event.stop()
            return

        if self._chat_mode and event.key == "ctrl+p":
            self._run_chat_command("/sessions")
            event.prevent_default()
            event.stop()
            return

        if self._chat_mode and event.key == "ctrl+t":
            if self._chat_state is not None:
                self._chat_state.thinking_level = (
                    None if self._chat_state.thinking_level else "on"
                )
                if self._chat_events is not None:
                    self._chat_events.set_include_thinking(bool(self._chat_state.thinking_level))
                self.run_worker(
                    partial(self._load_chat_history, self._chat_state.session_key, 200),
                    exclusive=True,
                    group="chat_history",
                )
            event.prevent_default()
            event.stop()
            return

        if event.key != "escape" or not self._chat_mode:
            return

        if self._chat_state is not None and self._chat_state.active_run_id:
            self.run_worker(
                partial(self._abort_chat_session, self._chat_state.session_key),
                exclusive=True,
                group="chat_abort",
            )
            event.stop()
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
        self.workers.cancel_group(self, "chat_gateway_reconnect")
        self.workers.cancel_group(self, "chat_queue_replay")
        ws_client = self._ws_client
        if ws_client is not None:
            stop_method = getattr(ws_client, "stop", None)
            if callable(stop_method):
                stop_result = stop_method()
                if inspect.isawaitable(stop_result):
                    shutdown_task = asyncio.create_task(stop_result)

                    def _consume_shutdown_error(task: asyncio.Task[object]) -> None:
                        try:
                            task.result()
                        except asyncio.CancelledError:
                            return
                        except Exception:
                            logger.exception("Gateway websocket shutdown failed")

                    shutdown_task.add_done_callback(_consume_shutdown_error)
        if hasattr(self, "_client"):
            logger.info("Closing gateway client")
            self._client.close()
