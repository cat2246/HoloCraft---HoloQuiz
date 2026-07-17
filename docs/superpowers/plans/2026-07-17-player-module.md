# Player Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live Player tab that shows Minecraft vitals, inventory icons, and hover details from the configured local player endpoint.

**Architecture:** A new Tkinter-free `holoquiz.player` module parses the API and owns HTTP/icon caching. A new `holoquiz.player_view` module owns a queue-backed poller plus the Player tab widgets; `holoquiz.gui` only registers the tab, forwards notebook visibility, and closes it. Tests exercise parsing, mapping, network boundaries, scheduling, stale-data behavior, and GUI wiring without requiring live services.

**Tech Stack:** Python 3.10+, Tkinter/ttk, `urllib.request`, Pillow, `concurrent.futures`, pytest, BlocksItems PNG API.

## Global Constraints

- Read player data from the existing `BotConfig.player_data_url`, defaulting to `http://127.0.0.1:8026/data/player`.
- Target Minecraft Java 1.21.10 and request vanilla item icons from `https://blocksitems.com/api/v1/items/{full_id}/icon?size=64`.
- Poll once per second only while the Player tab is selected, never overlap player requests, and retain the last successful snapshot after failures.
- Perform all network work off Tkinter's main thread; only the main thread may create or mutate Tk widgets, variables, or `PhotoImage` objects.
- Use an in-memory icon cache and a neutral fallback icon; do not add a disk cache.
- Show standard slots 0-40 in Minecraft layout order and occupied nonstandard slots in an Extra row.
- Add explicit code TODOs for a real player skin and future enchantment, lore, attribute, set-bonus, and other rich item metadata.
- Do not mutate inventory contents or alter the existing Coordinate Lock `PlayerDataClient`.

---

### Task 1: Player Models, Payload Parser, Layout, and Tooltip Text

**Files:**
- Create: `holoquiz/player.py`
- Create: `tests/test_player.py`

**Interfaces:**
- Produces: `PlayerHealth`, `PlayerHunger`, `PlayerLevel`, `PlayerLocation`, `PlayerItem`, `InventorySlot`, `PlayerSnapshot`, and `InventoryLayout` frozen dataclasses.
- Produces: `parse_player_payload(payload: object) -> PlayerSnapshot`.
- Produces: `build_inventory_layout(slots: tuple[InventorySlot, ...]) -> InventoryLayout`.
- Produces: `format_item_tooltip(slot: InventorySlot) -> str`.

- [ ] **Step 1: Write failing parser and layout tests**

Create `tests/test_player.py` with the representative live shape and behavioral assertions:

```python
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
```

- [ ] **Step 2: Run the tests and verify the missing module failure**

Run: `python -m pytest tests/test_player.py -v`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'holoquiz.player'`.

- [ ] **Step 3: Implement the immutable models, parser, standard-slot filling, and tooltip formatter**

Create `holoquiz/player.py` with these concrete boundaries:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
```

- [ ] **Step 4: Run focused tests and correct only parser/model behavior**

Run: `python -m pytest tests/test_player.py -v`

Expected: PASS for all tests in `tests/test_player.py`.

- [ ] **Step 5: Commit the data boundary**

```powershell
git add holoquiz/player.py tests/test_player.py
git commit -m "feat: parse player inventory data"
```

---

### Task 2: Player HTTP Client and BlocksItems Icon Cache

**Files:**
- Modify: `holoquiz/player.py`
- Modify: `tests/test_player.py`

**Interfaces:**
- Consumes: `parse_player_payload(payload: object) -> PlayerSnapshot` from Task 1.
- Produces: `PlayerOverviewClient(url: str, *, timeout_seconds: float = 0.75, opener=urlopen)` with `fetch() -> PlayerSnapshot`.
- Produces: `build_item_icon_url(item_id: str, size: int = 64) -> str`.
- Produces: `ItemIconClient(*, size: int = 64, timeout_seconds: float = 1.0, opener=urlopen)` with `get_icon(item_id: str) -> bytes`.

- [ ] **Step 1: Add failing HTTP, URL, cache, and fallback tests**

Append to `tests/test_player.py`:

```python
import json
from io import BytesIO

from PIL import Image

from holoquiz.player import (
    ItemIconClient,
    PlayerOverviewClient,
    build_item_icon_url,
)


class FakeResponse:
    def __init__(self, body, content_type="application/json"):
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


def png_bytes(color="red"):
    stream = BytesIO()
    Image.new("RGBA", (16, 16), color).save(stream, format="PNG")
    return stream.getvalue()


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
```

- [ ] **Step 2: Run the new client tests and verify missing-symbol failures**

Run: `python -m pytest tests/test_player.py -v`

Expected: FAIL because `PlayerOverviewClient`, `ItemIconClient`, and `build_item_icon_url` are not defined.

- [ ] **Step 3: Implement JSON retrieval, safe URL construction, PNG verification, locking, and fallback generation**

Add these imports and definitions to `holoquiz/player.py`:

```python
from io import BytesIO
import json
from threading import Lock
from typing import Callable
from urllib.parse import quote
from urllib.request import urlopen

from PIL import Image, ImageDraw, UnidentifiedImageError


ITEM_ICON_BASE_URL = "https://blocksitems.com/api/v1/items"
MINECRAFT_TARGET_VERSION = "1.21.10"


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
```

Keep `MINECRAFT_TARGET_VERSION` adjacent to the service constant so the version limitation is visible even though the direct icon endpoint does not accept a version query.

- [ ] **Step 4: Run client tests and the full player test file**

Run: `python -m pytest tests/test_player.py -v`

Expected: PASS with one request per unique icon ID and a valid 64-by-64 fallback PNG.

- [ ] **Step 5: Commit the HTTP boundary**

```powershell
git add holoquiz/player.py tests/test_player.py
git commit -m "feat: fetch and cache player item icons"
```

---

### Task 3: Queue-Backed Non-Overlapping Player Poller

**Files:**
- Create: `holoquiz/player_view.py`
- Create: `tests/test_player_view.py`

**Interfaces:**
- Consumes: `PlayerSnapshot` from Task 1.
- Produces: `PlayerViewData(snapshot: PlayerSnapshot, icon_png_by_item_id: dict[str, bytes])`.
- Produces: `PlayerPoller(scheduler, fetch, on_success, on_error, *, interval_ms=1000, drain_ms=25, executor=None)`.
- `PlayerPoller` methods: `activate()`, `deactivate()`, `refresh() -> bool`, `close()`.

- [ ] **Step 1: Write failing scheduler, overlap, stale-state, and shutdown tests**

Create `tests/test_player_view.py`:

```python
from concurrent.futures import Future

from holoquiz.player_view import PlayerPoller


class FakeScheduler:
    def __init__(self):
        self.callbacks = {}
        self.cancelled = []
        self.next_id = 0

    def after(self, delay_ms, callback):
        self.next_id += 1
        callback_id = f"after-{self.next_id}"
        self.callbacks[callback_id] = (delay_ms, callback)
        return callback_id

    def after_cancel(self, callback_id):
        self.cancelled.append(callback_id)
        self.callbacks.pop(callback_id, None)

    def run_delay(self, delay_ms):
        callback_id, (_, callback) = next(
            (item for item in self.callbacks.items() if item[1][0] == delay_ms)
        )
        del self.callbacks[callback_id]
        callback()


class ManualExecutor:
    def __init__(self):
        self.calls = []
        self.shutdown_calls = []

    def submit(self, function):
        future = Future()
        self.calls.append((function, future))
        return future

    def run_next(self):
        function, future = self.calls.pop(0)
        try:
            future.set_result(function())
        except Exception as error:
            future.set_exception(error)

    def shutdown(self, **kwargs):
        self.shutdown_calls.append(kwargs)


def test_player_poller_activates_immediately_and_prevents_overlap():
    scheduler = FakeScheduler()
    executor = ManualExecutor()
    poller = PlayerPoller(
        scheduler,
        lambda: "snapshot",
        lambda _value: None,
        lambda _error: None,
        executor=executor,
    )

    poller.activate()

    assert len(executor.calls) == 1
    assert poller.refresh() is False


def test_player_poller_delivers_worker_result_on_scheduler_drain_then_waits_one_second():
    scheduler = FakeScheduler()
    executor = ManualExecutor()
    successes = []
    poller = PlayerPoller(
        scheduler,
        lambda: "snapshot",
        successes.append,
        lambda _error: None,
        executor=executor,
    )
    poller.activate()
    executor.run_next()

    assert successes == []
    scheduler.run_delay(25)

    assert successes == ["snapshot"]
    assert any(delay == 1000 for delay, _callback in scheduler.callbacks.values())


def test_player_poller_reports_error_without_discarding_view_state():
    scheduler = FakeScheduler()
    executor = ManualExecutor()
    visible = ["old snapshot"]
    errors = []

    def fail():
        raise OSError("connection refused")

    poller = PlayerPoller(
        scheduler,
        fail,
        lambda value: visible.__setitem__(0, value),
        errors.append,
        executor=executor,
    )
    poller.activate()
    executor.run_next()
    scheduler.run_delay(25)

    assert visible == ["old snapshot"]
    assert str(errors[0]) == "connection refused"


def test_player_poller_deactivate_and_close_cancel_callbacks():
    scheduler = FakeScheduler()
    executor = ManualExecutor()
    poller = PlayerPoller(
        scheduler,
        lambda: "snapshot",
        lambda _value: None,
        lambda _error: None,
        executor=executor,
    )
    poller.activate()
    poller.deactivate()
    poller.close()

    assert poller.active is False
    assert scheduler.callbacks == {}
    assert executor.shutdown_calls == [{"wait": False, "cancel_futures": True}]
```

- [ ] **Step 2: Run the poller tests and verify the missing module failure**

Run: `python -m pytest tests/test_player_view.py -v`

Expected: FAIL during collection because `holoquiz.player_view` does not exist.

- [ ] **Step 3: Implement a worker-only fetch path and main-thread queue drain**

Create the initial `holoquiz/player_view.py`:

```python
from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
import queue
from typing import Any, Callable

from holoquiz.player import PlayerSnapshot


@dataclass(frozen=True)
class PlayerViewData:
    snapshot: PlayerSnapshot
    icon_png_by_item_id: dict[str, bytes]


class PlayerPoller:
    def __init__(
        self,
        scheduler: Any,
        fetch: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        *,
        interval_ms: int = 1000,
        drain_ms: int = 25,
        executor: Executor | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.fetch = fetch
        self.on_success = on_success
        self.on_error = on_error
        self.interval_ms = interval_ms
        self.drain_ms = drain_ms
        self.executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="player-view",
        )
        self.results: queue.Queue[tuple[bool, Any]] = queue.Queue()
        self.active = False
        self.in_flight = False
        self.closed = False
        self._poll_after_id: str | None = None
        self._drain_after_id: str | None = None

    def activate(self) -> None:
        if self.closed or self.active:
            return
        self.active = True
        self._schedule_drain()
        self.refresh()

    def deactivate(self) -> None:
        self.active = False
        self._cancel("_poll_after_id")
        self._cancel("_drain_after_id")

    def refresh(self) -> bool:
        if self.closed or not self.active or self.in_flight:
            return False
        self._cancel("_poll_after_id")
        self.in_flight = True
        self.executor.submit(self._fetch_to_queue)
        return True

    def _fetch_to_queue(self) -> None:
        try:
            self.results.put((True, self.fetch()))
        except Exception as error:
            self.results.put((False, error))

    def _schedule_drain(self) -> None:
        if self.active and not self.closed and self._drain_after_id is None:
            self._drain_after_id = self.scheduler.after(
                self.drain_ms,
                self._drain,
            )

    def _drain(self) -> None:
        self._drain_after_id = None
        delivered = False
        while True:
            try:
                ok, value = self.results.get_nowait()
            except queue.Empty:
                break
            delivered = True
            self.in_flight = False
            if not self.closed:
                if ok:
                    self.on_success(value)
                else:
                    self.on_error(value)
        if delivered and self.active and not self.closed:
            self._poll_after_id = self.scheduler.after(
                self.interval_ms,
                self._scheduled_refresh,
            )
        self._schedule_drain()

    def _scheduled_refresh(self) -> None:
        self._poll_after_id = None
        self.refresh()

    def _cancel(self, attribute: str) -> None:
        callback_id = getattr(self, attribute)
        if callback_id is not None:
            self.scheduler.after_cancel(callback_id)
            setattr(self, attribute, None)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.deactivate()
        self.executor.shutdown(wait=False, cancel_futures=True)
```

The worker method only calls `queue.put`; every `scheduler.after`, callback, and view mutation remains in the main-thread drain path.

- [ ] **Step 4: Run the focused poller tests**

Run: `python -m pytest tests/test_player_view.py -v`

Expected: PASS for activation, one-second scheduling, overlap prevention, error delivery, deactivation, and shutdown.

- [ ] **Step 5: Commit the polling controller**

```powershell
git add holoquiz/player_view.py tests/test_player_view.py
git commit -m "feat: add player data poller"
```

---

### Task 4: Minecraft-Inspired Player Tab and Hover Tooltips

**Files:**
- Modify: `holoquiz/player_view.py`
- Modify: `tests/test_player_view.py`

**Interfaces:**
- Consumes: `PlayerOverviewClient`, `ItemIconClient`, `build_inventory_layout`, and `format_item_tooltip` from Tasks 1-2.
- Consumes: `PlayerPoller` from Task 3.
- Produces: `PlayerTab(parent: ttk.Frame, *, player_url: str)` with `activate()`, `deactivate()`, `refresh()`, and `close()`.
- Produces: `health_percent(snapshot: PlayerSnapshot) -> float` and `hunger_percent(snapshot: PlayerSnapshot) -> float` for deterministic progress-bar calculations.

- [ ] **Step 1: Add failing percentage and view-data tests**

Append to `tests/test_player_view.py`:

```python
from holoquiz.player import parse_player_payload
from holoquiz.player_view import PlayerTab, health_percent, hunger_percent


def test_player_progress_values_are_clamped():
    payload = {
        "api_version": 1,
        "connected": True,
        "health": {"current": 33.5, "max": 42.5},
        "hunger": {"food_level": 20},
        "inventory": [],
    }
    snapshot = parse_player_payload(payload)

    assert health_percent(snapshot) == pytest.approx(78.8235, rel=0.001)
    assert hunger_percent(snapshot) == 100.0


def test_player_tab_public_lifecycle_is_explicit():
    assert callable(PlayerTab.activate)
    assert callable(PlayerTab.deactivate)
    assert callable(PlayerTab.refresh)
    assert callable(PlayerTab.close)
```

Also add `import pytest` at the top of `tests/test_player_view.py`.

- [ ] **Step 2: Run tests and verify missing view symbols**

Run: `python -m pytest tests/test_player_view.py -v`

Expected: FAIL because `PlayerTab`, `health_percent`, and `hunger_percent` do not exist.

- [ ] **Step 3: Implement the view using only main-thread image/widget creation**

Extend `holoquiz/player_view.py` with:

```python
from datetime import datetime
from io import BytesIO
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from holoquiz.player import (
    InventorySlot,
    ItemIconClient,
    PlayerOverviewClient,
    PlayerSnapshot,
    build_inventory_layout,
    format_item_tooltip,
)


SLOT_SIZE = 48
HEALTH_MAX_FALLBACK = 1.0
HUNGER_MAXIMUM = 20


def health_percent(snapshot: PlayerSnapshot) -> float:
    maximum = snapshot.health.maximum or HEALTH_MAX_FALLBACK
    return min(max(snapshot.health.current / maximum * 100.0, 0.0), 100.0)


def hunger_percent(snapshot: PlayerSnapshot) -> float:
    return min(max(snapshot.hunger.food_level / HUNGER_MAXIMUM * 100.0, 0.0), 100.0)


class ItemTooltip:
    def __init__(self, parent: tk.Misc) -> None:
        self.parent = parent
        self.window: tk.Toplevel | None = None

    def show(self, widget: tk.Widget, text: str) -> None:
        self.hide()
        self.window = tk.Toplevel(self.parent)
        self.window.wm_overrideredirect(True)
        label = tk.Label(
            self.window,
            text=text,
            justify="left",
            background="#130016",
            foreground="#f2e9ff",
            borderwidth=2,
            relief="solid",
            padx=9,
            pady=7,
            font=("Segoe UI", 9),
        )
        label.pack()
        self.window.geometry(f"+{widget.winfo_pointerx() + 14}+{widget.winfo_pointery() + 14}")

    def hide(self) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


class ItemSlotWidget:
    def __init__(self, parent: tk.Misc, tooltip: ItemTooltip) -> None:
        self.tooltip = tooltip
        self.canvas = tk.Canvas(
            parent,
            width=SLOT_SIZE,
            height=SLOT_SIZE,
            background="#8b8f94",
            highlightthickness=2,
            highlightbackground="#555b64",
        )
        self.slot: InventorySlot | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.canvas.bind("<Enter>", self._show_tooltip)
        self.canvas.bind("<Leave>", lambda _event: self.tooltip.hide())

    def grid(self, **kwargs: Any) -> None:
        self.canvas.grid(**kwargs)

    def render(self, slot: InventorySlot, photo: ImageTk.PhotoImage | None) -> None:
        self.slot = slot
        self.photo = photo
        self.canvas.delete("all")
        border = "#9b5de5" if slot.item.is_enchanted else "#555b64"
        self.canvas.configure(highlightbackground=border)
        if slot.item.empty or photo is None:
            return
        self.canvas.create_image(SLOT_SIZE // 2, SLOT_SIZE // 2, image=photo)
        if slot.item.count > 1:
            self.canvas.create_text(
                SLOT_SIZE - 4,
                SLOT_SIZE - 3,
                text=str(slot.item.count),
                anchor="se",
                fill="white",
                font=("Segoe UI Semibold", 9),
            )

    def _show_tooltip(self, _event: tk.Event) -> None:
        if self.slot is not None and not self.slot.item.empty:
            self.tooltip.show(self.canvas, format_item_tooltip(self.slot))


class PlayerTab:
    def __init__(self, parent: ttk.Frame, *, player_url: str) -> None:
        self.parent = parent
        self.player_client = PlayerOverviewClient(player_url)
        self.icon_client = ItemIconClient()
        self.status_var = tk.StringVar(value="Not connected")
        self.updated_var = tk.StringVar(value="No player data yet")
        self.health_var = tk.StringVar(value="Health: --")
        self.hunger_var = tk.StringVar(value="Hunger: --")
        self.details_var = tk.StringVar(value="")
        self.error_var = tk.StringVar(value="")
        self.tooltip = ItemTooltip(parent)
        self.photos: dict[str, ImageTk.PhotoImage] = {}
        self._build()
        self.poller = PlayerPoller(
            parent,
            self._fetch_view_data,
            self._render,
            self._show_error,
        )

    def _build(self) -> None:
        self.parent.columnconfigure(0, weight=1)
        self.parent.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(self.parent)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, text="Player", style="SectionLabel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(toolbar, textvariable=self.status_var).grid(row=0, column=1, sticky="e", padx=8)
        ttk.Button(toolbar, text="Refresh", command=self.refresh).grid(row=0, column=2, sticky="e")
        ttk.Label(toolbar, textvariable=self.updated_var, style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Label(toolbar, textvariable=self.error_var, foreground="#b42318").grid(row=2, column=0, columnspan=3, sticky="w")

        body = ttk.Frame(self.parent)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)

        profile = ttk.LabelFrame(body, text="Player overview", padding=10)
        profile.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        # TODO: Replace this placeholder when /data/player exposes a player
        # username or UUID that can be resolved to a real skin.
        skin = tk.Canvas(profile, width=150, height=220, background="#2b2f36", highlightthickness=0)
        skin.grid(row=0, column=1, rowspan=4, padx=8)
        skin.create_text(75, 110, text="Player skin\nunavailable", fill="#98a2b3", justify="center")
        self.armor_slots = [ItemSlotWidget(profile, self.tooltip) for _ in range(4)]
        for row, slot in enumerate(self.armor_slots):
            slot.grid(row=row, column=0, pady=2)
        self.offhand_slot = ItemSlotWidget(profile, self.tooltip)
        self.offhand_slot.grid(row=3, column=2, padx=(8, 0))

        content = ttk.Frame(body)
        content.grid(row=0, column=1, sticky="nsew")
        stats = ttk.LabelFrame(content, text="Vitals", padding=10)
        stats.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        stats.columnconfigure(0, weight=1)
        ttk.Label(stats, textvariable=self.health_var).grid(row=0, column=0, sticky="w")
        self.health_bar = ttk.Progressbar(stats, maximum=100)
        self.health_bar.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        ttk.Label(stats, textvariable=self.hunger_var).grid(row=2, column=0, sticky="w")
        self.hunger_bar = ttk.Progressbar(stats, maximum=100)
        self.hunger_bar.grid(row=3, column=0, sticky="ew", pady=(2, 6))
        ttk.Label(stats, textvariable=self.details_var, justify="left").grid(row=4, column=0, sticky="w")

        inventory = ttk.LabelFrame(content, text="Inventory", padding=8)
        inventory.grid(row=1, column=0, sticky="nw")
        self.main_slots = [ItemSlotWidget(inventory, self.tooltip) for _ in range(27)]
        for index, slot in enumerate(self.main_slots):
            slot.grid(row=index // 9, column=index % 9, padx=1, pady=1)
        self.hotbar_slots = [ItemSlotWidget(inventory, self.tooltip) for _ in range(9)]
        for index, slot in enumerate(self.hotbar_slots):
            slot.grid(row=4, column=index, padx=1, pady=(8, 1))
        self.extra_frame = ttk.Frame(content)
        self.extra_frame.grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.extra_label = ttk.Label(self.extra_frame, text="Extra", style="FieldLabel.TLabel")
        self.extra_label.grid(row=0, column=0, sticky="w")
        self.extra_label.grid_remove()
        self.extra_slots: list[ItemSlotWidget] = []

    def _fetch_view_data(self) -> PlayerViewData:
        snapshot = self.player_client.fetch()
        item_ids = {
            slot.item.item_id
            for slot in snapshot.inventory
            if not slot.item.empty and slot.item.item_id
        }
        icons = {item_id: self.icon_client.get_icon(item_id) for item_id in item_ids}
        return PlayerViewData(snapshot, icons)

    def _photo(self, item_id: str, png: bytes) -> ImageTk.PhotoImage:
        photo = self.photos.get(item_id)
        if photo is None:
            with Image.open(BytesIO(png)) as image:
                resized = image.convert("RGBA").resize((40, 40), Image.Resampling.NEAREST)
                photo = ImageTk.PhotoImage(resized)
            self.photos[item_id] = photo
        return photo

    def _render_slot(self, widget: ItemSlotWidget, slot: InventorySlot, icons: dict[str, bytes]) -> None:
        photo = None
        if not slot.item.empty:
            cache_key = slot.item.item_id or f"unknown:{slot.inventory_slot}"
            png = icons.get(slot.item.item_id, self.icon_client.fallback_icon)
            photo = self._photo(cache_key, png)
        widget.render(slot, photo)

    def _render(self, data: PlayerViewData) -> None:
        snapshot = data.snapshot
        layout = build_inventory_layout(snapshot.inventory)
        self.status_var.set("Connected" if snapshot.connected else "Disconnected")
        self.updated_var.set(f"Updated {datetime.now().strftime('%H:%M:%S')}")
        self.error_var.set("")
        self.health_var.set(f"Health: {snapshot.health.current:g} / {snapshot.health.maximum:g}")
        self.hunger_var.set(f"Hunger: {snapshot.hunger.food_level} / {HUNGER_MAXIMUM}  Saturation: {snapshot.hunger.saturation:g}")
        self.health_bar.configure(value=health_percent(snapshot))
        self.hunger_bar.configure(value=hunger_percent(snapshot))
        self.details_var.set(
            f"Armor: {snapshot.armor}\n"
            f"Level: {snapshot.level.experience_level} ({snapshot.level.experience_progress * 100:.0f}%)\n"
            f"Position: {snapshot.location.x:.1f}, {snapshot.location.y:.1f}, {snapshot.location.z:.1f}\n"
            f"Facing: {snapshot.facing_direction.title()}"
        )
        for widget, slot in zip(self.main_slots, layout.main):
            self._render_slot(widget, slot, data.icon_png_by_item_id)
        for widget, slot in zip(self.hotbar_slots, layout.hotbar):
            self._render_slot(widget, slot, data.icon_png_by_item_id)
        for widget, slot in zip(self.armor_slots, layout.armor):
            self._render_slot(widget, slot, data.icon_png_by_item_id)
        self._render_slot(self.offhand_slot, layout.offhand, data.icon_png_by_item_id)
        for widget in self.extra_slots:
            widget.canvas.destroy()
        self.extra_slots = []
        if layout.extra:
            self.extra_label.grid()
        else:
            self.extra_label.grid_remove()
        for index, slot in enumerate(layout.extra):
            widget = ItemSlotWidget(self.extra_frame, self.tooltip)
            widget.grid(row=1, column=index, padx=1)
            self._render_slot(widget, slot, data.icon_png_by_item_id)
            self.extra_slots.append(widget)

    def _show_error(self, error: Exception) -> None:
        self.status_var.set("Disconnected")
        self.error_var.set(f"Refresh failed: {error}")

    def activate(self) -> None:
        self.poller.activate()

    def deactivate(self) -> None:
        self.poller.deactivate()

    def refresh(self) -> None:
        self.poller.refresh()

    def close(self) -> None:
        self.tooltip.hide()
        self.poller.close()
```

Preserve the last rendered variables, bars, slots, and images in `_show_error`; it updates only connection/error text.

- [ ] **Step 4: Run view and player tests**

Run: `python -m pytest tests/test_player.py tests/test_player_view.py -v`

Expected: PASS with no real network requests or display-dependent test setup.

- [ ] **Step 5: Commit the Player tab component**

```powershell
git add holoquiz/player_view.py tests/test_player_view.py
git commit -m "feat: render player inventory tab"
```

---

### Task 5: Register Player in the Control Panel and Document It

**Files:**
- Modify: `holoquiz/gui.py`
- Modify: `tests/test_gui.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `PlayerTab(parent: ttk.Frame, *, player_url: str)` from Task 4.
- Produces: `HoloQuizControlPanel.player_view` lifecycle integration.
- Produces: `_on_feature_tab_changed(self, _event: tk.Event | None = None) -> None`.

- [ ] **Step 1: Write failing tab-registration and visibility-wiring tests**

Update the existing tab assertion in `tests/test_gui.py` and add a lifecycle test:

```python
def test_gui_feature_tabs_group_growing_toolset():
    assert gui.FEATURE_TAB_LABELS == (
        "HoloQuiz",
        "Screen Watcher",
        "Chat Triggers",
        "Coordinate Lock",
        "Player",
        "Activity",
    )


def test_player_view_runs_only_when_player_tab_is_selected():
    calls = []
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.player_view = SimpleNamespace(
        activate=lambda: calls.append("activate"),
        deactivate=lambda: calls.append("deactivate"),
    )
    panel.notebook = SimpleNamespace(
        select=lambda: "selected-tab",
        tab=lambda _tab_id, _option: "Player",
    )

    panel._on_feature_tab_changed()

    assert calls == ["activate"]

    panel.notebook = SimpleNamespace(
        select=lambda: "selected-tab",
        tab=lambda _tab_id, _option: "Activity",
    )
    panel._on_feature_tab_changed()

    assert calls == ["activate", "deactivate"]


def test_control_panel_close_closes_player_view():
    calls = []
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.player_view = SimpleNamespace(close=lambda: calls.append("player"))
    panel.mouse4_hotkey_listener = SimpleNamespace(stop=lambda: calls.append("mouse"))
    panel.worker = SimpleNamespace(stop=lambda: calls.append("worker"))
    panel.screen_phrase_worker = SimpleNamespace(stop=lambda: calls.append("screen"))
    panel.coordinate_lock_worker = SimpleNamespace(stop=lambda: calls.append("coordinate"))
    panel.root = SimpleNamespace(after=lambda _delay, callback: calls.append(callback))

    panel.close()

    assert calls[:5] == ["player", "mouse", "worker", "screen", "coordinate"]
```

- [ ] **Step 2: Run focused GUI tests and verify the expected failures**

Run: `python -m pytest tests/test_gui.py::test_gui_feature_tabs_group_growing_toolset tests/test_gui.py::test_player_view_runs_only_when_player_tab_is_selected tests/test_gui.py::test_control_panel_close_closes_player_view -v`

Expected: FAIL because `Player` is absent and `_on_feature_tab_changed` is undefined.

- [ ] **Step 3: Register, activate/deactivate, and close the Player view**

Modify `holoquiz/gui.py` as follows:

```python
from holoquiz.player_view import PlayerTab


FEATURE_TAB_LABELS = (
    "HoloQuiz",
    "Screen Watcher",
    "Chat Triggers",
    "Coordinate Lock",
    "Player",
    "Activity",
)
```

Expand `_build_ui` tab unpacking:

```python
(
    holoquiz_tab,
    screen_tab,
    chat_tab,
    coordinate_tab,
    player_tab,
    activity_tab,
) = (self._add_feature_tab(label) for label in FEATURE_TAB_LABELS)
```

After the Coordinate Lock widgets and before the Activity log widgets, create and bind the view:

```python
self.player_view = PlayerTab(
    player_tab,
    player_url=self.controls.get_config().player_data_url,
)
self.notebook.bind("<<NotebookTabChanged>>", self._on_feature_tab_changed)
```

Add the handler:

```python
def _on_feature_tab_changed(self, _event: tk.Event | None = None) -> None:
    selected_id = self.notebook.select()
    selected_label = str(self.notebook.tab(selected_id, "text"))
    if selected_label == "Player":
        self.player_view.activate()
    else:
        self.player_view.deactivate()
```

Close the view before scheduling root destruction:

```python
def close(self) -> None:
    self.player_view.close()
    self.mouse4_hotkey_listener.stop()
    self.worker.stop()
    self.screen_phrase_worker.stop()
    self.coordinate_lock_worker.stop()
    self.root.after(100, self.root.destroy)
```

- [ ] **Step 4: Update user documentation with the new runtime dependency and TODO boundaries**

Add this bullet under `Run With GUI` in `README.md`:

```markdown
- `Player` reads `player_data_url` once per second while its tab is selected and displays health, hunger, armor, experience, location, and the standard inventory layout. Vanilla item icons come from the BlocksItems service and fall back to neutral tiles when unavailable. The current local endpoint does not expose player identity or rich item metadata, so the skin remains a placeholder and hover details are limited to the fields returned by `/data/player`.
```

- [ ] **Step 5: Run focused integration tests**

Run: `python -m pytest tests/test_gui.py tests/test_player.py tests/test_player_view.py -v`

Expected: PASS.

- [ ] **Step 6: Commit the application integration**

```powershell
git add holoquiz/gui.py tests/test_gui.py README.md
git commit -m "feat: add Player module to control panel"
```

---

### Task 6: Full Verification and Live Visual QA

**Files:**
- Verify: `holoquiz/player.py`
- Verify: `holoquiz/player_view.py`
- Verify: `holoquiz/gui.py`
- Verify: `tests/test_player.py`
- Verify: `tests/test_player_view.py`
- Verify: `tests/test_gui.py`

**Interfaces:**
- Consumes: all completed Player feature interfaces.
- Produces: fresh automated and visual evidence that the approved design is satisfied.

- [ ] **Step 1: Run the complete test suite**

Run: `python -m pytest`

Expected: exit code 0 with all tests passing.

- [ ] **Step 2: Compile every package module**

Run: `python -m py_compile holoquiz/*.py`

Expected: exit code 0 with no output.

- [ ] **Step 3: Check whitespace and review only intended changes**

Run: `git diff --check 448b091..HEAD`

Expected: exit code 0 with no whitespace errors.

Run: `git status --short`

Expected: no Player-feature files remain unstaged or uncommitted; preserve the pre-existing unrelated `holoquiz-codex-6f5fdakt.txt` file.

- [ ] **Step 4: Launch against the live local endpoint and perform visual QA**

Run: `python holoquiz_gui.py`

With the Player tab selected, verify:

1. Connection state changes to `Connected` and the timestamp advances approximately once per second.
2. Health reads `33.5 / 42.5` and hunger reads `20 / 20` for the observed payload, with correctly proportioned bars.
3. Armor, level, position, and facing are visible.
4. Helmet/chestplate/leggings/boots appear top-to-bottom, main inventory is 9-by-3, hotbar is a separate 9-slot row, and offhand is visible.
5. `minecraft:iron_sword`, diamonds, steak, cake, armor, and potion use icons or neutral fallback tiles without freezing the UI.
6. Stack counts appear only above 1, and enchanted items have the highlighted border.
7. Hovering an occupied slot shows all current fields; hovering an empty slot shows nothing.
8. Switching away stops polling; returning triggers an immediate fetch.
9. Stopping the local service retains the last inventory, changes the state to `Disconnected`, and shows a concise error; restarting it recovers automatically.
10. Closing the app produces no late-callback Tkinter errors.

- [ ] **Step 5: Review requirements line by line before reporting completion**

Confirm the final diff contains both explicit TODO comments, uses BlocksItems only for vanilla icon imagery, makes no inventory mutations, does not alter Coordinate Lock behavior, and does not poll while hidden. If visual QA exposes a defect, add a failing automated regression test before changing production code.
