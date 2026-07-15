# Answer Sound Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent HoloQuiz checkbox that immediately mutes or unmutes the dry-run answer notification sound.

**Architecture:** Store an `answer_sound_enabled` boolean in `BotConfig`, mirror it in thread-safe `RuntimeControls`, and persist GUI changes with a focused JSON update helper. `ChatSender` continues to request the current runtime config for every answer and skips only dry-run sound playback when the setting is disabled.

**Tech Stack:** Python 3.10+, dataclasses, Tkinter/ttk, JSON, pytest.

## Global Constraints

- The checkbox label is exactly `Mute answer sound`.
- Existing and missing configs default to answer sound enabled (`True`).
- The checkbox value is the inverse of `answer_sound_enabled` and persists immediately to `config.json`.
- Muting changes only the dry-run answer-found sound; answer lookup, clipboard copying, live sending, browser search, screen-watcher sounds, and chat-trigger sounds remain unchanged.
- Follow test-driven development: write and run each failing test before its production change.
- Update `config.example.json` whenever the setting is added to config defaults.

---

## File Map

- `holoquiz/config.py`: define the persistent setting and the focused JSON save helper.
- `holoquiz/runtime.py`: hold and expose the live, thread-safe setting.
- `holoquiz/chat_sender.py`: suppress only the dry-run answer sound when disabled.
- `holoquiz/gui.py`: initialize, render, invert, update, and persist the mute checkbox.
- `config.example.json`: document the new setting.
- `tests/test_config.py`: verify defaults, backward compatibility, explicit loading, and focused persistence.
- `tests/test_runtime.py`: verify live runtime changes appear in snapshots and current config.
- `tests/test_chat_sender.py`: verify muted dry-run behavior preserves copying while suppressing sound.
- `tests/test_gui.py`: verify controller state updates and GUI toggle persistence.

### Task 1: Persistent Config and Runtime State

**Files:**
- Modify: `holoquiz/config.py:56-96, 210-239, 409-422`
- Modify: `holoquiz/runtime.py:37-182`
- Modify: `config.example.json:1-8`
- Test: `tests/test_config.py:1-62, 219-253`
- Test: `tests/test_runtime.py:29-50`

**Interfaces:**
- Produces: `BotConfig.answer_sound_enabled: bool` with default `True`.
- Produces: `save_answer_sound_setting(path: Path, *, enabled: bool) -> None`.
- Produces: `RuntimeSnapshot.answer_sound_enabled: bool`.
- Produces: `RuntimeControls.set_answer_sound_enabled(enabled: bool) -> None`.

- [ ] **Step 1: Write failing config tests**

Add `save_answer_sound_setting` to the imports in `tests/test_config.py`, add `"answer_sound_enabled": True` to the expected generated default JSON, add `"answer_sound_enabled": false` and its assertion to `test_load_config_overrides_defaults`, then add:

```python
def test_load_config_without_answer_sound_setting_defaults_enabled(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dry_run": True}), encoding="utf-8")

    config = load_config(config_path)

    assert config.answer_sound_enabled is True


def test_save_answer_sound_setting_preserves_other_config_values(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"dry_run": True, "codex_model": "gpt-5.4"}),
        encoding="utf-8",
    )

    save_answer_sound_setting(config_path, enabled=False)

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dry_run": True,
        "codex_model": "gpt-5.4",
        "answer_sound_enabled": False,
    }
```

- [ ] **Step 2: Run config tests to verify RED**

Run: `python -m pytest tests/test_config.py -q`

Expected: collection fails because `save_answer_sound_setting` does not exist, or assertions fail because `BotConfig` has no `answer_sound_enabled` field.

- [ ] **Step 3: Implement minimal config support**

Add the field immediately after `dry_run` in `BotConfig`:

```python
answer_sound_enabled: bool = True
```

Add this helper before `save_screen_phrase_settings`:

```python
def save_answer_sound_setting(path: Path, *, enabled: bool) -> None:
    raw_config: dict[str, Any] = {}
    if path.exists():
        raw_config = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw_config, dict):
            raise ValueError("Config root must be a JSON object.")

    raw_config["answer_sound_enabled"] = enabled
    path.write_text(
        json.dumps(raw_config, indent=2) + "\n",
        encoding="utf-8",
    )
```

Add `"answer_sound_enabled": true` after `"dry_run": true` in `config.example.json`. No special serialization conversion is needed because `_config_to_json_dict` starts from `asdict(config)`.

- [ ] **Step 4: Run config tests to verify GREEN**

Run: `python -m pytest tests/test_config.py -q`

Expected: all config tests pass.

- [ ] **Step 5: Write the failing runtime test**

Add to `tests/test_runtime.py`:

```python
def test_runtime_controls_update_answer_sound_setting():
    controls = RuntimeControls.from_config(BotConfig(answer_sound_enabled=True))

    controls.set_answer_sound_enabled(False)

    assert controls.snapshot().answer_sound_enabled is False
    assert controls.get_config().answer_sound_enabled is False
```

- [ ] **Step 6: Run runtime test to verify RED**

Run: `python -m pytest tests/test_runtime.py::test_runtime_controls_update_answer_sound_setting -q`

Expected: FAIL because `RuntimeControls.set_answer_sound_enabled` does not exist.

- [ ] **Step 7: Implement minimal runtime support**

Add `answer_sound_enabled: bool` after `dry_run` in `RuntimeSnapshot`. Initialize `self._answer_sound_enabled = base_config.answer_sound_enabled`, include `answer_sound_enabled=self._answer_sound_enabled` in both `get_config()` and `snapshot()`, and add:

```python
def set_answer_sound_enabled(self, enabled: bool) -> None:
    with self._lock:
        self._answer_sound_enabled = enabled
```

- [ ] **Step 8: Run focused tests to verify GREEN**

Run: `python -m pytest tests/test_config.py tests/test_runtime.py -q`

Expected: all config and runtime tests pass.

- [ ] **Step 9: Commit the config/runtime unit**

```powershell
git add -- holoquiz/config.py holoquiz/runtime.py config.example.json tests/test_config.py tests/test_runtime.py
git commit -m "feat: persist answer sound setting"
```

### Task 2: Suppress the Muted Answer Sound

**Files:**
- Modify: `holoquiz/chat_sender.py:77-88, 167-178`
- Test: `tests/test_chat_sender.py:39-64`

**Interfaces:**
- Consumes: `BotConfig.answer_sound_enabled: bool` from Task 1.
- Produces: `ChatSender.send(answer: str) -> None` behavior that copies and logs a muted dry-run answer without calling `PlaySound`.

- [ ] **Step 1: Write the failing sender test**

Add to `tests/test_chat_sender.py`:

```python
def test_dry_run_sender_copies_answer_without_sound_when_muted(capsys):
    clipboard = FakeClipboard()
    sound = FakeSound()
    sender = ChatSender(
        BotConfig(dry_run=True, answer_sound_enabled=False),
        clipboard_module=clipboard,
        sound_module=sound,
    )

    sender.send("Notch")

    assert clipboard.values == ["Notch"]
    assert sound.calls == []
    assert "[dry-run] Would send answer: Notch" in capsys.readouterr().out
```

- [ ] **Step 2: Run sender test to verify RED**

Run: `python -m pytest tests/test_chat_sender.py::test_dry_run_sender_copies_answer_without_sound_when_muted -q`

Expected: FAIL because `FakeSound.calls` contains the configured WAV playback.

- [ ] **Step 3: Implement minimal sound suppression**

Change the guard at the start of `_play_dry_run_sound` to:

```python
if not config.answer_sound_enabled or not config.dry_run_sound_path:
    return
```

Do not change clipboard copying, dry-run logging, live sending, macro sending, or any other sound player.

- [ ] **Step 4: Run sender tests to verify GREEN**

Run: `python -m pytest tests/test_chat_sender.py -q`

Expected: all chat sender tests pass, including the existing enabled-sound test.

- [ ] **Step 5: Commit the sender unit**

```powershell
git add -- holoquiz/chat_sender.py tests/test_chat_sender.py
git commit -m "feat: mute dry-run answer sound"
```

### Task 3: GUI Checkbox and Immediate Persistence

**Files:**
- Modify: `holoquiz/gui.py:14-35, 103-125, 727-734, 910-945, 1568-1578`
- Test: `tests/test_gui.py:1-18, 95-110`

**Interfaces:**
- Consumes: `save_answer_sound_setting(path: Path, *, enabled: bool) -> None` from Task 1.
- Consumes: `RuntimeControls.set_answer_sound_enabled(enabled: bool) -> None` from Task 1.
- Produces: `ControlPanelController.set_answer_sound_enabled(enabled: bool) -> None`.
- Produces: `HoloQuizControlPanel._on_answer_sound_mute_toggle() -> None`.

- [ ] **Step 1: Write the failing controller test**

Extend `test_control_panel_controller_updates_runtime_controls` in `tests/test_gui.py`:

```python
controller.set_answer_sound_enabled(False)
```

and add this assertion:

```python
assert controls.get_config().answer_sound_enabled is False
```

- [ ] **Step 2: Run controller test to verify RED**

Run: `python -m pytest tests/test_gui.py::test_control_panel_controller_updates_runtime_controls -q`

Expected: FAIL because `ControlPanelController.set_answer_sound_enabled` does not exist.

- [ ] **Step 3: Implement the controller method**

Add beside `set_dry_run`:

```python
def set_answer_sound_enabled(self, enabled: bool) -> None:
    self.controls.set_answer_sound_enabled(enabled)
```

- [ ] **Step 4: Run controller test to verify GREEN**

Run: `python -m pytest tests/test_gui.py::test_control_panel_controller_updates_runtime_controls -q`

Expected: PASS.

- [ ] **Step 5: Write the failing GUI toggle persistence test**

Add `HoloQuizControlPanel` to the imports from `holoquiz.gui`, then add:

```python
def test_answer_sound_mute_toggle_updates_runtime_and_persists(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"answer_sound_enabled": True}),
        encoding="utf-8",
    )
    controls = RuntimeControls.from_config(BotConfig(answer_sound_enabled=True))
    panel = object.__new__(HoloQuizControlPanel)
    panel.config_path = config_path
    panel.controls = controls
    panel.controller = ControlPanelController(controls)
    panel.answer_sound_muted_var = RecordingVar(True)

    panel._on_answer_sound_mute_toggle()

    assert controls.get_config().answer_sound_enabled is False
    assert json.loads(config_path.read_text(encoding="utf-8"))[
        "answer_sound_enabled"
    ] is False
```

Also add `import json` at the top of `tests/test_gui.py`.

- [ ] **Step 6: Run GUI toggle test to verify RED**

Run: `python -m pytest tests/test_gui.py::test_answer_sound_mute_toggle_updates_runtime_and_persists -q`

Expected: FAIL because `_on_answer_sound_mute_toggle` does not exist.

- [ ] **Step 7: Implement checkbox initialization, layout, inversion, and persistence**

Import `save_answer_sound_setting` from `holoquiz.config`. Initialize the Tk variable after `dry_run_var`:

```python
self.answer_sound_muted_var = tk.BooleanVar(
    value=not snapshot.answer_sound_enabled
)
```

After the `Find answer` function checkbutton is added, place the mute checkbox on the same row in column 1:

```python
if function.key == FIND_ANSWER_FUNCTION:
    ttk.Checkbutton(
        holoquiz_frame,
        text="Mute answer sound",
        variable=self.answer_sound_muted_var,
        command=self._on_answer_sound_mute_toggle,
    ).grid(row=holoquiz_function_row, column=1, sticky="w", padx=(12, 0))
```

Import `FIND_ANSWER_FUNCTION` from `holoquiz.runtime` so this placement is keyed to the existing feature rather than relying on registry order. Add the handler beside `_on_dry_run_toggle`:

```python
def _on_answer_sound_mute_toggle(self) -> None:
    enabled = not self.answer_sound_muted_var.get()
    self.controller.set_answer_sound_enabled(enabled)
    save_answer_sound_setting(self.config_path, enabled=enabled)
```

Because `_add_function_checkbutton` currently spans columns 0 and 1, change its grid call to `columnspan=1`; this preserves the existing label in column 0 and makes column 1 available for the mute checkbox.

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
git commit -m "feat: add answer sound mute toggle"
```

- [ ] **Step 11: Inspect the final change set**

Run: `git status --short` and `git log -4 --oneline`.

Expected: the worktree is clean and the recent log contains the design, config/runtime, sender, and GUI commits (plus the implementation-plan commit if it was committed separately).
