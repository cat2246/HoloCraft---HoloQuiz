# Player Auto Heal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, exact-name Auto Heal system that scans hotbar slots 9 through 1 and safely holds right-click on the first eligible configured item.

**Architecture:** Add immutable Auto Heal configuration to the existing config/runtime layers, a focused `holoquiz.auto_heal` selection engine and background worker, an exclusive item-use session in the shared input coordinator, and Player-tab configuration UI. The worker remains independent of Player-tab visibility and uses dependency injection for deterministic tests.

**Tech Stack:** Python 3.10+, frozen dataclasses, Tkinter/ttk, `threading`, `time.monotonic`, pyautogui, pytest.

## Global Constraints

- Preserve the existing uncommitted `ItemIconClient` request-header changes in `holoquiz/player.py` and `tests/test_player.py`.
- Auto Heal uses only inventory slots `0..8` and scans them in descending order.
- Rules match the exact case-sensitive displayed item `name`, including Unicode.
- A rule triggers when either enabled threshold is strictly crossed; `0` disables that threshold.
- `use_duration_seconds` defaults to exactly `2.0` and is persisted per item.
- Auto Heal defaults disabled and must never inject input unless Minecraft is foreground and no container is open.
- Every production behavior must be preceded by a focused failing test.

---

### Task 1: Auto Heal Configuration and Persistence

**Files:**
- Modify: `holoquiz/config.py`
- Modify: `tests/test_config.py`
- Modify: `config.example.json`

**Interfaces:**
- Produces: `AutoHealItemConfig(name: str, cooldown_seconds: float, use_duration_seconds: float = 2.0, health_below: float = 0.0, hunger_below: int = 0)`.
- Produces: `validate_auto_heal_item(item: AutoHealItemConfig) -> AutoHealItemConfig`.
- Produces: `validate_auto_heal_items(items: Iterable[AutoHealItemConfig]) -> tuple[AutoHealItemConfig, ...]`.
- Produces: `save_auto_heal_settings(path: Path, *, enabled: bool, items: Sequence[AutoHealItemConfig]) -> None`.
- Extends: `BotConfig.auto_heal_enabled` and `BotConfig.auto_heal_items`.

- [ ] **Step 1: Write failing configuration tests**

Add imports and focused tests to `tests/test_config.py`:

```python
import pytest

from holoquiz.config import (
    AutoHealItemConfig,
    BotConfig,
    load_config,
    save_auto_heal_settings,
    validate_auto_heal_items,
)


def test_auto_heal_defaults_are_safe():
    config = BotConfig()
    assert config.auto_heal_enabled is False
    assert config.auto_heal_items == ()


def test_load_config_preserves_exact_unicode_auto_heal_name(tmp_path):
    path = tmp_path / "config.json"
    name = ".｡*ﾟ+.*.｡ ʜᴏʟᴏ ᴀɴɴɪᴠ ᴄᴀᴋᴇ ｡+..｡*ﾟ"
    path.write_text(json.dumps({
        "auto_heal_enabled": True,
        "auto_heal_items": [{
            "name": name,
            "cooldown_seconds": 30,
            "use_duration_seconds": 2.5,
            "health_below": 20,
            "hunger_below": 8,
        }],
    }), encoding="utf-8")

    config = load_config(path)

    assert config.auto_heal_enabled is True
    assert config.auto_heal_items == (
        AutoHealItemConfig(name, 30.0, 2.5, 20.0, 8),
    )


def test_save_auto_heal_settings_preserves_unrelated_values(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"dry_run": false}\n', encoding="utf-8")
    item = AutoHealItemConfig("Steak", 5.0, 2.0, 10.0, 6)

    save_auto_heal_settings(path, enabled=True, items=(item,))

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["dry_run"] is False
    assert raw["auto_heal_enabled"] is True
    assert raw["auto_heal_items"] == [{
        "name": "Steak",
        "cooldown_seconds": 5.0,
        "use_duration_seconds": 2.0,
        "health_below": 10.0,
        "hunger_below": 6,
    }]


@pytest.mark.parametrize("item", [
    AutoHealItemConfig("", 1.0, 2.0, 5.0, 0),
    AutoHealItemConfig("Steak", -1.0, 2.0, 5.0, 0),
    AutoHealItemConfig("Steak", 1.0, 0.0, 5.0, 0),
    AutoHealItemConfig("Steak", 1.0, 2.0, 0.0, 0),
    AutoHealItemConfig("Steak", 1.0, 2.0, 5.0, 21),
])
def test_validate_auto_heal_items_rejects_invalid_rules(item):
    with pytest.raises(ValueError):
        validate_auto_heal_items((item,))


def test_validate_auto_heal_items_rejects_duplicate_exact_names():
    item = AutoHealItemConfig("Steak", 1.0, 2.0, 5.0, 0)
    with pytest.raises(ValueError, match="unique"):
        validate_auto_heal_items((item, item))
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_config.py -q`

Expected: collection fails because `AutoHealItemConfig`, validation, and persistence do not exist.

- [ ] **Step 3: Implement the immutable model, JSON conversion, and save helper**

Add to `holoquiz/config.py`:

```python
from collections.abc import Iterable, Sequence


@dataclass(frozen=True)
class AutoHealItemConfig:
    name: str
    cooldown_seconds: float
    use_duration_seconds: float = 2.0
    health_below: float = 0.0
    hunger_below: int = 0


def validate_auto_heal_item(item: AutoHealItemConfig) -> AutoHealItemConfig:
    if not item.name.strip():
        raise ValueError("Auto Heal item name is required.")
    if item.cooldown_seconds < 0:
        raise ValueError("Auto Heal cooldown must be 0 or greater.")
    if item.use_duration_seconds <= 0:
        raise ValueError("Auto Heal use duration must be greater than 0.")
    if item.health_below < 0:
        raise ValueError("Auto Heal health threshold must be 0 or greater.")
    if not 0 <= item.hunger_below <= 20:
        raise ValueError("Auto Heal hunger threshold must be between 0 and 20.")
    if item.health_below == 0 and item.hunger_below == 0:
        raise ValueError("Enable at least one Auto Heal threshold.")
    return item


def validate_auto_heal_items(
    items: Iterable[AutoHealItemConfig],
) -> tuple[AutoHealItemConfig, ...]:
    validated = tuple(validate_auto_heal_item(item) for item in items)
    names = [item.name for item in validated]
    if len(names) != len(set(names)):
        raise ValueError("Auto Heal item names must be unique.")
    return validated
```

Add `auto_heal_enabled: bool = False` and
`auto_heal_items: tuple[AutoHealItemConfig, ...] = ()` to `BotConfig`. Parse
`auto_heal_items` before `BotConfig(**values)`:

```python
values["auto_heal_items"] = _auto_heal_items_from_json(
    values.get("auto_heal_items")
)


def _auto_heal_items_from_json(value: Any) -> tuple[AutoHealItemConfig, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("auto_heal_items must be a list.")
    items = []
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("Each Auto Heal item must be an object.")
        items.append(AutoHealItemConfig(
            name=str(raw["name"]),
            cooldown_seconds=float(raw.get("cooldown_seconds", 0.0)),
            use_duration_seconds=float(raw.get("use_duration_seconds", 2.0)),
            health_below=float(raw.get("health_below", 0.0)),
            hunger_below=int(raw.get("hunger_below", 0)),
        ))
    return validate_auto_heal_items(items)


def _auto_heal_item_to_json(item: AutoHealItemConfig) -> dict[str, Any]:
    return {
        "name": item.name,
        "cooldown_seconds": item.cooldown_seconds,
        "use_duration_seconds": item.use_duration_seconds,
        "health_below": item.health_below,
        "hunger_below": item.hunger_below,
    }


def _read_existing_config_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw_config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw_config, dict):
        raise ValueError("Config root must be a JSON object.")
    return raw_config


def save_auto_heal_settings(
    path: Path,
    *,
    enabled: bool,
    items: Sequence[AutoHealItemConfig],
) -> None:
    raw_config = _read_existing_config_object(path)
    raw_config["auto_heal_enabled"] = bool(enabled)
    raw_config["auto_heal_items"] = [
        _auto_heal_item_to_json(item)
        for item in validate_auto_heal_items(items)
    ]
    path.write_text(json.dumps(raw_config, indent=2) + "\n", encoding="utf-8")
```

Use `_read_existing_config_object()` for the new Auto Heal save helper without
mechanically rewriting unrelated save helpers. Extend `_config_to_json_dict()`
with `values["auto_heal_items"] = [_auto_heal_item_to_json(item) for item in
config.auto_heal_items]`.

Add to `config.example.json`:

```json
"auto_heal_enabled": false,
"auto_heal_items": []
```

- [ ] **Step 4: Run configuration tests and verify GREEN**

Run: `python -m pytest tests/test_config.py -q`

Expected: all configuration tests pass.

- [ ] **Step 5: Commit the configuration slice**

```powershell
git add holoquiz/config.py tests/test_config.py config.example.json
git commit -m "feat: persist auto heal rules"
```

---

### Task 2: Thread-Safe Runtime State

**Files:**
- Modify: `holoquiz/runtime.py`
- Modify: `tests/test_runtime.py`

**Interfaces:**
- Consumes: `AutoHealItemConfig` and `validate_auto_heal_items` from Task 1.
- Produces: `RuntimeControls.set_auto_heal_enabled(enabled: bool) -> None`.
- Produces: `RuntimeControls.get_auto_heal_items() -> tuple[AutoHealItemConfig, ...]`.
- Produces: `RuntimeControls.set_auto_heal_items(items: Sequence[AutoHealItemConfig]) -> None`.
- Extends: `RuntimeSnapshot.auto_heal_enabled` and `RuntimeSnapshot.auto_heal_items`.

- [ ] **Step 1: Write failing runtime-state tests**

Add to `tests/test_runtime.py`:

```python
import pytest

from holoquiz.config import AutoHealItemConfig, BotConfig


def test_runtime_controls_track_auto_heal_settings():
    item = AutoHealItemConfig("Steak", 5.0, 2.0, 10.0, 6)
    controls = RuntimeControls.from_config(BotConfig())

    controls.set_auto_heal_enabled(True)
    controls.set_auto_heal_items((item,))

    assert controls.get_auto_heal_items() == (item,)
    assert controls.snapshot().auto_heal_enabled is True
    assert controls.snapshot().auto_heal_items == (item,)
    assert controls.get_config().auto_heal_enabled is True
    assert controls.get_config().auto_heal_items == (item,)


def test_runtime_controls_reject_invalid_auto_heal_items():
    controls = RuntimeControls.from_config(BotConfig())
    invalid = AutoHealItemConfig("Steak", 1.0, 2.0, 0.0, 0)
    with pytest.raises(ValueError, match="threshold"):
        controls.set_auto_heal_items((invalid,))
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_runtime.py -q`

Expected: failures because runtime Auto Heal state and methods are absent.

- [ ] **Step 3: Implement runtime state under the existing lock**

Initialize from `base_config`, include both fields in `get_config()` and
`snapshot()`, and add:

```python
from collections.abc import Sequence

from holoquiz.config import AutoHealItemConfig, validate_auto_heal_items


def set_auto_heal_enabled(self, enabled: bool) -> None:
    with self._lock:
        self._auto_heal_enabled = bool(enabled)


def get_auto_heal_items(self) -> tuple[AutoHealItemConfig, ...]:
    with self._lock:
        return tuple(self._auto_heal_items)


def set_auto_heal_items(
    self,
    items: Sequence[AutoHealItemConfig],
) -> None:
    validated = validate_auto_heal_items(items)
    with self._lock:
        self._auto_heal_items = validated
```

- [ ] **Step 4: Run runtime tests and verify GREEN**

Run: `python -m pytest tests/test_runtime.py -q`

Expected: all runtime tests pass.

- [ ] **Step 5: Commit the runtime slice**

```powershell
git add holoquiz/runtime.py tests/test_runtime.py
git commit -m "feat: expose auto heal runtime state"
```

---

### Task 3: Right-to-Left Selection Engine

**Files:**
- Create: `holoquiz/auto_heal.py`
- Create: `tests/test_auto_heal.py`

**Interfaces:**
- Consumes: `AutoHealItemConfig`, `PlayerSnapshot`, and `build_inventory_layout`.
- Produces: `AutoHealSelection(hotbar_slot: int, item_name: str, rule: AutoHealItemConfig)`.
- Produces: `auto_heal_threshold_met(snapshot: PlayerSnapshot, rule: AutoHealItemConfig) -> bool`.
- Produces: `select_auto_heal_item(snapshot, rules, last_used_at, now) -> AutoHealSelection | None`.

- [ ] **Step 1: Write failing pure selection tests**

Create `tests/test_auto_heal.py` with a small snapshot factory and these cases:

```python
from holoquiz.auto_heal import (
    auto_heal_threshold_met,
    select_auto_heal_item,
)
from holoquiz.config import AutoHealItemConfig
from holoquiz.player import parse_player_payload


def player_snapshot(*, health, hunger, hotbar=None, main=None):
    inventory = []
    for slot, name in (hotbar or {}).items():
        inventory.append({
            "inventory_slot": slot,
            "section": "hotbar",
            "item": {
                "empty": False,
                "id": "minecraft:test_item",
                "name": name,
                "count": 1,
            },
        })
    for slot, name in (main or {}).items():
        inventory.append({
            "inventory_slot": slot,
            "section": "main",
            "item": {
                "empty": False,
                "id": "minecraft:test_item",
                "name": name,
                "count": 1,
            },
        })
    return parse_player_payload({
        "api_version": 1,
        "timestamp_ms": 1,
        "connected": True,
        "health": {"current": health, "max": 20, "absorption": 0},
        "hunger": {"food_level": hunger, "saturation": 0},
        "inventory": inventory,
    })


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

    assert selection.hotbar_slot == 8
    assert selection.item_name == "Potion"


def test_select_auto_heal_item_skips_rightmost_item_on_cooldown():
    snapshot = player_snapshot(health=5, hunger=20, hotbar={7: "Steak", 8: "Potion"})
    rules = (
        AutoHealItemConfig("Steak", 5, 2, 10, 0),
        AutoHealItemConfig("Potion", 30, 2, 10, 0),
    )

    selection = select_auto_heal_item(
        snapshot, rules, {"Potion": 90.0}, now=100.0
    )

    assert selection.item_name == "Steak"


def test_auto_heal_thresholds_use_strict_or_semantics_and_zero_disables():
    rule = AutoHealItemConfig("Steak", 0, 2, health_below=10, hunger_below=6)
    assert auto_heal_threshold_met(player_snapshot(health=10, hunger=5), rule)
    assert not auto_heal_threshold_met(player_snapshot(health=10, hunger=6), rule)


def test_select_auto_heal_item_matches_exact_name_only():
    snapshot = player_snapshot(health=1, hunger=20, hotbar={8: "steak"})
    rules = (AutoHealItemConfig("Steak", 0, 2, 10, 0),)
    assert select_auto_heal_item(snapshot, rules, {}, now=0) is None


def test_select_auto_heal_item_ignores_configured_match_outside_hotbar():
    snapshot = player_snapshot(health=1, hunger=20, main={35: "Steak"})
    rules = (AutoHealItemConfig("Steak", 0, 2, 10, 0),)
    assert select_auto_heal_item(snapshot, rules, {}, now=0) is None
```

- [ ] **Step 2: Run the selection tests and verify RED**

Run: `python -m pytest tests/test_auto_heal.py -q`

Expected: collection fails because `holoquiz.auto_heal` does not exist.

- [ ] **Step 3: Implement the pure selection API**

Create `holoquiz/auto_heal.py` with:

```python
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
        return AutoHealSelection(slot.inventory_slot, slot.item.name, rule)
    return None
```

- [ ] **Step 4: Run selection tests and verify GREEN**

Run: `python -m pytest tests/test_auto_heal.py -q`

Expected: all pure selection tests pass.

- [ ] **Step 5: Commit the selection engine**

```powershell
git add holoquiz/auto_heal.py tests/test_auto_heal.py
git commit -m "feat: select auto heal hotbar items"
```

---

### Task 4: Exclusive Item-Use Input Session

**Files:**
- Modify: `holoquiz/keyboard_coordinator.py`
- Modify: `tests/test_keyboard_coordinator.py`

**Interfaces:**
- Produces: `KeyboardInputCoordinator.item_use_session() -> Iterator[bool]`.
- Changes: `click_session()` denies Auto Hit only during chat/pending chat or item use; it remains allowed during ordinary movement.

- [ ] **Step 1: Write failing concurrency tests**

Add:

```python
import threading


def test_item_use_session_blocks_movement_and_clicks():
    coordinator = KeyboardInputCoordinator()
    with coordinator.item_use_session() as allowed:
        assert allowed is True
        with coordinator.movement_session() as movement_allowed:
            assert movement_allowed is False
        with coordinator.click_session() as click_allowed:
            assert click_allowed is False


def test_item_use_session_is_denied_while_chat_is_pending():
    coordinator = KeyboardInputCoordinator()
    entered = threading.Event()
    release = threading.Event()

    def pending_chat():
        with coordinator.chat_session():
            entered.set()
            release.wait(1)

    thread = threading.Thread(target=pending_chat)
    thread.start()
    assert entered.wait(1)
    try:
        with coordinator.item_use_session() as allowed:
            assert allowed is False
    finally:
        release.set()
        thread.join(1)
```

Retain `test_click_session_is_allowed_during_movement_session` unchanged.

- [ ] **Step 2: Run coordinator tests and verify RED**

Run: `python -m pytest tests/test_keyboard_coordinator.py -q`

Expected: failures because `item_use_session` is absent.

- [ ] **Step 3: Implement item-use state without changing movement/Auto-Hit compatibility**

Initialize `_item_use_active = False` and add:

```python
@contextmanager
def item_use_session(self) -> Iterator[bool]:
    with self._state_lock:
        denied = self._pending_chat_sessions > 0
    acquired = False
    if not denied:
        acquired = self._input_lock.acquire(blocking=False)
    if acquired:
        with self._state_lock:
            if self._pending_chat_sessions > 0:
                self._input_lock.release()
                acquired = False
            else:
                self._item_use_active = True
    try:
        yield acquired
    finally:
        if acquired:
            with self._state_lock:
                self._item_use_active = False
            self._input_lock.release()
```

Update `click_session()` exactly as follows; this preserves clicks during
ordinary movement while blocking them during chat or item use:

```python
@contextmanager
def click_session(self) -> Iterator[bool]:
    self._state_lock.acquire()
    try:
        yield (
            self._pending_chat_sessions == 0
            and not self._item_use_active
        )
    finally:
        self._state_lock.release()
```

- [ ] **Step 4: Run coordinator and Coordinate Lock tests**

Run: `python -m pytest tests/test_keyboard_coordinator.py tests/test_coordinate_lock.py -q`

Expected: all tests pass, including concurrent movement-and-click behavior.

- [ ] **Step 5: Commit the input-coordination slice**

```powershell
git add holoquiz/keyboard_coordinator.py tests/test_keyboard_coordinator.py
git commit -m "feat: coordinate auto heal item use"
```

---

### Task 5: Auto Heal Background Worker

**Files:**
- Modify: `holoquiz/auto_heal.py`
- Modify: `tests/test_auto_heal.py`

**Interfaces:**
- Consumes: `RuntimeControls`, `PlayerOverviewClient`, `ContainerDataClient`, `minecraft_is_foreground`, and `KeyboardInputCoordinator.item_use_session()`.
- Produces: `AutoHealWorker.start()`, `stop()`, `is_running()`, and `check_once() -> bool`.

- [ ] **Step 1: Write failing worker safety and input tests**

Use injected fakes and no sleeps:

```python
import pytest

from holoquiz.auto_heal import AutoHealWorker
from holoquiz.config import AutoHealItemConfig, BotConfig
from holoquiz.runtime import RuntimeControls


class FakeInput:
    def __init__(self):
        self.events = []

    def press(self, key):
        self.events.append(("press", key))

    def mouseDown(self, *, button):
        self.events.append(("mouseDown", button))

    def mouseUp(self, *, button):
        self.events.append(("mouseUp", button))


class FakePlayerClient:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.url = "http://127.0.0.1:8026/data/player"
        self.fetch_count = 0

    def fetch(self):
        self.fetch_count += 1
        return self.snapshot


class FakeContainerClient:
    def __init__(self, is_open=False):
        self.open = is_open

    def is_open(self):
        return self.open


def auto_heal_worker(
    *,
    snapshot,
    rule=None,
    backend=None,
    foreground=True,
    container_open=False,
    clock=lambda: 100.0,
    wait_error=None,
):
    configured_rule = rule or AutoHealItemConfig("Potion", 30, 2, 10, 0)
    controls = RuntimeControls.from_config(BotConfig(
        program_enabled=True,
        auto_heal_enabled=True,
        auto_heal_items=(configured_rule,),
    ))
    input_backend = backend or FakeInput()

    def waiter(seconds):
        input_backend.events.append(("wait", seconds))
        if wait_error is not None:
            raise wait_error
        return False

    return AutoHealWorker(
        controls,
        lambda _message: None,
        player_client=FakePlayerClient(snapshot),
        container_client=FakeContainerClient(container_open),
        pyautogui_module=input_backend,
        foreground_provider=lambda: foreground,
        clock=clock,
        waiter=waiter,
    )


def test_worker_uses_selected_hotbar_item_for_configured_duration():
    backend = FakeInput()
    worker = auto_heal_worker(
        snapshot=player_snapshot(health=5, hunger=20, hotbar={8: "Potion"}),
        rule=AutoHealItemConfig("Potion", 30, 2.5, 10, 0),
        backend=backend,
        clock=lambda: 100.0,
    )

    assert worker.check_once() is True
    assert backend.events == [
        ("press", "9"),
        ("mouseDown", "right"),
        ("wait", 2.5),
        ("mouseUp", "right"),
    ]
    assert worker._last_used_at == {"Potion": 100.0}


@pytest.mark.parametrize("foreground,container_open", [
    (False, False),
    (True, True),
])
def test_worker_does_not_inject_when_environment_is_unsafe(
    foreground, container_open
):
    backend = FakeInput()
    worker = auto_heal_worker(
        snapshot=player_snapshot(health=1, hunger=20, hotbar={8: "Potion"}),
        backend=backend,
        foreground=foreground,
        container_open=container_open,
    )
    assert worker.check_once() is False
    assert backend.events == []


def test_worker_releases_right_button_when_wait_raises():
    backend = FakeInput()
    worker = auto_heal_worker(
        snapshot=player_snapshot(health=1, hunger=20, hotbar={8: "Potion"}),
        backend=backend,
        wait_error=RuntimeError("stopped"),
    )
    with pytest.raises(RuntimeError, match="stopped"):
        worker.check_once()
    assert backend.events[-1] == ("mouseUp", "right")
    assert worker._last_used_at == {}


def test_worker_disabled_gate_avoids_player_fetch():
    snapshot = player_snapshot(health=1, hunger=20, hotbar={8: "Potion"})
    client = FakePlayerClient(snapshot)
    worker = AutoHealWorker(
        RuntimeControls.from_config(BotConfig(auto_heal_enabled=False)),
        lambda _message: None,
        player_client=client,
    )
    assert worker.check_once() is False
    assert client.fetch_count == 0


def test_worker_records_cooldown_after_completed_use():
    times = iter((100.0, 102.5))
    worker = auto_heal_worker(
        snapshot=player_snapshot(health=1, hunger=20, hotbar={8: "Potion"}),
        clock=lambda: next(times),
    )
    assert worker.check_once() is True
    assert worker._last_used_at == {"Potion": 102.5}


def test_worker_start_and_stop_are_idempotent():
    worker = AutoHealWorker(
        RuntimeControls.from_config(BotConfig(auto_heal_enabled=False)),
        lambda _message: None,
        poll_seconds=0.01,
    )
    worker.start()
    first_thread = worker._thread
    worker.start()
    assert worker._thread is first_thread
    worker.stop()
    worker.stop()
    assert worker.is_running() is False
```

- [ ] **Step 2: Run worker tests and verify RED**

Run: `python -m pytest tests/test_auto_heal.py -q`

Expected: failures because `AutoHealWorker` is absent.

- [ ] **Step 3: Implement the worker with injected boundaries**

Add a worker whose constructor defaults match production:

```python
from threading import Event, Thread
from time import monotonic
from typing import Any, Callable

from holoquiz.coordinate_lock import ContainerDataClient, minecraft_is_foreground
from holoquiz.keyboard_coordinator import (
    KeyboardInputCoordinator,
    keyboard_input_coordinator,
)
from holoquiz.config import BotConfig
from holoquiz.player import PlayerOverviewClient
from holoquiz.runtime import RuntimeControls


class AutoHealWorker:
    def __init__(
        self,
        controls: RuntimeControls,
        status: Callable[[str], None],
        *,
        player_client: PlayerOverviewClient | None = None,
        container_client: ContainerDataClient | None = None,
        pyautogui_module: Any | None = None,
        foreground_provider: Callable[[], bool] = minecraft_is_foreground,
        input_coordinator: KeyboardInputCoordinator | None = None,
        poll_seconds: float = 0.25,
        clock: Callable[[], float] = monotonic,
        waiter: Callable[[float], bool] | None = None,
    ) -> None:
        self.controls = controls
        self._status_sink = status
        player_url = controls.get_config().player_data_url
        container_url = f"{player_url.rsplit('/', 1)[0]}/container"
        self.player_client = player_client or PlayerOverviewClient(player_url)
        self.container_client = container_client or ContainerDataClient(
            container_url
        )
        self._pyautogui = pyautogui_module
        self._foreground_provider = foreground_provider
        self._input_coordinator = input_coordinator or keyboard_input_coordinator
        self.poll_seconds = poll_seconds
        self._clock = clock
        self._stop_event = Event()
        self._waiter = waiter or self._stop_event.wait
        self._thread: Thread | None = None
        self._last_used_at: dict[str, float] = {}
        self._last_status = ""

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.check_once()
            except Exception as error:
                self._status(f"[auto-heal-error] {error}")
            self._stop_event.wait(self.poll_seconds)

    def _client(self, config: BotConfig) -> PlayerOverviewClient:
        if (
            self.player_client is None
            or self.player_client.url != config.player_data_url
        ):
            self.player_client = PlayerOverviewClient(config.player_data_url)
        return self.player_client

    def check_once(self) -> bool:
        config = self.controls.get_config()
        if not (
            config.program_enabled
            and config.auto_heal_enabled
            and config.auto_heal_items
        ):
            return False
        snapshot = self._client(config).fetch()
        if not snapshot.connected:
            return False
        if not self._environment_is_safe():
            return False
        selection = select_auto_heal_item(
            snapshot,
            config.auto_heal_items,
            self._last_used_at,
            self._clock(),
        )
        if selection is None:
            return False
        return self._use(selection)

    def _environment_is_safe(self) -> bool:
        return self._foreground_provider() and not self.container_client.is_open()

    def _use(self, selection: AutoHealSelection) -> bool:
        if not self._environment_is_safe():
            return False
        with self._input_coordinator.item_use_session() as allowed:
            if not allowed:
                return False
            pyautogui = self._pyautogui or self._load_pyautogui()
            pyautogui.press(str(selection.hotbar_slot + 1))
            right_press_attempted = False
            interrupted = False
            try:
                right_press_attempted = True
                pyautogui.mouseDown(button="right")
                interrupted = self._waiter(
                    selection.rule.use_duration_seconds
                )
            finally:
                if right_press_attempted:
                    pyautogui.mouseUp(button="right")
            if interrupted:
                return False
            self._last_used_at[selection.item_name] = self._clock()
            self._status(
                f"[auto-heal] Used {selection.item_name} from hotbar "
                f"slot {selection.hotbar_slot + 1}."
            )
            return True

    def _load_pyautogui(self) -> Any:
        import pyautogui
        self._pyautogui = pyautogui
        return pyautogui

    def _status(self, message: str) -> None:
        if message == self._last_status:
            return
        self._last_status = message
        self._status_sink(message)
```

Keep the shown `check_once()` and `_use()` boundaries so tests can verify one
cycle without a thread.

- [ ] **Step 4: Run Auto Heal, coordinator, and player tests**

Run: `python -m pytest tests/test_auto_heal.py tests/test_keyboard_coordinator.py tests/test_player.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit the worker slice**

```powershell
git add holoquiz/auto_heal.py tests/test_auto_heal.py
git commit -m "feat: run auto heal worker"
```

---

### Task 6: Player Auto Heal Configuration UI

**Files:**
- Modify: `holoquiz/player_view.py`
- Modify: `tests/test_player_view.py`

**Interfaces:**
- Consumes: `AutoHealItemConfig` and validation from Task 1.
- Produces: `parse_auto_heal_form(name, cooldown, duration, health, hunger) -> AutoHealItemConfig`.
- Extends: `ItemSlotWidget(parent: tk.Misc, tooltip: ItemTooltip, *, on_right_click: Callable[[InventorySlot], None] | None = None)`.
- Extends: `PlayerTab` with initial Auto Heal state and two mutation callbacks.

- [ ] **Step 1: Write failing form, right-click, and list-model tests**

Add non-display-dependent tests:

```python
from types import SimpleNamespace

from holoquiz.config import AutoHealItemConfig
from holoquiz.player import InventorySlot, PlayerItem
from holoquiz.player_view import (
    format_auto_heal_rule,
    ItemSlotWidget,
    PlayerTab,
    parse_auto_heal_form,
)


def test_parse_auto_heal_form_uses_default_two_second_duration():
    item = parse_auto_heal_form("Steak", "5", "", "10", "0")
    assert item == AutoHealItemConfig("Steak", 5.0, 2.0, 10.0, 0)


def test_parse_auto_heal_form_rejects_disabled_thresholds():
    with pytest.raises(ValueError, match="threshold"):
        parse_auto_heal_form("Steak", "5", "2", "0", "0")


def test_item_slot_right_click_reports_only_occupied_slot():
    selected = []
    widget = object.__new__(ItemSlotWidget)
    widget.slot = InventorySlot(8, "hotbar", PlayerItem(False, name="Steak"))
    widget.on_right_click = selected.append
    widget._on_right_click(None)
    assert [slot.item.name for slot in selected] == ["Steak"]
    widget.slot = InventorySlot(7, "hotbar")
    widget._on_right_click(None)
    assert [slot.item.name for slot in selected] == ["Steak"]


def test_player_tab_upserts_rule_by_exact_name_and_notifies():
    saved = []
    tab = object.__new__(PlayerTab)
    tab.auto_heal_items = (AutoHealItemConfig("Steak", 5, 2, 10, 0),)
    tab.on_auto_heal_items_changed = lambda items: saved.append(items)
    tab._refresh_auto_heal_rows = lambda: None

    updated = AutoHealItemConfig("Steak", 9, 2.5, 12, 4)
    tab._save_auto_heal_item(updated)

    assert tab.auto_heal_items == (updated,)
    assert saved == [(updated,)]


def test_player_tab_removes_exact_rule_and_notifies():
    saved = []
    steak = AutoHealItemConfig("Steak", 5, 2, 10, 0)
    potion = AutoHealItemConfig("Potion", 9, 2.5, 12, 4)
    tab = object.__new__(PlayerTab)
    tab.auto_heal_items = (steak, potion)
    tab.on_auto_heal_items_changed = lambda items: saved.append(items)
    tab._refresh_auto_heal_rows = lambda: None

    tab._remove_auto_heal_item("Steak")

    assert tab.auto_heal_items == (potion,)
    assert saved == [(potion,)]


def test_player_tab_auto_heal_toggle_notifies_current_value():
    saved = []
    tab = object.__new__(PlayerTab)
    tab.auto_heal_enabled_var = SimpleNamespace(get=lambda: True)
    tab.on_auto_heal_enabled_changed = saved.append
    tab._on_auto_heal_toggle()
    assert saved == [True]


def test_format_auto_heal_rule_lists_all_values():
    item = AutoHealItemConfig("Steak", 5, 2.5, 10, 6)
    assert format_auto_heal_rule(item) == (
        "Cooldown: 5s   Use: 2.5s   Health < 10   Hunger < 6"
    )
```

- [ ] **Step 2: Run Player-view tests and verify RED**

Run: `python -m pytest tests/test_player_view.py -q`

Expected: collection/attribute failures for the new form and callbacks.

- [ ] **Step 3: Implement form parsing and occupied-slot right-click binding**

Add:

```python
from collections.abc import Callable, Sequence

from holoquiz.config import (
    AutoHealItemConfig,
    validate_auto_heal_item,
)


def parse_auto_heal_form(
    name: str,
    cooldown: str,
    duration: str,
    health: str,
    hunger: str,
) -> AutoHealItemConfig:
    try:
        item = AutoHealItemConfig(
            name=name,
            cooldown_seconds=float(cooldown),
            use_duration_seconds=float(duration) if duration.strip() else 2.0,
            health_below=float(health or 0),
            hunger_below=int(hunger or 0),
        )
    except ValueError as error:
        raise ValueError("Auto Heal values must be numeric.") from error
    return validate_auto_heal_item(item)


def format_auto_heal_rule(item: AutoHealItemConfig) -> str:
    return (
        f"Cooldown: {item.cooldown_seconds:g}s   "
        f"Use: {item.use_duration_seconds:g}s   "
        f"Health < {item.health_below:g}   "
        f"Hunger < {item.hunger_below:g}"
    )
```

Change `ItemSlotWidget` with:

```python
def __init__(
    self,
    parent: tk.Misc,
    tooltip: ItemTooltip,
    *,
    on_right_click: Callable[[InventorySlot], None] | None = None,
) -> None:
    self.tooltip = tooltip
    self.on_right_click = on_right_click
    self.canvas.bind("<Button-3>", self._on_right_click)


def _on_right_click(self, _event: tk.Event | None) -> None:
    if (
        self.on_right_click is not None
        and self.slot is not None
        and not self.slot.item.empty
    ):
        self.on_right_click(self.slot)
```

Insert `self.on_right_click = on_right_click` directly after the existing
`self.tooltip = tooltip`, and insert the new bind directly after the existing
`<Leave>` bind; retain the intervening canvas construction unchanged.

- [ ] **Step 4: Build the dialog and per-row Remove UI**

Extend `PlayerTab.__init__` with:

```python
auto_heal_enabled: bool = False,
auto_heal_items: Sequence[AutoHealItemConfig] = (),
on_auto_heal_enabled_changed: Callable[[bool], None] | None = None,
on_auto_heal_items_changed: Callable[[tuple[AutoHealItemConfig, ...]], None] | None = None,
```

Pass `_open_auto_heal_dialog` to every inventory/hotbar/armor/offhand/extra
slot widget. Initialize the state before `_build()`:

```python
self.auto_heal_items = tuple(auto_heal_items)
self.on_auto_heal_enabled_changed = (
    on_auto_heal_enabled_changed or (lambda _enabled: None)
)
self.on_auto_heal_items_changed = (
    on_auto_heal_items_changed or (lambda _items: None)
)
self.auto_heal_enabled_var = tk.BooleanVar(value=auto_heal_enabled)
```

Build Auto Heal beside Vitals, then span Inventory and Extra across both
columns so the controls and hotbar fit the standard window:

```python
def layout_player_sections(content, stats, inventory, extra, auto_heal) -> None:
    content.columnconfigure(0, weight=1)
    content.columnconfigure(1, weight=1)
    stats.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
    auto_heal.grid(
        row=0,
        column=1,
        sticky="nsew",
        padx=(10, 0),
        pady=(0, 10),
    )
    inventory.grid(row=1, column=0, columnspan=2, sticky="nw")
    extra.grid(
        row=2,
        column=0,
        columnspan=2,
        sticky="w",
        pady=(8, 0),
    )


def _build_auto_heal_section(self, content: ttk.Frame) -> None:
    section = ttk.LabelFrame(content, text="Auto Heal", padding=8)
    self.auto_heal_section = section
    section.columnconfigure(0, weight=1)
    ttk.Checkbutton(
        section,
        text="Enable Auto Heal",
        variable=self.auto_heal_enabled_var,
        command=self._on_auto_heal_toggle,
    ).grid(row=0, column=0, sticky="w")
    self.auto_heal_empty_label = ttk.Label(
        section,
        text="Right-click an inventory item to add an Auto Heal rule.",
        style="Muted.TLabel",
    )
    self.auto_heal_empty_label.grid(row=1, column=0, sticky="w", pady=(6, 0))
    self.auto_heal_rows_frame = ttk.Frame(section)
    self.auto_heal_rows_frame.grid(row=2, column=0, sticky="ew", pady=(6, 0))
    self.auto_heal_rows_frame.columnconfigure(0, weight=1)
    self._refresh_auto_heal_rows()


def _on_auto_heal_toggle(self) -> None:
    self.on_auto_heal_enabled_changed(self.auto_heal_enabled_var.get())


def _open_auto_heal_dialog(self, slot: InventorySlot) -> None:
    name = slot.item.name
    existing = next(
        (item for item in self.auto_heal_items if item.name == name),
        None,
    )
    AutoHealItemDialog(
        self.parent,
        name=name,
        existing=existing,
        on_save=self._save_auto_heal_item,
    )


def _save_auto_heal_item(self, item: AutoHealItemConfig) -> None:
    updated = []
    replaced = False
    for existing in self.auto_heal_items:
        if existing.name == item.name:
            updated.append(item)
            replaced = True
        else:
            updated.append(existing)
    if not replaced:
        updated.append(item)
    self.auto_heal_items = tuple(updated)
    self._refresh_auto_heal_rows()
    self.on_auto_heal_items_changed(self.auto_heal_items)


def _remove_auto_heal_item(self, name: str) -> None:
    self.auto_heal_items = tuple(
        item for item in self.auto_heal_items if item.name != name
    )
    self._refresh_auto_heal_rows()
    self.on_auto_heal_items_changed(self.auto_heal_items)


def _refresh_auto_heal_rows(self) -> None:
    for child in self.auto_heal_rows_frame.winfo_children():
        child.destroy()
    if not self.auto_heal_items:
        self.auto_heal_empty_label.grid()
        return
    self.auto_heal_empty_label.grid_remove()
    for row_index, item in enumerate(self.auto_heal_items):
        row = ttk.Frame(self.auto_heal_rows_frame)
        row.grid(row=row_index, column=0, sticky="ew", pady=2)
        row.columnconfigure(0, weight=1)
        ttk.Label(row, text=item.name, wraplength=300).grid(
            row=0, column=0, sticky="w"
        )
        details = format_auto_heal_rule(item)
        ttk.Label(row, text=details, style="Muted.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        ttk.Button(
            row,
            text="Remove",
            command=partial(self._remove_auto_heal_item, item.name),
        ).grid(row=0, column=1, rowspan=2, padx=(8, 0))
```

Implement a modal `tk.Toplevel` dialog with read-only name, entries prefilled
from an existing exact-name rule or defaults (`0`, `2`, `0`, `0`). Use this
concrete dialog boundary:

```python
class AutoHealItemDialog:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        name: str,
        existing: AutoHealItemConfig | None,
        on_save: Callable[[AutoHealItemConfig], None],
    ) -> None:
        self.on_save = on_save
        self.window = tk.Toplevel(parent)
        self.window.title("Auto Heal item")
        self.window.transient(parent.winfo_toplevel())
        self.window.resizable(False, False)
        self.name = name
        self.cooldown_var = tk.StringVar(
            value=f"{existing.cooldown_seconds:g}" if existing else "0"
        )
        self.duration_var = tk.StringVar(
            value=f"{existing.use_duration_seconds:g}" if existing else "2"
        )
        self.health_var = tk.StringVar(
            value=f"{existing.health_below:g}" if existing else "0"
        )
        self.hunger_var = tk.StringVar(
            value=f"{existing.hunger_below:g}" if existing else "0"
        )
        self.error_var = tk.StringVar(value="")

        frame = ttk.Frame(self.window, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text="Item").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text=name, wraplength=420).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        fields = (
            ("Cooldown time (seconds)", self.cooldown_var),
            ("Use duration (seconds)", self.duration_var),
            ('Use when health below "x"', self.health_var),
            ('Use when hunger below "x"', self.hunger_var),
        )
        for row, (label, variable) in enumerate(fields, start=1):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
            ttk.Entry(frame, textvariable=variable, width=14).grid(
                row=row, column=1, sticky="w", padx=(8, 0), pady=2
            )
        ttk.Label(frame, textvariable=self.error_var, foreground="#b42318").grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )
        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.window.destroy).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(buttons, text="Save", command=self._save).grid(row=0, column=1)
        self.window.grab_set()

    def _save(self) -> None:
        try:
            item = parse_auto_heal_form(
                self.name,
                self.cooldown_var.get(),
                self.duration_var.get(),
                self.health_var.get(),
                self.hunger_var.get(),
            )
        except ValueError as error:
            self.error_var.set(str(error))
            return
        self.on_save(item)
        self.window.destroy()
```

Save calls `parse_auto_heal_form`, upserts by exact name without reordering
unrelated rules, refreshes rows, then invokes the mutation callback.

- [ ] **Step 5: Run Player-view tests and verify GREEN**

Run: `python -m pytest tests/test_player_view.py -q`

Expected: all Player-view tests pass without requiring a Tk display.

- [ ] **Step 6: Commit the UI slice**

```powershell
git add holoquiz/player_view.py tests/test_player_view.py
git commit -m "feat: configure auto heal in player tab"
```

---

### Task 7: Control-Panel Lifecycle, Persistence Wiring, and Documentation

**Files:**
- Modify: `holoquiz/gui.py`
- Modify: `tests/test_gui.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `AutoHealWorker`, `save_auto_heal_settings`, and expanded `PlayerTab`.
- Produces: `_on_auto_heal_enabled_changed(enabled: bool) -> None`.
- Produces: `_on_auto_heal_items_changed(items: tuple[AutoHealItemConfig, ...]) -> None`.
- Extends: `HoloQuizControlPanel.close()` to stop Auto Heal.

- [ ] **Step 1: Write failing lifecycle and persistence tests**

Add to `tests/test_gui.py`:

```python
from holoquiz.config import AutoHealItemConfig


def test_auto_heal_toggle_updates_runtime_and_persists(tmp_path):
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.config_path = tmp_path / "config.json"
    panel.config_path.write_text("{}\n", encoding="utf-8")
    panel.controls = RuntimeControls.from_config(BotConfig())

    panel._on_auto_heal_enabled_changed(True)

    assert panel.controls.get_config().auto_heal_enabled is True
    assert json.loads(panel.config_path.read_text())["auto_heal_enabled"] is True


def test_auto_heal_items_update_runtime_and_persist(tmp_path):
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.config_path = tmp_path / "config.json"
    panel.config_path.write_text("{}\n", encoding="utf-8")
    panel.controls = RuntimeControls.from_config(BotConfig(auto_heal_enabled=True))
    item = AutoHealItemConfig("Steak", 5, 2, 10, 6)

    panel._on_auto_heal_items_changed((item,))

    assert panel.controls.get_auto_heal_items() == (item,)
    assert json.loads(panel.config_path.read_text())["auto_heal_items"][0]["name"] == "Steak"


def test_control_panel_close_stops_auto_heal_before_root_destroy():
    calls = []
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.auto_heal_worker = SimpleNamespace(stop=lambda: calls.append("auto-heal"))
    panel.player_view = SimpleNamespace(close=lambda: calls.append("player"))
    panel.mouse4_hotkey_listener = SimpleNamespace(stop=lambda: calls.append("mouse"))
    panel.worker = SimpleNamespace(stop=lambda: calls.append("worker"))
    panel.screen_phrase_worker = SimpleNamespace(stop=lambda: calls.append("screen"))
    panel.coordinate_lock_worker = SimpleNamespace(stop=lambda: calls.append("coordinate"))
    panel.root = SimpleNamespace(
        after=lambda _delay, _callback: calls.append("destroy"),
        destroy=lambda: None,
    )
    panel.close()
    assert calls[0] == "auto-heal"
```

Replace the existing close lifecycle test with the shown test so every worker
remains represented once.

- [ ] **Step 2: Run GUI lifecycle tests and verify RED**

Run: `python -m pytest tests/test_gui.py -q`

Expected: failures because callbacks and worker lifecycle wiring are absent.

- [ ] **Step 3: Wire worker, callbacks, Player tab, and shutdown**

In `HoloQuizControlPanel.__init__`, create:

```python
from holoquiz.auto_heal import AutoHealWorker
from holoquiz.config import AutoHealItemConfig, save_auto_heal_settings
from holoquiz.player import PlayerOverviewClient


self.auto_heal_worker = AutoHealWorker(
    self.controls,
    self.log_queue.put,
    player_client=PlayerOverviewClient(config.player_data_url),
)
```

Construct `PlayerTab` with:

```python
def player_tab_auto_heal_options(config: BotConfig) -> dict[str, Any]:
    return {
        "auto_heal_enabled": config.auto_heal_enabled,
        "auto_heal_items": config.auto_heal_items,
    }


auto_heal_options = player_tab_auto_heal_options(
    self.controls.get_config()
)
self.player_view = PlayerTab(
    player_tab,
    player_url=self.controls.get_config().player_data_url,
    **auto_heal_options,
    on_auto_heal_enabled_changed=self._on_auto_heal_enabled_changed,
    on_auto_heal_items_changed=self._on_auto_heal_items_changed,
)
```

Start `self.auto_heal_worker` immediately after the other long-running workers
are started. Make shutdown order explicit:

```python
def close(self) -> None:
    self.auto_heal_worker.stop()
    self.player_view.close()
    self.mouse4_hotkey_listener.stop()
    self.worker.stop()
    self.screen_phrase_worker.stop()
    self.coordinate_lock_worker.stop()
    self.root.after(100, self.root.destroy)
```

Add the persistence callbacks:

```python
def _save_auto_heal_settings(self) -> None:
    config = self.controls.get_config()
    save_auto_heal_settings(
        self.config_path,
        enabled=config.auto_heal_enabled,
        items=config.auto_heal_items,
    )


def _on_auto_heal_enabled_changed(self, enabled: bool) -> None:
    self.controls.set_auto_heal_enabled(enabled)
    self._save_auto_heal_settings()


def _on_auto_heal_items_changed(
    self,
    items: tuple[AutoHealItemConfig, ...],
) -> None:
    self.controls.set_auto_heal_items(items)
    self._save_auto_heal_settings()
```

- [ ] **Step 4: Document Auto Heal behavior and safety boundaries**

Add a README bullet explaining exact-name rules, right-to-left hotbar-only
priority, per-item cooldown/use/threshold values, separate enable toggle,
foreground/container safety, and config persistence:

```markdown
- `Auto Heal` is configured in the Player tab by right-clicking an occupied item. Rules match the item's exact displayed name and store cooldown, right-click use duration (2 seconds by default), health-below, and hunger-below thresholds in `config.json`. When enabled, it scans hotbar slots 9 through 1, uses the first eligible item only while Minecraft is foreground and no container is open, and runs even when the Player tab is hidden.
```

- [ ] **Step 5: Run integrated focused tests**

Run: `python -m pytest tests/test_gui.py tests/test_player_view.py tests/test_auto_heal.py tests/test_config.py tests/test_runtime.py -q`

Expected: all focused integration tests pass.

- [ ] **Step 6: Commit application integration**

```powershell
git add holoquiz/gui.py tests/test_gui.py README.md
git commit -m "feat: integrate player auto heal"
```

---

### Task 8: Full Verification and Visual QA

**Files:**
- Verify all files changed in Tasks 1 through 7.

**Interfaces:**
- Consumes: the complete Auto Heal feature.
- Produces: fresh evidence that automated behavior and existing modules remain correct.

- [ ] **Step 1: Run the complete test suite**

Run: `python -m pytest`

Expected: exit code 0 with no failures or warnings introduced by Auto Heal.

- [ ] **Step 2: Compile all package modules**

Run: `python -m py_compile holoquiz/*.py`

Expected: exit code 0 with no output.

- [ ] **Step 3: Check whitespace and working-tree scope**

Run: `git diff --check`

Expected: exit code 0.

Run: `git status --short`

Expected: preserve the pre-existing `holoquiz/player.py`, `tests/test_player.py`,
and unrelated `holoquiz-codex-*.txt` changes unless they have been intentionally
included in their own user-owned commit.

- [ ] **Step 4: Perform non-destructive live UI QA**

Run: `python holoquiz_gui.py`

Verify:

1. The Auto Heal section is visible and centered with the existing Player UI.
2. Right-clicking Steak and the custom Unicode cake opens an exact-name dialog.
3. Blank duration defaults to 2 seconds; invalid numeric/threshold values stay open with a useful error.
4. Saving/editing/removing rows updates `config.json` immediately and survives restart.
5. The toggle persists independently from the main chat dry-run setting.
6. Do not enable Auto Heal during visual QA unless safe disposable test items and explicit user control are available; automated tests provide input evidence without mutating inventory.

- [ ] **Step 5: Review the approved specification line by line**

Confirm every section in
`docs/superpowers/specs/2026-07-17-player-auto-heal-design.md` maps to a passing
test or explicit visual check. If any defect appears, add a failing regression
test before changing production code.
