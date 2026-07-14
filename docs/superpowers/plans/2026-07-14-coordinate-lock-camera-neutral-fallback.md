# Coordinate Lock Camera-Neutral Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the camera unchanged while Coordinate Lock moves toward the saved coordinate whenever Look at target cannot track an eligible entity.

**Architecture:** Preserve target acquisition and tracking as-is. Simplify `CoordinateLockWorker._act()` so only explicit Look at lock mode turns toward the lock; target mode with no match, an entity API error, or missing pitch uses the existing camera-relative movement key and emits no mouse command.

**Tech Stack:** Python 3.10+, pytest, existing Coordinate Lock worker and fake input clients.

## Global Constraints

- Apply the adjustment only to `target` mode; preserve `lock` and `none` behavior.
- Keep moving toward the saved coordinate with forward, backward, left, or right based on current yaw.
- Preserve jump, stall recovery, error logging, Auto Hit, foreground-window, container, and input-coordination behavior.
- Do not send horizontal or vertical mouse movement when target tracking is unavailable.

---

### Task 1: Camera-Neutral Target Fallback

**Files:**
- Modify: `holoquiz/coordinate_lock.py:630-678`
- Test: `tests/test_coordinate_lock.py:489-581`

**Interfaces:**
- Consumes: `movement_key_for_target(position, lock) -> str | None`, `camera_turn_pixels_for_entity(position, entity) -> tuple[int, int]`, and the existing look-mode constants.
- Produces: revised `CoordinateLockWorker._act()` behavior; no new public interface.

- [ ] **Step 1: Change the three fallback tests first**

Replace the no-match test with:

```python
def test_worker_target_mode_keeps_camera_direction_without_match():
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

    assert keys.events == [("down", "a"), ("up", "a")]
```

Replace the API-error assertions with:

```python
def test_worker_target_api_error_logs_once_and_keeps_camera_direction():
    lock = CoordinateLockConfig("east", 10, 64, 0, active_area=20)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_look_mode="target",
            coordinate_locks=(lock,),
        )
    )
    logs = queue.Queue()
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        logs,
        player_client=FakePlayerClient(
            PlayerPosition(0, 64, 0, heading=0, pitch=0)
        ),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(error=OSError("offline")),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        mouse_mover=lambda x, y: keys.events.append(("move", x, y)),
        key_hold_seconds=0,
    )

    worker.check_once()
    worker.check_once()

    messages = []
    while not logs.empty():
        messages.append(logs.get_nowait())
    assert sum("look-target-error" in message for message in messages) == 1
    assert keys.events == [
        ("down", "a"),
        ("up", "a"),
        ("down", "a"),
        ("up", "a"),
    ]
```

Replace the missing-pitch assertions with:

```python
def test_worker_missing_player_pitch_keeps_camera_direction():
    lock = CoordinateLockConfig("east", 10, 64, 0, active_area=20)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_look_mode="target",
            coordinate_locks=(lock,),
        )
    )
    logs = queue.Queue()
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        logs,
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0, heading=0)),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(
            mobs=(NearbyEntity(4, "Zombie", None, x=0, y=64, z=4),)
        ),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        mouse_mover=lambda x, y: keys.events.append(("move", x, y)),
        key_hold_seconds=0,
    )

    worker.check_once()

    assert keys.events == [("down", "a"), ("up", "a")]
    assert "pitch" in logs.get_nowait().casefold()
```

- [ ] **Step 2: Run the fallback tests and verify RED**

Run:

```powershell
python -m pytest tests/test_coordinate_lock.py::test_worker_target_mode_keeps_camera_direction_without_match tests/test_coordinate_lock.py::test_worker_target_api_error_logs_once_and_keeps_camera_direction tests/test_coordinate_lock.py::test_worker_missing_player_pitch_keeps_camera_direction -q
```

Expected: all three tests FAIL because current target fallback presses `w` and turns the camera toward the east lock.

- [ ] **Step 3: Make target fallback camera-neutral**

Replace the look-mode decision and camera fallback portion of `CoordinateLockWorker._act()` with:

```python
mode = self.controls.get_config().coordinate_lock_look_mode
target = (
    self._look_target(lock)
    if mode == COORDINATE_LOCK_LOOK_TARGET
    else None
)
look_at_lock = mode == COORDINATE_LOCK_LOOK_LOCK

if not move_required:
    key = None
elif look_at_lock:
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
        self._last_look_target_error = ""
    except ValueError as error:
        self._report_look_target_error(error)
        mouse_x = mouse_y = 0
elif look_at_lock:
    mouse_x = camera_turn_pixels_for_target(
        position,
        lock,
        mouse_counts_per_degree=self._mouse_counts_per_degree,
    )
    mouse_y = 0
else:
    mouse_x = mouse_y = 0
```

Keep the existing jump/key assembly and `_apply_movement_and_camera()` call immediately after this block unchanged.

- [ ] **Step 4: Run focused and full tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_coordinate_lock.py -q
python -m pytest
$files = Get-ChildItem -Path holoquiz -Filter *.py | ForEach-Object { $_.FullName }
python -m py_compile $files
git diff --check
```

Expected: Coordinate Lock tests and the full suite PASS, compilation exits 0, and `git diff --check` prints no errors.

- [ ] **Step 5: Commit the adjustment**

```powershell
git add holoquiz/coordinate_lock.py tests/test_coordinate_lock.py
git commit -m "fix: preserve camera without coordinate target"
```
