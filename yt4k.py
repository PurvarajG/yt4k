#!/usr/bin/env python3
"""
yt4k — an interactive YouTube downloader that lives in your terminal.

Run it bare and it opens a focused, keyboard-first Textual workbench: choose
a destination, paste a link, review what yt4k understood, and download.

    yt4k                     # interactive workbench
    yt4k URL                 # one-shot, uses your saved settings
    yt4k URL --res 1080 --codec h264
    yt4k URL --audio wav
    yt4k URL -v              # raw yt-dlp / ffmpeg firehose

Plain English works too, on the command line or in the interactive request box:

    yt4k URL 1:20 to 3:45            # export only that slice
    yt4k URL 12:00 to the end        # and 'start to 4:05' for the opening
    yt4k URL first 30s in 1080p mp4
    yt4k URL just the audio as mp3 320k
    yt4k URL 2:10-4:05 h265 small file -o ~/Desktop

Requires nothing but Python 3.10+: ./install.sh puts yt-dlp and ffmpeg in
yt4k's own venv.

Every interactive session opens by asking where to save, with your default
highlighted — enter accepts it, [d] on another folder makes that the default.
Press [f] later, or pass -o DIR, to redirect a session without touching the
default. Downloads land in ~/Downloads/YouTube 4K until you change that;
settings persist in ~/.config/yt4k/config.json.

The interactive workbench owns the terminal for its whole lifetime (Textual's
alternate screen) and restores it exactly once on exit.
"""

import argparse
import sys
import time
from dataclasses import asdict
from pathlib import Path

# During the compatibility migration this script remains the public entrypoint
# while also exposing the adjacent shared package as ``yt4k.*``.
__path__ = [str(Path(__file__).with_name("yt4k"))]

from yt4k.jobs import CancellationToken, JobRunner
from yt4k.models import JobStage, Settings, ValidationError
from yt4k.models import Yt4kError as CoreYt4kError
from yt4k.parsing import parse_clip as core_parse_clip
from yt4k.parsing import normalize_metadata, parse_request as core_parse_request
from yt4k.planning import build_job_plan
from yt4k.settings import SettingsStore

CONFIG_PATH = Path("~/.config/yt4k/config.json").expanduser()
VERBOSE = False


# ------------------------------------------------------------------- colors

class C:
    reset = "\033[0m"
    bold = "\033[1m"
    dim = "\033[2m"
    red = "\033[31m"
    green = "\033[32m"
    yellow = "\033[33m"
    blue = "\033[34m"
    cyan = "\033[36m"
    purple = "\033[38;5;141m"
    grey = "\033[90m"
    inv = "\033[7m"


def supports_color() -> bool:
    import os
    return sys.stdout.isatty() and os.environ.get("TERM") not in (None, "dumb")


if not supports_color():
    for _name in dir(C):
        if not _name.startswith("_"):
            setattr(C, _name, "")


class Yt4kError(Exception):
    """Anything that aborts one download without killing the session."""


# ---------------------------------------------------------------- utilities

def die(msg: str) -> None:
    sys.stdout.write("\r\033[K")
    raise Yt4kError(msg)


def human_bytes(n: float | None) -> str:
    if not n:
        return "--"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit in ("B", "KB") else f"{n:.1f}{unit}"
        n /= 1024
    return "--"


def human_time(secs: float | None) -> str:
    if secs is None or secs < 0 or secs != secs or secs == float("inf"):
        return "--:--"
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def width() -> int:
    import shutil
    return max(shutil.get_terminal_size((80, 24)).columns, 40)


def tilde(p: Path | str) -> str:
    s = str(p)
    home = str(Path.home())
    return "~" + s[len(home):] if s.startswith(home) else s


class Bar:
    """One reusable single-line progress bar for the one-shot presenter."""

    def __init__(self, label: str):
        self.label = label
        self.tty = sys.stdout.isatty() and not VERBOSE
        self.last = 0.0
        self.start = time.time()
        if not self.tty:
            print(f"{label}...", flush=True)

    def update(self, frac: float, right: str, force: bool = False) -> None:
        if not self.tty:
            return
        now = time.time()
        if not force and now - self.last < 0.1:
            return
        self.last = now
        frac = min(max(frac, 0.0), 1.0)
        right = right.ljust(34)[:34]        # fixed width, so the bar can't jitter
        barw = max(width() - len(self.label) - len(right) - 10, 10)
        filled = int(barw * frac)
        bar = (C.cyan + "━" * filled + C.grey + "━" * (barw - filled) + C.reset)
        sys.stdout.write(f"\r\033[K{C.dim}{self.label}{C.reset} {bar} "
                         f"{frac*100:3.0f}% {C.grey}{right}{C.reset}")
        sys.stdout.flush()

    def done(self, right: str) -> None:
        if self.tty:
            self.update(1.0, right, force=True)
            sys.stdout.write("\n")
            sys.stdout.flush()
        else:
            print(f"  {self.label} done — {right}", flush=True)


# ---------------------------------------------------------------- settings

RESOLUTIONS = [
    (2160, "2160p (4K)"),
    (1440, "1440p (2K)"),
    (1080, "1080p"),
    (720, "720p"),
    (480, "480p"),
    (0, "best available"),
]

VIDEO_CODECS = [
    # value, label, yt-dlp vcodec prefix, transcode encoder family, short
    ("source", "keep source (no re-encode)", None, None, "keep source"),
    ("av1", "AV1 / av01 (no re-encode)", "av01", None, "av1"),
    ("vp9", "VP9 (no re-encode)", "vp9", None, "vp9"),
    ("h264", "H.264 / avc1 (no re-encode)", "avc1", None, "h264"),
    ("h264x", "H.264 (re-encode anything)", None, "h264", "h264 re-encode"),
    ("hevc", "H.265 / HEVC (re-encode)", None, "hevc", "h265 re-encode"),
]

CONTAINERS = [
    ("auto", "auto (mp4 when safe)"),
    ("mp4", "mp4"),
    ("mkv", "mkv"),
]

AUDIO_FORMATS = [
    # value, label, ext, ffmpeg codec, lossy?
    ("source", "keep source (opus/m4a)", None, None, False),
    ("wav", "wav · uncompressed", "wav", "pcm_s16le", False),
    ("flac", "flac · lossless", "flac", "flac", False),
    ("m4a", "m4a · aac", "m4a", "aac", True),
    ("mp3", "mp3", "mp3", "libmp3lame", True),
    ("opus", "opus", "opus", "libopus", True),
]

AUDIO_BITRATES = ["320k", "256k", "192k", "128k", "96k"]
PRESETS = ["ultrafast", "veryfast", "fast", "medium", "slow", "slower"]
MODES = [("video", "video"), ("audio", "audio only")]

# Where this run writes, when it isn't the saved default. Set by -o;
# deliberately never persisted, so a one-off destination can't quietly become
# the permanent one.
SESSION_DIR: str | None = None


def active_dir(s: dict) -> Path:
    return Path(SESSION_DIR or s["output_dir"]).expanduser()


def label_of(table, value, idx=1):
    for row in table:
        if row[0] == value:
            return row[idx]
    return str(value)


def res_label(res: int) -> str:
    return label_of(RESOLUTIONS, res)


def is_lossy(fmt: str) -> bool:
    for row in AUDIO_FORMATS:
        if row[0] == fmt:
            return row[4]
    return False


def summary(s: dict) -> str:
    if s["mode"] == "audio":
        af = label_of(AUDIO_FORMATS, s["audio_format"]).split(" · ")[0]
        bits = f" · {s['audio_bitrate']}" if is_lossy(s["audio_format"]) else ""
        return f"audio only · {af}{bits}"
    codec = label_of(VIDEO_CODECS, s["codec"], idx=4)
    cont = s["container"] if s["container"] != "auto" else "auto container"
    return f"video · {res_label(s['res'])} · {codec} · {cont}"


# ------------------------------------------------------- one-shot presenter

def _present_progress(bars: dict, event) -> None:
    """The only non-Textual progress printer: renders a ProgressEvent as a
    plain-text line, honouring VERBOSE (raw firehose handled upstream)."""
    key = (event.item_index, event.stage)
    label = {
        JobStage.METADATA: "  fetching info",
        JobStage.DOWNLOADING: "  downloading",
        JobStage.CLIPPING: "  clipping   ",
        JobStage.REMUXING: "  remuxing    ",
        JobStage.ENCODING: "  encoding    ",
        JobStage.FINALIZING: "  finalizing  ",
    }[event.stage]
    if event.stage == JobStage.METADATA:
        title = event.message[:width() - 4]
        print(f"\n  {C.bold}{title}{C.reset}")
        return
    if event.stage == JobStage.FINALIZING:
        return
    bar = bars.setdefault(key, Bar(label))
    frac = event.fraction if event.fraction is not None else 0.0
    if event.downloaded_bytes is not None:
        right = f"{human_bytes(event.downloaded_bytes)}/{human_bytes(event.total_bytes)}"
        if event.speed:
            right += f"  {human_bytes(event.speed)}/s"
        right += f"  eta {human_time(event.eta)}"
    else:
        right = f"eta {human_time(event.eta)}"
    bar.update(frac, right)


def run_one_shot(urls: list[str], settings: "Settings", clip, destination: Path) -> None:
    """Execute one or more URLs through the shared job engine, printing a
    plain-text summary per file. This is the only one-shot progress printer."""
    runner = JobRunner()
    try:
        metadata = tuple(
            normalize_metadata(url, runner.video_info(url)) for url in urls
        )
        plan = build_job_plan(tuple(urls), destination, settings, clip, (), metadata)
    except (ValidationError, CoreYt4kError) as error:
        die(str(error))
        return

    bars: dict = {}
    cancel = CancellationToken()

    def emit(event) -> None:
        if VERBOSE:
            return
        _present_progress(bars, event)

    try:
        results = runner.run(plan, emit, cancel)
    except KeyboardInterrupt:
        cancel.cancel()
        raise

    for _key, bar in list(bars.items()):
        bar.done("")
    for result in results:
        if result.status == "success":
            print(f"\n  {C.green}✓{C.reset} {C.bold}{result.output_path.name}{C.reset}")
            print(f"    {C.grey}{tilde(result.output_path.parent)}{C.reset}\n")
        elif result.status == "cancelled":
            print(f"\n  {C.yellow}cancelled{C.reset}  {result.url}\n")
        else:
            print(f"\n  {C.red}✗{C.reset} {result.url}: {result.message}\n",
                  file=sys.stderr)
    if any(r.status == "failed" for r in results):
        sys.exit(1)


# --------------------------------------------------------------- interactive

def run_interactive() -> None:
    """Launch the Textual workbench. Only imported when actually needed, so
    one-shot invocations (including --explain) never import Textual."""
    from yt4k.cli.app import Yt4kApp

    app = Yt4kApp()
    app.run()


# ---------------------------------------------------------------------- main

def main() -> None:
    global VERBOSE, SESSION_DIR

    store = SettingsStore()
    settings, notice = store.load()
    if notice:
        print(f"  {C.yellow}!{C.reset} {notice.message}", file=sys.stderr)
    s = asdict(settings)
    p = argparse.ArgumentParser(
        description="Interactive YouTube downloader. Run bare for the "
                    "Textual workbench, or pass a URL for a one-shot download. "
                    "Plain English after the URL works: "
                    "yt4k URL 1:20 to 3:45 in 1080p mp4")
    p.add_argument("words", nargs="*", metavar="URL [words…]",
                   help="YouTube video URL, optionally followed by a time "
                        "range and format words")
    p.add_argument("--clip", metavar="RANGE",
                   help="export only this slice, e.g. --clip 1:20-3:45, "
                        "--clip 'from 12:00', --clip 'last 90s'")
    p.add_argument("--explain", action="store_true",
                   help="show how the request was understood, download nothing")
    p.add_argument("-o", "--output-dir",
                   help=f"where to write this run's files, without changing "
                        f"the saved default ({s['output_dir']})")
    p.add_argument("--res", type=int, choices=[r[0] for r in RESOLUTIONS],
                   help="max vertical resolution (0 = best available)")
    p.add_argument("--codec", choices=[c[0] for c in VIDEO_CODECS],
                   help="video codec: keep the source stream or re-encode")
    p.add_argument("--container", choices=[c[0] for c in CONTAINERS])
    p.add_argument("--audio", choices=[a[0] for a in AUDIO_FORMATS],
                   help="audio-only download in this format")
    p.add_argument("--audio-bitrate", choices=AUDIO_BITRATES)
    p.add_argument("--crf", type=int, help="re-encode quality, lower = better")
    p.add_argument("--preset", choices=PRESETS)
    p.add_argument("--fast", action="store_true",
                   help="hardware encoder (much faster, slightly bigger)")
    p.add_argument("--keep-source", action="store_true",
                   help="also keep the original downloaded file")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="show raw yt-dlp / ffmpeg output instead of bars")
    # Back-compat with the old flag names.
    p.add_argument("--max-height", type=int, help=argparse.SUPPRESS)
    p.add_argument("--encoder", help=argparse.SUPPRESS)
    args = p.parse_args()

    VERBOSE = args.verbose

    # Plain English first, so explicit flags below always win over words.
    raw = " ".join(args.words)
    parsed_request = core_parse_request(raw, settings)
    urls = list(parsed_request.urls)
    settings = parsed_request.settings
    s = asdict(settings)
    clip = parsed_request.clip
    chips = list(parsed_request.modifiers)
    if args.clip:
        parsed, _leftover = core_parse_clip(args.clip)
        if parsed is None:
            parsed, _ = core_parse_clip(f"from {args.clip}")
        if parsed is None:
            p.error(f"couldn't read a time range from --clip {args.clip!r} "
                    f"(try 1:20-3:45, 'from 12:00', or 'last 90s')")
        clip = parsed

    if args.max_height is not None:
        s["res"] = args.max_height
    if args.encoder:
        s["codec"] = "hevc" if "hevc" in args.encoder else "h264x"
        s["hardware"] = not args.encoder.startswith("lib")
    for key, val in (("res", args.res), ("codec", args.codec),
                     ("container", args.container), ("crf", args.crf),
                     ("preset", args.preset),
                     ("audio_bitrate", args.audio_bitrate)):
        if val is not None:
            s[key] = val
    if args.output_dir:
        # For this run only — never persisted.
        SESSION_DIR = args.output_dir.replace("\\ ", " ").strip("'\"")
    if args.audio:
        s["mode"], s["audio_format"] = "audio", args.audio
    if args.fast:
        s["hardware"] = True
    if args.keep_source:
        s["keep_source"] = True
    s["recent_dirs"] = tuple(s.get("recent_dirs") or ())
    settings = Settings(**s)

    if args.explain:
        print(f"  {C.bold}understood as{C.reset}")
        print(f"    links     {', '.join(urls) or '(none)'}")
        print(f"    clip      {clip.label() if clip else '(whole video)'}")
        print(f"    settings  {summary(s)}")
        print(f"    folder    {tilde(active_dir(s))}"
              f"{'  (this run only)' if SESSION_DIR else ''}")
        if chips:
            print(f"    words     {' · '.join(chips)}")
        return

    if not urls:
        if raw:
            p.error(f"no URL found in {raw!r}")
        if not sys.stdin.isatty():
            p.error("no URL given (and stdin isn't a terminal)")
        run_interactive()
        return

    run_one_shot(urls, settings, clip, active_dir(s))


if __name__ == "__main__":
    try:
        main()
    except Yt4kError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.stdout.write("\r\033[K")
        print("cancelled", file=sys.stderr)
        sys.exit(130)
