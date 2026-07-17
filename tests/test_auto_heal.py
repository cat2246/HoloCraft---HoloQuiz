from holoquiz.auto_heal import (
    auto_heal_threshold_met,
    select_auto_heal_item,
)
from holoquiz.config import AutoHealItemConfig
from holoquiz.player import parse_player_payload


def player_snapshot(*, health, hunger, hotbar=None, main=None):
    inventory = []
    for slot, name in (hotbar or {}).items():
        inventory.append(
            {
                "inventory_slot": slot,
                "section": "hotbar",
                "item": {
                    "empty": False,
                    "id": "minecraft:test_item",
                    "name": name,
                    "count": 1,
                },
            }
        )
    for slot, name in (main or {}).items():
        inventory.append(
            {
                "inventory_slot": slot,
                "section": "main",
                "item": {
                    "empty": False,
                    "id": "minecraft:test_item",
                    "name": name,
                    "count": 1,
                },
            }
        )
    return parse_player_payload(
        {
            "api_version": 1,
            "timestamp_ms": 1,
            "connected": True,
            "health": {
                "current": health,
                "max": 20,
                "absorption": 0,
            },
            "hunger": {"food_level": hunger, "saturation": 0},
            "inventory": inventory,
        }
    )


def test_select_auto_heal_item_prioritizes_rightmost_hotbar_match():
    snapshot = player_snapshot(
        health=5,
        hunger=20,
        hotbar={7: "Steak", 8: "Potion"},
    )
    rules = (
        AutoHealItemConfig("Steak", 5, 2, 10, 0),
        AutoHealItemConfig("Potion", 5, 2, 10, 0),
    )

    selection = select_auto_heal_item(snapshot, rules, {}, now=100.0)

    assert selection is not None
    assert selection.hotbar_slot == 8
    assert selection.item_name == "Potion"


def test_select_auto_heal_item_skips_rightmost_item_on_cooldown():
    snapshot = player_snapshot(
        health=5,
        hunger=20,
        hotbar={7: "Steak", 8: "Potion"},
    )
    rules = (
        AutoHealItemConfig("Steak", 5, 2, 10, 0),
        AutoHealItemConfig("Potion", 30, 2, 10, 0),
    )

    selection = select_auto_heal_item(
        snapshot,
        rules,
        {"Potion": 90.0},
        now=100.0,
    )

    assert selection is not None
    assert selection.item_name == "Steak"


def test_auto_heal_thresholds_use_strict_or_semantics_and_zero_disables():
    rule = AutoHealItemConfig(
        "Steak",
        0,
        2,
        health_below=10,
        hunger_below=6,
    )

    assert auto_heal_threshold_met(
        player_snapshot(health=10, hunger=5),
        rule,
    )
    assert not auto_heal_threshold_met(
        player_snapshot(health=10, hunger=6),
        rule,
    )


def test_select_auto_heal_item_matches_exact_name_only():
    snapshot = player_snapshot(
        health=1,
        hunger=20,
        hotbar={8: "steak"},
    )
    rules = (AutoHealItemConfig("Steak", 0, 2, 10, 0),)

    assert select_auto_heal_item(snapshot, rules, {}, now=0) is None


def test_select_auto_heal_item_ignores_configured_match_outside_hotbar():
    snapshot = player_snapshot(
        health=1,
        hunger=20,
        main={35: "Steak"},
    )
    rules = (AutoHealItemConfig("Steak", 0, 2, 10, 0),)

    assert select_auto_heal_item(snapshot, rules, {}, now=0) is None


def test_select_auto_heal_item_skips_rule_without_crossed_threshold():
    snapshot = player_snapshot(
        health=20,
        hunger=20,
        hotbar={7: "Steak", 8: "Potion"},
    )
    rules = (
        AutoHealItemConfig("Steak", 0, 2, 21, 0),
        AutoHealItemConfig("Potion", 0, 2, 10, 0),
    )

    selection = select_auto_heal_item(snapshot, rules, {}, now=0)

    assert selection is not None
    assert selection.item_name == "Steak"
