import json
from io import BytesIO
import threading

import pytest
from PIL import Image

from holoquiz.player import (
    ItemIconClient,
    PlayerOverviewClient,
    build_inventory_layout,
    build_item_icon_url,
    format_item_tooltip,
    parse_player_payload,
)


def player_payload():
    return {
        "api_version": 1,
        "timestamp_ms": 1784275921866,
        "connected": True,
        "health": {"current": 33.5, "max": 42.5, "absorption": 0.0},
        "armor": 12,
        "hunger": {"food_level": 20, "saturation": 9.8},
        "level": {
            "experience_level": 180,
            "experience_progress": 0.44938433,
            "total_experience": 17275121,
        },
        "position": {"x": 9.0, "y": 76.0, "z": 35.0},
        "facing_direction": "north",
        "inventory": [
            {
                "inventory_slot": 0,
                "section": "hotbar",
                "item": {
                    "empty": False,
                    "id": "minecraft:iron_sword",
                    "name": "Merumeru",
                    "count": 1,
                    "max_stack_size": 1,
                    "damage": 10,
                    "max_damage": 250,
                    "is_enchanted": True,
                },
            },
            {
                "inventory_slot": 39,
                "section": "armor",
                "item": {
                    "empty": False,
                    "id": "minecraft:netherite_helmet",
                    "name": "Kijin Helmet",
                    "count": 1,
                    "max_stack_size": 1,
                    "damage": 156,
                    "max_damage": 407,
                    "is_enchanted": True,
                },
            },
            {
                "inventory_slot": 41,
                "section": "offhand",
                "item": {"empty": False, "id": "minecraft:diamond", "name": "Extra", "count": 2},
            },
            {
                "inventory_slot": 42,
                "section": "offhand",
                "item": {"empty": True},
            },
        ],
    }


def test_parse_player_payload_reads_vitals_and_items():
    snapshot = parse_player_payload(player_payload())

    assert snapshot.connected is True
    assert snapshot.health.current == 33.5
    assert snapshot.health.maximum == 42.5
    assert snapshot.hunger.food_level == 20
    assert snapshot.level.experience_level == 180
    assert snapshot.location.x == 9.0
    assert snapshot.facing_direction == "north"
    assert snapshot.inventory[0].item.item_id == "minecraft:iron_sword"
    assert snapshot.inventory[0].item.durability_remaining == 240


def test_build_inventory_layout_reorders_armor_and_preserves_occupied_extra_slots():
    layout = build_inventory_layout(parse_player_payload(player_payload()).inventory)

    assert [slot.inventory_slot for slot in layout.hotbar] == list(range(9))
    assert [slot.inventory_slot for slot in layout.main] == list(range(9, 36))
    assert [slot.inventory_slot for slot in layout.armor] == [39, 38, 37, 36]
    assert layout.offhand.inventory_slot == 40
    assert [slot.inventory_slot for slot in layout.extra] == [41]


def test_format_item_tooltip_uses_only_available_api_fields():
    slot = parse_player_payload(player_payload()).inventory[0]

    assert format_item_tooltip(slot) == (
        "Merumeru\n"
        "minecraft:iron_sword\n"
        "Count: 1\n"
        "Location: hotbar slot 0\n"
        "Durability: 240 / 250\n"
        "Maximum stack: 1\n"
        "Enchanted: Yes"
    )


def test_parse_player_payload_rejects_non_object_and_invalid_inventory():
    with pytest.raises(ValueError, match="JSON object"):
        parse_player_payload([])

    payload = player_payload()
    payload["inventory"] = "not-a-list"
    with pytest.raises(ValueError, match="inventory must be a list"):
        parse_player_payload(payload)


def test_parse_player_payload_keeps_recoverable_malformed_item_slot():
    payload = player_payload()
    payload["inventory"][0]["item"] = "corrupt-item"

    snapshot = parse_player_payload(payload)

    assert snapshot.inventory[0].inventory_slot == 0
    assert snapshot.inventory[0].item.empty is False
    assert snapshot.inventory[0].item.name == "Unreadable item"


class FakeResponse:
    def __init__(self, body, content_type="application/json"):
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, amount=None):
        if amount is None:
            return self.body
        return self.body[:amount]


def image_bytes(*, size=(64, 64), color="red", format="PNG"):
    stream = BytesIO()
    mode = "RGB" if format == "JPEG" else "RGBA"
    Image.new(mode, size, color).save(stream, format=format)
    return stream.getvalue()


def png_bytes(color="red"):
    return image_bytes(color=color)


def test_player_overview_client_uses_configured_url_and_timeout():
    requests = []

    def opener(url, *, timeout):
        requests.append((url, timeout))
        return FakeResponse(json.dumps(player_payload()))

    snapshot = PlayerOverviewClient(
        "http://127.0.0.1:8026/data/player",
        timeout_seconds=0.75,
        opener=opener,
    ).fetch()

    assert snapshot.armor == 12
    assert requests == [("http://127.0.0.1:8026/data/player", 0.75)]


def test_build_item_icon_url_preserves_namespaced_item_id():
    assert build_item_icon_url("minecraft:iron_sword") == (
        "https://blocksitems.com/api/v1/items/minecraft:iron_sword/icon?size=64"
    )


def test_item_icon_client_downloads_each_item_once():
    requests = []

    def opener(url, *, timeout):
        requests.append((url, timeout))
        return FakeResponse(png_bytes(), "image/png")

    client = ItemIconClient(opener=opener)

    assert client.get_icon("minecraft:diamond") == png_bytes()
    assert client.get_icon("minecraft:diamond") == png_bytes()
    assert len(requests) == 1


def test_item_icon_client_returns_cached_fallback_for_invalid_image():
    requests = []

    def opener(url, *, timeout):
        requests.append(url)
        return FakeResponse(b"not-an-image", "text/plain")

    client = ItemIconClient(opener=opener)
    first = client.get_icon("minecraft:missing")
    second = client.get_icon("minecraft:missing")

    with Image.open(BytesIO(first)) as image:
        assert image.size == (64, 64)
    assert second == first
    assert requests == [
        "https://blocksitems.com/api/v1/items/minecraft:missing/icon?size=64"
    ]


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        pytest.param(b"not-a-png", "image/png", id="invalid-png"),
        pytest.param(image_bytes(format="JPEG"), "image/jpeg", id="non-png"),
        pytest.param(
            image_bytes(size=(32, 64)),
            "image/png",
            id="wrong-dimensions",
        ),
    ],
)
def test_item_icon_client_caches_fallback_for_invalid_icon_boundary(
    body,
    content_type,
):
    requests = []

    def opener(url, *, timeout):
        requests.append(url)
        return FakeResponse(body, content_type)

    client = ItemIconClient(opener=opener)

    assert client.get_icon("minecraft:invalid") == client.fallback_icon
    assert client.get_icon("minecraft:invalid") == client.fallback_icon
    assert len(requests) == 1


def test_item_icon_client_rejects_oversized_response_before_decode():
    requests = []

    def opener(url, *, timeout):
        requests.append(url)
        return FakeResponse(png_bytes(), "image/png")

    client = ItemIconClient(opener=opener, max_response_bytes=32)

    assert client.get_icon("minecraft:oversized") == client.fallback_icon
    assert client.get_icon("minecraft:oversized") == client.fallback_icon
    assert len(requests) == 1


def test_item_icon_client_deduplicates_concurrent_cache_misses():
    requests = []
    request_started = threading.Event()
    release_request = threading.Event()

    def opener(url, *, timeout):
        requests.append(url)
        request_started.set()
        assert release_request.wait(timeout=1)
        return FakeResponse(png_bytes(), "image/png")

    client = ItemIconClient(opener=opener)
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(client.get_icon("minecraft:diamond"))
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    assert request_started.wait(timeout=1)
    release_request.set()
    for thread in threads:
        thread.join(timeout=1)

    assert len(results) == 2
    assert results[0] == results[1] == png_bytes()
    assert len(requests) == 1
