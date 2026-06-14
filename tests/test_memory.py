import json
import re

from holoquiz import memory as memory_module
from holoquiz.memory import QuizMemory, normalize_question


def test_normalize_question_removes_answer_marker_and_punctuation_noise():
    assert normalize_question("  Who created Minecraft? = ?  ") == "who created minecraft"


def test_normalize_question_removes_plain_trailing_question_mark():
    assert normalize_question("Who created Minecraft?") == "who created minecraft"


def test_memory_saves_and_loads_answer(tmp_path):
    memory_path = tmp_path / "quiz_memory.json"
    memory = QuizMemory.load(memory_path)

    memory.record_answer("Who created Minecraft?", "Notch", source="answer_reveal")
    reloaded = QuizMemory.load(memory_path)

    assert reloaded.lookup("who created minecraft?") == "Notch"


def test_memory_loads_bom_encoded_seeded_answer_without_recovery(tmp_path):
    memory_path = tmp_path / "quiz_memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "version": 1,
                "questions": {
                    "who created minecraft": {
                        "question": "Who created Minecraft?",
                        "answer": "Notch",
                        "source": "answer_reveal",
                        "times_seen": 0,
                        "times_used": 0,
                        "last_seen": "",
                        "last_corrected": "",
                    }
                },
            }
        ),
        encoding="utf-8-sig",
    )

    memory = QuizMemory.load(memory_path)

    assert not list(tmp_path.glob("quiz_memory.json.corrupt-*.bak"))
    assert memory.data["questions"]["who created minecraft"]["answer"] == "Notch"
    assert memory.lookup("Who created Minecraft?") == "Notch"


def test_lookup_finds_question_stored_under_original_text_key(tmp_path):
    memory_path = tmp_path / "quiz_memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "version": 1,
                "questions": {
                    "Who created Minecraft?": {
                        "question": "Who created Minecraft?",
                        "answer": "Notch",
                        "source": "answer_reveal",
                        "times_seen": 0,
                        "times_used": 0,
                        "last_seen": "",
                        "last_corrected": "",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    memory = QuizMemory.load(memory_path)

    assert memory.lookup("Who created Minecraft?") == "Notch"
    assert memory.lookup("who created minecraft") == "Notch"
    assert memory.lookup("Who created Minecraft? = ?") == "Notch"
    assert "who created minecraft" in memory.data["questions"]
    assert "Who created Minecraft?" not in memory.data["questions"]


def test_sanitizing_duplicate_question_keys_keeps_answered_entry(tmp_path):
    memory_path = tmp_path / "quiz_memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "version": 1,
                "questions": {
                    "Who created Minecraft?": {
                        "question": "Who created Minecraft?",
                        "answer": "Notch",
                        "source": "answer_reveal",
                        "times_seen": 0,
                        "times_used": 0,
                        "last_seen": "",
                        "last_corrected": "",
                    },
                    "who created minecraft": {
                        "question": "Who created Minecraft?",
                        "answer": "",
                        "source": "seen",
                        "times_seen": 1,
                        "times_used": 0,
                        "last_seen": "",
                        "last_corrected": "",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    memory = QuizMemory.load(memory_path)

    assert memory.lookup("Who created Minecraft?") == "Notch"
    assert list(memory.data["questions"]) == ["who created minecraft"]


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
    assert re.fullmatch(
        r"quiz_memory\.json\.corrupt-\d{14}\.bak",
        backups[0].name,
    )
    assert json.loads(memory_path.read_text(encoding="utf-8")) == {"version": 1, "questions": {}}


def test_invalid_json_shape_is_backed_up_and_rewritten(tmp_path):
    memory_path = tmp_path / "quiz_memory.json"
    memory_path.write_text(json.dumps({"version": 1, "questions": []}), encoding="utf-8")

    memory = QuizMemory.load(memory_path)

    backups = list(tmp_path.glob("quiz_memory.json.corrupt-*.bak"))
    assert memory.data == {"version": 1, "questions": {}}
    assert len(backups) == 1
    assert json.loads(memory_path.read_text(encoding="utf-8")) == {"version": 1, "questions": {}}


def test_invalid_question_entry_is_recovered_without_crashing(tmp_path):
    memory_path = tmp_path / "quiz_memory.json"
    memory_path.write_text(
        json.dumps({"version": 1, "questions": {"foo": "bar"}}),
        encoding="utf-8",
    )

    memory = QuizMemory.load(memory_path)

    assert memory.lookup("foo") is None
    assert memory.data == {"version": 1, "questions": {}}
    assert json.loads(memory_path.read_text(encoding="utf-8")) == {"version": 1, "questions": {}}


def test_malformed_question_entry_metadata_is_sanitized(tmp_path):
    memory_path = tmp_path / "quiz_memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "version": 1,
                "questions": {
                    "foo": {
                        "question": 123,
                        "answer": "bar",
                        "source": None,
                        "times_seen": "often",
                        "times_used": "many",
                        "last_seen": 456,
                        "last_corrected": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    memory = QuizMemory.load(memory_path)

    assert json.loads(memory_path.read_text(encoding="utf-8")) == memory.data
    assert memory.data["questions"]["foo"] == {
        "question": "foo",
        "answer": "bar",
        "source": "seen",
        "times_seen": 0,
        "times_used": 0,
        "last_seen": "",
        "last_corrected": "",
    }
    assert memory.lookup("foo") == "bar"
    entry = memory.data["questions"]["foo"]
    assert entry["question"] == "foo"
    assert entry["answer"] == "bar"
    assert entry["source"] == "seen"
    assert entry["times_seen"] == 0
    assert entry["times_used"] == 1
    assert isinstance(entry["last_seen"], str)
    assert entry["last_corrected"] == ""
    assert json.loads(memory_path.read_text(encoding="utf-8")) == memory.data


def test_repeated_recoveries_create_distinct_backups(tmp_path, monkeypatch):
    monkeypatch.setattr(memory_module, "_timestamp_for_filename", lambda: "20260614235959")
    memory_path = tmp_path / "quiz_memory.json"
    memory_path.write_text("{bad json", encoding="utf-8")
    QuizMemory.load(memory_path)

    memory_path.write_text(json.dumps([]), encoding="utf-8")
    QuizMemory.load(memory_path)

    base_backup = tmp_path / "quiz_memory.json.corrupt-20260614235959.bak"
    suffixed_backup = tmp_path / "quiz_memory.json.corrupt-20260614235959-1.bak"
    backups = list(tmp_path.glob("quiz_memory.json.corrupt-*.bak"))
    assert len(backups) == 2
    assert base_backup.exists()
    assert suffixed_backup.exists()
