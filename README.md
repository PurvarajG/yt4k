# yt4k

An interactive YouTube downloader that lives in your terminal. Run it bare
and it takes over the terminal as a downloader page: paste a link, press
enter, repeat.

```
  █   █  █████  █   █  █   █
  █   █    █    █   █  █  █
   █ █     █    █   █  █ █
    █      █    █████  ██
    █      █        █  █ █
    █      █        █  █  █
    █      █        █  █   █
  YOUTUBE DOWNLOADER
  ────────────────────────────────────────────────────────────
```

## Install

Requires **Python 3.10+**, [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), and
`ffmpeg`.

```bash
git clone https://github.com/PurvarajG/yt4k.git
cd yt4k
./install.sh
```

The installer:
- installs `yt-dlp` and `ffmpeg` (via Homebrew on macOS, via pip + your
  package manager on Linux) if they're missing
- copies `yt4k.py` to `~/yt4k.py`
- adds a `yt4k` launcher to `~/.local/bin`

If `~/.local/bin` isn't already on your `PATH`, the installer tells you the
line to add to your shell rc file.

Re-run `./install.sh` any time to pick up an update — pull the latest repo
changes first with `git pull`.

## Use

```bash
yt4k                       # interactive downloader page
yt4k URL                   # one-shot, uses your saved settings
yt4k URL --res 1080 --codec h264
yt4k URL --audio wav
yt4k URL -v                # raw yt-dlp / ffmpeg firehose
```

### Say what you want

After the link — in the paste box or on the command line — just describe the
download in plain English. The same line can carry a time range and the
format you want.

```bash
yt4k URL 2:10 to 4:05                  # export only that slice
yt4k URL first 30s in 1080p mp4
yt4k URL just the audio as mp3 320k
yt4k URL from 12:00 h265 small file    # 12:00 to the end, re-encoded
yt4k URL 1:20-3:45 --explain           # show what it understood, download nothing
```

**Time ranges** — `2:10 to 4:05`, `2:10-4:05`, `1h02m to 1h05m30s`,
`from 12:00`, `until 0:45`, `first 30s`, `last 90s`, or bare seconds
(`90 to 225`). Clips are fetched with yt-dlp's `--download-sections`, so only
the segment comes down the wire, and cuts land on the exact timestamps
(switch to faster keyframe cuts under `[s]` → *clip cuts*). The time range
ends up in the filename: `Title [id] (2m10s-4m05s).mp4`. There's also
`--clip 1:20-3:45` if you prefer a flag.

**Format words** — resolution (`4k`, `1440p`, `1080p`, `720p`, `480p`,
`best quality`), codec (`av1`, `vp9`, `h264`, `h265`/`hevc`, `keep source`),
container (`mp4`, `mkv`), audio (`just the audio`, `mp3`, `wav`, `flac`,
`m4a`, `opus`, `320k`), and shorthands (`fast`, `smaller file`,
`high quality`). Say `convert to h264` to force a re-encode; a bare `h264`
just prefers the stream YouTube already has. Explicit flags always beat
words, and audio words override any resolution you also mentioned.

Whatever it read back is shown as chips on the confirm screen before
anything downloads, so a misread is one keypress from being fixed.

Inside the interactive page, paste one or more space-separated links and
press enter. You'll get a quick prompt to confirm format (video/audio),
quality, encoding, and file type before the download starts — press `v`/`a`
to jump straight to video/audio, `1`/`2`/`3` for 4K/1440p/1080p, or just hit
enter to reuse your last settings.

| key | does |
|---|---|
| `s` | full settings — resolution, codec, audio format, folder |
| `o` | open the download folder in Finder |
| `:` | command palette |
| `?` / `h` | help |
| `esc` / `q` / `ctrl-d` | quit |

Downloads land in `~/Downloads/YouTube 4K` by default. Settings persist in
`~/.config/yt4k/config.json`.

## Moving to another machine

Clone this repo on the new machine and run `./install.sh` — that's it. Your
settings and downloads are per-machine (not synced by this repo); the
installer only needs `yt4k.py` to set things up fresh.
