# yt4k

An interactive YouTube (and Pinterest) downloader that lives in your terminal. Run it bare
and it opens a focused, keyboard-first Textual workbench: choose a
destination, paste a link, review what yt4k understood, and download.

## Install

One command on a fresh Mac or Linux machine. You don't need Python,
Homebrew, ffmpeg, or anything else installed first; only `git`:

```bash
git clone https://github.com/PurvarajG/yt4k.git && cd yt4k && ./install.sh
```

Then open a new terminal and run `yt4k`.

> On a brand-new Mac, the first `git` command may pop up "install command line
> developer tools". Click **Install**, wait for it to finish, and run the line
> again.

What `install.sh` does for you:

- **Python**: uses your Python if it's 3.10 or newer. If not, it downloads a
  private Python 3.12 with [uv](https://docs.astral.sh/uv/) into
  `~/.local`. No admin password, no Homebrew, and your system Python stays
  untouched.
- **Everything yt4k needs**: [Textual](https://textual.textualize.io/),
  [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), static `ffmpeg`/`ffprobe`,
  and [Deno](https://deno.com/) (the JavaScript runtime yt-dlp uses to get
  past YouTube's signature check; without it downloads fail with a 403).
  All of it goes into a dedicated venv at `~/.local/share/yt4k/venv`, so it
  never fights your system, Homebrew, or conda Python. If you already have
  `ffmpeg` installed, yt4k uses yours instead of the bundled copy.
- **The `yt4k` command**: a launcher in `~/.local/bin` that runs `yt4k.py`
  straight out of this folder (so keep the folder where it is). If
  `~/.local/bin` isn't on your `PATH`, it adds it to your shell rc file
  (`~/.zshrc`, `~/.bash_profile`/`~/.bashrc`, or `~/.profile`) once.
- It also removes `~/yt4k.py` if an older install left that copy behind.

Running `./install.sh` again is always safe; it repairs or refreshes whatever
is missing.

To update:

```bash
git pull && ./install.sh
```

`git pull` alone updates yt4k itself; re-running `./install.sh` also refreshes
the bundled `yt-dlp`.

You shouldn't often need that second part. YouTube changes how it serves video
every few weeks, and an out-of-date `yt-dlp` is the usual reason downloads
suddenly start failing, so yt4k keeps its own copy current: it checks once a
day in the background, and if a download fails in a way that looks like YouTube
outrunning `yt-dlp` (a 403, a failed signature challenge), it updates on the
spot and retries. To force it:

```bash
yt4k --update
```

This only ever touches yt4k's own venv - a `yt-dlp` you installed through
Homebrew, apt, or pipx is left alone.

## Use

```bash
yt4k                       # interactive Textual workbench
yt4k URL                   # one-shot, uses your saved settings
yt4k URL --res 1080 --codec h264
yt4k URL --audio wav
yt4k PLAYLIST_URL              # downloads each playlist entry in order
yt4k WATCH_URL?list=PLAYLIST --playlist
yt4k PINTEREST_PIN_URL      # a pin's video, or its original image(s)
yt4k URL -v                # raw yt-dlp / ffmpeg firehose
yt4k --update              # refresh yt-dlp now (also happens daily)
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

### Playlists

Paste a YouTube playlist URL in the workbench or pass it to `yt4k`; every
available entry becomes its own job and uses the same quality, audio, clip,
and conversion settings. The review screen shows the playlist title, entry
count, and any entries yt-dlp already knows are unavailable. One failed,
private, or deleted item does not stop the others.

A link that includes both a video and `list=` needs an explicit scope. The
workbench asks for each such link. In a one-shot command, pass `--video` for
that video alone or `--playlist` for the whole list; yt4k refuses to guess.

Playlist files land in a safe folder under your selected destination, named
after the playlist plus its stable list ID. Names begin with their original
playlist position (`001 - …`), even when jobs finish out of order. Retrying
from the workbench runs only failed or cancelled entries. `last 90s` and other
end-relative clips may read an entry's full metadata when flat playlist data
does not include its duration; if that lookup fails, only that entry fails.

### Pinterest

Paste any pin link: `pinterest.com/pin/…`, a regional domain like
`in.pinterest.com`, or a `pin.it/…` short link. yt4k reads the pin first and
picks the right path:

- **Video pins** go through yt-dlp like any other video, so resolution,
  codec, audio-only, and clip ranges all apply.
- **Image pins** are saved as the original full-resolution file, straight
  from Pinterest, with no re-encoding. A carousel pin saves every image,
  numbered `Title (1).jpg`, `Title (2).jpg`, and so on. Format words and clip
  ranges don't apply to images.

Image pins rely on Pinterest's internal pin data, which isn't a public API.
If Pinterest changes it, the pin fails with a clear error and everything
else keeps working.

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

Run the one-line install above on the new machine. That's it. Your
settings and downloads are per-machine (not synced by this repo); the
installer only needs this folder to set things up fresh.
