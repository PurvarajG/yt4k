from __future__ import annotations

from fetch4k.models import Settings, Fetch4kError
from fetch4k.parsing import Clip
from fetch4k.playlists import URLKind, classify_url, expand_playlist, resolve_source_items, safe_playlist_name
from fetch4k.planning import build_job_plan


def test_classify_pure_playlist_and_mixed_watch_urls():
    assert classify_url("https://www.youtube.com/playlist?list=PL123") is URLKind.PLAYLIST
    assert classify_url("https://www.youtube.com/watch?v=abc&list=PL123") is URLKind.AMBIGUOUS
    assert classify_url("https://youtu.be/abc?list=PL123") is URLKind.AMBIGUOUS
    assert classify_url("https://www.youtube.com/watch?v=abc") is URLKind.VIDEO


def test_expand_playlist_preserves_missing_entries_and_canonicalizes_ids():
    expansion = expand_playlist("https://youtube.com/playlist?list=PL123", {
        "title": "My / Playlist",
        "entries": [
            {"id": "first", "title": "First", "duration": 12},
            None,
            {"url": "second", "title": "Second", "duration": None},
        ],
    })

    assert expansion.title == "My / Playlist"
    assert [item.playlist_position for item in expansion.items] == [1, 2, 3]
    assert expansion.items[0].url == "https://www.youtube.com/watch?v=first"
    assert expansion.items[1].preflight_error == "Unavailable, private, or deleted playlist item"
    assert expansion.items[2].url == "https://www.youtube.com/watch?v=second"
    assert all(item.playlist_folder == "My Playlist [PL123]" for item in expansion.items)


def test_safe_playlist_name_cannot_be_empty_or_a_path_component():
    assert safe_playlist_name(" ../../ ") == "Playlist"
    assert safe_playlist_name('A:/bad\\name?*') == "A bad name"
    assert not safe_playlist_name("x" * 119 + ". ").endswith((".", " "))
    assert len(safe_playlist_name("日" * 100).encode("utf-8")) <= 120


def test_expand_playlist_uses_known_unavailable_entries_and_strips_list_scope():
    expansion = expand_playlist("https://youtube.com/playlist?list=PL123", {
        "title": "Playlist", "playlist_count": 12,
        "entries": [
            {"id": "private", "title": "Private", "availability": "private", "playlist_index": 7},
            {"id": "public", "title": "Public", "url": "https://youtube.com/watch?v=public&list=PL123", "playlist_index": 8},
        ],
    })

    assert expansion.items[0].preflight_kind == "unavailable"
    assert expansion.items[0].playlist_position == 7
    assert expansion.items[1].url == "https://www.youtube.com/watch?v=public"
    assert expansion.items[1].output_prefix == "008 - "


def test_public_title_mentioning_deleted_video_remains_downloadable():
    expansion = expand_playlist("https://youtube.com/playlist?list=PL123", {
        "title": "Playlist", "entries": [
            {"id": "public", "title": "How to recover a deleted video", "availability": "public"},
        ],
    })

    assert expansion.items[0].preflight_error is None


def test_resolve_source_items_expands_only_selected_ambiguous_playlist_and_refreshes_tail_duration(tmp_path):
    class Runner:
        def video_info(self, url):
            return {"title": "video", "duration": 90 if url.endswith("one") else 120}

        def playlist_info(self, url):
            return {"id": "PL", "title": "List", "entries": [
                {"id": "one", "title": "one", "duration": None},
                {"id": "two", "title": "two", "duration": 120},
            ]}

    items = resolve_source_items(
        ("https://youtube.com/watch?v=chosen&list=PL", "https://youtube.com/playlist?list=PL"),
        Runner(), (URLKind.VIDEO, URLKind.PLAYLIST), Clip(tail=30),
    )
    plan = build_job_plan((), tmp_path, Settings(), Clip(tail=30), (), (), items=items)

    assert len(plan.items) == 3
    assert plan.items[0].url.endswith("list=PL")
    assert plan.items[1].metadata.duration == 90
    assert not any(item.preflight_error for item in plan.items)


def test_resolve_source_items_rejects_unselected_ambiguous_url():
    class Runner:
        pass

    try:
        resolve_source_items(("https://youtube.com/watch?v=chosen&list=PL",), Runner(), (), None)
    except Fetch4kError as error:
        assert "--video or --playlist" in str(error)
    else:
        raise AssertionError("ambiguous URLs need an explicit scope")


def test_duplicate_playlist_sources_receive_distinct_output_folders():
    class Runner:
        def playlist_info(self, url):
            return {"id": "PL123", "title": "List", "entries": [{"id": "one", "title": "one"}]}

    items = resolve_source_items(
        ("https://youtube.com/playlist?list=PL123", "https://youtube.com/playlist?list=PL123"),
        Runner(), (URLKind.PLAYLIST, URLKind.PLAYLIST), None,
    )

    assert [item.playlist_folder for item in items] == ["List [PL123]", "List [PL123] (2)"]
