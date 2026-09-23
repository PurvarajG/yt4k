from __future__ import annotations

from dataclasses import replace

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Input, Select, Static, Switch

from ...models import Settings, ValidationError
from ..fields import (
    AUDIO_BITRATES, CONTAINERS, MODES, PRESETS, RESOLUTIONS, VIDEO_CODECS,
    is_lossy, is_reencode,
)
from ..widgets.common import ContextFooter, MinimumSizeGuard, WorkbenchHeader

AUDIO_FORMAT_OPTIONS = [
    ("source", "keep source"), ("wav", "wav · lossless"), ("flac", "flac · lossless"),
    ("m4a", "m4a · aac"), ("mp3", "mp3"), ("opus", "opus"),
]


class SettingsSaved(Message):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings


class SettingsScreen(Screen):
    """Edits a local draft; saving validates atomically and persists once."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, settings: Settings | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._initial = settings
        self.draft: Settings = settings or Settings()

    async def on_mount(self) -> None:
        if self._initial is None:
            self.draft = self.app.state.settings
        await self._render_fields()

    def compose(self) -> ComposeResult:
        yield WorkbenchHeader(screen_label="SETTINGS", id="header")
        with Container(id="screen-body"):
            yield Container(id="fields")
            yield Static("", id="settings-error", classes="error-text")
            with Horizontal(id="settings-actions"):
                yield Button("Save", id="save-button", variant="primary")
                yield Button("Cancel", id="cancel-button")
        yield MinimumSizeGuard()
        yield ContextFooter(hints=(("esc", "cancel"),), id="footer")

    async def _render_fields(self) -> None:
        fields = self.query_one("#fields", Container)
        await fields.remove_children()
        d = self.draft

        def opts(table):
            return [(label, value) for value, label in table]

        widgets = [
            Static("mode", classes="field-label"),
            Select(opts(MODES), value=d.mode, id="field-mode"),
        ]
        if d.mode == "video":
            widgets += [
                Static("resolution", classes="field-label"),
                Select(opts(RESOLUTIONS), value=d.res, id="field-res"),
                Static("video codec", classes="field-label"),
                Select(opts(VIDEO_CODECS), value=d.codec, id="field-codec"),
                Static("container", classes="field-label"),
                Select(opts(CONTAINERS), value=d.container, id="field-container"),
            ]
            if is_reencode(d.codec):
                widgets += [
                    Static("quality (crf, lower = better)", classes="field-label"),
                    Input(value=str(d.crf), id="field-crf"),
                    Static("encoder preset", classes="field-label"),
                    Select([(p, p) for p in PRESETS], value=d.preset, id="field-preset"),
                    Static("hardware encode (faster, slightly bigger)",
                          classes="field-label"),
                    Switch(value=d.hardware, id="field-hardware"),
                ]
        else:
            widgets += [
                Static("audio format", classes="field-label"),
                Select(opts(AUDIO_FORMAT_OPTIONS), value=d.audio_format,
                      id="field-audio-format"),
            ]
            if is_lossy(d.audio_format):
                widgets += [
                    Static("audio bitrate", classes="field-label"),
                    Select([(b, b) for b in AUDIO_BITRATES], value=d.audio_bitrate,
                          id="field-audio-bitrate"),
                ]
        widgets += [
            Static("clip cuts at exact timestamps (off = nearest keyframe, faster)",
                  classes="field-label"),
            Switch(value=d.clip_precise, id="field-clip-precise"),
            Static("keep the original downloaded file", classes="field-label"),
            Switch(value=d.keep_source, id="field-keep-source"),
        ]
        await fields.mount_all(widgets)

    @on(Select.Changed, "#field-mode")
    async def _mode_changed(self, event: Select.Changed) -> None:
        if event.value == self.draft.mode:
            return  # the value Select posts on its own initial mount
        self.draft = replace(self.draft, mode=event.value)
        await self._render_fields()

    @on(Select.Changed, "#field-res")
    def _res_changed(self, event: Select.Changed) -> None:
        self.draft = replace(self.draft, res=event.value)

    @on(Select.Changed, "#field-codec")
    async def _codec_changed(self, event: Select.Changed) -> None:
        if event.value == self.draft.codec:
            return
        self.draft = replace(self.draft, codec=event.value)
        await self._render_fields()

    @on(Select.Changed, "#field-container")
    def _container_changed(self, event: Select.Changed) -> None:
        self.draft = replace(self.draft, container=event.value)

    @on(Select.Changed, "#field-preset")
    def _preset_changed(self, event: Select.Changed) -> None:
        self.draft = replace(self.draft, preset=event.value)

    @on(Select.Changed, "#field-audio-format")
    async def _audio_format_changed(self, event: Select.Changed) -> None:
        if event.value == self.draft.audio_format:
            return
        self.draft = replace(self.draft, audio_format=event.value)
        await self._render_fields()

    @on(Select.Changed, "#field-audio-bitrate")
    def _audio_bitrate_changed(self, event: Select.Changed) -> None:
        self.draft = replace(self.draft, audio_bitrate=event.value)

    @on(Switch.Changed, "#field-hardware")
    def _hardware_changed(self, event: Switch.Changed) -> None:
        self.draft = replace(self.draft, hardware=event.value)

    @on(Switch.Changed, "#field-clip-precise")
    def _clip_precise_changed(self, event: Switch.Changed) -> None:
        self.draft = replace(self.draft, clip_precise=event.value)

    @on(Switch.Changed, "#field-keep-source")
    def _keep_source_changed(self, event: Switch.Changed) -> None:
        self.draft = replace(self.draft, keep_source=event.value)

    @on(Button.Pressed, "#save-button")
    def _save(self, _event: Button.Pressed) -> None:
        crf_text = None
        if self.query("#field-crf"):
            crf_text = self.query_one("#field-crf", Input).value
        draft = self.draft
        if crf_text is not None:
            try:
                crf = int(crf_text)
            except ValueError:
                self.query_one("#settings-error", Static).update(
                    "Quality (crf) must be a whole number 0-51."
                )
                return
            if not 0 <= crf <= 51:
                self.query_one("#settings-error", Static).update(
                    "Quality (crf) must be between 0 and 51."
                )
                return
            draft = replace(draft, crf=crf)
        self.post_message(SettingsSaved(draft))

    @on(Button.Pressed, "#cancel-button")
    def _cancel(self, _event: Button.Pressed) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.app.pop_screen()
