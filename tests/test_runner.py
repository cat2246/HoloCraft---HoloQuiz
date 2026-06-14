import json

import pytest

from holoquiz.config import BotConfig
from holoquiz.memory import QuizMemory
from holoquiz.runner import HoloQuizBot, build_bot


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


def test_bot_clears_pending_question_after_reveal_to_ignore_later_math_reveal(tmp_path):
    answer_service = FakeAnswerService({"Who created Minecraft?": "Jeb"})
    bot = make_bot(tmp_path, answer_service=answer_service)

    bot.handle_line("[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft?")
    bot.handle_line("[17:40:09] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] No one got the answer! The answer was Notch.")

    assert bot.memory.lookup("Who created Minecraft?") == "Notch"
    assert bot.pending_question is None

    bot.handle_line("[17:41:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] 0-(9+12+11+10) = ?")
    bot.handle_line("[17:41:09] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] No one got the answer! The answer was -42.")

    assert bot.memory.lookup("Who created Minecraft?") == "Notch"


def test_build_bot_rejects_configured_missing_log_path(tmp_path):
    missing_log_path = tmp_path / "missing" / "latest.log"
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"log_path": str(missing_log_path)}),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="latest.log"):
        build_bot(config_path=config_path, workspace=tmp_path)
