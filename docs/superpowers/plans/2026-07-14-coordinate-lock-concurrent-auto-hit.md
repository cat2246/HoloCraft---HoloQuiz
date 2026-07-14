# Coordinate Lock Concurrent Auto Hit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Coordinate Lock Auto Hit clicking at its configured interval while Look at target is still moving the camera or Coordinate Lock is moving the player.

**Architecture:** Add a short-lived `click_session()` to `KeyboardInputCoordinator` that may overlap movement/camera input but remains excluded by pending or active chat. Change only the Auto Hit click boundary to use that session, leaving target eligibility, container checks, foreground checks, camera tracking, and movement unchanged.

**Tech Stack:** Python 3.10+, `contextlib.contextmanager`, `threading`, pytest, existing Coordinate Lock worker and fake clients.

## Global Constraints

- Camera alignment must not be an Auto Hit prerequisite.
- Preserve the existing five-block Auto Hit radius, Players/Mobs selection, and optional Target Name filter.
- Preserve foreground-window, container, program-enabled, Coordinate Lock, active-area, and Auto Hit gates.
- Clicks may overlap movement/camera input but must not overlap pending or active chat input.
- Preserve existing chat priority over movement.
- Do not change camera target selection, camera correction, movement, or Auto Hit interval calculation.

---

### Task 1: Chat-Safe Concurrent Click Session

**Files:**
- Create: `tests/test_keyboard_coordinator.py`
- Modify: `holoquiz/keyboard_coordinator.py:29-49`

**Interfaces:**
- Consumes: `KeyboardInputCoordinator._state_lock` and `_pending_chat_sessions`.
- Produces: `KeyboardInputCoordinator.click_session() -> Iterator[bool]`, a context manager that yields `True` when no chat is pending or active and permits overlap with `movement_session()`.

- [ ] **Step 1: Write the failing coordinator tests**

Create `tests/test_keyboard_coordinator.py` with:

```python
import threading
import time

from holoquiz.keyboard_coordinator import KeyboardInputCoordinator


def test_click_session_is_allowed_during_movement_session():
    coordinator = KeyboardInputCoordinator()

    with coordinator.movement_session() as movement_allowed:
        assert movement_allowed is True
        with coordinator.click_session() as click_allowed:
            assert click_allowed is True


def test_click_session_is_denied_during_chat_session():
    coordinator = KeyboardInputCoordinator()

    with coordinator.chat_session():
        with coordinator.click_session() as click_allowed:
            assert click_allowed is False


def test_click_session_is_denied_while_chat_is_pending():
    coordinator = KeyboardInputCoordinator()

    def send_chat():
        with coordinator.chat_session():
            pass

    with coordinator.movement_session() as movement_allowed:
        assert movement_allowed is True
        chat_thread = threading.Thread(target=send_chat)
        chat_thread.start()
        deadline = time.monotonic() + 1.0
        while True:
            with coordinator._state_lock:
                chat_is_pending = coordinator._pending_chat_sessions > 0
            if chat_is_pending:
                break
            assert time.monotonic() < deadline
            time.sleep(0.001)

        with coordinator.click_session() as click_allowed:
            assert click_allowed is False

    chat_thread.join(timeout=1.0)
    assert chat_thread.is_alive() is False
```

- [ ] **Step 2: Run the coordinator tests and verify RED**

Run:

```powershell
python -m pytest tests/test_keyboard_coordinator.py -q
```

Expected: all three tests FAIL with `AttributeError: 'KeyboardInputCoordinator' object has no attribute 'click_session'`.

- [ ] **Step 3: Implement the minimal click session**

Add this method immediately after `movement_session()` in `holoquiz/keyboard_coordinator.py`:

```python
    @contextmanager
    def click_session(self) -> Iterator[bool]:
        self._state_lock.acquire()
        try:
            yield self._pending_chat_sessions == 0
        finally:
            self._state_lock.release()
```

Keeping `_state_lock` across the yielded click makes the decision atomic with chat startup. It does not acquire `_input_lock`, so an already-active movement/camera session does not suppress the click.

- [ ] **Step 4: Run coordinator and existing input-coordination tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_keyboard_coordinator.py tests/test_coordinate_lock.py::test_worker_pauses_movement_while_chat_is_typing_then_resumes -q
```

Expected: all tests PASS.

- [ ] **Step 5: Commit the coordinator change**

```powershell
git add holoquiz/keyboard_coordinator.py tests/test_keyboard_coordinator.py
git commit -m "feat: coordinate clicks independently from movement"
```

---

### Task 2: Auto Hit During Camera Movement

**Files:**
- Modify: `holoquiz/coordinate_lock.py:759-800`
- Test: `tests/test_coordinate_lock.py:809-1083`

**Interfaces:**
- Consumes: `KeyboardInputCoordinator.click_session() -> Iterator[bool]` from Task 1.
- Produces: revised `CoordinateLockWorker._auto_hit_once() -> bool` behavior that clicks during active movement/camera input while preserving all existing gates.

- [ ] **Step 1: Write the failing Coordinate Lock regression test**

Add this test before `test_worker_auto_hits_for_selected_player_custom_name()` in `tests/test_coordinate_lock.py`:

```python
def test_worker_auto_hits_during_active_camera_movement():
    lock = CoordinateLockConfig("home", 0, 64, 0)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_lock_look_mode="target",
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    coordinator = KeyboardInputCoordinator()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(
            players=(NearbyEntity(2.0, "Alex", None),)
        ),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        input_coordinator=coordinator,
    )
    worker._auto_hit_lock_id = lock.id
    worker._auto_hit_in_range.set()

    with coordinator.movement_session() as camera_movement_allowed:
        assert camera_movement_allowed is True
        assert worker._auto_hit_once() is True

    assert keys.events == [("click", "left")]
```

- [ ] **Step 2: Run the regression test and verify RED**

Run:

```powershell
python -m pytest tests/test_coordinate_lock.py::test_worker_auto_hits_during_active_camera_movement -q
```

Expected: FAIL because `_auto_hit_once()` still requests a nested `movement_session()` and returns `False` while the camera movement session is active.

- [ ] **Step 3: Move the final container check ahead of the click session**

Replace the final `movement_session()` block in `_auto_hit_once()` with the existing final container recheck outside any coordinator context:

```python
        try:
            if self.container_client.is_open():
                self._clear_auto_hit_state()
                return False
        except Exception as error:
            self._status(f"[coordinate-lock-auto-hit-container-error] {error}")
            return False
```

This preserves the post-entity-read container check without holding the coordinator state lock across the local HTTP request.

- [ ] **Step 4: Use the dedicated click session only around the left click**

Immediately after the final container check, add:

```python
        pyautogui = self._pyautogui or self._load_pyautogui()
        with self._input_coordinator.click_session() as input_allowed:
            if not input_allowed:
                return False
            pyautogui.click(button="left", _pause=False)
            return True
```

- [ ] **Step 5: Run the regression and focused safety tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_coordinate_lock.py::test_worker_auto_hits_during_active_camera_movement tests/test_coordinate_lock.py::test_worker_rechecks_inventory_after_nearby_entity_reads tests/test_coordinate_lock.py::test_worker_skips_auto_hit_when_inventory_check_fails tests/test_keyboard_coordinator.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Run full verification**

Run:

```powershell
python -m pytest
$files = Get-ChildItem -Path holoquiz -Filter *.py | ForEach-Object { $_.FullName }
python -m py_compile $files
git diff --check
```

Expected: the full suite PASSes, compilation exits 0, and `git diff --check` prints no errors.

- [ ] **Step 7: Commit the Auto Hit change**

```powershell
git add holoquiz/coordinate_lock.py tests/test_coordinate_lock.py
git commit -m "fix: keep auto hit active during target tracking"
```
