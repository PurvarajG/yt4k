import pytest

from fetch4k import pinterest
from fetch4k.models import Fetch4kError


def _payload(**data):
    return {"resource_response": {"data": data}}


@pytest.mark.parametrize("url, expected", [
    ("https://www.pinterest.com/pin/123/", True),
    ("https://in.pinterest.com/pin/123/", True),
    ("https://pinterest.co.uk/pin/123/", True),
    ("https://pin.it/abc", True),
    ("https://www.youtube.com/watch?v=x", False),
    ("https://notpinterest.com/pin/1/", False),
])
def test_is_pinterest(url, expected):
    assert pinterest.is_pinterest(url) is expected


def test_pin_id_handles_slugged_urls():
    assert pinterest.pin_id("https://www.pinterest.com/pin/some-title--998877/") == "998877"


def test_image_pin_returns_original_image():
    info = pinterest.pin_info("https://www.pinterest.com/pin/42/", fetch=lambda _: _payload(
        title="Sunset", images={"236x": {"url": "small.jpg", "width": 236},
                                "orig": {"url": "https://i.pinimg.com/originals/a.jpg"}}))
    assert info["title"] == "Sunset"
    assert not info["is_video"]
    assert info[pinterest.IMAGES_KEY] == ["https://i.pinimg.com/originals/a.jpg"]


def test_carousel_pin_returns_every_slot():
    info = pinterest.pin_info("https://www.pinterest.com/pin/42/", fetch=lambda _: _payload(
        carousel_data={"carousel_slots": [
            {"images": {"orig": {"url": "one.jpg"}}},
            {"images": {"736x": {"url": "two.jpg", "width": 736}}},
        ]}))
    assert info[pinterest.IMAGES_KEY] == ["one.jpg", "two.jpg"]
    assert info["title"] == "pinterest 42"


def test_video_pin_is_left_for_ytdlp():
    info = pinterest.pin_info("https://www.pinterest.com/pin/42/", fetch=lambda _: _payload(
        title="Clip", videos={"video_list": {}}, images={"orig": {"url": "poster.jpg"}}))
    assert info["is_video"]
    assert pinterest.IMAGES_KEY not in info


def test_missing_pin_raises_friendly_error():
    with pytest.raises(Fetch4kError):
        pinterest.pin_info("https://www.pinterest.com/pin/42/",
                           fetch=lambda _: {"resource_response": {"data": None}})
