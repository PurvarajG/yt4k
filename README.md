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
