# HoloQuiz Module Toggle and Delay Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent HoloQuiz-only master checkbox and persist the accepted minimum and maximum send-delay values.

**Architecture:** Store `holoquiz_enabled` in `BotConfig` and mirror it in thread-safe runtime controls. Gate only HoloQuiz event parsing after chat-trigger processing, then wire a dedicated GUI checkbox and focused JSON persistence helpers for the toggle and successfully applied delay ranges.

**Tech Stack:** Python 3.10+, dataclasses, Tkinter/ttk, JSON, pytest.

## Global Constraints

- The checkbox label is exactly `HoloQuiz enabled`.
- The checkbox is independent of `Program enabled` and `Find answer`.
- Existing configurations default HoloQuiz to enabled (`True`).
- Disabling HoloQuiz suppresses HoloQuiz question and answer-reveal processing without stopping Screen Watcher, Chat Triggers, Coordinate Lock, or Activity.
- Toggle changes persist immediately to `config.json`.
- Delay values persist only after `Apply` succeeds; invalid input is neither applied nor saved.
- Applied delay persistence writes `send_delay_seconds` as the accepted minimum and writes the accepted minimum and maximum to their range keys.
- Focused config writes preserve unrelated JSON keys.
- Follow test-driven development: run every new test and observe the expected failure before production changes.

---

## File Map

- `holoquiz/config.py`: define the persistent module setting and focused JSON save helpers.
- `holoquiz/runtime.py`: expose the live HoloQuiz enabled state to the GUI and bot.
- `holoquiz/runner.py`: skip only HoloQuiz event processing when the module is disabled.
- `holoquiz/gui.py`: render the checkbox, handle toggles, and save accepted delay ranges.
- `config.example.json`: document the new setting.
- `tests/test_config.py`: verify defaults, explicit loading, and focused persistence.
- `tests/test_runtime.py`: verify live HoloQuiz state updates.
- `tests/test_runner.py`: verify module gating and chat-trigger independence.
- `tests/test_gui.py`: verify controller/handler wiring and successful-only delay persistence.

### Task 1: Persistent Config and Runtime State

**Files:**
- Modify: `holoquiz/config.py:59-95, 214-240`
- Modify: `holoquiz/runtime.py:37-225`
- Modify: `config.example.json:1-8`
- Test: `tests/test_config.py:1-285`
- Test: `tests/test_runtime.py:25-175`

**Interfaces:**
- Produces: `BotConfig.holoquiz_enabled: bool` with default `True`.
- Produces: `save_holoquiz_enabled_setting(path: Path, *, enabled: bool) -> None`.
- Produces: `save_send_delay_settings(path: Path, *, min_seconds: float, max_seconds: float) -> None`.
- Produces: `RuntimeSnapshot.holoquiz_enabled: bool`.
- Produces: `RuntimeControls.is_holoquiz_enabled() -> bool`.
- Produces: `RuntimeControls.set_holoquiz_enabled(enabled: bool) -> None`.

- [ ] **Step 1: Write failing config tests**

Add the new save helpers to the import list in `tests/test_config.py`, add `"holoquiz_enabled": True` after `"program_enabled": True` in the expected generated config, add `"holoquiz_enabled": false` to `test_load_config_overrides_defaults`, and assert it loads as false. Then add:

```python
def test_load_config_without_holoquiz_setting_defaults_enabled(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dry_run": True}), encoding="utf-8")

    assert load_config(config_path).holoquiz_enabled is True


def test_save_holoquiz_enabled_setting_preserves_other_values(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"dry_run": True, "send_delay_min_seconds": 0.5}),
        encoding="utf-8",
    )

    save_holoquiz_enabled_setting(config_path, enabled=False)

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dry_run": True,
        "send_delay_min_seconds": 0.5,
        "holoquiz_enabled": False,
    }


def test_save_send_delay_settings_preserves_other_values(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"dry_run": True, "holoquiz_enabled": False}),
        encoding="utf-8",
    )

    save_send_delay_settings(config_path, min_seconds=1.0, max_seconds=3.0)

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dry_run": True,
        "holoquiz_enabled": False,
        "send_delay_seconds": 1.0,
        "send_delay_min_seconds": 1.0,
        "send_delay_max_seconds": 3.0,
    }
```

- [ ] **Step 2: Run config tests to verify RED**

Run: `python -m pytest tests/test_config.py -q`

Expected: collection fails because the save helpers do not exist, or assertions fail because `BotConfig` has no `holoquiz_enabled` field.

- [ ] **Step 3: Implement minimal config support**

Add this field after `program_enabled` in `BotConfig`:

```python
holoquiz_enabled: bool = True
```

Add focused persistence helpers beside `save_answer_sound_setting`:

```python
def save_holoquiz_enabled_setting(path: Path, *, enabled: bool) -> None:
    raw_config: dict[str, Any] = {}
    if path.exists():
        raw_config = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw_config, dict):
            raise ValueError("Config root must be a JSON object.")

    raw_config["holoquiz_enabled"] = enabled
    path.write_text(json.dumps(raw_config, indent=2) + "\n", encoding="utf-8")


def save_send_delay_settings(
    path: Path,
    *,
    min_seconds: float,
    max_seconds: float,
) -> None:
    raw_config: dict[str, Any] = {}
    if path.exists():
        raw_config = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw_config, dict):
            raise ValueError("Config root must be a JSON object.")

    raw_config["send_delay_seconds"] = min_seconds
    raw_config["send_delay_min_seconds"] = min_seconds
    raw_config["send_delay_max_seconds"] = max_seconds
    path.write_text(json.dumps(raw_config, indent=2) + "\n", encoding="utf-8")
```

Add `"holoquiz_enabled": true` after `"program_enabled": true` in `config.example.json`. No custom deserialization or serialization is needed because the dataclass constructor and `_config_to_json_dict` already handle booleans.

- [ ] **Step 4: Run config tests to verify GREEN**

Run: `python -m pytest tests/test_config.py -q`

Expected: all config tests pass.

- [ ] **Step 5: Write the failing runtime test**

Add to `tests/test_runtime.py`:

```python
def test_runtime_controls_track_holoquiz_enabled():
    controls = RuntimeControls.from_config(BotConfig(holoquiz_enabled=True))

    controls.set_holoquiz_enabled(False)

    assert controls.is_holoquiz_enabled() is False
    assert controls.snapshot().holoquiz_enabled is False
    assert controls.get_config().holoquiz_enabled is False
```

- [ ] **Step 6: Run the runtime test to verify RED**

Run: `python -m pytest tests/test_runtime.py::test_runtime_controls_track_holoquiz_enabled -q`

Expected: FAIL because `RuntimeControls.set_holoquiz_enabled` does not exist.

- [ ] **Step 7: Implement minimal runtime support**

Add `holoquiz_enabled: bool` after `program_enabled` in `RuntimeSnapshot`. Initialize `self._holoquiz_enabled = base_config.holoquiz_enabled`, include `holoquiz_enabled=self._holoquiz_enabled` in `get_config()` and `snapshot()`, and add:

```python
def is_holoquiz_enabled(self) -> bool:
    with self._lock:
        return self._holoquiz_enabled

def set_holoquiz_enabled(self, enabled: bool) -> None:
    with self._lock:
        self._holoquiz_enabled = enabled
```

- [ ] **Step 8: Run focused tests to verify GREEN**

Run: `python -m pytest tests/test_config.py tests/test_runtime.py -q`

Expected: all config and runtime tests pass.

- [ ] **Step 9: Commit the config/runtime unit**

```powershell
git add -- holoquiz/config.py holoquiz/runtime.py config.example.json tests/test_config.py tests/test_runtime.py
git commit -m "feat: persist HoloQuiz module settings"
```

### Task 2: Gate HoloQuiz Event Processing

**Files:**
- Modify: `holoquiz/runner.py:77-98`
- Test: `tests/test_runner.py:185-225, 337-365`

**Interfaces:**
- Consumes: `RuntimeControls.is_holoquiz_enabled() -> bool` from Task 1.
- Produces: `HoloQuizBot.handle_line(line: str) -> None` behavior that skips HoloQuiz parsing while leaving chat-trigger processing active.

- [ ] **Step 1: Write failing runner tests**

Add to `tests/test_runner.py`:

```python
def test_bot_skips_quiz_questions_when_holoquiz_disabled(tmp_path):
    controls = RuntimeControls.from_config(BotConfig(holoquiz_enabled=False))
    sender = FakeSender()
    answer_service = FakeAnswerService({"Who created Minecraft?": "Notch"})
    bot = make_bot_with_controls(
        tmp_path,
        controls=controls,
        answer_service=answer_service,
        sender=sender,
    )

    bot.handle_line(
        "[17:40:00] [Render thread/INFO]: [System] [CHAT] "
        "[HoloQuiz] Who created Minecraft?"
    )

    assert sender.sent == []
    assert answer_service.questions == []
    assert bot.pending_question is None
    assert controls.get_latest_question() is None
    assert bot.memory.lookup("Who created Minecraft?") is None


def test_bot_skips_answer_reveals_when_holoquiz_disabled(tmp_path):
    controls = RuntimeControls.from_config(BotConfig())
    bot = make_bot_with_controls(tmp_path, controls=controls)
    bot.handle_line(
        "[17:40:00] [Render thread/INFO]: [System] [CHAT] "
        "[HoloQuiz] Who created Minecraft?"
    )
    controls.set_holoquiz_enabled(False)

    bot.handle_line(
        "[17:40:09] [Render thread/INFO]: [System] [CHAT] "
        "[HoloQuiz] No one got the answer! The answer was Notch."
    )

    assert bot.memory.lookup("Who created Minecraft?") is None


def test_chat_triggers_run_when_holoquiz_disabled(tmp_path):
    config = BotConfig(
        holoquiz_enabled=False,
        chat_triggers=(
            ChatTriggerConfig(
                id="morning",
                trigger_phrase="Good Morning!",
                macro="tGood Morning{{Enter}}",
                cooldown_seconds=30,
            ),
        ),
    )
    controls = RuntimeControls.from_config(config)
    sender = FakeSender()
    bot = make_bot_with_controls(tmp_path, controls=controls, sender=sender)

    bot.handle_line("[System] [CHAT] Good Morning!")

    assert sender.macros == [("tGood Morning{{Enter}}", None)]
```

- [ ] **Step 2: Run runner tests to verify RED**

Run: `python -m pytest tests/test_runner.py -q`

Expected: the disabled HoloQuiz tests fail because quiz events are still parsed; the chat-trigger test already passes and protects the required ordering.

- [ ] **Step 3: Implement the HoloQuiz gate**

In `HoloQuizBot.handle_line`, keep the existing program check and chat-trigger call in place, then insert:

```python
if not self.runtime_controls.is_holoquiz_enabled():
    return
```

The resulting order must remain: global program check, chat-trigger processing, HoloQuiz enabled check, then HoloQuiz parsing.

- [ ] **Step 4: Run runner tests to verify GREEN**

Run: `python -m pytest tests/test_runner.py -q`

Expected: all runner tests pass.

- [ ] **Step 5: Commit the runner unit**

```powershell
git add -- holoquiz/runner.py tests/test_runner.py
git commit -m "feat: gate HoloQuiz event processing"
```

### Task 3: GUI Checkbox and Successful Delay Persistence

**Files:**
- Modify: `holoquiz/gui.py:14-35, 105-135, 727-950, 1585-1620`
- Test: `tests/test_gui.py:90-165`

**Interfaces:**
- Consumes: `save_holoquiz_enabled_setting(path: Path, *, enabled: bool) -> None` from Task 1.
- Consumes: `save_send_delay_settings(path: Path, *, min_seconds: float, max_seconds: float) -> None` from Task 1.
- Consumes: `RuntimeControls.set_holoquiz_enabled(enabled: bool) -> None` from Task 1.
- Produces: `ControlPanelController.set_holoquiz_enabled(enabled: bool) -> None`.
- Produces: `HoloQuizControlPanel._on_holoquiz_toggle() -> None`.
- Extends: `HoloQuizControlPanel._on_apply_delay() -> None` to persist only accepted ranges.

- [ ] **Step 1: Write the failing controller and checkbox-handler tests**

In `test_control_panel_controller_updates_runtime_controls`, call `controller.set_holoquiz_enabled(False)` and assert `controls.get_config().holoquiz_enabled is False`. Then add:

```python
def test_holoquiz_toggle_updates_runtime_and_persists(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dry_run": True}), encoding="utf-8")
    controls = RuntimeControls.from_config(BotConfig(holoquiz_enabled=True))
    panel = object.__new__(HoloQuizControlPanel)
    panel.config_path = config_path
    panel.controls = controls
    panel.controller = ControlPanelController(controls)
    panel.holoquiz_enabled_var = RecordingVar(False)

    panel._on_holoquiz_toggle()

    assert controls.is_holoquiz_enabled() is False
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dry_run": True,
        "holoquiz_enabled": False,
    }
```

- [ ] **Step 2: Run the checkbox tests to verify RED**

Run: `python -m pytest tests/test_gui.py::test_control_panel_controller_updates_runtime_controls tests/test_gui.py::test_holoquiz_toggle_updates_runtime_and_persists -q`

Expected: FAIL because the controller and panel toggle methods do not exist.

- [ ] **Step 3: Implement controller and checkbox behavior**

Import `save_holoquiz_enabled_setting` and `save_send_delay_settings` from `holoquiz.config`. Add to `ControlPanelController`:

```python
def set_holoquiz_enabled(self, enabled: bool) -> None:
    self.controls.set_holoquiz_enabled(enabled)
```

Initialize the Tk variable after `program_var`:

```python
self.holoquiz_enabled_var = tk.BooleanVar(value=snapshot.holoquiz_enabled)
```

In the `Answer automation` frame, keep the description on row 0, add this checkbox on row 1, move the delay row to row 2, and start `holoquiz_function_row` at 3:

```python
ttk.Checkbutton(
    holoquiz_frame,
    text="HoloQuiz enabled",
    variable=self.holoquiz_enabled_var,
    command=self._on_holoquiz_toggle,
).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))
```

Add beside the other toggle handlers:

```python
def _on_holoquiz_toggle(self) -> None:
    enabled = self.holoquiz_enabled_var.get()
    self.controller.set_holoquiz_enabled(enabled)
    save_holoquiz_enabled_setting(self.config_path, enabled=enabled)
```

- [ ] **Step 4: Run the checkbox tests to verify GREEN**

Run: `python -m pytest tests/test_gui.py::test_control_panel_controller_updates_runtime_controls tests/test_gui.py::test_holoquiz_toggle_updates_runtime_and_persists -q`

Expected: both tests pass.

- [ ] **Step 5: Write failing delay persistence tests**

Add to `tests/test_gui.py`:

```python
def test_apply_delay_persists_successful_range(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dry_run": True}), encoding="utf-8")
    controls = RuntimeControls.from_config(BotConfig())
    panel = object.__new__(HoloQuizControlPanel)
    panel.config_path = config_path
    panel.controls = controls
    panel.controller = ControlPanelController(controls)
    panel.delay_min_var = RecordingVar("1")
    panel.delay_max_var = RecordingVar("3")
    panel.delay_status_var = RecordingVar()

    panel._on_apply_delay()

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dry_run": True,
        "send_delay_seconds": 1.0,
        "send_delay_min_seconds": 1.0,
        "send_delay_max_seconds": 3.0,
    }


def test_apply_delay_does_not_persist_invalid_range(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dry_run": True}), encoding="utf-8")
    controls = RuntimeControls.from_config(BotConfig())
    panel = object.__new__(HoloQuizControlPanel)
    panel.config_path = config_path
    panel.controls = controls
    panel.controller = ControlPanelController(controls)
    panel.delay_min_var = RecordingVar("3")
    panel.delay_max_var = RecordingVar("1")
    panel.delay_status_var = RecordingVar()

    panel._on_apply_delay()

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dry_run": True,
    }
```

- [ ] **Step 6: Run delay persistence tests to verify RED**

Run: `python -m pytest tests/test_gui.py::test_apply_delay_persists_successful_range tests/test_gui.py::test_apply_delay_does_not_persist_invalid_range -q`

Expected: the successful-range test fails because `_on_apply_delay` does not save the accepted values; the invalid-range test passes and protects against unconditional saving.

- [ ] **Step 7: Implement successful-only delay persistence**

Inside the existing `if result.ok:` block in `_on_apply_delay`, after obtaining the snapshot and normalizing the text fields, add:

```python
save_send_delay_settings(
    self.config_path,
    min_seconds=snapshot.send_delay_min_seconds,
    max_seconds=snapshot.send_delay_max_seconds,
)
```

- [ ] **Step 8: Run GUI tests to verify GREEN**

Run: `python -m pytest tests/test_gui.py -q`

Expected: all GUI tests pass.

- [ ] **Step 9: Run complete verification**

Run: `python -m pytest`

Expected: all tests pass with zero failures.

Run: `python -m py_compile holoquiz/*.py`

Expected: exit code 0 with no syntax errors.

Run: `git diff --check`

Expected: exit code 0 with no whitespace errors.

- [ ] **Step 10: Commit the GUI unit**

```powershell
git add -- holoquiz/gui.py tests/test_gui.py
git commit -m "feat: add HoloQuiz module toggle"
```

- [ ] **Step 11: Inspect the final change set**

Run: `git status --short --branch`

Expected: the worktree is clean and the current branch is ahead only by the planned commits.

Run: `git log -5 --oneline`

Expected: recent history contains the design, implementation plan, and three feature commits.
