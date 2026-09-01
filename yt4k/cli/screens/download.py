from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, ProgressBar, Static

from ...jobs import CancellationToken
from ...models import JobResult, JobStage, ProgressEvent
from ...planning import JobPlan
from ..widgets.common import ContextFooter, MinimumSizeGuard, WorkbenchHeader
from ...updater import looks_stale
from ..widgets.progress import stage_label, status_line

LOG_LIMIT = 200
MAX_CONCURRENT_DOWNLOADS = 4


class DownloadFinished(Message):
    def __init__(self, results: list[JobResult]) -> None:
        super().__init__()
        self.results = results


class DownloadScreen(Screen):
    """Runs the job engine and renders its typed progress events.

    Every URL in the batch gets its own row with a real progress bar, and the
    whole batch downloads concurrently (capped at MAX_CONCURRENT_DOWNLOADS)
    instead of one file at a time.
    """

    BINDINGS = [("ctrl+c", "cancel_or_exit", "Cancel")]

    def __init__(self, plan: JobPlan, **kwargs) -> None:
        super().__init__(**kwargs)
        self.plan = plan
        self.cancel = CancellationToken()
        self._ctrl_c_count = 0
        self._log_lines: list[str] = []
        self.results: list[JobResult] | None = None

    def compose(self) -> ComposeResult:
        count = len(self.plan.urls)
        yield WorkbenchHeader(screen_label="DOWNLOAD", id="header")
        with Container(id="screen-body"):
            with VerticalScroll(id="download-items"):
                for index, url in enumerate(self.plan.urls):
                    metadata = (self.plan.metadata[index]
                               if index < len(self.plan.metadata) else None)
                    title = metadata.title if metadata else url
                    with Container(id=f"item-{index}", classes="download-item"):
                        yield Static(title, classes="item-title")
                        yield ProgressBar(total=100, show_eta=False,
                                          id=f"item-progress-{index}")
                        yield Static("Starting...", id=f"item-status-{index}",
                                    classes="item-status")
            yield Static(
                "Downloading..." if count > 1 else "Starting...",
                id="download-status",
            )
            with VerticalScroll(id="download-log"):
                yield Static("", id="download-log-content")
            with Horizontal(id="download-actions"):
                pass
        yield MinimumSizeGuard()
        yield ContextFooter(hints=(("ctrl+c", "cancel"),), id="footer")

    def on_mount(self) -> None:
        self._run()

    @work(thread=True, exclusive=True)
    def _run(self) -> None:
        results = self.app.runner.run_concurrent(
            self.plan, self._emit, self.cancel,
            max_workers=MAX_CONCURRENT_DOWNLOADS,
        )
        self.app.call_from_thread(self._finished, results)

    def _emit(self, event: ProgressEvent) -> None:
        self.app.call_from_thread(self._apply_event, event)

    def _apply_event(self, event: ProgressEvent) -> None:
        if self.cancel.is_cancelled:
            return
        try:
            bar = self.query_one(f"#item-progress-{event.item_index}", ProgressBar)
            status = self.query_one(f"#item-status-{event.item_index}", Static)
        except Exception:
            return
        if event.fraction is None:
            bar.update(total=None)
        else:
            bar.update(total=100, progress=event.fraction * 100)
        if event.stage == JobStage.METADATA:
            status.update(event.message or stage_label(event))
        else:
            status.update(status_line(event))
        self._log(f"[{event.item_index + 1}/{event.item_count}] {status_line(event)}")

    def _log(self, line: str) -> None:
        self._log_lines.append(line)
        self._log_lines = self._log_lines[-LOG_LIMIT:]
        self.query_one("#download-log-content", Static).update("\n".join(self._log_lines))

    def _finished(self, results: list[JobResult]) -> None:
        self.results = results
        self.app.state.results.extend(results)
        self.app.completed_count += sum(1 for r in results if r.status == "success")
        self._render_final(results)
        self.post_message(DownloadFinished(results))

    def _render_final(self, results: list[JobResult]) -> None:
        for index, result in enumerate(results):
            try:
                bar = self.query_one(f"#item-progress-{index}", ProgressBar)
                status = self.query_one(f"#item-status-{index}", Static)
            except Exception:
                continue
            if result.status == "success":
                bar.update(progress=100)
                status.update(f"Done - {result.message}")
            elif result.status == "cancelled":
                status.update("Cancelled")
            else:
                status.update(f"Failed - {result.message}")

        actions = self.query_one("#download-actions", Horizontal)
        actions.remove_children()
        failed = [r for r in results if r.status == "failed"]
        cancelled = [r for r in results if r.status == "cancelled"]
        if cancelled and not any(r.status == "success" for r in results):
            self.query_one("#download-status", Static).update("Cancelled")
        elif failed:
            self.query_one("#download-status", Static).update(
                f"{len(failed)} failed: {failed[0].message}"
            )
            actions.mount(Button("Retry", id="retry-button"))
            actions.mount(Button("Edit settings", id="edit-settings-button"))
            if any(looks_stale(r.message) for r in failed):
                self._update_ytdlp()
        else:
            done = sum(1 for r in results if r.status == "success")
            word = "file" if done == 1 else "files"
            self.query_one("#download-status", Static).update(f"Done - {done} {word}")
        actions.mount(Button("Home", id="home-button", variant="primary"))

    @work(thread=True, exclusive=True)
    def _update_ytdlp(self) -> None:
        """A 403 or a failed challenge almost always means yt-dlp fell behind
        YouTube. Fix it here, while the user is looking at the Retry button,
        rather than leaving them to discover it."""
        self.call_from_thread(
            self.query_one("#download-status", Static).update,
            "That looks like an outdated yt-dlp - updating...",
        )
        try:
            result = self.app.updater.update_now()
        except Exception as error:  # noqa: BLE001 - a failed update isn't fatal
            result = None
            message = f"Could not update yt-dlp: {error}"
        else:
            message = result.describe()
        if result is not None and result.changed:
            message = f"{message} - press Retry"
        self.call_from_thread(
            self.query_one("#download-status", Static).update, message,
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "home-button":
            self._return_home()
        elif event.button.id == "retry-button":
            self._retry()
        elif event.button.id == "edit-settings-button":
            self._edit_settings()

    def _return_home(self) -> None:
        from .home import HomeScreen

        self.app.state.request_draft = ""
        self.app.switch_screen(HomeScreen())

    def _retry(self) -> None:
        self.app.switch_screen(DownloadScreen(self.plan))

    def _edit_settings(self) -> None:
        from .settings import SettingsScreen

        self.app.push_screen(SettingsScreen(self.app.state.settings))

    def action_cancel_or_exit(self) -> None:
        self._ctrl_c_count += 1
        if self._ctrl_c_count == 1:
            self.cancel.cancel()
            self.query_one("#download-status", Static).update("Cancelling...")
        else:
            self.app.exit_with_summary()
