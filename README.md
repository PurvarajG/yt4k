# yt4k

An interactive YouTube downloader that lives in your terminal. Run it bare
and it opens a focused, keyboard-first Textual workbench: choose a
destination, paste a link, review what yt4k understood, and download.

## Install

Requires **Python 3.10+**, [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), and
`ffmpeg`. The installer also installs [Textual](https://textual.textualize.io/),
which powers the interactive workbench.

```bash
git clone https://github.com/PurvarajG/yt4k.git
cd yt4k
./install.sh
```

The installer:
- installs `yt-dlp` and `ffmpeg` (via Homebrew on macOS, via pip + your
  package manager on Linux) if they're missing
- adds a `yt4k` launcher to `~/.local/bin` that runs `yt4k.py` straight out
  of this folder — so keep the folder where it is, and `git pull` alone is
  enough to update
- removes `~/yt4k.py` if an older install left that copy behind

If `~/.local/bin` isn't already on your `PATH`, the installer tells you the
line to add to your shell rc file.

Re-run `./install.sh` only if you move the folder or the launcher goes
missing; updates themselves need nothing but `git pull`.

## Use

```bash
yt4k                       # interactive Textual workbench
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
yt4k URL 12:00 to the end              # …and 'start to 4:05' for the opening
yt4k URL first 30s in 1080p mp4
yt4k URL just the audio as mp3 320k
yt4k URL from 12:00 h265 small file    # 12:00 to the end, re-encoded
yt4k URL 1:20-3:45 --explain           # show what it understood, download nothing
```

**Time ranges** — `2:10 to 4:05`, `2:10-4:05`, `1h02m to 1h05m30s`,
`first 30s`, `last 90s`, or bare seconds (`90 to 225`). Either edge can be a
word instead of a number: `2:10 to the end`, `from 12:00`, `start to 4:05`,
`beginning to 3:00`, `until 0:45`. Clips are fetched with yt-dlp's `--download-sections`, so only
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

Whatever it read back is shown on the review screen before anything
downloads, so a misread is one keypress from being fixed.

### Inside the workbench

Every interactive session opens on the **destination screen** — it's always
first, and it's the one thing yt4k always asks before doing anything else.
Your saved default is highlighted; `enter` uses it for this session, `d` on
any folder (default, a recent one, or a path you type or paste) also makes it
the new default, and `esc` leaves yt4k since no destination was chosen yet.

From there you land on the **home screen**, with the request box focused and
your destination and current format visible above it. Paste one or more
space-separated links, optionally followed by a time range or format words,
and press enter. Every valid request opens the **review screen** — title,
destination, quality/format, clip range, and anything it read from your
words, with `Download` focused. Arrow keys move between fields, `enter`
cycles a field's value or confirms `Download`, and `esc` goes back to home
with your request preserved.

Confirming opens the **download screen**: stage, progress, size, speed, and
ETA for the active file (and batch position for more than one). `ctrl+c`
cancels — press it again during cleanup to force an exit. When it's done you
get one obvious action back to home, plus retry / edit-settings on failure.

| key | where | does |
|---|---|---|
| `enter` | destination | use the highlighted folder for this session |
| `d` | destination | use it, and make it the new default |
| `f` | home | change where this session saves |
| `s` | home | settings — resolution, codec, audio format |
| `?` | home | help — searchable keys and request syntax |
| `←→` / `enter` | review | change a field / confirm `Download` |
| `ctrl+c` | download | cancel (again to force-exit during cleanup) |
| `esc` | any screen | back, or quit from destination/home |

### Where things land

The destination screen asks where to save on every interactive session,
because the folder you wanted last week is rarely the one you want today.
`d` on any folder makes it the new default; `esc` (only from that screen)
leaves without picking one.

Downloads go to `~/Downloads/YouTube 4K` until you change that, and settings
persist in `~/.config/yt4k/config.json`.

Press `f` from home to point the current session somewhere else — a shoot
folder, an external drive, a project directory. The picker lists your default
plus the last few folders you used; `enter` uses one for this session only,
`d` also makes it the new default. `yt4k URL -o ~/Desktop/clips` does the
same for a one-shot run. Either way the saved default is left alone unless
you ask for it, so a one-off destination can't quietly become permanent.

## Moving to another machine

Clone this repo on the new machine and run `./install.sh` — that's it. Your
settings and downloads are per-machine (not synced by this repo); the
installer only needs this folder to set things up fresh.
