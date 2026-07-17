# Auto Heal Percentage and Return Item Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trigger Auto Heal from integer health/hunger percentages and safely switch to one configured global Return Item after healing.

**Architecture:** Migrate rule thresholds to explicit percentage fields while retaining same-number legacy JSON reads. Persist one exact-name Return Item through the existing config/runtime/GUI path, resolve its current hotbar slot from the same fresh player snapshot used for healing selection, and run a release-before-return input sequence with foreground, container, and shutdown gates.

**Tech Stack:** Python 3.10+, frozen dataclasses, JSON configuration, Tkinter/ttk, PyAutoGUI-compatible input backend, pytest.

## Global Constraints

- `health_percent_below` and `hunger_percent_below` are integers from `0` through `100`; zero disables a condition and at least one condition must be enabled.
- Trigger conditions retain strict `<` comparison and OR semantics.
- Health percentage is `current / maximum * 100`, excludes absorption, and cannot trigger from an invalid or non-positive maximum.
- Hunger percentage is `food_level / 20 * 100`; calculated values are clamped to `0..100`.
- New config keys win over legacy keys; same-number migration maps legacy `20` or `20.0` to `20%` and rejects fractional or out-of-range values.
- `auto_heal_return_item_name` stores one global exact display name without trimming or normalization; `""` disables return behavior.
- Only occupied hotbar items can be selected as the Return Item; duplicate exact names resolve to the rightmost hotbar match.
- Release right-click before any return-key attempt. Never press the return key after shutdown, outside Minecraft, or while a container is open.
- Keep exact-name healing matching, right-to-left healing priority, cooldown semantics, and two-second default use duration unchanged.
- Do not modify Minecraft Local Data API.

## File Structure

- Modify `holoquiz/config.py` — percentage rule model, legacy migration, Return Item validation, and serialization.
- Modify `config.example.json` — show percentage keys and the global Return Item setting.
- Modify `holoquiz/runtime.py` — keep Return Item state synchronized across runtime snapshots and live config.
- Modify `holoquiz/gui.py` — pass Return Item state into PlayerTab and persist its callback through the existing Auto Heal save path.
- Modify `holoquiz/auto_heal.py` — percentage math, Return Item resolution, and safe release-before-return behavior.
- Modify `holoquiz/player_view.py` — item action menu, hotbar-only Return Item action, summary/Clear UI, gold outline, and percentage form copy.
- Modify `tests/test_config.py`, `tests/test_runtime.py`, `tests/test_gui.py` — config/runtime/GUI persistence tests.
- Modify `tests/test_auto_heal.py` — percentage, resolver, input order, failure, and safety tests.
- Modify `tests/test_player_view.py` — action-menu, Return Item state, marker, form, and listing tests.

---

### Task 1: Percentage rules and Return Item configuration

**Files:**
- Modify: `holoquiz/config.py`
- Modify: `config.example.json`
- Test: `tests/test_config.py`
- Update fixtures: `tests/test_auto_heal.py`, `tests/test_gui.py`, `tests/test_runtime.py`, `tests/test_player_view.py`

**Interfaces:**
- Consumes: old JSON keys `health_below`/`hunger_below`, new JSON keys `health_percent_below`/`hunger_percent_below`, and optional `auto_heal_return_item_name`.
- Produces: `AutoHealItemConfig(..., health_percent_below: int = 0, hunger_percent_below: int = 0)` and `BotConfig.auto_heal_return_item_name: str = ""`.

- [ ] **Step 1: Write failing migration and precedence tests**

In `tests/test_config.py`, keep the existing Unicode-name load fixture using legacy keys, then assert same-number migration and no load-time rewrite:

```python
before = config_path.read_text(encoding="utf-8")
config = load_config(config_path)

assert config.auto_heal_items == (
    AutoHealItemConfig(name, 30.0, 2.5, 20, 8),
)
assert config_path.read_text(encoding="utf-8") == before
```

Add:

```python
def test_load_auto_heal_prefers_new_percentage_keys(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"auto_heal_items": [{
            "name": "Steak",
            "cooldown_seconds": 5,
            "health_percent_below": 45,
            "hunger_percent_below": 30,
            "health_below": 10,
            "hunger_below": 5,
        }]}),
        encoding="utf-8",
    )

    item = load_config(config_path).auto_heal_items[0]

    assert item.health_percent_below == 45
    assert item.hunger_percent_below == 30


def test_load_auto_heal_accepts_integral_legacy_numbers(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"auto_heal_items": [{
            "name": "Steak",
            "cooldown_seconds": 5,
            "health_below": 10.0,
            "hunger_below": 25.0,
        }]}),
        encoding="utf-8",
    )

    assert load_config(config_path).auto_heal_items[0] == AutoHealItemConfig(
        "Steak", 5.0, 2.0, 10, 25
    )
```

- [ ] **Step 2: Write failing Return Item and serialization tests**

Update the existing save test to call:

```python
save_auto_heal_settings(
    config_path,
    enabled=True,
    items=(AutoHealItemConfig("Steak", 5.0, 2.0, 50, 30),),
    return_item_name=".｡*ﾟ+.*.｡ Sword ｡+..｡*ﾟ",
)
```

Assert unrelated settings remain and the exact output is:

```python
assert raw["dry_run"] is False
assert raw["auto_heal_enabled"] is True
assert raw["auto_heal_return_item_name"] == ".｡*ﾟ+.*.｡ Sword ｡+..｡*ﾟ"
assert raw["auto_heal_items"] == [{
    "name": "Steak",
    "cooldown_seconds": 5.0,
    "use_duration_seconds": 2.0,
    "health_percent_below": 50,
    "hunger_percent_below": 30,
}]
```

Add:

```python
def test_load_config_defaults_missing_return_item_to_empty_string(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}\n", encoding="utf-8")

    assert load_config(config_path).auto_heal_return_item_name == ""


def test_load_config_preserves_return_item_name_exactly(tmp_path):
    name = "  .｡*ﾟ+.*.｡ Sword ｡+..｡*ﾟ  "
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"auto_heal_return_item_name": name}),
        encoding="utf-8",
    )

    assert load_config(config_path).auto_heal_return_item_name == name


def test_load_config_rejects_non_string_return_item_name(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"auto_heal_return_item_name": 7}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="return item name"):
        load_config(config_path)
```

- [ ] **Step 3: Write failing integer validation tests**

Add field-specific JSON cases:

```python
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("health_percent_below", 10.5, "health percentage"),
        ("health_below", 10.5, "health percentage"),
        ("hunger_percent_below", -1, "hunger percentage"),
        ("hunger_below", 101, "hunger percentage"),
    ],
)
def test_load_auto_heal_rejects_invalid_percentage_values(
    tmp_path, field, value, message
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"auto_heal_items": [{
            "name": "Steak",
            "cooldown_seconds": 5,
            field: value,
        }]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_config(config_path)
```

Update invalid dataclass cases to cover fractional, negative, `101`, boolean, and both-zero percentage values.

- [ ] **Step 4: Run config tests and confirm the red state**

Run:

```powershell
python -m pytest tests/test_config.py -q
```

Expected: FAIL because the model still uses absolute threshold names and no Return Item field exists.

- [ ] **Step 5: Rename the dataclass fields and add global config state**

Use:

```python
@dataclass(frozen=True)
class AutoHealItemConfig:
    name: str
    cooldown_seconds: float
    use_duration_seconds: float = 2.0
    health_percent_below: int = 0
    hunger_percent_below: int = 0
```

Add after `auto_heal_items` in `BotConfig`:

```python
auto_heal_return_item_name: str = ""
```

Replace threshold validation with:

```python
for value, label in (
    (item.health_percent_below, "health"),
    (item.hunger_percent_below, "hunger"),
):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 <= value <= 100
    ):
        raise ValueError(
            f"Auto Heal {label} percentage must be an integer between 0 and 100."
        )
if item.health_percent_below == 0 and item.hunger_percent_below == 0:
    raise ValueError("Enable at least one Auto Heal threshold.")
```

In `load_config`, validate without normalizing:

```python
return_item_name = values.get("auto_heal_return_item_name", "")
if not isinstance(return_item_name, str):
    raise ValueError("Auto Heal return item name must be a string.")
values["auto_heal_return_item_name"] = return_item_name
```

- [ ] **Step 6: Implement legacy percentage conversion and new-key-only output**

Add:

```python
def _auto_heal_percent_from_json(
    raw: dict[str, Any],
    *,
    new_key: str,
    legacy_key: str,
    label: str,
) -> int:
    key = new_key if new_key in raw else legacy_key
    value = raw.get(key, 0)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not float(value).is_integer()
    ):
        raise ValueError(
            f"Auto Heal {label} percentage must be an integer between 0 and 100."
        )
    percent = int(value)
    if not 0 <= percent <= 100:
        raise ValueError(
            f"Auto Heal {label} percentage must be an integer between 0 and 100."
        )
    return percent
```

Use it for both fields in `_auto_heal_items_from_json`, with new keys taking precedence. Serialize only:

```python
"health_percent_below": item.health_percent_below,
"hunger_percent_below": item.hunger_percent_below,
```

Change the save signature and body:

```python
def save_auto_heal_settings(
    path: Path,
    *,
    enabled: bool,
    items: Sequence[AutoHealItemConfig],
    return_item_name: str,
) -> None:
    if not isinstance(return_item_name, str):
        raise ValueError("Auto Heal return item name must be a string.")
    raw_config = _read_existing_config_object(path)
    raw_config["auto_heal_enabled"] = bool(enabled)
    raw_config["auto_heal_items"] = [
        _auto_heal_item_to_json(item)
        for item in validate_auto_heal_items(items)
    ]
    raw_config["auto_heal_return_item_name"] = return_item_name
    path.write_text(json.dumps(raw_config, indent=2) + "\n", encoding="utf-8")
```

- [ ] **Step 7: Update example config and fixtures**

Use this disabled example:

```json
"auto_heal_enabled": false,
"auto_heal_items": [
  {
    "name": "Steak",
    "cooldown_seconds": 5.0,
    "use_duration_seconds": 2.0,
    "health_percent_below": 50,
    "hunger_percent_below": 50
  }
],
"auto_heal_return_item_name": ""
```

Rename named constructor arguments and attribute assertions across tests. Keep old names only as quoted migration JSON keys. Audit with:

```powershell
rg -n "\.(health_below|hunger_below)|health_below=|hunger_below=" holoquiz tests
```

Expected: no output.

- [ ] **Step 8: Run focused tests and commit**

Run:

```powershell
python -m pytest tests/test_config.py -q
python -m json.tool config.example.json *> $null
```

Expected: config tests pass and JSON validation exits `0`.

Commit:

```powershell
git add -- holoquiz/config.py config.example.json tests/test_config.py tests/test_auto_heal.py tests/test_gui.py tests/test_runtime.py tests/test_player_view.py
git commit -m "feat: add percentage auto heal configuration"
```

---

### Task 2: Runtime and GUI persistence path

**Files:**
- Modify: `holoquiz/runtime.py`
- Modify: `holoquiz/gui.py`
- Test: `tests/test_runtime.py`
- Test: `tests/test_gui.py`

**Interfaces:**
- Consumes: `BotConfig.auto_heal_return_item_name` and extended `save_auto_heal_settings` from Task 1.
- Produces: `RuntimeSnapshot.auto_heal_return_item_name`, `RuntimeControls.get/set_auto_heal_return_item_name`, PlayerTab option `auto_heal_return_item_name`, and callback `on_auto_heal_return_item_changed(str)`.

- [ ] **Step 1: Write failing runtime state tests**

Extend `test_runtime_controls_track_auto_heal_settings`:

```python
controls.set_auto_heal_return_item_name("  Custom Sword  ")

assert controls.get_auto_heal_return_item_name() == "  Custom Sword  "
assert controls.snapshot().auto_heal_return_item_name == "  Custom Sword  "
assert controls.get_config().auto_heal_return_item_name == "  Custom Sword  "
```

Add replacement/clear behavior:

```python
def test_runtime_controls_replace_and_clear_return_item_name():
    controls = RuntimeControls.from_config(
        BotConfig(auto_heal_return_item_name="Sword")
    )

    controls.set_auto_heal_return_item_name("Axe")
    assert controls.get_auto_heal_return_item_name() == "Axe"
    controls.set_auto_heal_return_item_name("")
    assert controls.get_auto_heal_return_item_name() == ""
```

- [ ] **Step 2: Write failing GUI option and persistence tests**

Extend the options expectation:

```python
assert gui.player_tab_auto_heal_options(config) == {
    "auto_heal_enabled": True,
    "auto_heal_items": (item,),
    "auto_heal_return_item_name": "Sword",
}
```

Add:

```python
def test_return_item_update_runtime_and_persist_exact_name(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"dry_run": false}\n', encoding="utf-8")
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.config_path = config_path
    panel.controls = RuntimeControls.from_config(BotConfig())
    name = "  .｡*ﾟ+.*.｡ Sword ｡+..｡*ﾟ  "

    panel._on_auto_heal_return_item_changed(name)

    assert panel.controls.get_auto_heal_return_item_name() == name
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["auto_heal_return_item_name"] == name
    assert persisted["dry_run"] is False
```

- [ ] **Step 3: Run focused tests and confirm the red state**

Run:

```powershell
python -m pytest tests/test_runtime.py tests/test_gui.py -q
```

Expected: FAIL because runtime and GUI have no Return Item state or callback.

- [ ] **Step 4: Extend runtime snapshots and controls**

Add `auto_heal_return_item_name: str` to `RuntimeSnapshot`. In `RuntimeControls.__init__`:

```python
self._auto_heal_return_item_name = base_config.auto_heal_return_item_name
```

Include it in `get_config()` and `snapshot()`:

```python
auto_heal_return_item_name=self._auto_heal_return_item_name,
```

Add:

```python
def get_auto_heal_return_item_name(self) -> str:
    with self._lock:
        return self._auto_heal_return_item_name

def set_auto_heal_return_item_name(self, name: str) -> None:
    if not isinstance(name, str):
        raise ValueError("Auto Heal return item name must be a string.")
    with self._lock:
        self._auto_heal_return_item_name = name
```

- [ ] **Step 5: Wire GUI options, callback, and persistence**

Return the new option from `player_tab_auto_heal_options`:

```python
"auto_heal_return_item_name": config.auto_heal_return_item_name,
```

Pass this callback to `PlayerTab`:

```python
on_auto_heal_return_item_changed=(
    self._on_auto_heal_return_item_changed
),
```

Include the runtime value in `_save_auto_heal_settings`:

```python
return_item_name=config.auto_heal_return_item_name,
```

Add:

```python
def _on_auto_heal_return_item_changed(self, name: str) -> None:
    self.controls.set_auto_heal_return_item_name(name)
    self._save_auto_heal_settings()
```

- [ ] **Step 6: Run focused tests and commit**

Run:

```powershell
python -m pytest tests/test_runtime.py tests/test_gui.py -q
```

Expected: all runtime and GUI persistence tests pass.

Commit:

```powershell
git add -- holoquiz/runtime.py holoquiz/gui.py tests/test_runtime.py tests/test_gui.py
git commit -m "feat: persist global return item"
```

---

### Task 3: Percentage thresholds and Return Item resolver

**Files:**
- Modify: `holoquiz/auto_heal.py`
- Test: `tests/test_auto_heal.py`

**Interfaces:**
- Consumes: percentage rule fields, `BotConfig.auto_heal_return_item_name`, and the existing inventory snapshot.
- Produces: `auto_heal_threshold_met(snapshot, rule): bool` and `find_return_hotbar_slot(snapshot, return_item_name): int | None`.

- [ ] **Step 1: Extend the player snapshot fixture for boundary values**

Use:

```python
def player_snapshot(
    *,
    health,
    hunger,
    maximum_health=20,
    hotbar=None,
    main=None,
    connected=True,
):
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
        "connected": connected,
        "health": {
            "current": health,
            "max": maximum_health,
            "absorption": 0,
        },
        "hunger": {"food_level": hunger, "saturation": 0},
        "inventory": inventory,
    })
```

- [ ] **Step 2: Write failing percentage tests**

Add:

```python
def test_health_percentage_is_strict_and_uses_maximum_health():
    rule = AutoHealItemConfig("Steak", 0, 2, 50, 0)

    assert auto_heal_threshold_met(
        player_snapshot(health=9.9, maximum_health=20, hunger=20), rule
    )
    assert not auto_heal_threshold_met(
        player_snapshot(health=10, maximum_health=20, hunger=20), rule
    )


def test_hunger_percentage_is_strict_and_clamped():
    rule = AutoHealItemConfig("Steak", 0, 2, 0, 50)

    assert auto_heal_threshold_met(player_snapshot(health=20, hunger=9), rule)
    assert not auto_heal_threshold_met(player_snapshot(health=20, hunger=10), rule)
    assert auto_heal_threshold_met(player_snapshot(health=20, hunger=-5), rule)
    assert not auto_heal_threshold_met(player_snapshot(health=20, hunger=25), rule)


@pytest.mark.parametrize("maximum", [0, -1, float("nan"), float("inf")])
def test_invalid_maximum_health_disables_only_health_condition(maximum):
    health_only = AutoHealItemConfig("Potion", 0, 2, 50, 0)
    hunger_fallback = AutoHealItemConfig("Potion", 0, 2, 50, 50)
    snapshot = player_snapshot(health=0, maximum_health=maximum, hunger=5)

    assert not auto_heal_threshold_met(snapshot, health_only)
    assert auto_heal_threshold_met(snapshot, hunger_fallback)
```

- [ ] **Step 3: Write failing Return Item resolution tests**

Import `find_return_hotbar_slot` and add:

```python
def test_return_item_resolver_uses_rightmost_exact_hotbar_name():
    snapshot = player_snapshot(
        health=20,
        hunger=20,
        hotbar={0: "Sword", 5: "Sword", 8: "sword"},
    )

    assert find_return_hotbar_slot(snapshot, "Sword") == 5


def test_return_item_resolver_ignores_empty_name_and_main_inventory():
    snapshot = player_snapshot(
        health=20,
        hunger=20,
        hotbar={0: "Sword"},
        main={20: "Main Sword"},
    )

    assert find_return_hotbar_slot(snapshot, "") is None
    assert find_return_hotbar_slot(snapshot, "Main Sword") is None
    assert find_return_hotbar_slot(snapshot, "Missing") is None
```

- [ ] **Step 4: Run tests and confirm the red state**

Run:

```powershell
python -m pytest tests/test_auto_heal.py -q
```

Expected: percentage boundaries fail and the resolver import is unavailable.

- [ ] **Step 5: Implement finite percentage math and rightmost resolution**

Add `import math`, then use:

```python
def auto_heal_threshold_met(
    snapshot: PlayerSnapshot,
    rule: AutoHealItemConfig,
) -> bool:
    health_triggered = False
    maximum = snapshot.health.maximum
    current = snapshot.health.current
    if (
        rule.health_percent_below > 0
        and math.isfinite(maximum)
        and maximum > 0
        and math.isfinite(current)
    ):
        health_percent = min(max(current / maximum * 100.0, 0.0), 100.0)
        health_triggered = health_percent < rule.health_percent_below

    hunger_percent = min(
        max(snapshot.hunger.food_level / 20.0 * 100.0, 0.0),
        100.0,
    )
    hunger_triggered = (
        rule.hunger_percent_below > 0
        and hunger_percent < rule.hunger_percent_below
    )
    return health_triggered or hunger_triggered


def find_return_hotbar_slot(
    snapshot: PlayerSnapshot,
    return_item_name: str,
) -> int | None:
    if not return_item_name:
        return None
    hotbar = build_inventory_layout(snapshot.inventory).hotbar
    for slot in reversed(hotbar):
        if not slot.item.empty and slot.item.name == return_item_name:
            return slot.inventory_slot
    return None
```

- [ ] **Step 6: Run focused tests and commit**

Run:

```powershell
python -m pytest tests/test_auto_heal.py -q
```

Expected: percentage, resolver, exact-name, right-to-left healing priority, and cooldown-selection tests pass.

Commit:

```powershell
git add -- holoquiz/auto_heal.py tests/test_auto_heal.py
git commit -m "feat: resolve percentage healing and return item"
```

---

### Task 4: Release-before-return input sequence

**Files:**
- Modify: `holoquiz/auto_heal.py`
- Test: `tests/test_auto_heal.py`

**Interfaces:**
- Consumes: `find_return_hotbar_slot`, `AutoHealSelection.hotbar_slot`, and `BotConfig.auto_heal_return_item_name`.
- Produces: `_use(selection, return_hotbar_slot): bool` and `_return_to_hotbar_slot(pyautogui, return_hotbar_slot, healing_hotbar_slot): None`.

- [ ] **Step 1: Update success ordering test**

Configure `auto_heal_return_item_name="Sword"`, put `Sword` in slot `0` and `Potion` in slot `8`, then expect:

```python
assert backend.events == [
    ("press", "9"),
    ("mouseDown", "right"),
    ("wait", 2.5),
    ("mouseUp", "right"),
    ("press", "1"),
]
assert worker._last_used_at == {"Potion": 100.0}
```

Extend `auto_heal_worker` with `return_item_name=""`, `container_client=None`, and callable foreground support:

```python
BotConfig(
    program_enabled=True,
    auto_heal_enabled=True,
    auto_heal_items=(configured_rule,),
    auto_heal_return_item_name=return_item_name,
)

container_backend = container_client or FakeContainerClient(container_open)
foreground_provider = foreground if callable(foreground) else lambda: foreground
```

- [ ] **Step 2: Add missing/same-slot and error tests**

Add:

```python
@pytest.mark.parametrize(
    ("return_name", "hotbar"),
    [
        ("", {8: "Potion"}),
        ("Missing", {8: "Potion"}),
        ("Potion", {8: "Potion"}),
    ],
)
def test_worker_skips_unavailable_or_same_slot_return(return_name, hotbar):
    backend = FakeInput()
    worker = auto_heal_worker(
        snapshot=player_snapshot(health=5, hunger=20, hotbar=hotbar),
        backend=backend,
        return_item_name=return_name,
    )

    assert worker.check_once() is True
    assert [event for event in backend.events if event[0] == "press"] == [
        ("press", "9")
    ]


def test_worker_releases_then_returns_when_wait_raises():
    backend = FakeInput()
    worker = auto_heal_worker(
        snapshot=player_snapshot(
            health=5, hunger=20, hotbar={0: "Sword", 8: "Potion"}
        ),
        backend=backend,
        return_item_name="Sword",
        wait_error=RuntimeError("failed wait"),
    )

    with pytest.raises(RuntimeError, match="failed wait"):
        worker.check_once()

    assert backend.events[-2:] == [("mouseUp", "right"), ("press", "1")]
    assert worker._last_used_at == {}


class MouseDownFailInput(FakeInput):
    def mouseDown(self, *, button):
        super().mouseDown(button=button)
        raise RuntimeError("right click failed")


def test_worker_releases_then_returns_when_mouse_down_raises():
    backend = MouseDownFailInput()
    worker = auto_heal_worker(
        snapshot=player_snapshot(
            health=5, hunger=20, hotbar={0: "Sword", 8: "Potion"}
        ),
        backend=backend,
        return_item_name="Sword",
    )

    with pytest.raises(RuntimeError, match="right click failed"):
        worker.check_once()

    assert backend.events == [
        ("press", "9"),
        ("mouseDown", "right"),
        ("mouseUp", "right"),
        ("press", "1"),
    ]
    assert worker._last_used_at == {}
```

- [ ] **Step 3: Add unsafe, shutdown, and non-fatal return failure tests**

Use mutable foreground/container state:

```python
@pytest.mark.parametrize("unsafe_kind", ["foreground", "container"])
def test_worker_skips_return_when_environment_becomes_unsafe(unsafe_kind):
    backend = FakeInput()
    foreground = {"safe": True}
    container = FakeContainerClient(False)
    worker = auto_heal_worker(
        snapshot=player_snapshot(
            health=5, hunger=20, hotbar={0: "Sword", 8: "Potion"}
        ),
        backend=backend,
        return_item_name="Sword",
        foreground=lambda: foreground["safe"],
        container_client=container,
    )

    def make_unsafe(seconds):
        backend.events.append(("wait", seconds))
        if unsafe_kind == "foreground":
            foreground["safe"] = False
        else:
            container.open = True
        return False

    worker._waiter = make_unsafe

    assert worker.check_once() is True
    assert backend.events[-1] == ("mouseUp", "right")
    assert ("press", "1") not in backend.events
```

Add shutdown and restore-backend failure coverage:

```python
def test_worker_never_returns_after_shutdown_begins():
    backend = FakeInput()
    worker = auto_heal_worker(
        snapshot=player_snapshot(
            health=5, hunger=20, hotbar={0: "Sword", 8: "Potion"}
        ),
        backend=backend,
        return_item_name="Sword",
    )

    def stop_during_wait(seconds):
        backend.events.append(("wait", seconds))
        worker._stop_event.set()
        return True

    worker._waiter = stop_during_wait

    assert worker.check_once() is False
    assert backend.events[-1] == ("mouseUp", "right")
    assert ("press", "1") not in backend.events
    assert worker._last_used_at == {}


class ReturnFailInput(FakeInput):
    def press(self, key):
        super().press(key)
        if len([event for event in self.events if event[0] == "press"]) == 2:
            raise RuntimeError("return failed")


def test_return_failure_does_not_fail_completed_use_or_clear_cooldown():
    backend = ReturnFailInput()
    worker = auto_heal_worker(
        snapshot=player_snapshot(
            health=5, hunger=20, hotbar={0: "Sword", 8: "Potion"}
        ),
        backend=backend,
        return_item_name="Sword",
    )

    assert worker.check_once() is True
    assert worker._last_used_at == {"Potion": 100.0}
```

- [ ] **Step 4: Run worker tests and confirm the red state**

Run:

```powershell
python -m pytest tests/test_auto_heal.py -q
```

Expected: return-order tests fail because `check_once` does not resolve or pass a Return Item slot.

- [ ] **Step 5: Resolve from the same snapshot and implement safe return**

In `check_once`, resolve the Return Item immediately before invoking `_use`:

```python
return_hotbar_slot = find_return_hotbar_slot(
    snapshot,
    config.auto_heal_return_item_name,
)
return self._use(selection, return_hotbar_slot)
```

Replace `_use` with:

```python
def _use(
    self,
    selection: AutoHealSelection,
    return_hotbar_slot: int | None,
) -> bool:
    if self._stop_event.is_set() or not self._environment_is_safe():
        return False
    with self._input_coordinator.item_use_session() as allowed:
        if not allowed or self._stop_event.is_set():
            return False
        pyautogui = self._pyautogui or self._load_pyautogui()
        slot_changed = False
        right_press_attempted = False
        interrupted = False
        try:
            pyautogui.press(str(selection.hotbar_slot + 1))
            slot_changed = True
            try:
                right_press_attempted = True
                pyautogui.mouseDown(button="right")
                interrupted = self._waiter(
                    selection.rule.use_duration_seconds
                )
            finally:
                if right_press_attempted:
                    pyautogui.mouseUp(button="right")
        finally:
            if slot_changed:
                self._return_to_hotbar_slot(
                    pyautogui,
                    return_hotbar_slot,
                    selection.hotbar_slot,
                )

        if interrupted:
            return False
        self._last_used_at[selection.item_name] = self._clock()
        self._last_status = ""
        self._status_sink(
            f"[auto-heal] Used {selection.item_name} from hotbar "
            f"slot {selection.hotbar_slot + 1}."
        )
        return True
```

Add:

```python
def _return_to_hotbar_slot(
    self,
    pyautogui: Any,
    return_hotbar_slot: int | None,
    healing_hotbar_slot: int,
) -> None:
    if (
        return_hotbar_slot is None
        or return_hotbar_slot == healing_hotbar_slot
        or self._stop_event.is_set()
    ):
        return
    try:
        if self._stop_event.is_set() or not self._environment_is_safe():
            return
        if self._stop_event.is_set():
            return
        pyautogui.press(str(return_hotbar_slot + 1))
    except Exception as error:
        self._status(f"[auto-heal-return-error] {error}")
```

Only the uninterrupted branch in `_use` records cooldown and emits the success
status. The second stop check in `_return_to_hotbar_slot` closes the race
between environment probing and key injection.

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
python -m pytest tests/test_auto_heal.py -q
```

Expected: all selection, input-order, release, safety, error, shutdown, and cooldown tests pass.

Commit:

```powershell
git add -- holoquiz/auto_heal.py tests/test_auto_heal.py
git commit -m "feat: return to configured item after auto heal"
```

---

### Task 5: Item action menu, Return Item UI, and percentage copy

**Files:**
- Modify: `holoquiz/player_view.py`
- Test: `tests/test_player_view.py`

**Interfaces:**
- Consumes: `auto_heal_return_item_name` and callback from Task 2.
- Produces: `inventory_item_action_labels`, a right-click action menu, hotbar-only selection, Return Item summary/Clear control, gold marker, and percentage-form output.

- [ ] **Step 1: Write failing action-label and callback tests**

Add:

```python
def test_inventory_item_actions_offer_return_only_for_hotbar():
    hotbar = InventorySlot(0, "hotbar", PlayerItem(empty=False, name="Sword"))
    main = InventorySlot(9, "main", PlayerItem(empty=False, name="Steak"))
    configured = (AutoHealItemConfig("Steak", 5, 2, 50, 0),)

    assert inventory_item_action_labels(hotbar, configured) == (
        "Add Auto Heal Item",
        "Set as Return Item",
    )
    assert inventory_item_action_labels(main, configured) == (
        "Edit Auto Heal Item",
    )


def test_player_tab_sets_replaces_and_clears_global_return_item():
    saved = []
    tab = object.__new__(PlayerTab)
    tab.auto_heal_return_item_name = "Old Sword"
    tab.on_auto_heal_return_item_changed = saved.append
    tab.return_item_var = SimpleNamespace(set=lambda value: saved.append(("label", value)))
    tab.return_item_clear_button = SimpleNamespace(
        configure=lambda **value: saved.append(("button", value))
    )
    tab._rerender_inventory = lambda: saved.append("rerender")

    tab._set_return_item("New Sword")
    tab._clear_return_item()

    assert "New Sword" in saved
    assert "" in saved
    assert tab.auto_heal_return_item_name == ""


def test_player_tab_item_action_menu_routes_commands(monkeypatch):
    events = []

    class FakeMenu:
        def __init__(self):
            self.commands = []

        def add_command(self, *, label, command):
            self.commands.append((label, command))

        def add_separator(self):
            events.append("separator")

        def tk_popup(self, x, y):
            events.append(("popup", x, y))

        def grab_release(self):
            events.append("release")

    menu = FakeMenu()
    monkeypatch.setattr(player_view.tk, "Menu", lambda *_args, **_kwargs: menu)
    tab = object.__new__(PlayerTab)
    tab.parent = object()
    tab.auto_heal_items = ()
    tab._show_auto_heal_dialog = lambda name: events.append(("heal", name))
    tab._set_return_item = lambda name: events.append(("return", name))
    slot = InventorySlot(0, "hotbar", PlayerItem(empty=False, name="Sword"))

    tab._open_item_actions(slot, SimpleNamespace(x_root=120, y_root=240))
    menu.commands[0][1]()
    menu.commands[1][1]()

    assert [label for label, _command in menu.commands] == [
        "Add Auto Heal Item",
        "Set as Return Item",
    ]
    assert events == [
        "separator",
        ("popup", 120, 240),
        "release",
        ("heal", "Sword"),
        ("return", "Sword"),
    ]
```

Add `_refresh_return_item_state()` as specified in Step 7 so this state test can
assert label text and button state without constructing Tk.

- [ ] **Step 2: Write failing border and right-click event tests**

Update the current occupied-slot right-click test so the callback records `(slot, event)` and verifies empty slots still do nothing. Add a render-border helper test:

```python
def test_item_slot_border_uses_gold_for_return_item_before_enchantment():
    enchanted = InventorySlot(
        0,
        "hotbar",
        PlayerItem(empty=False, name="Sword", is_enchanted=True),
    )

    assert item_slot_border(enchanted, is_return_item=True) == "#d4a017"
    assert item_slot_border(enchanted, is_return_item=False) == "#9b5de5"
```

- [ ] **Step 3: Write failing percentage form and listing tests**

Add:

```python
@pytest.mark.parametrize(
    ("health", "hunger", "message"),
    [
        ("50.5", "0", "health percentage"),
        ("-1", "0", "health percentage"),
        ("101", "0", "health percentage"),
        ("0", "25.5", "hunger percentage"),
        ("0", "101", "hunger percentage"),
    ],
)
def test_parse_auto_heal_form_rejects_invalid_percentage_text(
    health, hunger, message
):
    with pytest.raises(ValueError, match=message):
        parse_auto_heal_form("Steak", "5", "2", health, hunger)


def test_format_auto_heal_rule_lists_percentage_values():
    item = AutoHealItemConfig("Steak", 5, 2.5, 50, 30)

    assert format_auto_heal_rule(item) == (
        "Cooldown: 5s   Use: 2.5s   Health < 50%   Hunger < 30%"
    )
```

- [ ] **Step 4: Run view tests and confirm the red state**

Run:

```powershell
python -m pytest tests/test_player_view.py -q
```

Expected: imports/state tests fail because action labels, Return Item controls, gold marker, and percentage output are not implemented.

- [ ] **Step 5: Add pure action and border helpers**

Add:

```python
RETURN_ITEM_BORDER = "#d4a017"

def inventory_item_action_labels(
    slot: InventorySlot,
    auto_heal_items: Sequence[AutoHealItemConfig],
) -> tuple[str, ...]:
    configured_names = {item.name for item in auto_heal_items}
    auto_heal_label = (
        "Edit Auto Heal Item"
        if slot.item.name in configured_names
        else "Add Auto Heal Item"
    )
    labels = [auto_heal_label]
    if slot.section == "hotbar":
        labels.append("Set as Return Item")
    return tuple(labels)


def item_slot_border(slot: InventorySlot, *, is_return_item: bool) -> str:
    if is_return_item:
        return RETURN_ITEM_BORDER
    if slot.item.is_enchanted:
        return "#9b5de5"
    return "#555b64"
```

Change `ItemSlotWidget.render` to accept `is_return_item: bool = False` and configure `item_slot_border(...)`.

- [ ] **Step 6: Replace direct right-click dialog opening with an item action menu**

Change the callback type to accept the event and pass it through:

```python
on_right_click: Callable[[InventorySlot, tk.Event | None], None] | None = None

self.on_right_click(self.slot, event)
```

Point all inventory slot widgets to `_open_item_actions`. Implement:

```python
def _open_item_actions(
    self,
    slot: InventorySlot,
    event: tk.Event | None,
) -> None:
    menu = tk.Menu(self.parent, tearoff=False)
    labels = inventory_item_action_labels(slot, self.auto_heal_items)
    menu.add_command(
        label=labels[0],
        command=partial(self._show_auto_heal_dialog, slot.item.name),
    )
    if slot.section == "hotbar":
        menu.add_separator()
        menu.add_command(
            label="Set as Return Item",
            command=partial(self._set_return_item, slot.item.name),
        )
    if event is None:
        return
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()
```

The `event is None` branch keeps unit invocation side-effect-free; live right-click always supplies coordinates.

- [ ] **Step 7: Add PlayerTab Return Item state and controls**

Extend the constructor with:

```python
auto_heal_return_item_name: str = "",
on_auto_heal_return_item_changed: Callable[[str], None] | None = None,
```

Store exact state and callback, then add to the Auto Heal section between the checkbox and empty/rule list:

```python
self.return_item_var = tk.StringVar()
return_row = ttk.Frame(section)
return_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
return_row.columnconfigure(0, weight=1)
ttk.Label(return_row, textvariable=self.return_item_var).grid(
    row=0, column=0, sticky="w"
)
self.return_item_clear_button = ttk.Button(
    return_row,
    text="Clear",
    command=self._clear_return_item,
)
self.return_item_clear_button.grid(row=0, column=1, padx=(8, 0))
```

Move the empty label and rows frame down one row. Add:

```python
def _refresh_return_item_state(self) -> None:
    name = self.auto_heal_return_item_name
    self.return_item_var.set(f"Return Item: {name or 'None'}")
    self.return_item_clear_button.configure(
        state="normal" if name else "disabled"
    )

def _set_return_item(self, name: str) -> None:
    self.auto_heal_return_item_name = name
    self._refresh_return_item_state()
    self._rerender_inventory()
    self.on_auto_heal_return_item_changed(name)

def _clear_return_item(self) -> None:
    self.auto_heal_return_item_name = ""
    self._refresh_return_item_state()
    self._rerender_inventory()
    self.on_auto_heal_return_item_changed("")

def _rerender_inventory(self) -> None:
    if self._snapshot is not None:
        self._render_inventory(self._snapshot)
```

Call `_refresh_return_item_state()` during section construction. In `_render_slot`, pass:

```python
is_return_item=(
    slot.section == "hotbar"
    and not slot.item.empty
    and slot.item.name == self.auto_heal_return_item_name
),
```

- [ ] **Step 8: Implement percentage parsing, prefill, labels, and listing**

Add:

```python
def _parse_auto_heal_percent(value: str, label: str) -> int:
    try:
        return int(value.strip() or "0")
    except ValueError as error:
        raise ValueError(
            f"Auto Heal {label} percentage must be an integer between 0 and 100."
        ) from error
```

Construct rules with `health_percent_below` and `hunger_percent_below`, call the
shared validator, and prefill with:

```python
self.health_var = tk.StringVar(
    value=str(existing.health_percent_below) if existing else "0"
)
self.hunger_var = tk.StringVar(
    value=str(existing.hunger_percent_below) if existing else "0"
)
```

Use these exact labels:

```python
("Use when health below (%)", self.health_var),
("Use when hunger below (%)", self.hunger_var),
```

Format listing text with:

```python
f"Health < {item.health_percent_below}%   "
f"Hunger < {item.hunger_percent_below}%"
```

- [ ] **Step 9: Run view tests and commit**

Run:

```powershell
python -m pytest tests/test_player_view.py -q
```

Expected: action labels, hotbar-only Return Item action, exact global state replacement/Clear, gold override, percentage parsing, and listing tests pass.

Commit:

```powershell
git add -- holoquiz/player_view.py tests/test_player_view.py
git commit -m "feat: add return item inventory controls"
```

---

### Task 6: Complete verification and live UI check

**Files:**
- Verify only after Tasks 1–5.

**Interfaces:**
- Consumes: all implemented tasks.
- Produces: automated, syntax, JSON, static-audit, and visual evidence without changing Minecraft Local Data API.

- [ ] **Step 1: Run complete automated verification**

Run:

```powershell
python -m pytest
python -m py_compile holoquiz\*.py
python -m json.tool config.example.json *> $null
git diff --check
```

Expected: the full pytest suite passes, compilation and JSON validation exit `0`, and the diff check prints nothing.

- [ ] **Step 2: Audit renamed fields and confirm no API dependency**

Run:

```powershell
rg -n "health_percent_below|hunger_percent_below|auto_heal_return_item_name" holoquiz tests config.example.json
rg -n "\.(health_below|hunger_below)|health_below=|hunger_below=|selected_hotbar_slot" holoquiz tests
git status --short
```

Expected: new names appear across config, runtime, worker, GUI, view, and tests; the old attribute patterns and selected-slot API field produce no output; status is clean after planned commits.

- [ ] **Step 3: Launch and visually verify the Player UI**

Run:

```powershell
python holoquiz_gui.py
```

Verify:

1. The Player page still scrolls.
2. Right-clicking an occupied main-inventory item offers Add/Edit Auto Heal Item but not Set as Return Item.
3. Right-clicking an occupied hotbar item also offers Set as Return Item.
4. Selecting the sword updates `Return Item: <exact name>`, enables Clear, and gives every exact-name hotbar match a gold outline.
5. Clear resets the label to `Return Item: None`, disables itself, and removes the gold outline.
6. Auto Heal dialog labels use `(%)`; fractional input reports a field-specific error.
7. Saving `50` renders `Health < 50%` or `Hunger < 50%`.
8. Edit and Remove continue to work.

Close the GUI without changing unrelated settings.

- [ ] **Step 4: Perform an isolated input-sequence smoke check**

Use the test backend, not real keyboard/mouse injection:

```powershell
python -m pytest tests/test_auto_heal.py -q -k "return or releases or cooldown"
```

Expected: all selected worker tests pass and their event assertions prove healing key → right-down → wait → right-up → Return Item key ordering.

- [ ] **Step 5: Record completion evidence**

Report the final pytest pass count, syntax/JSON results, static-audit result, and visual checks. Explicitly state that Minecraft Local Data API was not modified or required.
