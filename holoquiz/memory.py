from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from json import JSONDecodeError
from pathlib import Path
import re
from typing import Any


EMPTY_MEMORY = {"version": 1, "questions": {}}


def normalize_question(question: str) -> str:
    normalized = question.strip().lower()
    normalized = re.sub(r"\s*=\s*\?\s*$", "", normalized)
    normalized = re.sub(r"\?+\s*$", "", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


class QuizMemory:
    def __init__(self, path: Path, data: dict[str, Any]):
        self.path = path
        self.data = data

    @classmethod
    def load(cls, path: Path) -> QuizMemory:
        if not path.exists():
            memory = cls(path, _empty_memory())
            memory.save()
            return memory

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except JSONDecodeError:
            return cls._recover_invalid_file(path)

        if not isinstance(data, dict) or not isinstance(data.get("questions"), dict):
            return cls._recover_invalid_file(path)

        if not all(isinstance(entry, dict) for entry in data["questions"].values()):
            return cls._recover_invalid_file(path)

        return cls(path, data)

    @classmethod
    def _recover_invalid_file(cls, path: Path) -> QuizMemory:
        path.replace(_backup_path(path))
        memory = cls(path, _empty_memory())
        memory.save()
        return memory

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def lookup(self, question: str) -> str | None:
        key = normalize_question(question)
        entry = self.data["questions"].get(key)
        if not entry:
            return None

        answer = entry.get("answer", "")
        if not answer:
            return None

        entry["times_used"] = int(entry.get("times_used", 0)) + 1
        entry["last_seen"] = _timestamp()
        self.save()
        return answer

    def record_seen(self, question: str) -> None:
        key = normalize_question(question)
        entry = self._entry_for(key, question)
        entry["times_seen"] = int(entry.get("times_seen", 0)) + 1
        entry["last_seen"] = _timestamp()
        self.save()

    def record_answer(self, question: str, answer: str, source: str) -> None:
        key = normalize_question(question)
        entry = self._entry_for(key, question)
        clean_answer = answer.strip()
        previous_answer = entry.get("answer", "")

        entry["question"] = question.strip()
        entry["answer"] = clean_answer
        entry["source"] = source
        entry["last_seen"] = _timestamp()
        if clean_answer and clean_answer != previous_answer:
            entry["last_corrected"] = entry["last_seen"]

        self.save()

    def _entry_for(self, key: str, question: str) -> dict[str, Any]:
        questions = self.data["questions"]
        if key not in questions:
            questions[key] = {
                "question": question.strip(),
                "answer": "",
                "source": "seen",
                "times_seen": 0,
                "times_used": 0,
                "last_seen": "",
                "last_corrected": "",
            }
        return questions[key]


def _empty_memory() -> dict[str, Any]:
    return deepcopy(EMPTY_MEMORY)


def _timestamp() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _timestamp_for_filename() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d%H%M%S%f")


def _backup_path(path: Path) -> Path:
    base_name = f"{path.name}.corrupt-{_timestamp_for_filename()}"
    candidate = path.with_name(f"{base_name}.bak")
    suffix = 1

    while candidate.exists():
        candidate = path.with_name(f"{base_name}-{suffix}.bak")
        suffix += 1

    return candidate
