import pytest

from holoquiz.player import (
    build_inventory_layout,
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
