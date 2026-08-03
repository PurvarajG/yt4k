from __future__ import annotations

from pathlib import Path

from textual import events
from textual.app import App

from ..jobs import JobRunner
from ..models import SessionState
from ..settings import SettingsStore

MIN_WIDTH = 40
MIN_HEIGHT = 12


class Yt4kApp(App):
    """Owns session state, screen routing, workers, and terminal restoration."""

    CSS_PATH = "theme.tcss"

    def __init__(
        self,
        state: SessionState | None = None,
        store: SettingsStore | None = None,
        runner: JobRunner | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.store = store or SettingsStore()
        self.config_notice = None
        if state is None:
            settings, notice = self.store.load()
            state = SessionState(settings=settings)
            self.config_notice = notice
        self.state = state
        self.runner = runner or JobRunner()
        self.completed_count = 0

    def on_mount(self) -> None:
        from .screens.destination import DestinationScreen

        self.push_screen(DestinationScreen())

    def on_resize(self, event: events.Resize) -> None:
        too_small = event.size.width < MIN_WIDTH or event.size.height < MIN_HEIGHT
        for screen in self.screen_stack:
            screen.set_class(too_small, "size-blocked")

    def exit_with_summary(self) -> None:
        destination = self.state.destination
        count = self.completed_count
        self.exit()
        if count:
            word = "file" if count == 1 else "files"
            print(f"\n  {count} {word} in {destination}\n")
        else:
            print("\n  bye.\n")
