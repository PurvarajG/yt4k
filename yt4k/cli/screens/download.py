from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Static

from ...jobs import CancellationToken
from ...models import JobResult, JobStage, ProgressEvent
from ...planning import JobPlan
from ..widgets.common import ContextFooter, MinimumSizeGuard, WorkbenchHeader
from ..widgets.progress import batch_line, status_line

LOG_LIMIT = 200


class DownloadFinished(Message):
    def __init__(self, results: list[JobResult]) -> None:
        super().__init__()
        self.results = results


class DownloadScreen(Screen):
    """Runs the job engine and renders its typed progress events."""

    BINDINGS = [("ctrl+c", "cancel_or_exit", "Cancel")]

    def __init__(self, plan: JobPlan, **kwargs) -> None:
        super().__init__(**kwargs)
        self.plan = plan
        self.cancel = CancellationToken()
        self._ctrl_c_count = 0
        self._log_lines: list[str] = []
        self.results: list[JobResult] | None = None

    def compose(self) -> ComposeResult:
        yield WorkbenchHeader(screen_label="DOWNLOAD", id="header")
        with Container(id="screen-body"):
            metadata = self.plan.metadata[0] if self.plan.metadata else None
            title = metadata.title if metadata else self.plan.urls[0]
            yield Static(title, id="download-title")
            yield Static(batch_line_zero(self.plan), id="download-batch")
            yield Static("Starting...", id="download-status")
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
        results = self.app.runner.run(self.plan, self._emit, self.cancel)
        self.app.call_from_thread(self._finished, results)

    def _emit(self, event: ProgressEvent) -> None:
        self.app.call_from_thread(self._apply_event, event)

    def _apply_event(self, event: ProgressEvent) -> None:
        self.query_one("#download-batch", Static).update(batch_line(event))
        if self.cancel.is_cancelled:
            return
        self.query_one("#download-status", Static).update(status_line(event))
        self._log(status_line(event))

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
        else:
            done = sum(1 for r in results if r.status == "success")
            word = "file" if done == 1 else "files"
            self.query_one("#download-status", Static).update(f"Done - {done} {word}")
        actions.mount(Button("Home", id="home-button", variant="primary"))

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


def batch_line_zero(plan: JobPlan) -> str:
    count = len(plan.urls)
    return f"[1/{count}]" if count else ""
