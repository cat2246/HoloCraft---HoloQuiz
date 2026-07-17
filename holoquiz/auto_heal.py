from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from holoquiz.config import AutoHealItemConfig
from holoquiz.player import PlayerSnapshot, build_inventory_layout


@dataclass(frozen=True)
class AutoHealSelection:
    hotbar_slot: int
    item_name: str
    rule: AutoHealItemConfig


def auto_heal_threshold_met(
    snapshot: PlayerSnapshot,
    rule: AutoHealItemConfig,
) -> bool:
    return (
        rule.health_below > 0
        and snapshot.health.current < rule.health_below
    ) or (
        rule.hunger_below > 0
        and snapshot.hunger.food_level < rule.hunger_below
    )


def select_auto_heal_item(
    snapshot: PlayerSnapshot,
    rules: Sequence[AutoHealItemConfig],
    last_used_at: Mapping[str, float],
    now: float,
) -> AutoHealSelection | None:
    by_name = {rule.name: rule for rule in rules}
    hotbar = build_inventory_layout(snapshot.inventory).hotbar
    for slot in reversed(hotbar):
        if slot.item.empty:
            continue
        rule = by_name.get(slot.item.name)
        if rule is None or not auto_heal_threshold_met(snapshot, rule):
            continue
        previous = last_used_at.get(rule.name)
        if previous is not None and now - previous < rule.cooldown_seconds:
            continue
        return AutoHealSelection(
            hotbar_slot=slot.inventory_slot,
            item_name=slot.item.name,
            rule=rule,
        )
    return None
