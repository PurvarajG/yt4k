<div align="center">

# ⚡ fetch4k

**Paste a link. Get the file.**<br>
A keyboard-first video downloader that lives in your terminal.

YouTube · Instagram · TikTok · X · Reddit · Vimeo · Twitch · SoundCloud · Pinterest · *and over a thousand more*

![macOS](https://img.shields.io/badge/macOS-000000?style=flat-square&logo=apple&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-FCC624?style=flat-square&logo=linux&logoColor=black)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Built on yt-dlp](https://img.shields.io/badge/built%20on-yt--dlp-red?style=flat-square)
![Textual](https://img.shields.io/badge/UI-Textual-5a4fcf?style=flat-square)

</div>

```text
$ fetch4k https://youtu.be/dQw4w9WgXcQ 1:20 to 3:45 in 1080p mp4

 REVIEW
 1 link   Rick Astley - Never Gonna Give You Up
 ~/Downloads/fetch4k
 FROM YOUR REQUEST   1080p  mp4

   format         video
   quality        1080p
   encoding       keep source (no re-encode)
   container      mp4
   clip           01:20 → 03:45
 ▸ Download
```

---

## ✨ Why fetch4k

|  |  |
|---|---|
| 🎬 **Up to 4K, no quality loss** | Grabs the best streams the site has and keeps them as they are. Re-encoding only happens if you ask for it. |
| 🗣️ **Just say what you want** | `first 30s`, `just the audio as mp3`, `12:00 to the end in 720p`. Plain English after the link. |
| ✂️ **Clip before you download** | Only the part you asked for is downloaded, and it's cut at the exact timestamps. |
| 🎯 **Only options that apply** | A 1080p TikTok won't offer 4K, and an image pin skips the video settings entirely. |
| 📚 **Whole YouTube playlists** | Every video becomes its own job, numbered in order, and one broken video doesn't stop the rest. |
| 🖼️ **Pinterest images too** | Image pins and carousels are saved as the full-size originals. |
| 🔄 **Keeps itself working** | It updates yt-dlp every day, and again on the spot if a site starts blocking downloads. |
| 🧼 **Zero setup** | One command installs everything into its own folder. No Homebrew, no admin password. |

---

## 🚀 Install

You only need `git`. The installer takes care of everything else.

```bash
git clone https://github.com/PurvarajG/yt4k.git fetch4k && cd fetch4k && ./install.sh
```

Open a new terminal and run **`fetch4k`**.

> [!TIP]
> On a brand-new Mac, `git` may ask to install the *command line developer tools*. Click **Install**, wait, then run the line again.

**Update** at any time from inside the folder:

```bash
git pull && ./install.sh
```

<details>
<summary><b>What does <code>install.sh</code> actually do?</b></summary>

<br>

- **Python.** Uses yours if it's 3.10 or newer. If not, it downloads a private Python 3.12 into `~/.local` with [uv](https://docs.astral.sh/uv/). It doesn't need `sudo` and doesn't touch your system Python.
- **Dependencies.** Installs [Textual](https://textual.textualize.io/), [yt-dlp](https://github.com/yt-dlp/yt-dlp), static `ffmpeg`/`ffprobe`, and [Deno](https://deno.com/) into a dedicated venv at `~/.local/share/fetch4k/venv`. yt-dlp needs Deno for YouTube's signature check; without it, downloads fail with a 403. If you already have `ffmpeg` installed, fetch4k uses yours.
- **The command.** Puts a `fetch4k` launcher in `~/.local/bin` and adds that folder to your shell's `PATH` once. The launcher runs the code straight from the cloned folder, so leave the folder where it is.
- **Safe to re-run.** Running it again repairs or refreshes anything that's missing.

</details>

<details>
<summary><b>Upgrading from yt4k?</b></summary>

<br>

fetch4k used to be called **yt4k**. Run `git pull && ./install.sh` once. It moves your settings to `~/.config/fetch4k`, removes the old `yt4k` command and venv, and installs `fetch4k` in their place.

</details>

---

## 🎮 Use

```bash
fetch4k                          # open the interactive workbench
fetch4k URL                      # one-shot download with your saved settings
fetch4k URL --res 1080 --codec h264
fetch4k URL --audio wav
fetch4k PLAYLIST_URL             # every entry, in order
fetch4k URL -o ~/Desktop/clips   # save somewhere else, just this once
fetch4k URL --explain            # show what it understood, download nothing
fetch4k --update                 # refresh yt-dlp now
```

### 🗣️ Say it in plain English

Anything after the link describes the download you want. This works on the command line and in the workbench's paste box.

```bash
fetch4k URL 2:10 to 4:05                  # just that slice
fetch4k URL first 30s in 1080p mp4
fetch4k URL last 90s
fetch4k URL just the audio as mp3 320k
fetch4k URL from 12:00 h265 small file    # 12:00 to the end, re-encoded small
```

| You can say… | Examples |
|---|---|
| **Time ranges** | `2:10 to 4:05` · `2:10-4:05` · `1h02m to 1h05m30s` · `first 30s` · `last 90s` · `from 12:00` · `start to 4:05` · `2:10 to the end` |
| **Resolution** | `4k` · `1440p` · `1080p` · `720p` · `480p` · `best quality` |
| **Codec** | `av1` · `vp9` · `h264` · `h265` / `hevc` · `keep source` · `convert to h264` |
| **Container** | `mp4` · `mkv` |
| **Audio** | `just the audio` · `mp3` · `wav` · `flac` · `m4a` · `opus` · `320k` |
| **Shorthands** | `fast` · `smaller file` · `high quality` |

A bare `h264` picks the H.264 version the site already has. Saying `convert to h264` forces a re-encode. Flags always win over words, and the review screen shows exactly what fetch4k understood before anything downloads.

---

## 🌍 Supported sites

fetch4k handles any link [yt-dlp supports](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md). Some common ones:

| Social | Video | Audio | Other |
|---|---|---|---|
| Instagram | YouTube | SoundCloud | TED |
| TikTok | Vimeo | Bandcamp | Internet Archive |
| X / Twitter | Twitch | Mixcloud | BBC, CNN |
| Reddit | Dailymotion |  | Loom |
| Facebook | Bilibili |  | Pinterest 🖼️ |

> [!NOTE]
> - Playlists and channels expand into separate downloads only on **YouTube**. Links from other sites download as a single video.
> - fetch4k doesn't sign in anywhere, so **private accounts and members-only posts** won't work.
> - **DRM services** such as Netflix, Disney+ and Spotify are never supported.

<details>
<summary><b>📚 Playlists</b></summary>

<br>

Paste a YouTube playlist link and every available video becomes its own job, using the same quality, clip and format settings. The review screen shows the playlist name, how many videos it has, and any that are already known to be unavailable. A private or deleted video fails on its own and the rest keep going.

Files go into a folder named after the playlist and numbered in playlist order (`001 - …`), even when downloads finish out of order. **Retry** only re-runs the videos that failed.

If a link has both a video and a `list=` in it, the workbench asks which one you mean. For a one-shot download, add `--video` or `--playlist`.

</details>

<details>
<summary><b>🖼️ Pinterest</b></summary>

<br>

Works with `pinterest.com/pin/…` links, regional domains such as `in.pinterest.com`, and `pin.it/…` short links.

- **Video pins** download like any other video, so every quality, codec, audio and clip option applies.
- **Image pins** are saved as the original full-size file. A carousel saves every image as `Title (1).jpg`, `Title (2).jpg` and so on. The review screen just shows `image · original file`, because there's nothing to configure.

Image pins rely on Pinterest's internal pin data, which isn't a public API. If Pinterest changes it, you'll get a clear error and everything else keeps working.

</details>

---

## ⌨️ The workbench

Run `fetch4k` on its own and you get four screens:

```text
 Destination  ─▶  Home  ─▶  Review  ─▶  Download
 where to save    paste     check it     progress, speed, ETA
```

1. **Destination.** Always asked first. Pick a folder for this session, or press `d` to make it your new default.
2. **Home.** Paste one or more links, add plain-English extras if you like, and press `enter`.
3. **Review.** Shows the title, destination, format, quality and clip range. Change any field with the arrow keys, then press `enter` on **Download**.
4. **Download.** Shows live progress. When it finishes you can go home, retry what failed, or change settings.

| Key | Where | Does |
|:---:|---|---|
| `enter` | destination | use this folder for this session |
| `d` | destination | use it **and** make it the default |
| `f` | home | change where this session saves |
| `s` | home | settings: resolution, codec, audio |
| `?` | home | searchable help |
| `← →` | review | change the highlighted field |
| `ctrl+c` | download | cancel (press again to force quit) |
| `esc` | anywhere | back, or quit |

---

## 📁 Where things go

| What | Where |
|---|---|
| Downloads | `~/Downloads/fetch4k` (change it with `d` on the destination screen, or `-o` for one run) |
| Settings | `~/.config/fetch4k/config.json` |
| Dependencies | `~/.local/share/fetch4k/venv` |

Choosing a folder for one session never changes your saved default unless you press `d`.

---

## 🛠️ Troubleshooting

<details>
<summary><b>Downloads suddenly fail with 403 or a "signature" error</b></summary>

<br>

YouTube changes how it serves video every few weeks. fetch4k checks for a new yt-dlp once a day, and when a failure looks like this it updates and retries on the spot. To force an update yourself:

```bash
fetch4k --update
```

This only updates fetch4k's own copy. A yt-dlp you installed with Homebrew, apt or pipx is left alone.

</details>

<details>
<summary><b><code>fetch4k: command not found</code></b></summary>

<br>

Open a **new** terminal window after installing. If it's still missing, go into the folder you cloned and run `./install.sh` again.

</details>

<details>
<summary><b>Moving to a new machine</b></summary>

<br>

Run the install line on the new machine. Settings and downloads stay on each machine; nothing is synced.

</details>

---

<div align="center">
<sub>Built on <a href="https://github.com/yt-dlp/yt-dlp">yt-dlp</a>, <a href="https://ffmpeg.org">FFmpeg</a> and <a href="https://textual.textualize.io">Textual</a>. Only download content you have the right to.</sub>
</div>
