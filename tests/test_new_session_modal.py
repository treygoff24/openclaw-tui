from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static

from openclaw_tui.chat.new_session_flow import ModelChoice
from openclaw_tui.widgets.new_session_modal import NewSessionModal


class _ModalHarness(App[None]):
    def __init__(self, modal: NewSessionModal) -> None:
        super().__init__()
        self._modal = modal
        self.modal_result: tuple[str, str | None] | None | object = object()

    def compose(self) -> ComposeResult:
        yield Static("root")

    def on_mount(self) -> None:
        self.push_screen(self._modal, callback=self._capture_modal_result)

    def _capture_modal_result(self, result: tuple[str, str | None] | None) -> None:
        self.modal_result = result


def _make_modal() -> NewSessionModal:
    return NewSessionModal(
        models=[
            ModelChoice(provider="anthropic", model_id="claude-opus-4-6", name="Opus"),
            ModelChoice(provider="anthropic", model_id="claude-sonnet-4-6", name="Sonnet"),
            ModelChoice(provider="openai", model_id="gpt-5.2", name="GPT-5.2"),
        ]
    )


@pytest.mark.asyncio
async def test_modal_renders_models_list() -> None:
    app = _ModalHarness(_make_modal())
    async with app.run_test() as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, NewSessionModal)
        model_list = modal.query_one("#new-session-model-list", OptionList)
        assert model_list.option_count == 3


@pytest.mark.asyncio
async def test_modal_filters_model_list_from_search_input() -> None:
    app = _ModalHarness(_make_modal())
    async with app.run_test() as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, NewSessionModal)

        search = modal.query_one("#new-session-model-search", Input)
        search.value = "sonnet"
        await pilot.pause()

        model_list = modal.query_one("#new-session-model-list", OptionList)
        assert model_list.option_count == 1
        option = model_list.get_option_at_index(0)
        assert "sonnet" in str(option.prompt).lower()


@pytest.mark.asyncio
async def test_modal_escape_cancels() -> None:
    app = _ModalHarness(_make_modal())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.modal_result is None


@pytest.mark.asyncio
async def test_modal_enter_submits_selected_model_and_optional_label() -> None:
    app = _ModalHarness(_make_modal())
    async with app.run_test() as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, NewSessionModal)
        label = modal.query_one("#new-session-label", Input)
        label.value = "sprint planning"
        modal.action_submit()
        await pilot.pause()
        assert app.modal_result == ("anthropic/claude-opus-4-6", "sprint planning")
