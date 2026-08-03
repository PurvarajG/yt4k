from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Input, OptionList, Static

from ...models import ValidationError
from ...settings import validate_destination
from ..widgets.common import ContextFooter, MinimumSizeGuard, WorkbenchHeader
from ..widgets.destination import CUSTOM_OPTION_ID, build_destination_options, build_destination_rows


class DestinationChosen(Message):
    def __init__(self, path: Path, make_default: bool, session_start: bool) -> None:
        super().__init__()
        self.path = path
        self.make_default = make_default
        self.session_start = session_start


class DestinationScreen(Screen):
    """The first screen of an interactive session, and the target of the
    home screen's 'f' shortcut for changing a destination mid-session."""

    BINDINGS = [
        ("d", "make_default", "Make default"),
        ("escape", "request_exit", "Quit"),
    ]

    def __init__(self, session_start: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session_start = session_start

    def compose(self) -> ComposeResult:
        yield WorkbenchHeader(screen_label="DESTINATION", id="header")
        with Container(id="screen-body"):
            yield Static(
                "Where should this session save?",
                id="destination-heading",
                classes="supporting-copy",
            )
            yield OptionList(*self._options(), id="destination-list")
            yield Input(placeholder="type or paste a path…", id="custom-path-input",
                        classes="hidden")
            yield Static("", id="destination-error", classes="error-text")
        yield MinimumSizeGuard()
        yield ContextFooter(
            hints=(("enter", "use folder"), ("d", "make default"), ("esc", "quit")),
            id="footer",
        )

    def _options(self):
        return build_destination_options(self._settings())

    def _settings(self):
        return self.app.state.settings

    def _rows(self):
        return build_destination_rows(self._settings())

    def on_mount(self) -> None:
        option_list = self.query_one("#destination-list", OptionList)
        option_list.highlighted = 0
        option_list.focus()

    def _resolve_highlighted_path(self) -> Path | None:
        option_list = self.query_one("#destination-list", OptionList)
        index = option_list.highlighted
        if index is None:
            return None
        rows = self._rows()
        if index >= len(rows):
            return None
        return rows[index][1]

    def _show_error(self, message: str) -> None:
        self.query_one("#destination-error", Static).update(message)

    def _open_custom_input(self) -> None:
        field = self.query_one("#custom-path-input", Input)
        field.remove_class("hidden")
        field.focus()

    def _commit(self, raw: str, make_default: bool) -> None:
        try:
            path = validate_destination(raw, create=True)
        except ValidationError as error:
            self._show_error(str(error))
            if self.query_one("#custom-path-input", Input).has_class("hidden") is False:
                self.query_one("#custom-path-input", Input).focus()
            else:
                self._open_custom_input()
            return
        self._show_error("")
        self.post_message(DestinationChosen(path, make_default, self.session_start))

    @on(OptionList.OptionSelected, "#destination-list")
    def _option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == CUSTOM_OPTION_ID:
            self._open_custom_input()
            return
        path = self._resolve_highlighted_path()
        if path is None:
            return
        self._commit(str(path), make_default=False)

    @on(Input.Submitted, "#custom-path-input")
    def _custom_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.replace("\\ ", " ").strip().strip("'\"")
        self._commit(raw, make_default=False)

    def action_make_default(self) -> None:
        option_list = self.query_one("#destination-list", OptionList)
        if self.focus is option_list or option_list.highlighted is not None:
            path = self._resolve_highlighted_path()
            if path is not None:
                self._commit(str(path), make_default=True)
                return
        field = self.query_one("#custom-path-input", Input)
        if not field.has_class("hidden") and field.value.strip():
            self._commit(field.value, make_default=True)

    def action_request_exit(self) -> None:
        if self.session_start:
            self.app.exit_with_summary()
        else:
            self.app.pop_screen()
