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
