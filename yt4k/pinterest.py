"""Read Pinterest pins natively, so image pins download too.

yt-dlp handles video pins but gives up on image pins ("No video formats
found"). Pinterest's own pin resource answers both, so we ask it first: a
video pin goes on to yt-dlp as usual, an image pin (or carousel) is fetched
straight from i.pinimg.com at its original resolution.
"""

from __future__ import annotations

import json
import re
import shutil
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .models import Yt4kError

IMAGES_KEY = "_yt4k_images"

_HOST_RE = re.compile(r"(?:^|\.)(?:pinterest\.[a-z.]+|pin\.it)$", re.I)
_PIN_ID_RE = re.compile(r"/pin/(?:[^/]*--)?(\d+)")
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"),
    "X-Pinterest-PWS-Handler": "www/[username].js",
}
_TIMEOUT = 20


def is_pinterest(url: str) -> bool:
    return bool(_HOST_RE.search(urllib.parse.urlparse(url).netloc.split(":")[0]))


def _open(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers=_HEADERS),
                                  timeout=_TIMEOUT)


@lru_cache(maxsize=256)
def pin_id(url: str) -> str:
    """The numeric pin id, following pin.it short links to find it."""
    m = _PIN_ID_RE.search(urllib.parse.urlparse(url).path)
    if not m:
        try:
            with _open(url) as resp:
                m = _PIN_ID_RE.search(urllib.parse.urlparse(resp.geturl()).path)
        except OSError as error:
            raise Yt4kError(f"could not open Pinterest link: {error}") from error
    if not m:
        raise Yt4kError("that Pinterest link doesn't point at a pin")
    return m.group(1)


def canonical_url(url: str) -> str:
    return f"https://www.pinterest.com/pin/{pin_id(url)}/"


def _images_of(data: dict) -> list[str]:
    """Original-size image URLs, one per carousel slot (or the single image)."""
    slots = ((data.get("carousel_data") or {}).get("carousel_slots") or [])
    urls = []
    for slot in slots:
        best = _best_image(slot.get("images") or {})
        if best:
            urls.append(best)
    if not urls:
        best = _best_image(data.get("images") or {})
        if best:
            urls.append(best)
    return urls


def _best_image(images: dict) -> str | None:
    if (images.get("orig") or {}).get("url"):
        return images["orig"]["url"]
    sized = [v for v in images.values() if isinstance(v, dict) and v.get("url")]
    return max(sized, key=lambda v: v.get("width") or 0)["url"] if sized else None


def _has_video(data: dict) -> bool:
    if data.get("videos"):
        return True
    story = data.get("story_pin_data") or {}
    return any(block.get("video") for page in story.get("pages") or []
               for block in page.get("blocks") or [])


def pin_info(url: str, fetch: Callable[[str], dict] | None = None) -> dict:
    """Metadata for a pin. Image pins carry their image URLs under IMAGES_KEY;
    video pins come back with `is_video` set, to be handed to yt-dlp."""
    pid = pin_id(url)
    query = json.dumps({"options": {"field_set_key": "unauth_react_main_pin",
                                    "id": pid}})
    api = ("https://www.pinterest.com/resource/PinResource/get/?data="
           + urllib.parse.quote(query))
    try:
        if fetch:
            payload = fetch(api)
        else:
            with _open(api) as resp:
                payload = json.load(resp)
        data = payload["resource_response"]["data"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Yt4kError("could not read that pin (deleted, private, or "
                        "Pinterest changed its API)") from error
    if not isinstance(data, dict):
        raise Yt4kError("could not read that pin (deleted or private)")

    title = (data.get("title") or data.get("grid_title")
             or (data.get("description") or "").strip()[:80]
             or f"pinterest {pid}")
    pinner = data.get("pinner") or {}
    info = {"id": pid, "title": title.strip(), "duration": None,
            "uploader": pinner.get("full_name") or pinner.get("username"),
            "webpage_url": f"https://www.pinterest.com/pin/{pid}/",
            "is_video": _has_video(data)}
    if not info["is_video"]:
        images = _images_of(data)
        if not images:
            raise Yt4kError("that pin has no image or video to download")
        info[IMAGES_KEY] = images
    return info


def download_images(urls: list[str], dst_stem: Path,
                    unique: Callable[[Path], Path]) -> list[Path]:
    """Save each image next to `dst_stem`, numbering carousel slots."""
    saved = []
    for n, img in enumerate(urls, start=1):
        ext = Path(urllib.parse.urlparse(img).path).suffix or ".jpg"
        suffix = f" ({n})" if len(urls) > 1 else ""
        dst = unique(dst_stem.with_name(f"{dst_stem.name}{suffix}{ext}"))
        tmp = dst.with_name(dst.name + ".part")
        try:
            with _open(img) as resp, open(tmp, "wb") as fh:
                shutil.copyfileobj(resp, fh)
            tmp.replace(dst)
        except OSError as error:
            tmp.unlink(missing_ok=True)
            raise Yt4kError(f"could not download pin image: {error}") from error
        saved.append(dst)
    return saved
