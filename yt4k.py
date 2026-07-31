#!/usr/bin/env python3
"""
yt4k — an interactive YouTube downloader that lives in your terminal.

Run it bare and it takes over the terminal as a downloader page: paste a link,
press enter, repeat. Press [s] to change resolution / codec / audio format,
[q] to leave.

    yt4k                     # interactive downloader page
    yt4k URL                 # one-shot, uses your saved settings
    yt4k URL --res 1080 --codec h264
    yt4k URL --audio wav
    yt4k URL -v              # raw yt-dlp / ffmpeg firehose

Requires: yt-dlp and ffmpeg on PATH.
    brew install yt-dlp ffmpeg      # macOS

Downloads land in ~/Downloads/YouTube 4K by default (created if missing).
Settings persist in ~/.config/yt4k/config.json.
"""

import argparse
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import termios
import time
import tty
from pathlib import Path

DEFAULT_OUTPUT_DIR = "~/Downloads/YouTube 4K"
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
    return sys.stdout.isatty() and os.environ.get("TERM") not in (None, "dumb")


if not supports_color():
    for _name in dir(C):
        if not _name.startswith("_"):
            setattr(C, _name, "")


class Yt4kError(Exception):
    """Anything that aborts one download without killing the session."""


# ---------------------------------------------------------------- utilities

def require(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        die(f"'{tool}' not found on PATH. Install it with: brew install {tool}")
    return path


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


def num(s: str) -> float | None:
    try:
        v = float(s)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def width() -> int:
    return max(shutil.get_terminal_size((80, 24)).columns, 40)


def tilde(p: Path | str) -> str:
    s = str(p)
    home = str(Path.home())
    return "~" + s[len(home):] if s.startswith(home) else s


class Bar:
    """One reusable single-line progress bar."""

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


def stream(cmd: list[str], handler) -> None:
    """Run cmd, feeding each stdout line to handler. Raises on failure."""
    if VERBOSE:
        print("+", " ".join(cmd), flush=True)
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            die(f"command failed with exit code {proc.returncode}")
        return

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    for line in proc.stdout:
        handler(line.rstrip("\n"))
    proc.wait()
    if proc.returncode != 0:
        tail = (proc.stderr.read() or "").strip().splitlines()[-8:]
        sys.stdout.write("\r\033[K")
        for t in tail:
            print(f"  {C.grey}{t}{C.reset}", file=sys.stderr)
        die(f"{Path(cmd[0]).name} failed (exit {proc.returncode})")


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

DEFAULTS = {
    "mode": "video",
    "res": 2160,
    "codec": "source",
    "container": "auto",
    "crf": 18,
    "preset": "slow",
    "hardware": False,
    "audio_format": "m4a",
    "audio_bitrate": "192k",
    "keep_source": False,
    "output_dir": DEFAULT_OUTPUT_DIR,
}


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(CONFIG_PATH.read_text()))
    except Exception:
        pass
    return {k: s.get(k, v) for k, v in DEFAULTS.items()}


def save_settings(s: dict) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(s, indent=2) + "\n")
    except Exception:
        pass


def label_of(table, value, idx=1):
    for row in table:
        if row[0] == value:
            return row[idx]
    return str(value)


def res_label(res: int) -> str:
    return label_of(RESOLUTIONS, res)


def summary(s: dict) -> str:
    if s["mode"] == "audio":
        af = label_of(AUDIO_FORMATS, s["audio_format"]).split(" · ")[0]
        bits = f" · {s['audio_bitrate']}" if is_lossy(s["audio_format"]) else ""
        return f"audio only · {af}{bits}"
    codec = label_of(VIDEO_CODECS, s["codec"], idx=4)
    cont = s["container"] if s["container"] != "auto" else "auto container"
    return f"video · {res_label(s['res'])} · {codec} · {cont}"


def is_lossy(fmt: str) -> bool:
    for row in AUDIO_FORMATS:
        if row[0] == fmt:
            return row[4]
    return False


# ---------------------------------------------------------------- metadata

def video_info(url: str) -> dict:
    out = subprocess.run(
        [require("yt-dlp"), "--no-playlist", "--no-warnings", "-J", url],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        tail = (out.stderr or "").strip().splitlines()[-4:]
        for t in tail:
            print(f"  {C.grey}{t}{C.reset}", file=sys.stderr)
        die("could not read video info (bad URL, or yt-dlp needs updating)")
    return json.loads(out.stdout)


def probe(path: Path) -> dict:
    out = subprocess.run(
        [require("ffprobe"), "-v", "error",
         "-show_entries", "stream=codec_name,codec_type,width,height:"
                          "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        return {}
    data = json.loads(out.stdout)
    info = {"duration": num((data.get("format") or {}).get("duration", ""))}
    for st in data.get("streams") or []:
        if st.get("codec_type") == "video" and "vcodec" not in info:
            info["vcodec"] = st.get("codec_name")
            info["height"] = st.get("height")
        elif st.get("codec_type") == "audio" and "acodec" not in info:
            info["acodec"] = st.get("codec_name")
    return info


def available_summary(meta: dict, limit: int = 4) -> str:
    """A compact 'what YouTube actually has' line."""
    seen: dict[int, set] = {}
    for f in meta.get("formats") or []:
        h, vc = f.get("height"), (f.get("vcodec") or "")
        if not h or vc in ("none", ""):
            continue
        fam = ("av1" if vc.startswith("av01") else
               "vp9" if vc.startswith("vp") else
               "h264" if vc.startswith("avc") else vc.split(".")[0])
        seen.setdefault(int(h), set()).add(fam)
    if not seen:
        return ""
    parts = [f"{h}p {'/'.join(sorted(seen[h]))}"
             for h in sorted(seen, reverse=True)[:limit]]
    return "  ·  ".join(parts)


# ---------------------------------------------------------------- download

def build_video_format(res: int, codec: str) -> str:
    h = f"[height<={res}]" if res else ""
    pref = None
    for row in VIDEO_CODECS:
        if row[0] == codec:
            pref = row[2]
    chain = []
    if pref:
        chain.append(f"bestvideo[vcodec^={pref}]{h}+bestaudio")
    chain += [f"bestvideo{h}+bestaudio", f"best{h}", "best"]
    return "/".join(chain)


def yt_dlp_fetch(url: str, workdir: Path, fmt: str, merge: str | None) -> Path:
    template = str(workdir / "%(title).150B [%(id)s].%(ext)s")
    bar = Bar("  downloading")

    def on_line(line: str) -> None:
        if not line.startswith("YT4K "):
            return
        _, got, est, tot, speed, eta = (line.split(" ") + ["NA"] * 5)[:6]
        got_b = num(got) or 0.0
        total_b = num(tot) or num(est)
        frac = (got_b / total_b) if total_b else 0.0
        sp = num(speed)
        right = f"{human_bytes(got_b)}/{human_bytes(total_b)}"
        if sp:
            right += f"  {human_bytes(sp)}/s"
        right += f"  eta {human_time(num(eta))}"
        bar.update(frac, right)

    cmd = [require("yt-dlp"), "-f", fmt, "--no-playlist", "--no-warnings",
           "--newline", "--quiet", "--progress",
           "--progress-template",
           ("download:YT4K %(progress.downloaded_bytes)s "
            "%(progress.total_bytes_estimate)s %(progress.total_bytes)s "
            "%(progress.speed)s %(progress.eta)s"),
           "-o", template, url]
    if merge:
        cmd[3:3] = ["--merge-output-format", merge]

    stream(cmd, on_line)

    files = [p for p in workdir.iterdir() if p.is_file()]
    if not files:
        die("yt-dlp produced no file")
    newest = max(files, key=lambda p: p.stat().st_mtime)
    bar.done(f"{human_bytes(newest.stat().st_size)} in "
             f"{human_time(time.time() - bar.start)}")
    return newest


# --------------------------------------------------------------- transcode

def run_ffmpeg(cmd: list[str], duration: float | None, label: str) -> None:
    cmd = cmd[:1] + ["-nostdin", "-hide_banner", "-loglevel", "error",
                     "-progress", "pipe:1", "-nostats"] + cmd[1:]
    bar = Bar(label)

    def on_line(line: str) -> None:
        if "=" not in line:
            return
        key, val = line.split("=", 1)
        if key == "out_time_us" and duration:
            secs = (num(val) or 0.0) / 1_000_000
            frac = secs / duration
            elapsed = time.time() - bar.start
            eta = (elapsed / frac - elapsed) if frac > 0.001 else None
            bar.update(frac, f"{human_time(secs)}/{human_time(duration)}"
                             f"  eta {human_time(eta)}")

    stream(cmd, on_line)
    bar.done(f"finished in {human_time(time.time() - bar.start)}")


_encoders_cache: set[str] | None = None


def has_encoder(name: str) -> bool:
    global _encoders_cache
    if _encoders_cache is None:
        out = subprocess.run([require("ffmpeg"), "-hide_banner", "-encoders"],
                             capture_output=True, text=True)
        _encoders_cache = set(re.findall(r"^\s*\S+\s+(\S+)", out.stdout, re.M))
    return name in _encoders_cache


def pick_encoder(family: str, hardware: bool) -> str:
    table = {
        "h264": (["h264_videotoolbox", "h264_nvenc", "h264_qsv"], "libx264"),
        "hevc": (["hevc_videotoolbox", "hevc_nvenc", "hevc_qsv"], "libx265"),
    }[family]
    if hardware:
        for enc in table[0]:
            if has_encoder(enc):
                return enc
    if not has_encoder(table[1]):
        die(f"ffmpeg has no {table[1]} encoder; try --fast for hardware "
            f"encoding, or pick 'keep source' as the codec")
    return table[1]


def transcode_video(src: Path, dst: Path, family: str, s: dict,
                    duration: float | None) -> None:
    encoder = pick_encoder(family, s["hardware"])
    crf = int(s["crf"])
    cmd = [require("ffmpeg"), "-y", "-i", str(src),
           "-map", "0:v:0", "-map", "0:a:0?", "-c:v", encoder]

    if encoder in ("libx264", "libx265"):
        cmd += ["-crf", str(crf), "-preset", s["preset"]]
    elif encoder.endswith("videotoolbox"):
        cmd += ["-q:v", str(max(1, 100 - crf * 2)), "-b:v", "0"]
    else:
        cmd += ["-cq", str(crf), "-b:v", "0"]

    cmd += ["-pix_fmt", "yuv420p", "-profile:v",
            "high" if family == "h264" else "main"]
    if family == "h264":
        cmd += ["-level", "5.2"]          # required for 4K
    if encoder == "libx265" or encoder == "hevc_videotoolbox":
        cmd += ["-tag:v", "hvc1"]         # so QuickTime will play it
    cmd += ["-c:a", "aac", "-b:a", s["audio_bitrate"],
            "-movflags", "+faststart", str(dst)]

    label = f"  {family.replace('hevc', 'h265')} encode"
    run_ffmpeg(cmd, duration, f"{label:<13}")


def remux(src: Path, dst: Path, duration: float | None,
          audio: str = "copy", bitrate: str = "192k") -> None:
    cmd = [require("ffmpeg"), "-y", "-i", str(src),
           "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy", "-c:a", audio]
    if audio != "copy":
        cmd += ["-b:a", bitrate]
    cmd += ["-movflags", "+faststart", str(dst)]
    run_ffmpeg(cmd, duration, "  remuxing    ")


def convert_audio(src: Path, dst: Path, codec: str, bitrate: str,
                  lossy: bool, duration: float | None) -> None:
    cmd = [require("ffmpeg"), "-y", "-i", str(src), "-vn", "-c:a", codec]
    if lossy:
        cmd += ["-b:a", bitrate]
    cmd += [str(dst)]
    run_ffmpeg(cmd, duration, "  encoding    ")


# ------------------------------------------------------------------ the job

MP4_SAFE_VIDEO = {"h264", "hevc", "av1"}
MP4_SAFE_AUDIO = {"aac", "mp3", "ac3"}


def normalize(codec: str | None) -> str:
    c = (codec or "").lower()
    return {"avc1": "h264", "av01": "av1", "h265": "hevc",
            "vp09": "vp9"}.get(c, c)


def run_job(url: str, s: dict) -> Path:
    require("yt-dlp")
    require("ffmpeg")
    require("ffprobe")

    out_dir = Path(s["output_dir"]).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    meta = video_info(url)
    title = meta.get("title") or "video"
    dur = num(str(meta.get("duration", "")))

    print(f"\n  {C.bold}{title[:width() - 4]}{C.reset}")
    bits = [human_time(dur)] if dur else []
    if s["mode"] == "video":
        avail = available_summary(meta)
        if avail:
            bits.append(avail)
    else:
        bits.append("audio only")
    if bits:
        print(f"  {C.grey}{' · '.join(bits)}{C.reset}")
    print()

    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".yt4k-") as tmp:
        workdir = Path(tmp)
        final = (audio_job(url, workdir, out_dir, s, dur) if s["mode"] == "audio"
                 else video_job(url, workdir, out_dir, s, dur))

    info = probe(final)
    tags = []
    if info.get("height"):
        tags.append(f"{info['height']}p")
    if info.get("vcodec"):
        tags.append(normalize(info["vcodec"]))
    if s["mode"] == "audio" and info.get("acodec"):
        tags.append(normalize(info["acodec"]))
    tags.append(human_bytes(final.stat().st_size))
    tags.append(f"{human_time(time.time() - started)} total")

    print(f"\n  {C.green}✓{C.reset} {C.bold}{final.name}{C.reset}")
    print(f"    {C.grey}{' · '.join(tags)}{C.reset}")
    print(f"    {C.grey}{tilde(final.parent)}{C.reset}\n")
    return final


def unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 100):
        cand = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not cand.exists():
            return cand
    return path.with_name(f"{path.stem} ({int(time.time())}){path.suffix}")


def video_job(url: str, workdir: Path, out_dir: Path, s: dict,
              dur: float | None) -> Path:
    fmt = build_video_format(int(s["res"]), s["codec"])
    src = yt_dlp_fetch(url, workdir, fmt, merge="mkv")

    info = probe(src)
    vcodec = normalize(info.get("vcodec"))
    acodec = normalize(info.get("acodec"))
    duration = info.get("duration") or dur

    target = None
    for row in VIDEO_CODECS:
        if row[0] == s["codec"]:
            target = row[3]

    # Decide the container.
    want = s["container"]
    if target:                                  # we're re-encoding to h264/hevc
        ext = "mp4" if want != "mkv" else "mkv"
    elif want == "mp4":
        ext = "mp4"
    elif want == "mkv":
        ext = "mkv"
    else:                                       # auto
        ext = "mp4" if (vcodec in MP4_SAFE_VIDEO
                        and acodec in MP4_SAFE_AUDIO) else "mkv"

    final = unique(out_dir / f"{src.stem}.{ext}")

    if target and vcodec != target:
        transcode_video(src, final, target, s, duration)
        if s["keep_source"]:
            shutil.move(str(src), unique(out_dir / src.name))
    elif ext == "mkv" and src.suffix == ".mkv":
        shutil.move(str(src), final)            # nothing to do at all
    else:
        needs_aac = ext == "mp4" and acodec not in MP4_SAFE_AUDIO
        remux(src, final, duration,
              audio="aac" if needs_aac else "copy", bitrate=s["audio_bitrate"])
    return final


def audio_job(url: str, workdir: Path, out_dir: Path, s: dict,
              dur: float | None) -> Path:
    src = yt_dlp_fetch(url, workdir, "bestaudio/best", merge=None)
    info = probe(src)
    duration = info.get("duration") or dur

    row = next(r for r in AUDIO_FORMATS if r[0] == s["audio_format"])
    _, _, ext, codec, lossy = row

    if codec is None:                           # keep whatever YouTube gave us
        final = unique(out_dir / src.name)
        shutil.move(str(src), final)
        return final

    if lossy and not has_encoder(codec):
        die(f"ffmpeg has no {codec} encoder — pick another audio format")

    final = unique(out_dir / f"{src.stem}.{ext}")
    convert_audio(src, final, codec, s["audio_bitrate"], lossy, duration)
    if s["keep_source"]:
        shutil.move(str(src), unique(out_dir / src.name))
    return final


# ----------------------------------------------------------------- key input

class KeyMode:
    """Hold the terminal in cbreak for a whole screen.

    Flipping modes between individual keystrokes loses escape sequences to the
    canonical-mode line buffer, so arrow keys end up echoed at the next prompt.
    """

    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.old = None

    def __enter__(self):
        try:
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)          # cbreak keeps \n → \r\n on output
            sys.stdout.write("\033[?25l")   # hide cursor
            sys.stdout.flush()
        except termios.error:
            self.old = None
        return self

    def __exit__(self, *_):
        self.restore()
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    def restore(self) -> None:
        if self.old is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def resume(self) -> None:
        if self.old is not None:
            tty.setcbreak(self.fd)


def read_key() -> str:
    """Read one keypress. The terminal must already be in cbreak mode.

    Reads the fd directly: sys.stdin is buffered, so the tail of an escape
    sequence can sit in Python's buffer while select() reports the fd idle —
    which makes every arrow key look like a bare Esc.
    """
    fd = sys.stdin.fileno()

    def get(timeout: float | None = None) -> str:
        if timeout is not None and not select.select([fd], [], [], timeout)[0]:
            return ""
        return os.read(fd, 1).decode(errors="replace")

    ch = get()
    if ch == "":
        return "esc"                        # stdin closed
    if ch == "\x1b":
        if get(0.05) == "[":
            code = get(0.05)
            return {"A": "up", "B": "down",
                    "C": "right", "D": "left"}.get(code, "")
        return "esc"
    if ch in ("\r", "\n"):
        return "enter"
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch == "\x04":
        return "ctrl-d"
    if ch == "\x0c":
        return "ctrl-l"
    if ch == "\x7f":
        return "backspace"
    return ch


# -------------------------------------------------------------------- screens

def clear() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def rule(char: str = "─") -> str:
    return C.grey + char * (width() - 4) + C.reset


def banner() -> None:
    inner = width() - 4
    logo = (
        "█   █  █████  █   █  █   █",
        "█   █    █    █   █  █  █ ",
        " █ █     █    █   █  █ █  ",
        "  █      █    █████  ██   ",
        "  █      █        █  █ █  ",
        "  █      █        █  █  █ ",
        "  █      █        █  █   █",
    )
    for line in logo:
        print(f"  {C.red}{C.bold}{line}{C.reset}")
    print(f"  {C.dim}YOUTUBE DOWNLOADER{C.reset}")
    print(f"  {C.grey}{'─' * inner}{C.reset}")


def chip(label: str, color: str = C.grey) -> str:
    return f"{color}{C.bold} {label} {C.reset}"


def panel_line(text: str = "", marker: str = "│") -> None:
    """Print one clipped line inside the dashboard panel."""
    usable = max(width() - 8, 20)
    print(f"  {C.grey}{marker}{C.reset}  {text[:usable]}")


def home(s: dict, note: str = "", recent: list[str] | None = None) -> None:
    banner()
    print()
    print(f"  {C.red}DOWNLOAD DESK{C.reset}")
    print(f"  {C.bold}Idle — downloader ready{C.reset}  "
          f"{C.dim}Paste a YouTube link to begin.{C.reset}")
    print(f"  {C.dim}OUTPUT{C.reset}  {tilde(Path(s['output_dir']).expanduser())}")
    print(f"  {rule()}")
    print()
    count = len(recent or [])
    noun = "item" if count == 1 else "items"
    print(f"  {C.bold}QUEUE{C.reset}  {C.dim}{count} {noun}{C.reset}")
    if recent:
        for item in recent[-3:]:
            print(f"  {item[:max(width() - 4, 20)]}")
    else:
        print(f"  {C.dim}Queue is empty — paste a link below to add one.{C.reset}")
    print()
    print(f"  {C.bold}What are we downloading?{C.reset}")
    print(f"  {C.dim}Paste one YouTube link, or space-separate several links for a batch.{C.reset}")
    print(f"  {C.grey}{'─' * max(width() - 4, 20)}{C.reset}")
    if note:
        print(f"  {C.red}!{C.reset} {note}")
    res = {2160: "4K", 1440: "1440p", 1080: "1080p"}.get(s["res"], res_label(s["res"]))
    quality = "  ".join(
        f"{C.red}{C.bold}[{label}]{C.reset}" if label == res else f"{C.dim}{label}{C.reset}"
        for label in ("4K", "1440p", "1080p")
    )
    video = f"{C.red}{C.bold}[VIDEO]{C.reset}" if s["mode"] == "video" else f"{C.dim}VIDEO{C.reset}"
    audio = f"{C.red}{C.bold}[AUDIO ONLY]{C.reset}" if s["mode"] == "audio" else f"{C.dim}AUDIO ONLY{C.reset}"
    print(f"  {C.dim}QUALITY{C.reset}  {quality}    {C.dim}FORMAT{C.reset}  {video}  {audio}")
    print(f"  {rule()}")
    print(f"  {C.dim}[s]{C.reset} settings  {C.dim}[o]{C.reset} folder  {C.dim}[:]{C.reset} commands  "
          f"{C.dim}[?]{C.reset} help  {C.dim}[esc]{C.reset} quit")


def help_screen() -> None:
    clear()
    banner()
    lines = [
        ("paste a link", "downloads it with your current settings"),
        ("several links", "paste them space-separated to queue a batch"),
        ("1 / 2 / 3", "use 4K, 1440p, or 1080p for new downloads"),
        ("v / a", "switch between video and audio-only mode"),
        ("s", "settings — resolution, codec, audio format, folder"),
        ("o", "open the download folder in Finder"),
        (":", "open the command palette"),
        ("h", "this screen"),
        ("esc / q / ctrl-d", "leave the downloader from the home screen"),
        ("ctrl-l", "redraw the screen — useful after a terminal resize"),
        ("ctrl-c", "cancel the active download; from home, leave the app"),
    ]
    print()
    for k, v in lines:
        print(f"  {C.cyan}{k:<16}{C.reset}{C.grey}{v}{C.reset}")
    print()
    print(f"  {C.grey}codecs: 'keep source' never re-encodes — fastest, and "
          f"exactly what{C.reset}")
    print(f"  {C.grey}YouTube served. AV1 / VP9 / avc1 pick that stream if it "
          f"exists.{C.reset}")
    print(f"  {C.grey}'re-encode' options convert anything to H.264 / H.265 "
          f"with ffmpeg.{C.reset}")
    print(f"\n  {C.dim}press any key to return · esc also returns{C.reset}")
    with KeyMode():
        read_key()


def command_palette() -> str:
    """A lightweight command palette — familiar to terminal coding tools."""
    clear()
    banner()
    print()
    print(f"  {C.red}COMMAND PALETTE{C.reset}  {C.dim}press a key to run an action{C.reset}\n")
    commands = [
        ("s", "Settings", "quality, format, encoder, destination"),
        ("o", "Reveal folder", "open completed downloads in Finder"),
        ("1 / 2 / 3", "Quality", "4K, 1440p, or 1080p for new downloads"),
        ("v / a", "Format", "video or audio-only for new downloads"),
        ("h", "Help", "shortcuts and download behaviour"),
        ("q", "Quit YT4K", "return to your terminal"),
    ]
    for key, title, detail in commands:
        print(f"  {C.red}[{key}]{C.reset}  {C.bold}{title:<16}{C.reset} {C.grey}{detail}{C.reset}")
    print(f"\n  {C.dim}esc to return{C.reset}")
    with KeyMode():
        key = read_key()
    return "" if key == "esc" else key


def read_command() -> str:
    """Read a command without giving up immediate Escape / Ctrl-D handling.

    The normal ``input`` prompt is line-buffered, which means a bare Escape
    waits for Return and feels broken.  This deliberately tiny line editor is
    enough for pasted URLs while making all advertised shortcuts instant.
    """
    value: list[str] = []
    sys.stdout.write(f"  {C.red}{C.bold}›{C.reset} ")
    sys.stdout.flush()
    with KeyMode():
        while True:
            key = read_key()
            if key == "enter":
                print()
                return "".join(value).strip()
            if key in ("esc", "ctrl-d"):
                print()
                return key
            if key == "ctrl-l":
                # Let the main loop redraw a clean, complete interface.
                print()
                return key
            if key == "backspace":
                if value:
                    value.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if len(key) == 1 and key >= " ":
                value.append(key)
                sys.stdout.write(key)
                sys.stdout.flush()


def cycle_field(draft: dict, key: str, step: int) -> None:
    """Advance draft[key] by `step` through its allowed values in place.

    Shared by the full settings screen and the quick per-link prompt so both
    stay in lockstep on what each field's valid values are.
    """
    if key == "mode":
        vals = [m[0] for m in MODES]
    elif key == "res":
        vals = [r[0] for r in RESOLUTIONS]
    elif key == "codec":
        vals = [c[0] for c in VIDEO_CODECS]
    elif key == "container":
        vals = [c[0] for c in CONTAINERS]
    elif key == "audio_format":
        vals = [a[0] for a in AUDIO_FORMATS]
    elif key == "audio_bitrate":
        vals = AUDIO_BITRATES
    elif key == "preset":
        vals = PRESETS
    elif key == "crf":
        draft["crf"] = min(51, max(0, int(draft["crf"]) + step))
        return
    elif key in ("hardware", "keep_source"):
        draft[key] = not draft[key]
        return
    else:
        return
    i = vals.index(draft[key]) if draft[key] in vals else 0
    draft[key] = vals[(i + step) % len(vals)]


def settings_screen(s: dict) -> dict:
    """Arrow-key settings page. Returns the (possibly edited) settings."""
    draft = dict(s)

    def rows():
        video = draft["mode"] == "video"
        audio = draft["mode"] == "audio"
        lossy = audio and is_lossy(draft["audio_format"])
        reenc = video and any(r[0] == draft["codec"] and r[3]
                              for r in VIDEO_CODECS)
        return [
            ("mode", "mode", label_of(MODES, draft["mode"]), True),
            ("res", "resolution", res_label(draft["res"]), video),
            ("codec", "video codec", label_of(VIDEO_CODECS, draft["codec"]),
             video),
            ("container", "container", label_of(CONTAINERS, draft["container"]),
             video),
            ("crf", "quality (crf)", f"{draft['crf']}  "
             f"{'smaller ← → better' if reenc else ''}", reenc),
            ("preset", "encoder preset", draft["preset"], reenc),
            ("hardware", "hardware encode",
             "on (fast)" if draft["hardware"] else "off (best quality)", reenc),
            ("audio_format", "audio format",
             label_of(AUDIO_FORMATS, draft["audio_format"]), audio),
            ("audio_bitrate", "audio bitrate", draft["audio_bitrate"],
             lossy or reenc),
            ("keep_source", "keep original file",
             "yes" if draft["keep_source"] else "no", True),
            ("output_dir", "folder  (enter to edit)",
             tilde(Path(draft["output_dir"]).expanduser()), True),
        ]

    cur = 0
    keys = KeyMode()
    with keys:
      while True:
        table = rows()
        clear()
        banner()
        print(f"  {C.red}YT4K SETTINGS{C.reset}")
        print(f"  {C.grey}↑↓ move    ←→ change    enter save    esc / ctrl-d cancel"
              f"{C.reset}\n")
        for i, (key, label, val, active) in enumerate(table):
            marker = f"{C.cyan}›{C.reset}" if i == cur else " "
            name = f"{label:<25}"
            if not active:
                print(f"  {marker} {C.dim}{name}{val}{C.reset}")
            elif i == cur:
                print(f"  {marker} {C.bold}{name}{C.reset}"
                      f"{C.cyan}‹ {val} ›{C.reset}")
            else:
                print(f"  {marker} {C.grey}{name}{C.reset}{val}")
        print()

        k = read_key()
        if k == "up":
            cur = (cur - 1) % len(table)
        elif k == "down":
            cur = (cur + 1) % len(table)
        elif k in ("left", "right"):
            cycle_field(draft, table[cur][0], -1 if k == "left" else 1)
        elif k == "enter":
            if table[cur][0] == "output_dir":
                keys.restore()              # cooked mode so input() can edit
                sys.stdout.write("\033[?25h")
                print(f"  {C.cyan}folder ›{C.reset} ", end="", flush=True)
                try:
                    raw = input().strip()
                except (EOFError, KeyboardInterrupt):
                    raw = ""
                if raw:
                    draft["output_dir"] = raw.replace("\\ ", " ").strip("'\"")
                keys.resume()
                sys.stdout.write("\033[?25l")
                continue
            save_settings(draft)
            return draft
        elif k in ("esc", "q", "ctrl-d"):
            return s


def quick_job_screen(s: dict, count: int) -> dict | None:
    """Fast per-link confirm screen: format, quality, encoding, file type.

    Shown right after a link (or batch of links) is submitted, so switching
    between video and audio — or picking a different codec/container — never
    requires a detour through the full settings screen. Whatever is chosen
    here becomes the new default, so a repeat paste just needs a bare enter.
    Returns the chosen settings, or None if the user cancelled.
    """
    draft = dict(s)
    quick_res = {"1": 2160, "2": 1440, "3": 1080}

    def rows():
        table = [("mode", "format", label_of(MODES, draft["mode"]))]
        if draft["mode"] == "video":
            table += [
                ("res", "quality", res_label(draft["res"])),
                ("codec", "encoding", label_of(VIDEO_CODECS, draft["codec"])),
                ("container", "file type",
                 label_of(CONTAINERS, draft["container"])),
            ]
        else:
            table.append(("audio_format", "file type",
                          label_of(AUDIO_FORMATS, draft["audio_format"])))
            if is_lossy(draft["audio_format"]):
                table.append(("audio_bitrate", "bitrate",
                             draft["audio_bitrate"]))
        return table

    cur = 0
    with KeyMode():
        while True:
            table = rows()
            cur = min(cur, len(table) - 1)
            clear()
            banner()
            what = "this link" if count == 1 else f"these {count} links"
            print(f"  {C.red}BEFORE WE GRAB{C.reset}  {C.dim}{what}{C.reset}")
            print(f"  {C.grey}↑↓ move    ←→ change    v/a format    1/2/3 quality"
                  f"    enter start    esc cancel{C.reset}\n")
            for i, (key, label, val) in enumerate(table):
                marker = f"{C.cyan}›{C.reset}" if i == cur else " "
                name = f"{label:<10}"
                if i == cur:
                    print(f"  {marker} {C.bold}{name}{C.reset}"
                          f"{C.cyan}‹ {val} ›{C.reset}")
                else:
                    print(f"  {marker} {C.grey}{name}{C.reset}{val}")
            print()

            k = read_key()
            if k == "up":
                cur = (cur - 1) % len(table)
            elif k == "down":
                cur = (cur + 1) % len(table)
            elif k in ("left", "right"):
                cycle_field(draft, table[cur][0], -1 if k == "left" else 1)
            elif k in ("v", "a"):
                draft["mode"] = "video" if k == "v" else "audio"
                cur = 0
            elif k in quick_res:
                draft["res"] = quick_res[k]
                draft["mode"] = "video"
            elif k == "enter":
                save_settings(draft)
                return draft
            elif k in ("esc", "q", "ctrl-d"):
                return None


# --------------------------------------------------------------------- shell

URL_RE = re.compile(r"https?://\S+")


def open_folder(s: dict) -> None:
    path = Path(s["output_dir"]).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    if shutil.which(opener):
        subprocess.run([opener, str(path)])


def interactive() -> None:
    s = load_settings()
    note = ""
    recent: list[str] = []
    while True:
        home(s, note, recent)
        note = ""
        try:
            raw = read_command()
        except KeyboardInterrupt:
            print()
            break

        if raw in ("esc", "ctrl-d"):
            break
        if raw == "ctrl-l":
            continue
        if not raw:
            continue
        cmd = raw.lower()
        if cmd in (":", "commands", "palette"):
            choice = command_palette().lower()
            if not choice:
                continue
            cmd = choice
        quick_res = {"1": 2160, "2": 1440, "3": 1080}
        if cmd in quick_res:
            s["res"] = quick_res[cmd]
            save_settings(s)
            note = f"{C.green}✓{C.reset} quality set to {res_label(s['res'])}"
            continue
        if cmd in ("v", "video"):
            s["mode"] = "video"
            save_settings(s)
            note = f"{C.green}✓{C.reset} video mode selected"
            continue
        if cmd in ("a", "audio"):
            s["mode"] = "audio"
            save_settings(s)
            note = f"{C.green}✓{C.reset} audio-only mode selected"
            continue
        if cmd in ("q", "quit", "exit"):
            break
        if cmd in ("s", "settings"):
            s = settings_screen(s)
            continue
        if cmd in ("h", "help", "?"):
            help_screen()
            continue
        if cmd in ("o", "open"):
            open_folder(s)
            note = f"{C.grey}opened {tilde(Path(s['output_dir']).expanduser())}{C.reset}"
            continue

        urls = URL_RE.findall(raw)
        if not urls:
            note = f"{C.yellow}!{C.reset} that didn't look like a link — " \
                   f"{C.grey}paste a full https://… url{C.reset}"
            continue

        chosen = quick_job_screen(s, len(urls))
        if chosen is None:
            note = f"{C.grey}cancelled{C.reset}"
            continue
        s = chosen

        banner()
        done = 0
        for i, url in enumerate(urls, 1):
            if len(urls) > 1:
                print(f"\n  {C.grey}[{i}/{len(urls)}]{C.reset}")
            try:
                final = run_job(url, s)
                done += 1
                recent.append(f"{C.green}✓{C.reset} {final.name}")
            except Yt4kError as e:
                print(f"\n  {C.red}✗{C.reset} {e}\n")
                recent.append(f"{C.red}✗{C.reset} {url[:60]}")
            except KeyboardInterrupt:
                sys.stdout.write("\r\033[K")
                print(f"\n  {C.yellow}cancelled{C.reset}\n")
                recent.append(f"{C.yellow}•{C.reset} cancelled {url[:55]}")
        word = "download" if done == 1 else "downloads"
        note = (f"{C.green}✓{C.reset} {done} {word} finished"
                if done else f"{C.red}nothing downloaded{C.reset}")
        print(f"  {C.dim}press enter to continue · esc to leave{C.reset}", end="", flush=True)
        try:
            with KeyMode():
                key = read_key()
            print()
            if key in ("esc", "ctrl-d", "q"):
                break
        except (EOFError, KeyboardInterrupt):
            print()
            break

    print(f"\n  {C.grey}bye.{C.reset}\n")


# ---------------------------------------------------------------------- main

def main() -> None:
    global VERBOSE

    s = load_settings()
    p = argparse.ArgumentParser(
        description="Interactive YouTube downloader. Run bare for the "
                    "downloader page, or pass a URL for a one-shot download.")
    p.add_argument("url", nargs="?", help="YouTube video URL")
    p.add_argument("-o", "--output-dir", help=f"where to write the file "
                                              f"(default: {s['output_dir']})")
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

    if args.max_height is not None:
        s["res"] = args.max_height
    if args.encoder:
        s["codec"] = "hevc" if "hevc" in args.encoder else "h264x"
        s["hardware"] = not args.encoder.startswith("lib")
    for key, val in (("res", args.res), ("codec", args.codec),
                     ("container", args.container), ("crf", args.crf),
                     ("preset", args.preset),
                     ("audio_bitrate", args.audio_bitrate),
                     ("output_dir", args.output_dir)):
        if val is not None:
            s[key] = val
    if args.audio:
        s["mode"], s["audio_format"] = "audio", args.audio
    if args.fast:
        s["hardware"] = True
    if args.keep_source:
        s["keep_source"] = True

    if not args.url:
        if not sys.stdin.isatty():
            p.error("no URL given (and stdin isn't a terminal)")
        interactive()
        return

    run_job(args.url, s)


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
