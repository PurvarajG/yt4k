from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from textual import events, work
from textual.app import App

from ..jobs import JobRunner
from ..models import SessionState, ValidationError, Yt4kError
from ..parsing import normalize_metadata, parse_request
from ..planning import JobPlan, build_job_plan
from ..settings import SettingsStore, remember_destination
from ..updater import Updater
from .screens.destination import DestinationChosen
from .screens.home import RequestSubmitted
from .screens.review import ReviewConfirmed
from .screens.settings import SettingsSaved

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
        updater: Updater | None = None,
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
        self.updater = updater or Updater()
        self.completed_count = 0
        self.update_notice: str | None = None

    def on_mount(self) -> None:
        # Off the UI thread and at most daily: the workbench must open at the
        # same speed on a machine with no network as on one with a fast pip.
        self.updater.check_in_background(self._note_update)

        from .screens.destination import DestinationScreen

        self.push_screen(DestinationScreen())

    def _note_update(self, result) -> None:
        """Remember a successful background update so a later failure screen
        can say the retry is worth taking. Called from the update thread."""
        self.update_notice = result.describe()

    def on_resize(self, event: events.Resize) -> None:
        too_small = event.size.width < MIN_WIDTH or event.size.height < MIN_HEIGHT
        for screen in self.screen_stack:
            screen.set_class(too_small, "size-blocked")

    def on_destination_chosen(self, message: DestinationChosen) -> None:
        settings = remember_destination(self.state.settings, message.path)
        if message.make_default:
            settings = replace(settings, output_dir=str(message.path))
        self.store.save(settings)
        self.state.settings = settings
        self.state.destination = message.path
        from .screens.home import HomeScreen

        if message.session_start:
            self.switch_screen(HomeScreen())
        else:
            self.pop_screen()
            if isinstance(self.screen, HomeScreen):
                self.screen.refresh_context()

    def on_request_submitted(self, message: RequestSubmitted) -> None:
        self._fetch_metadata_and_review(message.raw)

    @work(thread=True, exclusive=True)
    def _fetch_metadata_and_review(self, raw: str) -> None:
        parsed = parse_request(raw, self.state.settings)
        try:
            metadata = tuple(
                normalize_metadata(url, self.runner.video_info(url))
                for url in parsed.urls
            )
            plan = build_job_plan(
                parsed.urls, self.state.destination, parsed.settings,
                parsed.clip, parsed.modifiers, metadata,
            )
        except (ValidationError, Yt4kError) as error:
            self.call_from_thread(self._show_home_error, str(error))
            return
        self.call_from_thread(self._push_review, plan)

    def _show_home_error(self, message: str) -> None:
        from .screens.home import HomeScreen

        if isinstance(self.screen, HomeScreen):
            self.screen.show_error(message)

    def _push_review(self, plan: JobPlan) -> None:
        from .screens.review import ReviewScreen

        self.push_screen(ReviewScreen(plan))

    def on_review_confirmed(self, message: ReviewConfirmed) -> None:
        if message.plan.settings != self.state.settings:
            self.state.settings = message.plan.settings
            self.store.save(self.state.settings)
        from .screens.download import DownloadScreen

        self.switch_screen(DownloadScreen(message.plan))

    def on_settings_saved(self, message: SettingsSaved) -> None:
        self.state.settings = message.settings
        self.store.save(message.settings)
        self.pop_screen()
        from .screens.home import HomeScreen

        if isinstance(self.screen, HomeScreen):
            self.screen.refresh_context()

    def exit_with_summary(self) -> None:
        destination = self.state.destination
        count = self.completed_count
        self.exit()
        if count:
            word = "file" if count == 1 else "files"
            print(f"\n  {count} {word} in {destination}\n")
        else:
            print("\n  bye.\n")
