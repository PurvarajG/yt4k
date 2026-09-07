from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ...playlists import URLKind, classify_url
from ..widgets.common import ContextFooter, MinimumSizeGuard, WorkbenchHeader


class PlaylistScopesChosen(Message):
    def __init__(self, raw: str, scopes: tuple[URLKind, ...]) -> None:
        super().__init__()
        self.raw = raw
        self.scopes = scopes


class PlaylistChoiceScreen(Screen):
    """Ask about every link that names both a video and a playlist."""

    BINDINGS = [("escape", "cancel", "Back")]

    def __init__(self, raw: str, urls: tuple[str, ...], **kwargs) -> None:
        super().__init__(**kwargs)
        self.raw = raw
        self.urls = urls
        self.ambiguous = tuple(
            index for index, url in enumerate(urls)
            if URLKind.AMBIGUOUS == classify_url(url)
        )
        self.scopes = [classify_url(url) for url in urls]
        self.current = 0

    def compose(self) -> ComposeResult:
        yield WorkbenchHeader(screen_label="PLAYLIST", id="header")
        with Container(id="screen-body"):
            yield Static("", id="playlist-choice-prompt")
            yield OptionList(
                Option("This video only", id="choice-video"),
                Option("The whole playlist", id="choice-playlist"),
                id="playlist-choice-options",
            )
        yield MinimumSizeGuard()
        yield ContextFooter(hints=(("↑↓", "choose"), ("enter", "continue"),
                                   ("esc", "back")), id="footer")

    def on_mount(self) -> None:
        self._show_current()
        self.query_one("#playlist-choice-options", OptionList).focus()

    def _show_current(self) -> None:
        position = self.current + 1
        total = len(self.ambiguous)
        url = self.urls[self.ambiguous[self.current]]
        self.query_one("#playlist-choice-prompt", Static).update(
            f"Link {position} of {total} has a video and playlist\n{url}\n\nWhat should download?"
        )

    @on(OptionList.OptionSelected, "#playlist-choice-options")
    def _selected(self, event: OptionList.OptionSelected) -> None:
        self.scopes[self.ambiguous[self.current]] = (
            URLKind.PLAYLIST if event.option.id == "choice-playlist" else URLKind.VIDEO
        )
        self.current += 1
        if self.current == len(self.ambiguous):
            self.post_message(PlaylistScopesChosen(self.raw, tuple(self.scopes)))
            return
        self._show_current()

    def action_cancel(self) -> None:
        self.app.pop_screen()
