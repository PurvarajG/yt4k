from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Input, Static

from ...parsing import parse_request
from ..widgets.common import ContextFooter, MinimumSizeGuard, WorkbenchHeader
from ..widgets.request import context_line, format_results


class RequestSubmitted(Message):
    def __init__(self, raw: str) -> None:
        super().__init__()
        self.raw = raw


class HomeScreen(Screen):
    """Focuses the request input; destination and defaults stay visible."""

    BINDINGS = [("escape", "request_exit", "Quit")]

    _SHORTCUTS = {
        "f": "change_destination", "folder": "change_destination",
        "save to": "change_destination", "saveto": "change_destination",
        "s": "open_settings", "settings": "open_settings",
        "?": "open_help", "help": "open_help",
    }

    def compose(self) -> ComposeResult:
        state = self.app.state
        yield WorkbenchHeader(screen_label="HOME", id="header")
        with Container(id="screen-body"):
            yield Static(
                context_line(state.destination, state.settings),
                id="context-line",
            )
            yield Input(placeholder="paste a link…", id="request-input",
                        value=state.request_draft)
            yield Static("", id="request-error", classes="error-text")
            yield Static(format_results(state.results), id="session-results")
        yield MinimumSizeGuard()
        yield ContextFooter(
            hints=(("f", "folder"), ("s", "settings"), ("?", "help"), ("esc", "quit")),
            id="footer",
        )

    def on_mount(self) -> None:
        self.query_one("#request-input", Input).focus()

    def refresh_context(self) -> None:
        state = self.app.state
        self.query_one("#context-line", Static).update(
            context_line(state.destination, state.settings)
        )
        self.query_one("#session-results", Static).update(
            format_results(state.results)
        )

    def show_error(self, message: str) -> None:
        self.query_one("#request-error", Static).update(message)

    @on(Input.Submitted, "#request-input")
    def _submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        if not raw:
            return
        action = self._SHORTCUTS.get(raw.lower())
        if action is not None:
            self.query_one("#request-input", Input).value = ""
            getattr(self, f"action_{action}")()
            return
        self.app.state.request_draft = raw
        parsed = parse_request(raw, self.app.state.settings)
        if not parsed.urls:
            self.show_error(
                "That didn't look like a link - paste a full https://… URL, "
                "then say what you want."
            )
            return
        self.show_error("")
        self.post_message(RequestSubmitted(raw))

    def action_change_destination(self) -> None:
        from .destination import DestinationScreen

        self.app.push_screen(DestinationScreen(session_start=False))

    def action_open_settings(self) -> None:
        from .settings import SettingsScreen

        self.app.push_screen(SettingsScreen())

    def action_open_help(self) -> None:
        from .help import HelpScreen

        self.app.push_screen(HelpScreen())

    def action_request_exit(self) -> None:
        self.app.exit_with_summary()
