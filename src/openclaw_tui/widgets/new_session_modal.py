from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static

from ..chat.new_session_flow import ModelChoice


class NewSessionModal(ModalScreen[tuple[str, str | None] | None]):
    """Modal picker for creating a fresh main-agent session."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "submit", "Create"),
    ]

    DEFAULT_CSS = """
    NewSessionModal {
        align: center middle;
    }
    #new-session-shell {
        width: 80;
        max-width: 96%;
        height: auto;
        max-height: 90%;
        border: round #2A2E3D;
        background: #16213E;
        padding: 1 2;
    }
    #new-session-title {
        color: #F5A623;
        text-style: bold;
        margin-bottom: 1;
    }
    #new-session-model-search {
        margin-bottom: 1;
    }
    #new-session-model-list {
        height: 10;
        margin-bottom: 1;
    }
    #new-session-label {
        margin-bottom: 1;
    }
    #new-session-help {
        color: #A8B5A2;
    }
    #new-session-error {
        color: #C67B5C;
    }
    """

    def __init__(self, models: list[ModelChoice]) -> None:
        super().__init__()
        self._all_models = models
        self._visible_models: list[ModelChoice] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="new-session-shell"):
            yield Static("New Session", id="new-session-title")
            yield Input(
                placeholder="Filter models (provider/model)",
                id="new-session-model-search",
            )
            yield OptionList(id="new-session-model-list")
            yield Input(
                placeholder="Optional label",
                id="new-session-label",
            )
            yield Static("Enter to create - Esc to cancel", id="new-session-help")
            yield Static("", id="new-session-error")

    def on_mount(self) -> None:
        self._apply_model_filter("")
        self.query_one("#new-session-model-search", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "new-session-model-search":
            self._apply_model_filter(event.value)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.action_submit()

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        self.action_submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        model_ref = self._selected_model_ref()
        if not model_ref:
            self._set_error("No model selected")
            return
        label_input = self.query_one("#new-session-label", Input)
        label = label_input.value.strip() or None
        self.dismiss((model_ref, label))

    def _apply_model_filter(self, query: str) -> None:
        needle = query.strip().lower()
        if not needle:
            visible = self._all_models
        else:
            visible = [
                model
                for model in self._all_models
                if needle in model.ref.lower() or needle in (model.name or "").lower()
            ]

        self._visible_models = visible
        options = self.query_one("#new-session-model-list", OptionList)
        options.clear_options()

        if not visible:
            options.add_option("[dim]No models found[/]")
            self._set_error("No models match this filter")
            return

        self._set_error("")
        for model in visible:
            if model.name and model.name != model.model_id:
                options.add_option(f"{model.ref} - {model.name}")
            else:
                options.add_option(model.ref)
        options.highlighted = 0

    def _selected_model_ref(self) -> str | None:
        if not self._visible_models:
            return None
        options = self.query_one("#new-session-model-list", OptionList)
        index = options.highlighted
        if index is None or index < 0 or index >= len(self._visible_models):
            index = 0
        return self._visible_models[index].ref

    def _set_error(self, text: str) -> None:
        self.query_one("#new-session-error", Static).update(text)

