# HoloQuiz GUI Control Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Tkinter control panel that can toggle the running HoloQuiz bot, answer finding, dry-run, and send delay live.

**Architecture:** Add thread-safe runtime controls that merge GUI state into the existing frozen `BotConfig`. The GUI renders controls from a function registry and starts the existing log watcher in a background thread.

**Tech Stack:** Python 3.10+, Tkinter standard library, pytest.

---

### Task 1: Runtime Controls

**Files:**
- Create: `holoquiz/runtime.py`
- Test: `tests/test_runtime.py`

- [ ] Write tests for default function registry, config merging, program toggle, function toggle, dry-run toggle, and send delay update.
- [ ] Implement `FunctionDefinition`, `FunctionRegistry`, and `RuntimeControls` with a lock around mutable state.
- [ ] Run `pytest tests/test_runtime.py -q`.

### Task 2: Wire Runtime Into Bot Core

**Files:**
- Modify: `holoquiz/runner.py`
- Modify: `holoquiz/chat_sender.py`
- Modify: `holoquiz/codex_client.py`
- Test: `tests/test_runner.py`
- Test: `tests/test_chat_sender.py`
- Test: `tests/test_codex_client.py`

- [ ] Add failing tests that disabled program skips a question, disabled `find_answer` skips answer lookup/sending, sender uses updated dry-run/delay, and Codex uses updated search flag.
- [ ] Update constructors to accept an optional runtime/config provider while preserving existing tests and CLI behavior.
- [ ] Run the targeted tests.

### Task 3: Add Tkinter GUI

**Files:**
- Create: `holoquiz/gui.py`
- Create: `holoquiz_gui.py`
- Modify: `run_bot.bat`
- Test: `tests/test_gui.py`

- [ ] Add controller-level tests that GUI state writes to `RuntimeControls` without entering `mainloop`.
- [ ] Implement `HoloQuizControlPanel` with status label, toggle buttons, send-delay entry, function toggle rows, start/stop thread handling, and log output.
- [ ] Add `holoquiz_gui.py` entry point.
- [ ] Update `run_bot.bat` to launch the GUI.

### Task 4: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `config.example.json`

- [ ] Document `python holoquiz_gui.py` and the GUI controls.
- [ ] Ensure example config contains persisted runtime defaults.
- [ ] Run `pytest -q`.
