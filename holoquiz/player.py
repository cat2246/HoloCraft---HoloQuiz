from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from threading import Lock
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import urlopen

from PIL import Image, ImageDraw, UnidentifiedImageError


ITEM_ICON_BASE_URL = "https://blocksitems.com/api/v1/items"
MINECRAFT_TARGET_VERSION = "1.21.10"


@dataclass(frozen=True)
class PlayerHealth:
    current: float = 0.0
    maximum: float = 0.0
    absorption: float = 0.0


@dataclass(frozen=True)
class PlayerHunger:
    food_level: int = 0
    saturation: float = 0.0


@dataclass(frozen=True)
class PlayerLevel:
    experience_level: int = 0
    experience_progress: float = 0.0
    total_experience: int = 0


@dataclass(frozen=True)
class PlayerLocation:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass(frozen=True)
class PlayerItem:
    empty: bool = True
    item_id: str = ""
    name: str = ""
    count: int = 0
    max_stack_size: int = 0
    damage: int = 0
    max_damage: int = 0
    is_enchanted: bool = False

    @property
    def durability_remaining(self) -> int | None:
        if self.max_damage <= 0:
            return None
        return max(self.max_damage - self.damage, 0)


@dataclass(frozen=True)
class InventorySlot:
    inventory_slot: int
    section: str
    item: PlayerItem = PlayerItem()


@dataclass(frozen=True)
class PlayerSnapshot:
    api_version: int
    timestamp_ms: int
    connected: bool
    health: PlayerHealth
    armor: int
    hunger: PlayerHunger
    level: PlayerLevel
    location: PlayerLocation
    facing_direction: str
    inventory: tuple[InventorySlot, ...]


@dataclass(frozen=True)
class InventoryLayout:
    hotbar: tuple[InventorySlot, ...]
    main: tuple[InventorySlot, ...]
    armor: tuple[InventorySlot, ...]
    offhand: InventorySlot
    extra: tuple[InventorySlot, ...]


def _mapping(value: object, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Player {field} must be a JSON object.")
    return value


def _float(mapping: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(mapping.get(key, default))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Player {key} must be numeric.") from error


def _int(mapping: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(mapping.get(key, default))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Player {key} must be an integer.") from error


def _parse_item(value: object) -> PlayerItem:
    data = _mapping(value, "inventory item")
    empty = bool(data.get("empty", True))
    if empty:
        return PlayerItem()
    return PlayerItem(
        empty=False,
        item_id=str(data.get("id", "")),
        name=str(data.get("name", data.get("id", "Unknown item"))),
        count=_int(data, "count"),
        max_stack_size=_int(data, "max_stack_size"),
        damage=_int(data, "damage"),
        max_damage=_int(data, "max_damage"),
        is_enchanted=bool(data.get("is_enchanted", False)),
    )


def parse_player_payload(payload: object) -> PlayerSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("Player endpoint must return a JSON object.")
    inventory_payload = payload.get("inventory", [])
    if not isinstance(inventory_payload, list):
        raise ValueError("Player inventory must be a list.")
    inventory = []
    for raw_slot in inventory_payload:
        slot_data = _mapping(raw_slot, "inventory slot")
        try:
            item = _parse_item(slot_data.get("item"))
        except ValueError:
            item = PlayerItem(empty=False, name="Unreadable item")
        inventory.append(
            InventorySlot(
                inventory_slot=_int(slot_data, "inventory_slot"),
                section=str(slot_data.get("section", "unknown")),
                item=item,
            )
        )
    health = _mapping(payload.get("health"), "health")
    hunger = _mapping(payload.get("hunger"), "hunger")
    level = _mapping(payload.get("level"), "level")
    position = _mapping(payload.get("position"), "position")
    return PlayerSnapshot(
        api_version=_int(payload, "api_version", 1),
        timestamp_ms=_int(payload, "timestamp_ms"),
        connected=bool(payload.get("connected", False)),
        health=PlayerHealth(
            current=_float(health, "current"),
            maximum=_float(health, "max"),
            absorption=_float(health, "absorption"),
        ),
        armor=_int(payload, "armor"),
        hunger=PlayerHunger(
            food_level=_int(hunger, "food_level"),
            saturation=_float(hunger, "saturation"),
        ),
        level=PlayerLevel(
            experience_level=_int(level, "experience_level"),
            experience_progress=_float(level, "experience_progress"),
            total_experience=_int(level, "total_experience"),
        ),
        location=PlayerLocation(
            x=_float(position, "x"),
            y=_float(position, "y"),
            z=_float(position, "z"),
        ),
        facing_direction=str(payload.get("facing_direction", "Unknown")),
        inventory=tuple(inventory),
    )


class PlayerOverviewClient:
    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float = 0.75,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def fetch(self) -> PlayerSnapshot:
        with self._opener(self.url, timeout=self.timeout_seconds) as response:
            try:
                payload = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("Player endpoint returned invalid JSON.") from error
        return parse_player_payload(payload)


def build_item_icon_url(item_id: str, size: int = 64) -> str:
    if size <= 0:
        raise ValueError("Item icon size must be positive.")
    encoded_id = quote(item_id.strip(), safe=":")
    return f"{ITEM_ICON_BASE_URL}/{encoded_id}/icon?size={size}"


def _fallback_icon(size: int) -> bytes:
    stream = BytesIO()
    image = Image.new("RGBA", (size, size), "#2b2f36")
    draw = ImageDraw.Draw(image)
    draw.rectangle((1, 1, size - 2, size - 2), outline="#68707c", width=2)
    draw.line((size * 0.3, size * 0.3, size * 0.7, size * 0.7), fill="#98a2b3", width=3)
    draw.line((size * 0.7, size * 0.3, size * 0.3, size * 0.7), fill="#98a2b3", width=3)
    image.save(stream, format="PNG")
    return stream.getvalue()


class ItemIconClient:
    def __init__(
        self,
        *,
        size: int = 64,
        timeout_seconds: float = 1.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.size = size
        self.timeout_seconds = timeout_seconds
        self._opener = opener
        self._cache: dict[str, bytes] = {}
        self._lock = Lock()
        self._fallback = _fallback_icon(size)

    @property
    def fallback_icon(self) -> bytes:
        return self._fallback

    def get_icon(self, item_id: str) -> bytes:
        with self._lock:
            cached = self._cache.get(item_id)
        if cached is not None:
            return cached
        try:
            url = build_item_icon_url(item_id, self.size)
            with self._opener(url, timeout=self.timeout_seconds) as response:
                content_type = str(response.headers.get("Content-Type", ""))
                if not content_type.casefold().startswith("image/"):
                    raise ValueError("Item icon endpoint did not return an image.")
                icon = response.read()
            with Image.open(BytesIO(icon)) as image:
                image.verify()
        except (OSError, ValueError, UnidentifiedImageError):
            icon = self._fallback
        with self._lock:
            return self._cache.setdefault(item_id, icon)


def _empty_slot(index: int, section: str) -> InventorySlot:
    return InventorySlot(index, section)


def build_inventory_layout(slots: tuple[InventorySlot, ...]) -> InventoryLayout:
    by_index = {slot.inventory_slot: slot for slot in slots}
    get = lambda index, section: by_index.get(index, _empty_slot(index, section))
    return InventoryLayout(
        hotbar=tuple(get(index, "hotbar") for index in range(0, 9)),
        main=tuple(get(index, "main") for index in range(9, 36)),
        armor=tuple(get(index, "armor") for index in (39, 38, 37, 36)),
        offhand=get(40, "offhand"),
        extra=tuple(
            slot
            for index, slot in sorted(by_index.items())
            if index not in range(0, 41) and not slot.item.empty
        ),
    )


def format_item_tooltip(slot: InventorySlot) -> str:
    item = slot.item
    durability = (
        "Not applicable"
        if item.durability_remaining is None
        else f"{item.durability_remaining} / {item.max_damage}"
    )
    # TODO: Add enchantments, lore, attributes, set bonuses, and other rich
    # item details when /data/player exposes them.
    return "\n".join(
        (
            item.name or "Unknown item",
            item.item_id or "Unknown ID",
            f"Count: {item.count}",
            f"Location: {slot.section} slot {slot.inventory_slot}",
            f"Durability: {durability}",
            f"Maximum stack: {item.max_stack_size}",
            f"Enchanted: {'Yes' if item.is_enchanted else 'No'}",
        )
    )
