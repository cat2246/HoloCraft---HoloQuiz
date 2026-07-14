# Coordinate Lock Look at Target Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mutually exclusive Look at target mode that tracks the closest eligible entity in 3D while Coordinate Lock moves the player back to the active saved coordinate.

**Architecture:** Replace the legacy look boolean with a validated `none`/`lock`/`target` mode across config, runtime, and GUI. Extend local API models with player pitch and entity positions, keep target selection and camera geometry in pure helpers, and let the worker independently choose a camera aim point and a movement key each polling cycle.

**Tech Stack:** Python 3.10+, dataclasses, Tkinter/ttk, urllib JSON clients, PyAutoGUI/native relative mouse input, pytest.

## Global Constraints

- Preserve existing Auto Hit behavior and its inclusive five-block target radius.
- Preserve existing Coordinate Lock safeguards for open containers, foreground-window checks, and coordinated keyboard input.
- Match player `custom_name` and mob `name` exactly after trimming and case-folding.
- Measure Look at target Active area from the player using the API-reported entity distance.
- Aim from player position plus 1.62 blocks to target position plus 0.9 blocks.
- Use `http://127.0.0.1:8026/data/player` as the default player endpoint.
- Run `python -m pytest` and `python -m py_compile holoquiz/*.py` before handoff.

---

## File Structure

- `holoquiz/config.py`: look-mode constants, persisted mode, legacy boolean migration, and legacy player-URL migration.
- `holoquiz/runtime.py`: thread-safe live look-mode state and validation.
- `holoquiz/coordinate_lock.py`: nested player/entity parsing, pure target-selection and 3D camera helpers, worker tracking and fallback behavior.
- `holoquiz/gui.py`: mutually exclusive Look at lock and Look at target controls.
- `config.example.json`: document the new mode and player endpoint.
- `tests/test_config.py`: configuration migration/persistence coverage.
- `tests/test_runtime.py`: live mode state coverage.
- `tests/test_coordinate_lock.py`: API parsing, selection, geometry, worker movement/tracking/fallback coverage.
- `tests/test_gui.py`: mutual-exclusion callback coverage.

---

### Task 1: Look Mode Configuration and Runtime State

**Files:**
- Modify: `holoquiz/config.py:35-78, 105-145, 222-245`
- Modify: `holoquiz/runtime.py:33-50, 75-151, 253-255`
- Modify: `holoquiz/coordinate_lock.py:479-501`
- Modify: `holoquiz/gui.py:706-713, 766-768, 1898-1902, 2098-2112`
- Modify: `config.example.json:36-56`
- Test: `tests/test_config.py:15-145`
- Test: `tests/test_runtime.py:73-92`
- Test: `tests/test_coordinate_lock.py:280-315`

**Interfaces:**
- Produces: `COORDINATE_LOCK_LOOK_NONE`, `COORDINATE_LOCK_LOOK_LOCK`, `COORDINATE_LOCK_LOOK_TARGET`, `VALID_COORDINATE_LOCK_LOOK_MODES`, `BotConfig.coordinate_lock_look_mode: str`, and `RuntimeControls.set_coordinate_lock_look_mode(mode: str) -> None`.
- Consumes: no interfaces from later tasks.

- [ ] **Step 1: Write failing configuration and runtime tests**

Replace legacy assertions and add migration cases:

```python
from holoquiz.config import (
    COORDINATE_LOCK_LOOK_LOCK,
    COORDINATE_LOCK_LOOK_NONE,
    COORDINATE_LOCK_LOOK_TARGET,
)


def test_load_config_migrates_legacy_coordinate_look_and_player_url(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "coordinate_lock_look_at_enabled": True,
                "player_data_url": "http://localhost:8025/data/player",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.coordinate_lock_look_mode == COORDINATE_LOCK_LOOK_LOCK
    assert config.player_data_url == "http://127.0.0.1:8026/data/player"


def test_new_coordinate_look_mode_takes_precedence_over_legacy_boolean(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "coordinate_lock_look_mode": "target",
                "coordinate_lock_look_at_enabled": True,
            }
        ),
        encoding="utf-8",
    )

    assert load_config(config_path).coordinate_lock_look_mode == (
        COORDINATE_LOCK_LOOK_TARGET
    )


def test_save_coordinate_locks_persists_mode_without_legacy_boolean(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    save_coordinate_lock_settings(
        config_path,
        [],
        enabled=True,
        look_mode=COORDINATE_LOCK_LOOK_TARGET,
    )

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["coordinate_lock_look_mode"] == "target"
    assert "coordinate_lock_look_at_enabled" not in raw


def test_runtime_controls_track_coordinate_lock_look_mode():
    controls = RuntimeControls.from_config(BotConfig())

    controls.set_coordinate_lock_look_mode(COORDINATE_LOCK_LOOK_TARGET)

    assert controls.get_config().coordinate_lock_look_mode == "target"
    assert controls.snapshot().coordinate_lock_look_mode == "target"


def test_runtime_controls_reject_invalid_coordinate_lock_look_mode():
    controls = RuntimeControls.from_config(BotConfig())

    try:
        controls.set_coordinate_lock_look_mode("sideways")
    except ValueError as error:
        assert "look mode" in str(error).casefold()
    else:
        raise AssertionError("Expected an invalid look mode to fail")
```

Update the default-config assertion to expect:

```python
"coordinate_lock_look_mode": "none",
"player_data_url": "http://127.0.0.1:8026/data/player",
```

In the existing save/load test, change the save call and assertion to:

```python
save_coordinate_lock_settings(
    config_path,
    locks,
    enabled=True,
    auto_hit_enabled=True,
    auto_hit_min_seconds=0.1,
    auto_hit_max_seconds=0.5,
    look_mode=COORDINATE_LOCK_LOOK_TARGET,
)
assert config.coordinate_lock_look_mode == COORDINATE_LOCK_LOOK_TARGET
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_config.py tests/test_runtime.py -q
```

Expected: FAIL because look-mode constants, fields, save argument, and runtime setter do not exist.

- [ ] **Step 3: Implement configuration and runtime mode**

In `holoquiz/config.py`, define and validate the mode, migrate raw settings before `BotConfig(**values)`, and persist only the new field:

```python
COORDINATE_LOCK_LOOK_NONE = "none"
COORDINATE_LOCK_LOOK_LOCK = "lock"
COORDINATE_LOCK_LOOK_TARGET = "target"
VALID_COORDINATE_LOCK_LOOK_MODES = frozenset(
    {
        COORDINATE_LOCK_LOOK_NONE,
        COORDINATE_LOCK_LOOK_LOCK,
        COORDINATE_LOCK_LOOK_TARGET,
    }
)
LEGACY_PLAYER_DATA_URLS = frozenset(
    {
        "http://localhost:8025/data/player",
        "http://127.0.0.1:8025/data/player",
    }
)
DEFAULT_PLAYER_DATA_URL = "http://127.0.0.1:8026/data/player"


def validate_coordinate_lock_look_mode(mode: str) -> str:
    normalized = str(mode).strip().casefold()
    if normalized not in VALID_COORDINATE_LOCK_LOOK_MODES:
        raise ValueError(f"Invalid coordinate lock look mode: {mode}")
    return normalized
```

Use these `BotConfig` fields:

```python
coordinate_lock_look_mode: str = COORDINATE_LOCK_LOOK_NONE
player_data_url: str = DEFAULT_PLAYER_DATA_URL
```

Add this migration in `load_config` before constructing `BotConfig`:

```python
legacy_look_enabled = bool(values.pop("coordinate_lock_look_at_enabled", False))
values["coordinate_lock_look_mode"] = validate_coordinate_lock_look_mode(
    values.get(
        "coordinate_lock_look_mode",
        COORDINATE_LOCK_LOOK_LOCK
        if legacy_look_enabled
        else COORDINATE_LOCK_LOOK_NONE,
    )
)
if values.get("player_data_url") in LEGACY_PLAYER_DATA_URLS:
    values["player_data_url"] = DEFAULT_PLAYER_DATA_URL
```

Change `save_coordinate_lock_settings` to accept `look_mode: str = COORDINATE_LOCK_LOOK_NONE`, write the validated mode, and remove the old field:

```python
raw_config["coordinate_lock_look_mode"] = validate_coordinate_lock_look_mode(
    look_mode
)
raw_config.pop("coordinate_lock_look_at_enabled", None)
```

In `holoquiz/runtime.py`, replace every look-at boolean snapshot/internal field with `coordinate_lock_look_mode: str`, initialize it from `base_config`, merge it into config/snapshots, and add:

```python
def set_coordinate_lock_look_mode(self, mode: str) -> None:
    validated = validate_coordinate_lock_look_mode(mode)
    with self._lock:
        self._coordinate_lock_look_mode = validated
```

Keep production and tests green before the target UI is added by converting the existing Look at lock call sites in the same task:

```python
# holoquiz/coordinate_lock.py
look_at_lock = (
    self.controls.get_config().coordinate_lock_look_mode
    == COORDINATE_LOCK_LOOK_LOCK
)

# holoquiz/gui.py initialization
self.coordinate_lock_look_at_var = tk.BooleanVar(
    value=config.coordinate_lock_look_mode == COORDINATE_LOCK_LOOK_LOCK
)

# holoquiz/gui.py existing callback
self.controls.set_coordinate_lock_look_mode(
    COORDINATE_LOCK_LOOK_LOCK
    if self.coordinate_lock_look_at_var.get()
    else COORDINATE_LOCK_LOOK_NONE
)
```

Change all GUI save calls to pass `look_mode=self.controls.get_config().coordinate_lock_look_mode`. Update the existing Look at lock worker fixture to pass `coordinate_lock_look_mode="lock"` instead of the removed constructor keyword.

Update the Coordinate Lock test fake so dependency injection continues to match the new configured endpoint:

```python
class FakePlayerClient:
    url = "http://127.0.0.1:8026/data/player"
```

Update `config.example.json` to contain:

```json
"coordinate_lock_look_mode": "none",
"player_data_url": "http://127.0.0.1:8026/data/player"
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest -q
```

Expected: the full suite PASS with no warnings.

- [ ] **Step 5: Commit Task 1**

```powershell
git add holoquiz/config.py holoquiz/runtime.py holoquiz/coordinate_lock.py holoquiz/gui.py config.example.json tests/test_config.py tests/test_runtime.py tests/test_coordinate_lock.py
git commit -m "feat: add coordinate lock look modes"
```

---

### Task 2: Player/Entity Parsing, Selection, and 3D Aim Geometry

**Files:**
- Modify: `holoquiz/coordinate_lock.py:18-165, 224-258`
- Test: `tests/test_coordinate_lock.py:1-120, 194-275`

**Interfaces:**
- Consumes: look-mode constants from Task 1.
- Produces: `PlayerPosition.pitch`, entity coordinates, `nearest_look_target()`, `camera_angle_deltas_for_entity()`, and `camera_turn_pixels_for_entity()` for Task 3.

- [ ] **Step 1: Write failing parser, selection, and geometry tests**

Add imports for the new helpers and these tests:

```python
def test_player_data_client_reads_nested_position_and_rotation():
    client = PlayerDataClient(
        opener=lambda *_args, **_kwargs: FakeResponse(
            {
                "position": {"x": 58.25, "y": 116, "z": -181.5},
                "rotation": {"yaw": -122.5, "pitch": 3.25},
            }
        )
    )

    assert client.get_position() == PlayerPosition(
        58.25, 116.0, -181.5, heading=-122.5, pitch=3.25
    )


def test_player_data_client_keeps_legacy_flat_shape_without_pitch():
    client = PlayerDataClient(
        opener=lambda *_args, **_kwargs: FakeResponse(
            {"posX": 1, "posY": 64, "posZ": 2, "heading": 90}
        )
    )

    assert client.get_position() == PlayerPosition(1, 64, 2, heading=90, pitch=None)


def test_nearby_entity_client_reads_world_position():
    client = NearbyEntityClient(
        opener=lambda *_args, **_kwargs: FakeResponse(
            {
                "players": [
                    {
                        "distance": 4.5,
                        "name": "Alex",
                        "custom_name": "Tatsunoko",
                        "position": {"x": 4, "y": 64, "z": 3},
                    }
                ]
            }
        )
    )

    assert client.get_players() == (
        NearbyEntity(4.5, "Alex", "Tatsunoko", x=4, y=64, z=3),
    )


def test_nearest_look_target_filters_types_name_and_active_area():
    lock = CoordinateLockConfig(
        "farm",
        0,
        64,
        0,
        active_area=20,
        auto_hit_players=True,
        auto_hit_mobs=False,
        auto_hit_target_name="Tatsunoko",
    )
    players = (
        NearbyEntity(8, "Alex", "Other", x=8, y=64, z=0),
        NearbyEntity(6, "Alex", "tatsunoko", x=6, y=64, z=0),
        NearbyEntity(21, "Alex", "Tatsunoko", x=21, y=64, z=0),
    )
    mobs = (NearbyEntity(2, "Tatsunoko", None, x=2, y=64, z=0),)

    assert nearest_look_target(lock, players=players, mobs=mobs) == players[1]


def test_nearest_look_target_chooses_closest_when_name_is_any():
    lock = CoordinateLockConfig("farm", 0, 64, 0, active_area=20)
    players = (NearbyEntity(7, "Alex", None, x=7, y=64, z=0),)
    mobs = (NearbyEntity(3, "Zombie", None, x=3, y=64, z=0),)

    assert nearest_look_target(lock, players=players, mobs=mobs) == mobs[0]


def test_camera_angle_deltas_aim_at_target_body_center():
    position = PlayerPosition(0, 64, 0, heading=0, pitch=0)
    target = NearbyEntity(10, "Zombie", None, x=10, y=64, z=0)

    yaw_delta, pitch_delta = camera_angle_deltas_for_entity(position, target)

    assert yaw_delta == -90
    assert 4.0 < pitch_delta < 4.2


def test_camera_turn_for_entity_requires_player_pitch():
    position = PlayerPosition(0, 64, 0, heading=0, pitch=None)
    target = NearbyEntity(10, "Zombie", None, x=10, y=64, z=0)

    try:
        camera_turn_pixels_for_entity(position, target)
    except ValueError as error:
        assert "pitch" in str(error).casefold()
    else:
        raise AssertionError("Expected target tracking without pitch to fail")
```

Update existing entity-client fixtures with a valid `position` object.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_coordinate_lock.py -q
```

Expected: FAIL because pitch, entity coordinates, selection helpers, and 3D camera helpers are absent.

- [ ] **Step 3: Implement data models and pure helpers**

Use these model shapes and parsing rules:

```python
PLAYER_EYE_HEIGHT = 1.62
TARGET_BODY_CENTER_HEIGHT = 0.9


@dataclass(frozen=True)
class PlayerPosition:
    x: float
    y: float
    z: float
    heading: float = 0.0
    pitch: float | None = None


@dataclass(frozen=True)
class NearbyEntity:
    distance: float
    name: str
    custom_name: str | None = None
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
```

In `PlayerDataClient.get_position`, parse nested data when both objects exist and otherwise retain the flat parser:

```python
position = payload.get("position")
rotation = payload.get("rotation")
if isinstance(position, dict) and isinstance(rotation, dict):
    return PlayerPosition(
        x=_required_float(position, "x", "Player position"),
        y=_required_float(position, "y", "Player position"),
        z=_required_float(position, "z", "Player position"),
        heading=_required_float(rotation, "yaw", "Player rotation"),
        pitch=_required_float(rotation, "pitch", "Player rotation"),
    )
return PlayerPosition(
    x=_coordinate(payload, "posX", "x"),
    y=_coordinate(payload, "posY", "y"),
    z=_coordinate(payload, "posZ", "z"),
    heading=float(payload.get("heading", payload.get("yaw", 0.0))),
)
```

Define `_required_float` to reject missing, non-numeric, and non-finite values. Parse each entity's `position` with it before constructing `NearbyEntity`:

```python
def _required_float(payload: dict[str, Any], key: str, context: str) -> float:
    try:
        value = float(payload[key])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{context} has an invalid {key}.") from error
    if not math.isfinite(value):
        raise ValueError(f"{context} has an invalid {key}.")
    return value
```

Implement target selection without the Auto Hit five-block restriction:

```python
def _entity_name_matches(
    entity: NearbyEntity,
    *,
    target_name: str,
    name_attribute: str,
) -> bool:
    normalized_target = target_name.strip().casefold()
    if not normalized_target:
        return True
    candidate = getattr(entity, name_attribute)
    return candidate is not None and candidate.strip().casefold() == normalized_target


def nearest_look_target(
    lock: CoordinateLockConfig,
    *,
    players: tuple[NearbyEntity, ...] = (),
    mobs: tuple[NearbyEntity, ...] = (),
) -> NearbyEntity | None:
    candidates = []
    if lock.auto_hit_players:
        candidates.extend(
            entity
            for entity in players
            if entity.distance <= lock.active_area
            and _entity_name_matches(
                entity,
                target_name=lock.auto_hit_target_name,
                name_attribute="custom_name",
            )
        )
    if lock.auto_hit_mobs:
        candidates.extend(
            entity
            for entity in mobs
            if entity.distance <= lock.active_area
            and _entity_name_matches(
                entity,
                target_name=lock.auto_hit_target_name,
                name_attribute="name",
            )
        )
    return min(candidates, key=lambda entity: entity.distance, default=None)
```

Refactor `entity_matches_auto_hit_target` to combine `_entity_name_matches` with `entity.distance <= AUTO_HIT_TARGET_DISTANCE`.

Implement Minecraft yaw/pitch geometry and adaptive mouse counts:

```python
def camera_angle_deltas_for_entity(
    position: PlayerPosition,
    entity: NearbyEntity,
) -> tuple[float, float]:
    if position.pitch is None:
        raise ValueError("Player endpoint is missing camera pitch.")
    delta_x = entity.x - position.x
    delta_z = entity.z - position.z
    horizontal_distance = math.hypot(delta_x, delta_z)
    target_yaw = math.degrees(math.atan2(-delta_x, delta_z))
    target_pitch = math.degrees(
        math.atan2(
            position.y + PLAYER_EYE_HEIGHT
            - (entity.y + TARGET_BODY_CENTER_HEIGHT),
            horizontal_distance,
        )
    )
    yaw_delta = (target_yaw - position.heading + 180.0) % 360.0 - 180.0
    return yaw_delta, target_pitch - position.pitch


def camera_turn_pixels_for_entity(
    position: PlayerPosition,
    entity: NearbyEntity,
    *,
    mouse_counts_per_degree: float = 64.0,
) -> tuple[int, int]:
    yaw_delta, pitch_delta = camera_angle_deltas_for_entity(position, entity)
    return (
        _adaptive_camera_counts(yaw_delta, mouse_counts_per_degree),
        _adaptive_camera_counts(pitch_delta, mouse_counts_per_degree),
    )
```

Extract the angle threshold, strength, clamping, and rounding into this helper; retain the lock-distance multiplier in `camera_turn_pixels_for_target` so its existing tests remain meaningful:

```python
def _adaptive_camera_counts(
    angle_delta: float,
    mouse_counts_per_degree: float,
    *,
    strength_multiplier: float = 1.0,
) -> int:
    absolute_angle = abs(angle_delta)
    if absolute_angle < 0.75:
        return 0
    angle_strength = 0.22 + 0.68 * min(absolute_angle / 90.0, 1.0)
    correction_degrees = angle_delta * angle_strength * strength_multiplier
    mouse_counts = correction_degrees * mouse_counts_per_degree
    return round(max(-9600.0, min(9600.0, mouse_counts)))
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_coordinate_lock.py -q
```

Expected: PASS with no warnings.

- [ ] **Step 5: Commit Task 2**

```powershell
git add holoquiz/coordinate_lock.py tests/test_coordinate_lock.py
git commit -m "feat: calculate closest target camera aim"
```

---

### Task 3: Worker Tracking, Movement, and Fallback

**Files:**
- Modify: `holoquiz/coordinate_lock.py:280-625`
- Test: `tests/test_coordinate_lock.py:280-815`

**Interfaces:**
- Consumes: Task 1 look-mode constants and Task 2 selection/camera helpers.
- Produces: complete Coordinate Lock worker behavior for the GUI in Task 4.

- [ ] **Step 1: Write failing worker behavior tests**

Add worker tests covering tracking while moving, tracking while already locked, closest-target selection, and fallback:

```python
def test_worker_tracks_closest_target_while_strafing_toward_lock():
    lock = CoordinateLockConfig("home", 10, 64, 0, active_area=20)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_look_mode="target",
            coordinate_locks=(lock,),
        )
    )
    farther = NearbyEntity(8, "Zombie", None, x=0, y=64, z=8)
    closest = NearbyEntity(4, "Zombie", None, x=0, y=64, z=4)
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(
            PlayerPosition(0, 64, 0, heading=0, pitch=0)
        ),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(mobs=(farther, closest)),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        mouse_mover=lambda x, y: keys.events.append(("move", x, y)),
        key_hold_seconds=0,
    )

    worker.check_once()

    assert ("down", "a") in keys.events
    movements = [event for event in keys.events if event[0] == "move"]
    assert sum(event[1] for event in movements) == 0
    assert sum(event[2] for event in movements) > 0


def test_worker_keeps_tracking_target_when_already_at_lock():
    lock = CoordinateLockConfig("home", 0, 64, 0, active_area=20)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_look_mode="target",
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(
            PlayerPosition(0, 64, 0, heading=0, pitch=0)
        ),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(
            mobs=(NearbyEntity(4, "Zombie", None, x=4, y=64, z=0),)
        ),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        mouse_mover=lambda x, y: keys.events.append(("move", x, y)),
        key_hold_seconds=0,
    )

    worker.check_once()

    assert not any(event[0] in {"down", "up"} for event in keys.events)
    assert any(event[0] == "move" for event in keys.events)


def test_worker_target_mode_falls_back_to_look_at_lock_without_match():
    lock = CoordinateLockConfig("east", 10, 64, 0, active_area=20)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_look_mode="target",
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(
            PlayerPosition(0, 64, 0, heading=0, pitch=0)
        ),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        mouse_mover=lambda x, y: keys.events.append(("move", x, y)),
        key_hold_seconds=0,
    )

    worker.check_once()

    assert keys.events[0] == ("down", "w")
    assert sum(event[1] for event in keys.events if event[0] == "move") < 0


def test_worker_target_api_error_logs_once_and_falls_back_to_lock():
    lock = CoordinateLockConfig("east", 10, 64, 0, active_area=20)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_look_mode="target",
            coordinate_locks=(lock,),
        )
    )
    logs = queue.Queue()
    worker = CoordinateLockWorker(
        controls,
        logs,
        player_client=FakePlayerClient(
            PlayerPosition(0, 64, 0, heading=0, pitch=0)
        ),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(error=OSError("offline")),
        pyautogui_module=FakePyAutoGui(),
        foreground_provider=lambda: True,
        mouse_mover=lambda _x, _y: None,
        key_hold_seconds=0,
    )

    worker.check_once()
    worker.check_once()

    messages = []
    while not logs.empty():
        messages.append(logs.get_nowait())
    assert sum("look-target-error" in message for message in messages) == 1
```

Update the existing Look at lock worker test to configure `coordinate_lock_look_mode="lock"`.

- [ ] **Step 2: Run worker tests and verify RED**

Run:

```powershell
python -m pytest tests/test_coordinate_lock.py -q
```

Expected: FAIL because the worker does not select targets, move the camera vertically, track while locked, or fall back from target errors.

- [ ] **Step 3: Implement independent camera and movement decisions**

Add a throttled look-target error field and selection method:

```python
self._last_look_target_error = ""


def _look_target(self, lock: CoordinateLockConfig) -> NearbyEntity | None:
    try:
        players = self.entity_client.get_players() if lock.auto_hit_players else ()
        mobs = self.entity_client.get_mobs() if lock.auto_hit_mobs else ()
        target = nearest_look_target(lock, players=players, mobs=mobs)
        self._last_look_target_error = ""
        return target
    except Exception as error:
        self._report_look_target_error(error)
        return None


def _report_look_target_error(self, error: Exception) -> None:
    message = f"[coordinate-lock-look-target-error] {error}"
    if message != self._last_look_target_error:
        self.log_queue.put(message)
        self._last_look_target_error = message
```

Refactor movement into `_act(position, lock, *, move_required)`:

```python
def _act(
    self,
    position: PlayerPosition,
    lock: CoordinateLockConfig,
    *,
    move_required: bool,
) -> None:
    mode = self.controls.get_config().coordinate_lock_look_mode
    target = self._look_target(lock) if mode == COORDINATE_LOCK_LOOK_TARGET else None
    fallback_to_lock = mode == COORDINATE_LOCK_LOOK_LOCK or (
        mode == COORDINATE_LOCK_LOOK_TARGET and target is None
    )

    if not move_required:
        key = None
    elif fallback_to_lock:
        key = "w"
    else:
        key = movement_key_for_target(position, lock)

    if target is not None:
        try:
            mouse_x, mouse_y = camera_turn_pixels_for_entity(
                position,
                target,
                mouse_counts_per_degree=self._mouse_counts_per_degree,
            )
        except ValueError as error:
            self._report_look_target_error(error)
            target = None
            fallback_to_lock = True
            key = "w" if move_required else None
            mouse_x = camera_turn_pixels_for_target(
                position,
                lock,
                mouse_counts_per_degree=self._mouse_counts_per_degree,
            )
            mouse_y = 0
    elif fallback_to_lock:
        mouse_x = camera_turn_pixels_for_target(
            position,
            lock,
            mouse_counts_per_degree=self._mouse_counts_per_degree,
        )
        mouse_y = 0
    else:
        mouse_x = mouse_y = 0

    should_jump = move_required and (
        lock.y - position.y > 0.6 or self._stalled_checks >= 3
    )
    keys = ([key] if key else []) + (["space"] if should_jump else [])
    if not keys and not mouse_x and not mouse_y:
        return

    self._apply_movement_and_camera(keys, mouse_x, mouse_y, position)
```

Extract the current input-session/key-release logic into `_apply_movement_and_camera`. Change `_smooth_camera_turn` to accept both axes, compute the step count from `max(abs(mouse_x), abs(mouse_y))`, and distribute both totals across the eased steps:

```python
def _apply_movement_and_camera(
    self,
    keys: list[str],
    mouse_x: int,
    mouse_y: int,
    position: PlayerPosition,
) -> None:
    with self._input_coordinator.movement_session() as movement_allowed:
        if not movement_allowed:
            return
        pyautogui = self._pyautogui or self._load_pyautogui()
        pressed_keys: list[str] = []
        try:
            for key in keys:
                pyautogui.keyDown(key)
                pressed_keys.append(key)
            if mouse_x or mouse_y:
                self._smooth_camera_turn(mouse_x, mouse_y, pyautogui)
                self._last_camera_command = mouse_x
                self._last_camera_heading = position.heading
            else:
                self._stop_event.wait(self.key_hold_seconds)
        finally:
            for key in reversed(pressed_keys):
                pyautogui.keyUp(key)
```

```python
def _smooth_camera_turn(
    self,
    mouse_x: int,
    mouse_y: int,
    pyautogui: Any,
) -> None:
    magnitude = max(abs(mouse_x), abs(mouse_y))
    step_count = max(12, min(120, math.ceil(magnitude / 18)))
    step_seconds = self.key_hold_seconds / step_count
    previous_x = previous_y = 0
    for step in range(1, step_count + 1):
        progress = step / step_count
        eased_progress = 1.0 - (1.0 - progress) ** 2
        current_x = round(mouse_x * eased_progress)
        current_y = round(mouse_y * eased_progress)
        step_x = current_x - previous_x
        step_y = current_y - previous_y
        if step_x or step_y:
            self._turn_camera(step_x, step_y, pyautogui)
        previous_x, previous_y = current_x, current_y
        if self._stop_event.wait(step_seconds):
            break
```

In `check_once`, call `_act` both outside and inside tolerance after the foreground check:

```python
move_required = distance > config.coordinate_lock_tolerance
if not self._foreground_provider():
    self._status(
        "[coordinate-lock] Waiting for Minecraft to be the active window."
    )
    return
if move_required:
    self._update_stall_state(position)
self._act(position, lock, move_required=move_required)
if not move_required:
    self._status(
        "[coordinate-lock] Position locked at "
        f"{lock.x:g}, {lock.y:g}, {lock.z:g}."
    )
    self._stalled_checks = 0
```

Keep camera calibration based on yaw feedback and store the horizontal component of each command. Pitch uses the same Minecraft sensitivity scale and fresh pitch feedback closes the vertical loop on subsequent polls.

- [ ] **Step 4: Run Coordinate Lock tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_coordinate_lock.py -q
```

Expected: PASS with no warnings.

- [ ] **Step 5: Commit Task 3**

```powershell
git add holoquiz/coordinate_lock.py tests/test_coordinate_lock.py
git commit -m "feat: track closest coordinate lock target"
```

---

### Task 4: Mutually Exclusive GUI Controls and Final Verification

**Files:**
- Modify: `holoquiz/gui.py:700-715, 760-770, 1200-1230, 1898-1902, 2098-2112`
- Test: `tests/test_gui.py:210-375`

**Interfaces:**
- Consumes: Task 1 look modes/runtime setter and Task 3 completed worker behavior.
- Produces: user-selectable and persisted Look at lock / Look at target UI.

- [ ] **Step 1: Write failing GUI mutual-exclusion tests**

Add:

```python
def test_selecting_look_at_target_deselects_look_at_lock_and_persists():
    saved = []
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.controls = RuntimeControls.from_config(BotConfig())
    panel.coordinate_lock_look_at_lock_var = RecordingVar(True)
    panel.coordinate_lock_look_at_target_var = RecordingVar(True)
    panel._save_coordinate_lock_settings = lambda: saved.append(True)

    panel._on_coordinate_lock_look_mode_toggle("target")

    assert panel.coordinate_lock_look_at_lock_var.value is False
    assert panel.coordinate_lock_look_at_target_var.value is True
    assert panel.controls.get_config().coordinate_lock_look_mode == "target"
    assert saved == [True]


def test_deselecting_active_look_mode_returns_to_none():
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.controls = RuntimeControls.from_config(
        BotConfig(coordinate_lock_look_mode="lock")
    )
    panel.coordinate_lock_look_at_lock_var = RecordingVar(False)
    panel.coordinate_lock_look_at_target_var = RecordingVar(False)
    panel._save_coordinate_lock_settings = lambda: None

    panel._on_coordinate_lock_look_mode_toggle("lock")

    assert panel.controls.get_config().coordinate_lock_look_mode == "none"
```

Define the reusable test helper near the other simple fakes:

```python
class RecordingVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
```

- [ ] **Step 2: Run GUI tests and verify RED**

Run:

```powershell
python -m pytest tests/test_gui.py -q
```

Expected: FAIL because the two variables and shared mode callback do not exist.

- [ ] **Step 3: Implement the GUI controls**

Initialize both BooleanVars from `config.coordinate_lock_look_mode`:

```python
self.coordinate_lock_look_at_lock_var = tk.BooleanVar(
    value=config.coordinate_lock_look_mode == COORDINATE_LOCK_LOOK_LOCK
)
self.coordinate_lock_look_at_target_var = tk.BooleanVar(
    value=config.coordinate_lock_look_mode == COORDINATE_LOCK_LOOK_TARGET
)
```

Place the controls beside each other and move the behavior-row stretch column to 5:

```python
ttk.Checkbutton(
    behavior_row,
    text="Look at lock",
    variable=self.coordinate_lock_look_at_lock_var,
    command=lambda: self._on_coordinate_lock_look_mode_toggle(
        COORDINATE_LOCK_LOOK_LOCK
    ),
).grid(row=0, column=3, sticky="w", padx=(0, 18))
ttk.Checkbutton(
    behavior_row,
    text="Look at target",
    variable=self.coordinate_lock_look_at_target_var,
    command=lambda: self._on_coordinate_lock_look_mode_toggle(
        COORDINATE_LOCK_LOOK_TARGET
    ),
).grid(row=0, column=4, sticky="w")
```

Implement shared selection behavior:

```python
def _on_coordinate_lock_look_mode_toggle(self, mode: str) -> None:
    selected_var = (
        self.coordinate_lock_look_at_lock_var
        if mode == COORDINATE_LOCK_LOOK_LOCK
        else self.coordinate_lock_look_at_target_var
    )
    other_var = (
        self.coordinate_lock_look_at_target_var
        if mode == COORDINATE_LOCK_LOOK_LOCK
        else self.coordinate_lock_look_at_lock_var
    )
    if selected_var.get():
        other_var.set(False)
        selected_mode = mode
    else:
        selected_mode = COORDINATE_LOCK_LOOK_NONE
    self.controls.set_coordinate_lock_look_mode(selected_mode)
    self._save_coordinate_lock_settings()
```

Pass `look_mode=self.controls.get_config().coordinate_lock_look_mode` in both GUI calls to `save_coordinate_lock_settings`.

- [ ] **Step 4: Run focused GUI and Coordinate Lock tests**

Run:

```powershell
python -m pytest tests/test_gui.py tests/test_coordinate_lock.py -q
```

Expected: PASS with no warnings.

- [ ] **Step 5: Run full verification**

Run:

```powershell
python -m pytest
python -m py_compile holoquiz/*.py
git diff --check
```

Expected: all tests pass, compilation exits 0, and `git diff --check` prints no errors.

- [ ] **Step 6: Commit Task 4**

```powershell
git add holoquiz/gui.py tests/test_gui.py
git commit -m "feat: add look at target control"
```
