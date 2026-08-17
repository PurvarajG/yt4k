from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Sequence

from .models import JobResult, JobStage, ProgressEvent, Yt4kError
from .parsing import Clip, clip_section, clip_tag
from .planning import JobPlan

Popen = subprocess.Popen

VIDEO_CODECS = [
    # value, yt-dlp vcodec prefix, transcode encoder family
    ("source", None, None),
    ("av1", "av01", None),
    ("vp9", "vp9", None),
    ("h264", "avc1", None),
    ("h264x", None, "h264"),
    ("hevc", None, "hevc"),
]

AUDIO_FORMATS = [
    # value, ext, ffmpeg codec, lossy?
    ("source", None, None, False),
    ("wav", "wav", "pcm_s16le", False),
    ("flac", "flac", "flac", False),
    ("m4a", "m4a", "aac", True),
    ("mp3", "mp3", "libmp3lame", True),
    ("opus", "opus", "libopus", True),
]

MP4_SAFE_VIDEO = {"h264", "hevc", "av1"}
MP4_SAFE_AUDIO = {"aac", "mp3", "ac3"}

GRACE_PERIOD_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 0.5


def _num(value) -> float | None:
    try:
        v = float(value)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _normalize_codec(codec: str | None) -> str:
    c = (codec or "").lower()
    return {"avc1": "h264", "av01": "av1", "h265": "hevc",
            "vp09": "vp9"}.get(c, c)


class CancellationToken:
    """A thread-safe flag a worker checks between subprocess reads."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()


class Cancelled(Yt4kError):
    """Raised internally when a job is stopped mid-flight."""


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 100):
        cand = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not cand.exists():
            return cand
    return path.with_name(f"{path.stem} ({int(time.time())}){path.suffix}")


class JobRunner:
    """Runs yt-dlp/ffmpeg subprocesses and emits typed progress events.

    Every subprocess primitive is injectable so tests can supply a fake
    process factory instead of touching the network or the filesystem tools.
    """

    def __init__(
        self,
        popen: Callable[..., "subprocess.Popen"] = subprocess.Popen,
        run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
        killpg: Callable[[int, int], None] | None = None,
        grace_period: float = GRACE_PERIOD_SECONDS,
        poll_interval: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        self._popen = popen
        self._run = run
        self._which = which
        self._killpg = killpg or (lambda pid, sig: os.killpg(pid, sig))
        self._grace_period = grace_period
        self._poll_interval = poll_interval
        self._active_workdirs: set[Path] = set()
        self._workdirs_lock = threading.Lock()

    def _require(self, tool: str) -> str:
        path = self._which(tool)
        if not path:
            raise Yt4kError(f"'{tool}' not found on PATH. Install it with: "
                             f"brew install {tool}")
        return path

    # ------------------------------------------------------------ process

    def _start(self, cmd: Sequence[str]) -> "subprocess.Popen":
        return self._popen(
            list(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, start_new_session=True,
        )

    def _terminate(self, proc: "subprocess.Popen") -> None:
        """Stop a process group, escalating to SIGKILL after a grace period."""
        try:
            pgid = os.getpgid(proc.pid)
        except (OSError, AttributeError):
            pgid = proc.pid
        try:
            self._killpg(pgid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            return
        try:
            proc.wait(timeout=self._grace_period)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            self._killpg(pgid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.wait(timeout=self._grace_period)
        except subprocess.TimeoutExpired:
            pass

    def _stream(self, cmd: Sequence[str], cancel: CancellationToken,
                on_line: Callable[[str], None]) -> None:
        proc = self._start(cmd)
        try:
            for line in proc.stdout:
                if cancel.is_cancelled:
                    self._terminate(proc)
                    raise Cancelled("cancelled")
                on_line(line.rstrip("\n"))
            proc.wait()
        except Cancelled:
            raise
        except BaseException:
            self._terminate(proc)
            raise
        if cancel.is_cancelled:
            raise Cancelled("cancelled")
        if proc.returncode != 0:
            stderr = proc.stderr.read() if proc.stderr else ""
            tail = "\n".join((stderr or "").strip().splitlines()[-8:])
            raise Yt4kError(
                f"{Path(cmd[0]).name} failed (exit {proc.returncode})",
            ) if not tail else Yt4kError(
                f"{Path(cmd[0]).name} failed (exit {proc.returncode})\n{tail}"
            )

    # ------------------------------------------------------------ metadata

    def video_info(self, url: str) -> dict:
        out = self._run(
            [self._require("yt-dlp"), "--no-playlist", "--no-warnings", "-J", url],
            capture_output=True, text=True,
        )
        if out.returncode != 0:
            raise Yt4kError("could not read video info (bad URL, or yt-dlp "
                             "needs updating)")
        import json
        return json.loads(out.stdout)

    def probe(self, path: Path) -> dict:
        import json
        out = self._run(
            [self._require("ffprobe"), "-v", "error",
             "-show_entries", "stream=codec_name,codec_type,width,height:"
                              "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True,
        )
        if out.returncode != 0:
            return {}
        data = json.loads(out.stdout)
        info = {"duration": _num((data.get("format") or {}).get("duration", ""))}
        for st in data.get("streams") or []:
            if st.get("codec_type") == "video" and "vcodec" not in info:
                info["vcodec"] = st.get("codec_name")
                info["height"] = st.get("height")
            elif st.get("codec_type") == "audio" and "acodec" not in info:
                info["acodec"] = st.get("codec_name")
        return info

    def supports_sections(self) -> bool:
        out = self._run([self._require("yt-dlp"), "--help"],
                         capture_output=True, text=True)
        return "--download-sections" in (out.stdout or "")

    def has_encoder(self, name: str) -> bool:
        out = self._run([self._require("ffmpeg"), "-hide_banner", "-encoders"],
                         capture_output=True, text=True)
        return bool(re.search(rf"^\s*\S+\s+{re.escape(name)}\b", out.stdout, re.M))

    # ------------------------------------------------------------- fetch

    def build_video_format(self, res: int, codec: str) -> str:
        h = f"[height<={res}]" if res else ""
        pref = None
        for value, vcodec_prefix, _family in VIDEO_CODECS:
            if value == codec:
                pref = vcodec_prefix
        chain = []
        if pref:
            chain.append(f"bestvideo[vcodec^={pref}]{h}+bestaudio")
        chain += [f"bestvideo{h}+bestaudio", f"best{h}", "best"]
        return "/".join(chain)

    def _fetch(self, url: str, workdir: Path, fmt: str, merge: str | None,
               item_index: int, item_count: int, stage: JobStage,
               emit: Callable[[ProgressEvent], None], cancel: CancellationToken,
               section: str | None = None, precise: bool = True) -> Path:
        template = str(workdir / "%(title).150B [%(id)s].%(ext)s")
        cmd = [self._require("yt-dlp"), "-f", fmt, "--no-playlist", "--no-warnings",
               "--newline", "--quiet", "--progress",
               "--progress-template",
               ("download:YT4K %(progress.downloaded_bytes)s "
                "%(progress.total_bytes_estimate)s %(progress.total_bytes)s "
                "%(progress.speed)s %(progress.eta)s"),
               "-o", template]
        if merge:
            cmd += ["--merge-output-format", merge]
        if section:
            cmd += ["--download-sections", section]
            if precise:
                cmd.append("--force-keyframes-at-cuts")
        cmd.append(url)

        def on_line(line: str) -> None:
            if not line.startswith("YT4K "):
                return
            _, got, est, tot, speed, eta = (line.split(" ") + ["NA"] * 5)[:6]
            got_b = _num(got) or 0.0
            total_b = _num(tot) or _num(est)
            frac = (got_b / total_b) if total_b else None
            emit(ProgressEvent(
                item_index=item_index, item_count=item_count, stage=stage,
                fraction=frac, downloaded_bytes=got_b, total_bytes=total_b,
                speed=_num(speed), eta=_num(eta),
            ))

        if section:
            # yt-dlp hands --download-sections off to its ffmpeg external
            # downloader, which only calls its progress hook once, at
            # completion - never during. Without this, the UI would sit
            # frozen on whatever stage preceded the fetch for the entire
            # download. Poll the growing output file on disk instead.
            stop_poll = threading.Event()
            poller = threading.Thread(
                target=self._poll_output_progress,
                args=(workdir, item_index, item_count, stage, emit, stop_poll),
                daemon=True,
            )
            poller.start()
            try:
                self._stream(cmd, cancel, on_line)
            finally:
                stop_poll.set()
                poller.join(timeout=2)
        else:
            self._stream(cmd, cancel, on_line)
        files = [p for p in workdir.iterdir() if p.is_file()]
        if not files:
            raise Yt4kError("yt-dlp produced no file")
        return max(files, key=lambda p: p.stat().st_mtime)

    def _poll_output_progress(self, workdir: Path, item_index: int,
                              item_count: int, stage: JobStage,
                              emit: Callable[[ProgressEvent], None],
                              stop: threading.Event,
                              interval: float | None = None) -> None:
        """Emit byte-based progress from the growing output file on disk.

        Used as a fallback while a downloader gives no interim progress of
        its own (see the --download-sections case above). Total size isn't
        known ahead of time, so `fraction` stays None; the UI shows this as
        an indeterminate bar with live bytes/speed instead of a percentage.
        """
        interval = self._poll_interval if interval is None else interval
        last_bytes = 0.0
        last_time = time.time()
        while not stop.wait(interval):
            try:
                files = [p for p in workdir.iterdir() if p.is_file()]
            except OSError:
                continue
            if not files:
                continue
            newest = max(files, key=lambda p: p.stat().st_mtime)
            try:
                size = float(newest.stat().st_size)
            except OSError:
                continue
            now = time.time()
            elapsed = now - last_time
            speed = ((size - last_bytes) / elapsed
                     if elapsed > 0 and size >= last_bytes else None)
            last_bytes, last_time = size, now
            emit(ProgressEvent(item_index=item_index, item_count=item_count,
                                stage=stage, fraction=None,
                                downloaded_bytes=size, speed=speed))

    def _trim_local(self, src: Path, start: float, end: float | None,
                    item_index: int, item_count: int,
                    emit: Callable[[ProgressEvent], None],
                    cancel: CancellationToken) -> Path:
        dst = src.with_name(f"{src.stem}.clip{src.suffix}")
        cmd = [self._require("ffmpeg"), "-y", "-ss", f"{start:.3f}"]
        if end is not None:
            cmd += ["-to", f"{end:.3f}"]
        cmd += ["-i", str(src), "-map", "0:v:0?", "-map", "0:a:0?",
                "-c", "copy", str(dst)]
        self._run_ffmpeg(cmd, (end - start) if end else None, item_index,
                          item_count, JobStage.CLIPPING, emit, cancel)
        src.unlink(missing_ok=True)
        return dst

    def _fetch_maybe_clipped(self, url: str, workdir: Path, fmt: str,
                             merge: str | None, plan: JobPlan,
                             cut: tuple[float, float | None] | None,
                             item_index: int, item_count: int,
                             emit: Callable[[ProgressEvent], None],
                             cancel: CancellationToken) -> Path:
        if not cut:
            return self._fetch(url, workdir, fmt, merge, item_index, item_count,
                                JobStage.DOWNLOADING, emit, cancel)
        start, end = cut
        if self.supports_sections():
            return self._fetch(
                url, workdir, fmt, merge, item_index, item_count,
                JobStage.CLIPPING, emit, cancel,
                section=clip_section(start, end),
                precise=bool(plan.settings.clip_precise) and end is not None,
            )
        src = self._fetch(url, workdir, fmt, merge, item_index, item_count,
                           JobStage.DOWNLOADING, emit, cancel)
        return self._trim_local(src, start, end, item_index, item_count,
                                 emit, cancel)

    # ---------------------------------------------------------- transcode

    def _run_ffmpeg(self, cmd: Sequence[str], duration: float | None,
                    item_index: int, item_count: int, stage: JobStage,
                    emit: Callable[[ProgressEvent], None],
                    cancel: CancellationToken) -> None:
        cmd = list(cmd)[:1] + ["-nostdin", "-hide_banner", "-loglevel", "error",
                               "-progress", "pipe:1", "-nostats"] + list(cmd)[1:]
        start_time = time.time()

        def on_line(line: str) -> None:
            if "=" not in line:
                return
            key, val = line.split("=", 1)
            if key == "out_time_us" and duration:
                secs = (_num(val) or 0.0) / 1_000_000
                frac = min(max(secs / duration, 0.0), 1.0)
                elapsed = time.time() - start_time
                eta = (elapsed / frac - elapsed) if frac > 0.001 else None
                emit(ProgressEvent(item_index=item_index, item_count=item_count,
                                    stage=stage, fraction=frac, eta=eta))

        self._stream(cmd, cancel, on_line)

    def _pick_encoder(self, family: str, hardware: bool) -> str:
        table = {
            "h264": (["h264_videotoolbox", "h264_nvenc", "h264_qsv"], "libx264"),
            "hevc": (["hevc_videotoolbox", "hevc_nvenc", "hevc_qsv"], "libx265"),
        }[family]
        if hardware:
            for enc in table[0]:
                if self.has_encoder(enc):
                    return enc
        if not self.has_encoder(table[1]):
            raise Yt4kError(f"ffmpeg has no {table[1]} encoder; enable hardware "
                             f"encoding, or pick 'keep source' as the codec")
        return table[1]

    def _transcode_video(self, src: Path, dst: Path, family: str, plan: JobPlan,
                         duration: float | None, item_index: int, item_count: int,
                         emit: Callable[[ProgressEvent], None],
                         cancel: CancellationToken) -> None:
        s = plan.settings
        encoder = self._pick_encoder(family, s.hardware)
        crf = int(s.crf)
        cmd = [self._require("ffmpeg"), "-y", "-i", str(src),
               "-map", "0:v:0", "-map", "0:a:0?", "-c:v", encoder]
        if encoder in ("libx264", "libx265"):
            cmd += ["-crf", str(crf), "-preset", s.preset]
        elif encoder.endswith("videotoolbox"):
            cmd += ["-q:v", str(max(1, 100 - crf * 2)), "-b:v", "0"]
        else:
            cmd += ["-cq", str(crf), "-b:v", "0"]
        cmd += ["-pix_fmt", "yuv420p", "-profile:v",
                "high" if family == "h264" else "main"]
        if family == "h264":
            cmd += ["-level", "5.2"]
        if encoder in ("libx265", "hevc_videotoolbox"):
            cmd += ["-tag:v", "hvc1"]
        cmd += ["-c:a", "aac", "-b:a", s.audio_bitrate,
                "-movflags", "+faststart", str(dst)]
        self._run_ffmpeg(cmd, duration, item_index, item_count,
                          JobStage.ENCODING, emit, cancel)

    def _remux(self, src: Path, dst: Path, duration: float | None,
              item_index: int, item_count: int,
              emit: Callable[[ProgressEvent], None], cancel: CancellationToken,
              audio: str = "copy", bitrate: str = "192k") -> None:
        cmd = [self._require("ffmpeg"), "-y", "-i", str(src),
               "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy", "-c:a", audio]
        if audio != "copy":
            cmd += ["-b:a", bitrate]
        cmd += ["-movflags", "+faststart", str(dst)]
        self._run_ffmpeg(cmd, duration, item_index, item_count,
                          JobStage.REMUXING, emit, cancel)

    def _convert_audio(self, src: Path, dst: Path, codec: str, bitrate: str,
                       lossy: bool, duration: float | None, item_index: int,
                       item_count: int, emit: Callable[[ProgressEvent], None],
                       cancel: CancellationToken) -> None:
        cmd = [self._require("ffmpeg"), "-y", "-i", str(src), "-vn", "-c:a", codec]
        if lossy:
            cmd += ["-b:a", bitrate]
        cmd += [str(dst)]
        self._run_ffmpeg(cmd, duration, item_index, item_count,
                          JobStage.ENCODING, emit, cancel)

    # --------------------------------------------------------------- jobs

    def _video_job(self, url: str, workdir: Path, out_dir: Path, plan: JobPlan,
                   dur: float | None, cut: tuple[float, float | None] | None,
                   item_index: int, item_count: int,
                   emit: Callable[[ProgressEvent], None],
                   cancel: CancellationToken) -> Path:
        s = plan.settings
        fmt = self.build_video_format(int(s.res), s.codec)
        src = self._fetch_maybe_clipped(url, workdir, fmt, "mkv", plan, cut,
                                         item_index, item_count, emit, cancel)
        info = self.probe(src)
        vcodec = _normalize_codec(info.get("vcodec"))
        acodec = _normalize_codec(info.get("acodec"))
        duration = info.get("duration") or dur

        target = None
        for value, _prefix, family in VIDEO_CODECS:
            if value == s.codec:
                target = family

        want = s.container
        if target:
            ext = "mp4" if want != "mkv" else "mkv"
        elif want == "mp4":
            ext = "mp4"
        elif want == "mkv":
            ext = "mkv"
        else:
            ext = "mp4" if (vcodec in MP4_SAFE_VIDEO
                            and acodec in MP4_SAFE_AUDIO) else "mkv"

        stem = src.stem + (f" ({clip_tag(*cut, cut[1] is None)})" if cut else "")
        final = _unique(out_dir / f"{stem}.{ext}")

        if target and vcodec != target:
            self._transcode_video(src, final, target, plan, duration,
                                   item_index, item_count, emit, cancel)
            if s.keep_source:
                shutil.move(str(src), _unique(out_dir / src.name))
        elif ext == "mkv" and src.suffix == ".mkv":
            shutil.move(str(src), final)
        else:
            needs_aac = ext == "mp4" and acodec not in MP4_SAFE_AUDIO
            self._remux(src, final, duration, item_index, item_count, emit,
                        cancel, audio="aac" if needs_aac else "copy",
                        bitrate=s.audio_bitrate)
        return final

    def _audio_job(self, url: str, workdir: Path, out_dir: Path, plan: JobPlan,
                   dur: float | None, cut: tuple[float, float | None] | None,
                   item_index: int, item_count: int,
                   emit: Callable[[ProgressEvent], None],
                   cancel: CancellationToken) -> Path:
        s = plan.settings
        src = self._fetch_maybe_clipped(url, workdir, "bestaudio/best", None,
                                         plan, cut, item_index, item_count,
                                         emit, cancel)
        info = self.probe(src)
        duration = info.get("duration") or dur

        row = next(r for r in AUDIO_FORMATS if r[0] == s.audio_format)
        _value, ext, codec, lossy = row
        stem = src.stem + (f" ({clip_tag(*cut, cut[1] is None)})" if cut else "")

        if codec is None:
            final = _unique(out_dir / f"{stem}{src.suffix}")
            shutil.move(str(src), final)
            return final

        if lossy and not self.has_encoder(codec):
            raise Yt4kError(f"ffmpeg has no {codec} encoder - pick another "
                             f"audio format")

        final = _unique(out_dir / f"{stem}.{ext}")
        self._convert_audio(src, final, codec, s.audio_bitrate, lossy, duration,
                             item_index, item_count, emit, cancel)
        if s.keep_source:
            shutil.move(str(src), _unique(out_dir / src.name))
        return final

    def _run_item(self, item_index: int, url: str, plan: JobPlan,
                  emit: Callable[[ProgressEvent], None],
                  cancel: CancellationToken) -> JobResult:
        item_count = len(plan.urls)
        metadata = plan.metadata[item_index]
        emit(ProgressEvent(item_index=item_index, item_count=item_count,
                            stage=JobStage.METADATA, fraction=None,
                            message=metadata.title))

        cut = None
        dur = metadata.duration
        if plan.clip:
            start, end = plan.clip.resolve(dur)
            to_end = end is None
            if to_end and dur:
                end = dur
            cut = (start, end)
            dur = (end - start) if end is not None else dur

        plan.destination.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(dir=plan.destination, prefix=".yt4k-"))
        with self._workdirs_lock:
            self._active_workdirs.add(workdir)
        try:
            final = (self._audio_job(url, workdir, plan.destination, plan, dur,
                                      cut, item_index, item_count, emit, cancel)
                     if plan.settings.mode == "audio" else
                     self._video_job(url, workdir, plan.destination, plan, dur,
                                      cut, item_index, item_count, emit, cancel))
            emit(ProgressEvent(item_index=item_index, item_count=item_count,
                                stage=JobStage.FINALIZING, fraction=1.0,
                                message=final.name))
            return JobResult(url=url, status="success", output_path=final,
                              message=f"Saved {final.name}")
        finally:
            # Only ever remove a directory this runner created for this job.
            with self._workdirs_lock:
                created_here = workdir in self._active_workdirs
                self._active_workdirs.discard(workdir)
            if created_here:
                shutil.rmtree(workdir, ignore_errors=True)

    def run_item(self, item_index: int, url: str, plan: JobPlan,
                emit: Callable[[ProgressEvent], None],
                cancel: CancellationToken) -> JobResult:
        """Run a single URL from `plan` and return its result.

        Safe to call concurrently from multiple threads for different items
        of the same plan - each item gets its own temp workdir and mutates no
        shared state beyond the lock-guarded workdir bookkeeping.
        """
        if cancel.is_cancelled:
            return JobResult(url=url, status="cancelled", output_path=None,
                             message="Cancelled")
        try:
            return self._run_item(item_index, url, plan, emit, cancel)
        except Cancelled:
            return JobResult(url=url, status="cancelled", output_path=None,
                             message="Cancelled")
        except Yt4kError as error:
            return JobResult(url=url, status="failed", output_path=None,
                             message=str(error), technical_detail=str(error))

    def run(self, plan: JobPlan, emit: Callable[[ProgressEvent], None],
            cancel: CancellationToken) -> list[JobResult]:
        """Run every URL in `plan` in order, emitting progress via `emit`.

        A cancelled job stops the remaining batch; completed items keep
        their results.
        """
        return [self.run_item(i, url, plan, emit, cancel)
                for i, url in enumerate(plan.urls)]

    def run_concurrent(self, plan: JobPlan, emit: Callable[[ProgressEvent], None],
                       cancel: CancellationToken, max_workers: int = 4) -> list[JobResult]:
        """Run every URL in `plan` at once (capped at `max_workers`), so a
        batch downloads together instead of one file at a time.

        Results are returned in the same order as `plan.urls` regardless of
        completion order.
        """
        if len(plan.urls) <= 1:
            return self.run(plan, emit, cancel)
        results: list[JobResult | None] = [None] * len(plan.urls)
        with ThreadPoolExecutor(max_workers=min(max_workers, len(plan.urls))) as pool:
            futures = {
                pool.submit(self.run_item, i, url, plan, emit, cancel): i
                for i, url in enumerate(plan.urls)
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        return results
