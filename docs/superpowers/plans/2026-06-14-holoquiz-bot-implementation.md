# HoloQuiz Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows Python helper that watches Minecraft Java logs, answers non-math HoloQuiz prompts from JSON memory or Codex CLI, and can type the answer into Minecraft chat.

**Architecture:** The app is a small CLI with focused modules: config loading, log parsing, JSON memory, Codex CLI answering, keyboard sending, log tailing, and orchestration. Unit tests cover each boundary without requiring Minecraft, Codex network calls, or real keyboard automation.

**Tech Stack:** Python 3.10+, pytest, pyautogui for live keyboard sending, Codex CLI via `subprocess.run`.

---

## File Structure

- Create: `pyproject.toml`
  - Project metadata, pytest settings, and the `pyautogui` runtime dependency.
- Create: `.gitignore`
  - Ignore local runtime files, test caches, and temporary logs.
- Create: `config.example.json`
  - Editable configuration template with dry-run enabled.
- Create: `quiz_memory.example.json`
  - Example memory database shape.
- Create: `README.md`
  - Setup, dry-run workflow, live-send workflow, and safety notes.
- Create: `holoquiz_bot.py`
  - Thin entrypoint that calls `holoquiz.runner.main`.
- Create: `holoquiz/__init__.py`
  - Package marker and version.
- Create: `holoquiz/config.py`
  - `BotConfig`, defaults, config loading, config creation, and log path discovery.
- Create: `holoquiz/parser.py`
  - HoloQuiz log parsing, answer-reveal parsing, and math prompt rejection.
- Create: `holoquiz/memory.py`
  - JSON memory loading, backup on corrupt JSON, lookup, usage tracking, and answer correction.
- Create: `holoquiz/codex_client.py`
  - Prompt creation, `codex exec` command building, timeout handling, and answer cleanup.
- Create: `holoquiz/chat_sender.py`
  - Dry-run sender and live `pyautogui` sender with lazy import.
- Create: `holoquiz/log_tailer.py`
  - Nonblocking file tailer with truncation handling.
- Create: `holoquiz/runner.py`
  - Main event loop and `HoloQuizBot` orchestration class.
- Create: `tests/test_config.py`
  - Config defaults, config file loading, and common log path discovery.
- Create: `tests/test_parser.py`
  - Question parsing, math ignoring, answer reveal parsing, and irrelevant chat ignoring.
- Create: `tests/test_memory.py`
  - Normalization, save/load, corrupt JSON backup, lookup, and correction behavior.
- Create: `tests/test_codex_client.py`
  - Prompt format, command arguments, timeout behavior, and answer cleanup.
- Create: `tests/test_chat_sender.py`
  - Dry-run output and live sender behavior using a fake pyautogui object.
- Create: `tests/test_log_tailer.py`
  - Reads appended lines and resets when the file is truncated.
- Create: `tests/test_runner.py`
  - Memory-first answering, Codex fallback, math ignore, cooldown, and answer-reveal learning.

---

### Task 1: Project Scaffold and Configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `config.example.json`
- Create: `quiz_memory.example.json`
- Create: `holoquiz/__init__.py`
- Create: `holoquiz/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing config tests**

Create `tests/test_config.py`:

```python
from pathlib import Path

from holoquiz.config import BotConfig, discover_default_log_path, load_config


def test_load_config_creates_default_when_missing(tmp_path):
    config_path = tmp_path / "config.json"

    config = load_config(config_path)

    assert config == BotConfig()
    assert config_path.exists()
    assert '"dry_run": true' in config_path.read_text(encoding="utf-8")


def test_load_config_overrides_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
{
  "log_path": "C:/Minecraft/logs/latest.log",
  "dry_run": false,
  "codex_model": "gpt-5.4-nano",
  "codex_timeout_seconds": 3,
  "send_delay_seconds": 0.2
}
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.log_path == Path("C:/Minecraft/logs/latest.log")
    assert config.dry_run is False
    assert config.codex_model == "gpt-5.4-nano"
    assert config.codex_timeout_seconds == 3
    assert config.send_delay_seconds == 0.2
    assert config.codex_command == "codex"


def test_discover_default_log_path_prefers_existing_latest_log(tmp_path, monkeypatch):
    appdata = tmp_path / "AppData" / "Roaming"
    expected = appdata / ".minecraft" / "logs" / "latest.log"
    expected.parent.mkdir(parents=True)
    expected.write_text("", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "User"))

    assert discover_default_log_path() == expected
```

- [ ] **Step 2: Run config tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'holoquiz'`.

- [ ] **Step 3: Create project metadata and example JSON files**

Create `pyproject.toml`:

```toml
[project]
name = "holoquiz-bot"
version = "0.1.0"
description = "Minecraft HoloQuiz helper that learns answers and can type them into chat."
requires-python = ">=3.10"
dependencies = [
  "pyautogui>=0.9.54"
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0"
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

Create `.gitignore`:

```gitignore
__pycache__/
.pytest_cache/
*.pyc
.tmp/
config.json
quiz_memory.json
*.bak
```

Create `config.example.json`:

```json
{
  "log_path": "",
  "dry_run": true,
  "codex_command": "codex",
  "codex_model": "gpt-5.4-mini",
  "codex_timeout_seconds": 6,
  "codex_enable_search": false,
  "codex_persistent_session": false,
  "send_delay_seconds": 0.8,
  "question_cooldown_seconds": 3.0,
  "keyboard_open_chat_key": "t",
  "typing_interval_seconds": 0.01
}
```

Create `quiz_memory.example.json`:

```json
{
  "version": 1,
  "questions": {}
}
```

Create `holoquiz/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Implement config loading**

Create `holoquiz/config.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BotConfig:
    log_path: Path | None = None
    dry_run: bool = True
    codex_command: str = "codex"
    codex_model: str = "gpt-5.4-mini"
    codex_timeout_seconds: int = 6
    codex_enable_search: bool = False
    codex_persistent_session: bool = False
    send_delay_seconds: float = 0.8
    question_cooldown_seconds: float = 3.0
    keyboard_open_chat_key: str = "t"
    typing_interval_seconds: float = 0.01
    memory_path: Path = Path("quiz_memory.json")


def _config_to_json(config: BotConfig) -> dict[str, Any]:
    data = asdict(config)
    data["log_path"] = "" if config.log_path is None else str(config.log_path)
    data["memory_path"] = str(config.memory_path)
    return data


def _coerce_config(raw: dict[str, Any]) -> BotConfig:
    defaults = BotConfig()
    values = asdict(defaults)
    values.update(raw)
    values["log_path"] = Path(values["log_path"]) if values.get("log_path") else None
    values["memory_path"] = Path(values.get("memory_path") or defaults.memory_path)
    return BotConfig(**values)


def load_config(path: Path = Path("config.json")) -> BotConfig:
    if not path.exists():
        config = BotConfig()
        path.write_text(json.dumps(_config_to_json(config), indent=2), encoding="utf-8")
        return config

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return _coerce_config(raw)


def discover_default_log_path() -> Path | None:
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    userprofile = os.environ.get("USERPROFILE")

    if appdata:
        candidates.append(Path(appdata) / ".minecraft" / "logs" / "latest.log")
    if userprofile:
        home = Path(userprofile)
        candidates.append(home / "AppData" / "Roaming" / ".minecraft" / "logs" / "latest.log")
        candidates.append(home / ".tlauncher" / "legacy" / "Minecraft" / "game" / "logs" / "latest.log")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None
```

- [ ] **Step 5: Run config tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_config.py -v
```

Expected: PASS, 3 tests.

- [ ] **Step 6: Commit scaffold and config**

Run:

```powershell
git add pyproject.toml .gitignore config.example.json quiz_memory.example.json holoquiz/__init__.py holoquiz/config.py tests/test_config.py
git commit -m "Add project scaffold and config loader"
```

Expected: commit succeeds.

---

### Task 2: HoloQuiz Log Parser

**Files:**
- Create: `holoquiz/parser.py`
- Test: `tests/test_parser.py`

- [ ] **Step 1: Write parser tests**

Create `tests/test_parser.py`:

```python
from holoquiz.parser import AnswerReveal, QuizQuestion, parse_log_line


def test_parse_holoquiz_question():
    line = "[17:36:04] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft? = ?"

    event = parse_log_line(line)

    assert event == QuizQuestion(question="Who created Minecraft? = ?")


def test_parse_holoquiz_question_without_equals_marker():
    line = "[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] What mob explodes near players?"

    event = parse_log_line(line)

    assert event == QuizQuestion(question="What mob explodes near players?")


def test_ignore_non_holoquiz_chat():
    line = "[17:36:16] [Render thread/INFO]: [System] [CHAT] [Newbie] truntd: 42"

    assert parse_log_line(line) is None


def test_ignore_math_expression_prompt():
    line = "[17:36:04] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] 0-(9+12+11+10) = ?"

    assert parse_log_line(line) is None


def test_ignore_fraction_math_expression_prompt():
    line = "[17:35:29] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] (2+3-0/5)+13 = ?"

    assert parse_log_line(line) is None


def test_parse_answer_reveal():
    line = "[17:35:59] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] No one got the answer! The answer was 18."

    event = parse_log_line(line)

    assert event == AnswerReveal(answer="18")


def test_parse_answer_reveal_with_negative_answer():
    line = "[17:36:19] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] FedericoAlio214 wins after 14.738 seconds! The answer was -42!"

    event = parse_log_line(line)

    assert event == AnswerReveal(answer="-42")
```

- [ ] **Step 2: Run parser tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_parser.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'holoquiz.parser'`.

- [ ] **Step 3: Implement parser**

Create `holoquiz/parser.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import re


CHAT_MARKER = "[System] [CHAT]"
HOLOQUIZ_MARKER = "[HoloQuiz]"


@dataclass(frozen=True)
class QuizQuestion:
    question: str


@dataclass(frozen=True)
class AnswerReveal:
    answer: str


def parse_log_line(line: str) -> QuizQuestion | AnswerReveal | None:
    if CHAT_MARKER not in line or HOLOQUIZ_MARKER not in line:
        return None

    message = line.split(HOLOQUIZ_MARKER, 1)[1].strip()
    reveal = _parse_answer_reveal(message)
    if reveal:
        return reveal

    if not _looks_like_question(message):
        return None

    if is_math_prompt(message):
        return None

    return QuizQuestion(question=message)


def is_math_prompt(message: str) -> bool:
    cleaned = message.strip()
    if cleaned.endswith("?"):
        cleaned = cleaned[:-1].strip()
    if cleaned.endswith("="):
        cleaned = cleaned[:-1].strip()

    has_operator = any(operator in cleaned for operator in "+-*/")
    if not has_operator:
        return False

    return bool(re.fullmatch(r"[0-9\s()+\-*/.]+", cleaned))


def _looks_like_question(message: str) -> bool:
    if "The answer was" in message:
        return False
    return message.endswith("?") or message.endswith("= ?")


def _parse_answer_reveal(message: str) -> AnswerReveal | None:
    match = re.search(r"The answer was\s+(.+?)[.!]?$", message, flags=re.IGNORECASE)
    if not match:
        return None
    answer = match.group(1).strip()
    return AnswerReveal(answer=answer)
```

- [ ] **Step 4: Run parser tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_parser.py -v
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Commit parser**

Run:

```powershell
git add holoquiz/parser.py tests/test_parser.py
git commit -m "Add HoloQuiz log parser"
```

Expected: commit succeeds.

---

### Task 3: JSON Quiz Memory

**Files:**
- Create: `holoquiz/memory.py`
- Test: `tests/test_memory.py`

- [ ] **Step 1: Write memory tests**

Create `tests/test_memory.py`:

```python
import json

from holoquiz.memory import QuizMemory, normalize_question


def test_normalize_question_removes_answer_marker_and_punctuation_noise():
    assert normalize_question("  Who created Minecraft? = ?  ") == "who created minecraft"


def test_memory_saves_and_loads_answer(tmp_path):
    memory_path = tmp_path / "quiz_memory.json"
    memory = QuizMemory.load(memory_path)

    memory.record_answer("Who created Minecraft?", "Notch", source="answer_reveal")
    reloaded = QuizMemory.load(memory_path)

    assert reloaded.lookup("who created minecraft?") == "Notch"


def test_lookup_tracks_usage(tmp_path):
    memory_path = tmp_path / "quiz_memory.json"
    memory = QuizMemory.load(memory_path)
    memory.record_answer("What mob explodes near players?", "Creeper", source="answer_reveal")

    assert memory.lookup("What mob explodes near players?") == "Creeper"
    entry = memory.data["questions"]["what mob explodes near players"]

    assert entry["times_used"] == 1


def test_record_seen_tracks_question_without_answer(tmp_path):
    memory_path = tmp_path / "quiz_memory.json"
    memory = QuizMemory.load(memory_path)

    memory.record_seen("What is the Nether dimension?")

    entry = memory.data["questions"]["what is the nether dimension"]
    assert entry["answer"] == ""
    assert entry["times_seen"] == 1


def test_record_answer_corrects_existing_answer(tmp_path):
    memory_path = tmp_path / "quiz_memory.json"
    memory = QuizMemory.load(memory_path)
    memory.record_answer("Who created Minecraft?", "Jeb", source="codex")

    memory.record_answer("Who created Minecraft?", "Notch", source="answer_reveal")

    entry = memory.data["questions"]["who created minecraft"]
    assert entry["answer"] == "Notch"
    assert entry["source"] == "answer_reveal"
    assert entry["last_corrected"]


def test_corrupt_json_is_backed_up(tmp_path):
    memory_path = tmp_path / "quiz_memory.json"
    memory_path.write_text("{bad json", encoding="utf-8")

    memory = QuizMemory.load(memory_path)

    backups = list(tmp_path.glob("quiz_memory.json.corrupt-*.bak"))
    assert memory.data == {"version": 1, "questions": {}}
    assert len(backups) == 1
    assert json.loads(memory_path.read_text(encoding="utf-8")) == {"version": 1, "questions": {}}
```

- [ ] **Step 2: Run memory tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_memory.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'holoquiz.memory'`.

- [ ] **Step 3: Implement memory**

Create `holoquiz/memory.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
from typing import Any


EMPTY_MEMORY = {"version": 1, "questions": {}}


def normalize_question(question: str) -> str:
    value = question.strip().lower()
    value = re.sub(r"\s*=\s*\?\s*$", "", value)
    value = re.sub(r"\?+$", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


class QuizMemory:
    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = path
        self.data = data

    @classmethod
    def load(cls, path: Path) -> "QuizMemory":
        if not path.exists():
            memory = cls(path, _empty_memory())
            memory.save()
            return memory

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            backup_path = path.with_name(
                f"{path.name}.corrupt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.bak"
            )
            shutil.copy2(path, backup_path)
            memory = cls(path, _empty_memory())
            memory.save()
            return memory

        if not isinstance(data, dict) or not isinstance(data.get("questions"), dict):
            data = _empty_memory()
        return cls(path, data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")

    def lookup(self, question: str) -> str | None:
        key = normalize_question(question)
        entry = self.data["questions"].get(key)
        if not entry or not entry.get("answer"):
            return None
        entry["times_used"] = int(entry.get("times_used", 0)) + 1
        entry["last_seen"] = _now()
        self.save()
        return str(entry["answer"])

    def record_seen(self, question: str) -> None:
        key = normalize_question(question)
        entry = self.data["questions"].setdefault(
            key,
            {
                "question": question.strip(),
                "answer": "",
                "source": "seen",
                "times_seen": 0,
                "times_used": 0,
                "last_seen": "",
                "last_corrected": "",
            },
        )
        entry["times_seen"] = int(entry.get("times_seen", 0)) + 1
        entry["last_seen"] = _now()
        self.save()

    def record_answer(self, question: str, answer: str, source: str) -> None:
        key = normalize_question(question)
        clean_answer = answer.strip()
        entry = self.data["questions"].setdefault(
            key,
            {
                "question": question.strip(),
                "answer": "",
                "source": source,
                "times_seen": 0,
                "times_used": 0,
                "last_seen": "",
                "last_corrected": "",
            },
        )
        old_answer = str(entry.get("answer") or "")
        entry["question"] = question.strip()
        entry["answer"] = clean_answer
        entry["source"] = source
        entry["last_seen"] = _now()
        if old_answer and old_answer != clean_answer:
            entry["last_corrected"] = _now()
        elif not entry.get("last_corrected"):
            entry["last_corrected"] = _now()
        self.save()


def _empty_memory() -> dict[str, Any]:
    return {"version": 1, "questions": {}}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
```

- [ ] **Step 4: Run memory tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_memory.py -v
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit memory**

Run:

```powershell
git add holoquiz/memory.py tests/test_memory.py
git commit -m "Add quiz memory store"
```

Expected: commit succeeds.

---

### Task 4: Codex CLI Answer Client

**Files:**
- Create: `holoquiz/codex_client.py`
- Test: `tests/test_codex_client.py`

- [ ] **Step 1: Write Codex client tests**

Create `tests/test_codex_client.py`:

```python
import subprocess

from holoquiz.config import BotConfig
from holoquiz.codex_client import CodexAnswerClient, build_prompt, clean_answer


def test_build_prompt_includes_examples_and_question():
    prompt = build_prompt("Who created Minecraft?")

    assert "Return ONLY the answer text." in prompt
    assert "Question: What mob explodes near players?" in prompt
    assert "Answer: Creeper" in prompt
    assert "Question: Who created Minecraft?" in prompt
    assert prompt.rstrip().endswith("Answer:")


def test_clean_answer_uses_first_non_empty_line_and_removes_prefix():
    output = "\n\nAnswer: Notch\nExtra text\n"

    assert clean_answer(output) == "Notch"


def test_clean_answer_strips_quotes_and_trailing_period():
    assert clean_answer('"Creeper."') == "Creeper"


def test_ask_builds_codex_exec_command(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, timeout, check, capture_output, text):
        calls.append(
            {
                "command": command,
                "timeout": timeout,
                "check": check,
                "capture_output": capture_output,
                "text": text,
            }
        )
        output_path = command[command.index("--output-last-message") + 1]
        output_path.write_text("Notch\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = BotConfig(codex_model="gpt-5.4-mini", codex_timeout_seconds=4)
    client = CodexAnswerClient(config=config, workspace=tmp_path)

    assert client.ask("Who created Minecraft?") == "Notch"

    command = calls[0]["command"]
    assert command[:3] == ["codex", "exec", "-m"]
    assert "gpt-5.4-mini" in command
    assert "--sandbox" in command
    assert "--ask-for-approval" in command
    assert "--ephemeral" in command
    assert "--color" in command
    assert "--output-last-message" in command
    assert calls[0]["timeout"] == 4


def test_ask_returns_none_on_timeout(tmp_path, monkeypatch):
    def fake_run(command, timeout, check, capture_output, text):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = CodexAnswerClient(config=BotConfig(codex_timeout_seconds=1), workspace=tmp_path)

    assert client.ask("Who created Minecraft?") is None
```

- [ ] **Step 2: Run Codex client tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_codex_client.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'holoquiz.codex_client'`.

- [ ] **Step 3: Implement Codex client**

Create `holoquiz/codex_client.py`:

```python
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from holoquiz.config import BotConfig


def build_prompt(question: str) -> str:
    return f"""You answer Minecraft server quiz questions.

Return ONLY the answer text.
No explanation.
No punctuation unless it is part of the answer.
Use the shortest common answer.
If the question asks for a number, return digits only.
If unsure, return the best likely answer.
Do not run tools or commands.

Examples:
Question: What mob explodes near players?
Answer: Creeper

Question: What ore is used to make a beacon base?
Answer: Iron

Question: Who created Minecraft?
Answer: Notch

Question: {question}
Answer:"""


def clean_answer(output: str) -> str | None:
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("answer:"):
            line = line.split(":", 1)[1].strip()
        line = line.strip().strip("\"'")
        if line.endswith(".") and line.count(".") == 1:
            line = line[:-1]
        return line or None
    return None


class CodexAnswerClient:
    def __init__(self, config: BotConfig, workspace: Path) -> None:
        self.config = config
        self.workspace = workspace

    def ask(self, question: str) -> str | None:
        prompt = build_prompt(question)
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as output:
            output_path = Path(output.name)

        command = self._build_command(prompt, output_path)
        try:
            subprocess.run(
                command,
                timeout=self.config.codex_timeout_seconds,
                check=True,
                capture_output=True,
                text=True,
            )
            return clean_answer(output_path.read_text(encoding="utf-8"))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return None
        finally:
            output_path.unlink(missing_ok=True)

    def _build_command(self, prompt: str, output_path: Path) -> list[str]:
        command = [
            self.config.codex_command,
            "exec",
            "-m",
            self.config.codex_model,
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
            "--ephemeral",
            "--color",
            "never",
            "--output-last-message",
            output_path,
            prompt,
        ]
        if self.config.codex_enable_search:
            command.insert(1, "--search")
        return command
```

- [ ] **Step 4: Run Codex client tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_codex_client.py -v
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit Codex client**

Run:

```powershell
git add holoquiz/codex_client.py tests/test_codex_client.py
git commit -m "Add Codex answer client"
```

Expected: commit succeeds.

---

### Task 5: Chat Sender

**Files:**
- Create: `holoquiz/chat_sender.py`
- Test: `tests/test_chat_sender.py`

- [ ] **Step 1: Write chat sender tests**

Create `tests/test_chat_sender.py`:

```python
from holoquiz.chat_sender import ChatSender
from holoquiz.config import BotConfig


class FakePyAutoGui:
    def __init__(self):
        self.calls = []

    def press(self, key):
        self.calls.append(("press", key))

    def write(self, text, interval):
        self.calls.append(("write", text, interval))


def test_dry_run_sender_prints_answer(capsys):
    sender = ChatSender(BotConfig(dry_run=True))

    sender.send("Notch")

    captured = capsys.readouterr()
    assert "[dry-run] Would send answer: Notch" in captured.out


def test_live_sender_uses_chat_key_and_enter(monkeypatch):
    fake = FakePyAutoGui()
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    sender = ChatSender(
        BotConfig(
            dry_run=False,
            send_delay_seconds=0.1,
            keyboard_open_chat_key="t",
            typing_interval_seconds=0.02,
        ),
        pyautogui_module=fake,
    )

    sender.send("Creeper")

    assert fake.calls == [
        ("press", "t"),
        ("write", "Creeper", 0.02),
        ("press", "enter"),
    ]


def test_live_sender_ignores_empty_answer():
    fake = FakePyAutoGui()
    sender = ChatSender(BotConfig(dry_run=False), pyautogui_module=fake)

    sender.send("   ")

    assert fake.calls == []
```

- [ ] **Step 2: Run chat sender tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_chat_sender.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'holoquiz.chat_sender'`.

- [ ] **Step 3: Implement chat sender**

Create `holoquiz/chat_sender.py`:

```python
from __future__ import annotations

import time
from typing import Any

from holoquiz.config import BotConfig


class ChatSender:
    def __init__(self, config: BotConfig, pyautogui_module: Any | None = None) -> None:
        self.config = config
        self._pyautogui = pyautogui_module

    def send(self, answer: str) -> None:
        clean_answer = answer.strip()
        if not clean_answer:
            return

        if self.config.dry_run:
            print(f"[dry-run] Would send answer: {clean_answer}")
            return

        pyautogui = self._load_pyautogui()
        time.sleep(self.config.send_delay_seconds)
        pyautogui.press(self.config.keyboard_open_chat_key)
        pyautogui.write(clean_answer, interval=self.config.typing_interval_seconds)
        pyautogui.press("enter")

    def _load_pyautogui(self) -> Any:
        if self._pyautogui is not None:
            return self._pyautogui

        import pyautogui

        self._pyautogui = pyautogui
        return self._pyautogui
```

- [ ] **Step 4: Run chat sender tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_chat_sender.py -v
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Commit chat sender**

Run:

```powershell
git add holoquiz/chat_sender.py tests/test_chat_sender.py
git commit -m "Add chat sender"
```

Expected: commit succeeds.

---

### Task 6: Log Tailer

**Files:**
- Create: `holoquiz/log_tailer.py`
- Test: `tests/test_log_tailer.py`

- [ ] **Step 1: Write log tailer tests**

Create `tests/test_log_tailer.py`:

```python
from holoquiz.log_tailer import LogTailer


def test_tailer_reads_only_appended_lines(tmp_path):
    log_path = tmp_path / "latest.log"
    log_path.write_text("old line\n", encoding="utf-8")
    tailer = LogTailer(log_path, start_at_end=True)

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("new line 1\nnew line 2\n")

    assert tailer.read_available() == ["new line 1\n", "new line 2\n"]


def test_tailer_reads_existing_lines_when_not_starting_at_end(tmp_path):
    log_path = tmp_path / "latest.log"
    log_path.write_text("line 1\nline 2\n", encoding="utf-8")
    tailer = LogTailer(log_path, start_at_end=False)

    assert tailer.read_available() == ["line 1\n", "line 2\n"]


def test_tailer_resets_after_truncation(tmp_path):
    log_path = tmp_path / "latest.log"
    log_path.write_text("old line\n", encoding="utf-8")
    tailer = LogTailer(log_path, start_at_end=True)

    log_path.write_text("fresh line\n", encoding="utf-8")

    assert tailer.read_available() == ["fresh line\n"]
```

- [ ] **Step 2: Run log tailer tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_log_tailer.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'holoquiz.log_tailer'`.

- [ ] **Step 3: Implement log tailer**

Create `holoquiz/log_tailer.py`:

```python
from __future__ import annotations

from pathlib import Path


class LogTailer:
    def __init__(self, path: Path, start_at_end: bool = True) -> None:
        self.path = path
        self.position = path.stat().st_size if start_at_end and path.exists() else 0

    def read_available(self) -> list[str]:
        if not self.path.exists():
            return []

        size = self.path.stat().st_size
        if size < self.position:
            self.position = 0

        with self.path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(self.position)
            lines = handle.readlines()
            self.position = handle.tell()
        return lines
```

- [ ] **Step 4: Run log tailer tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_log_tailer.py -v
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Commit log tailer**

Run:

```powershell
git add holoquiz/log_tailer.py tests/test_log_tailer.py
git commit -m "Add Minecraft log tailer"
```

Expected: commit succeeds.

---

### Task 7: Bot Orchestration

**Files:**
- Create: `holoquiz/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write runner tests**

Create `tests/test_runner.py`:

```python
from holoquiz.config import BotConfig
from holoquiz.memory import QuizMemory
from holoquiz.runner import HoloQuizBot


class FakeAnswerService:
    def __init__(self, answers):
        self.answers = answers
        self.questions = []

    def ask(self, question):
        self.questions.append(question)
        return self.answers.get(question)


class FakeSender:
    def __init__(self):
        self.sent = []

    def send(self, answer):
        self.sent.append(answer)


def make_bot(tmp_path, answer_service=None, sender=None, cooldown=3.0):
    memory = QuizMemory.load(tmp_path / "quiz_memory.json")
    return HoloQuizBot(
        config=BotConfig(question_cooldown_seconds=cooldown),
        memory=memory,
        answer_service=answer_service or FakeAnswerService({}),
        sender=sender or FakeSender(),
        clock=lambda: 100.0,
    )


def test_bot_answers_from_memory_before_codex(tmp_path):
    sender = FakeSender()
    answer_service = FakeAnswerService({"Who created Minecraft?": "Wrong"})
    bot = make_bot(tmp_path, answer_service=answer_service, sender=sender)
    bot.memory.record_answer("Who created Minecraft?", "Notch", source="answer_reveal")

    bot.handle_line("[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft?")

    assert sender.sent == ["Notch"]
    assert answer_service.questions == []


def test_bot_uses_codex_for_unknown_question(tmp_path):
    sender = FakeSender()
    answer_service = FakeAnswerService({"What mob explodes near players?": "Creeper"})
    bot = make_bot(tmp_path, answer_service=answer_service, sender=sender)

    bot.handle_line("[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] What mob explodes near players?")

    assert sender.sent == ["Creeper"]
    assert bot.pending_question.question == "What mob explodes near players?"
    assert bot.pending_question.candidate_answer == "Creeper"


def test_bot_ignores_math_question(tmp_path):
    sender = FakeSender()
    answer_service = FakeAnswerService({})
    bot = make_bot(tmp_path, answer_service=answer_service, sender=sender)

    bot.handle_line("[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] 0-(9+12+11+10) = ?")

    assert sender.sent == []
    assert answer_service.questions == []


def test_bot_applies_cooldown_for_duplicate_question(tmp_path):
    sender = FakeSender()
    answer_service = FakeAnswerService({"Who created Minecraft?": "Notch"})
    bot = make_bot(tmp_path, answer_service=answer_service, sender=sender, cooldown=3.0)

    line = "[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft?"
    bot.handle_line(line)
    bot.handle_line(line)

    assert sender.sent == ["Notch"]


def test_bot_records_revealed_answer_for_pending_question(tmp_path):
    answer_service = FakeAnswerService({"Who created Minecraft?": "Jeb"})
    bot = make_bot(tmp_path, answer_service=answer_service)

    bot.handle_line("[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft?")
    bot.handle_line("[17:40:09] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] No one got the answer! The answer was Notch.")

    assert bot.memory.lookup("Who created Minecraft?") == "Notch"
```

- [ ] **Step 2: Run runner tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_runner.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'holoquiz.runner'`.

- [ ] **Step 3: Implement runner orchestration**

Create `holoquiz/runner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
import time
from typing import Callable, Protocol

from holoquiz.chat_sender import ChatSender
from holoquiz.codex_client import CodexAnswerClient
from holoquiz.config import BotConfig, discover_default_log_path, load_config
from holoquiz.log_tailer import LogTailer
from holoquiz.memory import QuizMemory, normalize_question
from holoquiz.parser import AnswerReveal, QuizQuestion, parse_log_line


class AnswerService(Protocol):
    def ask(self, question: str) -> str | None:
        ...


class Sender(Protocol):
    def send(self, answer: str) -> None:
        ...


@dataclass
class PendingQuestion:
    question: str
    candidate_answer: str | None


class HoloQuizBot:
    def __init__(
        self,
        config: BotConfig,
        memory: QuizMemory,
        answer_service: AnswerService,
        sender: Sender,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.memory = memory
        self.answer_service = answer_service
        self.sender = sender
        self.clock = clock
        self.pending_question: PendingQuestion | None = None
        self.last_question_times: dict[str, float] = {}

    def handle_line(self, line: str) -> None:
        event = parse_log_line(line)
        if event is None:
            return

        if isinstance(event, QuizQuestion):
            self._handle_question(event.question)
            return

        if isinstance(event, AnswerReveal):
            self._handle_answer_reveal(event.answer)

    def _handle_question(self, question: str) -> None:
        key = normalize_question(question)
        now = self.clock()
        last_seen = self.last_question_times.get(key)
        if last_seen is not None and now - last_seen < self.config.question_cooldown_seconds:
            return
        self.last_question_times[key] = now

        self.memory.record_seen(question)
        answer = self.memory.lookup(question)
        source = "memory"

        if answer is None:
            answer = self.answer_service.ask(question)
            source = "codex"

        self.pending_question = PendingQuestion(question=question, candidate_answer=answer)

        if answer:
            if source == "codex":
                self.memory.record_answer(question, answer, source="codex")
            print(f"[{source}] {question} -> {answer}")
            self.sender.send(answer)
        else:
            print(f"[skip] No answer available for: {question}")

    def _handle_answer_reveal(self, answer: str) -> None:
        if not self.pending_question:
            print(f"[reveal] Answer was {answer}, but no pending question was tracked.")
            return
        self.memory.record_answer(self.pending_question.question, answer, source="answer_reveal")
        print(f"[learned] {self.pending_question.question} -> {answer}")


def build_bot(config_path: Path = Path("config.json"), workspace: Path = Path(".")) -> tuple[HoloQuizBot, Path]:
    config = load_config(config_path)
    log_path = config.log_path or discover_default_log_path()
    if log_path is None:
        raise FileNotFoundError(
            "Could not find latest.log. Set log_path in config.json to your Minecraft logs/latest.log file."
        )

    memory = QuizMemory.load(config.memory_path)
    answer_service = CodexAnswerClient(config=config, workspace=workspace)
    sender = ChatSender(config)
    return HoloQuizBot(config, memory, answer_service, sender), log_path


def run_forever(config_path: Path = Path("config.json"), poll_seconds: float = 0.2) -> int:
    try:
        bot, log_path = build_bot(config_path=config_path, workspace=Path("."))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Watching {log_path}")
    if bot.config.dry_run:
        print("Dry-run is enabled. Answers will be printed but not typed into Minecraft.")

    tailer = LogTailer(log_path, start_at_end=True)
    while True:
        for line in tailer.read_available():
            bot.handle_line(line)
        time.sleep(poll_seconds)


def main() -> int:
    return run_forever()
```

- [ ] **Step 4: Run runner tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_runner.py -v
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit runner**

Run:

```powershell
git add holoquiz/runner.py tests/test_runner.py
git commit -m "Add HoloQuiz bot orchestration"
```

Expected: commit succeeds.

---

### Task 8: CLI Entrypoint and Documentation

**Files:**
- Create: `holoquiz_bot.py`
- Create: `README.md`
- Modify: `config.example.json`
- Modify: `quiz_memory.example.json`

- [ ] **Step 1: Create CLI entrypoint**

Create `holoquiz_bot.py`:

```python
from __future__ import annotations

import sys

from holoquiz.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Create README**

Create `README.md`:

```markdown
# HoloQuiz Bot

HoloQuiz Bot watches Minecraft Java Edition logs, detects non-math `[HoloQuiz]` questions, answers from `quiz_memory.json`, asks Codex CLI for unknown questions, and can type the answer into Minecraft chat.

Use this only where server rules allow automation.

## Setup

```powershell
python -m pip install -e ".[dev]"
```

The first run creates `config.json` and `quiz_memory.json` if they are missing.

## Configure

Copy the example config:

```powershell
Copy-Item config.example.json config.json
```

Set `log_path` if automatic discovery cannot find your TLauncher Minecraft log:

```json
{
  "log_path": "C:/Users/you/AppData/Roaming/.minecraft/logs/latest.log",
  "dry_run": true
}
```

Keep `dry_run` as `true` until you confirm the bot detects the correct questions.

## Run

```powershell
python holoquiz_bot.py
```

In dry-run mode the bot prints answers:

```text
[memory] Who created Minecraft? -> Notch
[dry-run] Would send answer: Notch
```

## Enable Live Sending

After dry-run works, edit `config.json`:

```json
{
  "dry_run": false
}
```

Put Minecraft in the foreground. The bot sends answers with:

```text
t -> answer -> Enter
```

## Codex CLI

Unknown questions use:

```powershell
codex exec -m gpt-5.4-mini --sandbox read-only --ask-for-approval never --ephemeral --color never --output-last-message <temp-answer-file> "<prompt>"
```

Change `codex_model` in `config.json` if your Codex CLI does not have access to the default model.

## Memory

Known answers are stored in `quiz_memory.json`. The bot updates this file when Minecraft reveals:

```text
The answer was Notch.
```

The JSON file is editable, so you can correct answers manually.
```

- [ ] **Step 3: Run all tests**

Run:

```powershell
python -m pytest -v
```

Expected: PASS, all tests.

- [ ] **Step 4: Commit CLI and docs**

Run:

```powershell
git add holoquiz_bot.py README.md config.example.json quiz_memory.example.json
git commit -m "Add CLI entrypoint and usage docs"
```

Expected: commit succeeds.

---

### Task 9: Manual Dry-Run Verification

**Files:**
- No new files required.

- [ ] **Step 1: Create a temporary sample log**

Run:

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
Set-Content -Path .tmp\latest.log -Value "" -Encoding UTF8
Copy-Item config.example.json config.json
```

Expected: `.tmp\latest.log` and `config.json` exist.

- [ ] **Step 2: Point config at the sample log**

Edit `config.json` so the first fields are:

```json
{
  "log_path": ".tmp/latest.log",
  "dry_run": true,
  "codex_command": "codex",
  "codex_model": "gpt-5.4-mini",
  "codex_timeout_seconds": 6,
  "codex_enable_search": false,
  "codex_persistent_session": false,
  "send_delay_seconds": 0.8,
  "question_cooldown_seconds": 3.0,
  "keyboard_open_chat_key": "t",
  "typing_interval_seconds": 0.01
}
```

Expected: `config.json` contains `.tmp/latest.log` and `"dry_run": true`.

- [ ] **Step 3: Seed one known answer in memory**

Run:

```powershell
@'
{
  "version": 1,
  "questions": {
    "who created minecraft": {
      "question": "Who created Minecraft?",
      "answer": "Notch",
      "source": "answer_reveal",
      "times_seen": 1,
      "times_used": 0,
      "last_seen": "2026-06-14T00:00:00+08:00",
      "last_corrected": "2026-06-14T00:00:00+08:00"
    }
  }
}
'@ | Set-Content -Path quiz_memory.json -Encoding UTF8
```

Expected: `quiz_memory.json` contains the `who created minecraft` answer before the bot starts.

- [ ] **Step 4: Start the bot in dry-run mode**

Run:

```powershell
python holoquiz_bot.py
```

Expected output includes:

```text
Watching .tmp\latest.log
Dry-run is enabled. Answers will be printed but not typed into Minecraft.
```

- [ ] **Step 5: Append a known memory question**

In a second PowerShell window, run:

```powershell
Add-Content -Path .tmp\latest.log -Value "[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft?"
```

Expected bot output:

```text
[memory] Who created Minecraft? -> Notch
[dry-run] Would send answer: Notch
```

- [ ] **Step 6: Append a math question**

Run:

```powershell
Add-Content -Path .tmp\latest.log -Value "[17:40:10] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] 0-(9+12+11+10) = ?"
```

Expected: no answer is printed and no dry-run send line appears.

- [ ] **Step 7: Stop the bot**

Press `Ctrl+C`.

Expected: PowerShell returns to the prompt.

- [ ] **Step 8: Confirm runtime files are ignored**

Do not commit `.tmp`, `config.json`, or `quiz_memory.json`. Run:

```powershell
git status --short
```

Expected: no tracked source files are modified and ignored runtime files do not appear. If `.tmp`, `config.json`, or `quiz_memory.json` appear, confirm `.gitignore` exists and then remove the temp files:

```powershell
Remove-Item -Recurse -Force .tmp
Remove-Item -Force config.json
Remove-Item -Force quiz_memory.json
```

---

## Self-Review

Spec coverage:

- Watches `latest.log`: Task 6 and Task 7.
- Detects `[System] [CHAT] [HoloQuiz]`: Task 2.
- Ignores math prompts: Task 2 and Task 7.
- Uses JSON memory: Task 3 and Task 7.
- Calls Codex CLI for unknown questions: Task 4 and Task 7.
- Learns from `The answer was X`: Task 2, Task 3, and Task 7.
- Sends `t`, answer, `Enter`: Task 5.
- Defaults to dry-run: Task 1, Task 5, Task 8, and Task 9.
- Uses `gpt-5.4-mini`, timeout, `codex exec`, and `--output-last-message`: Task 1 and Task 4.
- Documents setup and live mode: Task 8.

Type consistency:

- `BotConfig` fields match all modules and tests.
- `QuizQuestion`, `AnswerReveal`, and `PendingQuestion` are used consistently.
- `AnswerService.ask(question) -> str | None` and `Sender.send(answer) -> None` match runner tests and concrete classes.

Execution notes:

- Keep each task commit small.
- Run the task-specific test before the full suite.
- Do not enable live keyboard sending until dry-run output matches the Minecraft log.
