import json
from collections import deque

import pytest

from holoquiz.config import BotConfig, ChatTriggerConfig
from holoquiz.memory import QuizMemory
from holoquiz.runtime import FIND_ANSWER_FUNCTION, RuntimeControls
from holoquiz.runner import HoloQuizBot, build_bot, drain_answer_reveals


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
        self.macros = []

    def send(self, answer):
        self.sent.append(answer)

    def send_macro(self, macro, typing_interval_seconds=None):
        self.macros.append((macro, typing_interval_seconds))


class FakeSoundPlayer:
    def __init__(self):
        self.paths = []

    def play(self, sound_path):
        self.paths.append(sound_path)


class DebugAnswerService:
    last_debug_log = "[codex-cli] debug details"

    def ask(self, question):
        return None


def make_bot(tmp_path, answer_service=None, sender=None, cooldown=3.0):
    memory = QuizMemory.load(tmp_path / "quiz_memory.json")
    return HoloQuizBot(
        config=BotConfig(question_cooldown_seconds=cooldown),
        memory=memory,
        answer_service=answer_service or FakeAnswerService({}),
        sender=sender or FakeSender(),
        clock=lambda: 100.0,
    )


def make_bot_with_controls(
    tmp_path,
    controls,
    answer_service=None,
    sender=None,
):
    memory = QuizMemory.load(tmp_path / "quiz_memory.json")
    return HoloQuizBot(
        config=controls.get_config(),
        memory=memory,
        answer_service=answer_service or FakeAnswerService({}),
        sender=sender or FakeSender(),
        runtime_controls=controls,
        clock=lambda: 100.0,
    )


class FakeTailer:
    def __init__(self, lines=None):
        self.lines = deque(lines or [])

    def read_available(self):
        lines = list(self.lines)
        self.lines.clear()
        return lines


def test_bot_answers_from_memory_before_codex(tmp_path):
    sender = FakeSender()
    answer_service = FakeAnswerService({"Who created Minecraft?": "Wrong"})
    bot = make_bot(tmp_path, answer_service=answer_service, sender=sender)
    bot.memory.record_answer("Who created Minecraft?", "Notch", source="answer_reveal")

    bot.handle_line("[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft?")

    assert sender.sent == ["Notch"]
    assert answer_service.questions == []


def test_bot_tracks_latest_question_for_browser_search(tmp_path):
    controls = RuntimeControls.from_config(BotConfig())
    bot = make_bot_with_controls(tmp_path, controls=controls)

    bot.handle_line(
        "[17:40:00] [Render thread/INFO]: [System] [CHAT] "
        "[HoloQuiz] Hololive - Trivia: Kronii's -------- is listed officially on Urban Dictionary."
    )

    assert (
        controls.get_latest_question()
        == "Hololive - Trivia: Kronii's -------- is listed officially on Urban Dictionary."
    )


def test_math_question_clears_latest_browser_search_question(tmp_path):
    controls = RuntimeControls.from_config(BotConfig())
    bot = make_bot_with_controls(tmp_path, controls=controls)

    bot.handle_line(
        "[17:40:00] [Render thread/INFO]: [System] [CHAT] "
        "[HoloQuiz] Who created Minecraft?"
    )
    bot.handle_line(
        "[17:41:00] [Render thread/INFO]: [System] [CHAT] "
        "[HoloQuiz] 0-(9+12+11+10) = ?"
    )

    assert controls.get_latest_question() is None


def test_live_bot_skips_codex_answer_when_reveal_arrived_while_searching(tmp_path):
    sender = FakeSender()
    answer_service = FakeAnswerService({"Who created Minecraft?": "Jeb"})
    pending_lines = deque(
        [
            "[17:40:09] [Render thread/INFO]: [System] [CHAT] "
            "[HoloQuiz] Alex wins after 6.238 seconds! The answer was Notch.\n"
        ]
    )
    tailer = FakeTailer()
    memory = QuizMemory.load(tmp_path / "quiz_memory.json")

    bot = HoloQuizBot(
        config=BotConfig(dry_run=False),
        memory=memory,
        answer_service=answer_service,
        sender=sender,
        before_live_answer_send=lambda: drain_answer_reveals(
            bot,
            tailer,
            pending_lines,
        ),
        clock=lambda: 100.0,
    )

    bot.handle_line("[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft?")

    assert sender.sent == []
    assert bot.memory.lookup("Who created Minecraft?") == "Notch"


def test_live_reveal_drain_clears_pending_question_on_math_prompt(tmp_path):
    sender = FakeSender()
    answer_service = FakeAnswerService({"Who created Minecraft?": "Jeb"})
    pending_lines = deque(
        [
            "[17:41:00] [Render thread/INFO]: [System] [CHAT] "
            "[HoloQuiz] 0-(9+12+11+10) = ?\n",
            "[17:41:09] [Render thread/INFO]: [System] [CHAT] "
            "[HoloQuiz] No one got the answer! The answer was -42.\n",
        ]
    )
    tailer = FakeTailer()
    memory = QuizMemory.load(tmp_path / "quiz_memory.json")

    bot = HoloQuizBot(
        config=BotConfig(dry_run=False),
        memory=memory,
        answer_service=answer_service,
        sender=sender,
        before_live_answer_send=lambda: drain_answer_reveals(
            bot,
            tailer,
            pending_lines,
        ),
        clock=lambda: 100.0,
    )

    bot.handle_line("[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft?")

    assert sender.sent == []
    assert bot.memory.lookup("Who created Minecraft?") is None


def test_bot_skips_quiz_lines_when_program_disabled(tmp_path):
    controls = RuntimeControls.from_config(BotConfig())
    controls.set_program_enabled(False)
    sender = FakeSender()
    answer_service = FakeAnswerService({"Who created Minecraft?": "Notch"})
    bot = make_bot_with_controls(
        tmp_path,
        controls=controls,
        answer_service=answer_service,
        sender=sender,
    )

    bot.handle_line("[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft?")

    assert sender.sent == []
    assert answer_service.questions == []
    assert bot.memory.lookup("Who created Minecraft?") is None


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


def test_bot_skips_answer_lookup_when_find_answer_function_disabled(tmp_path):
    controls = RuntimeControls.from_config(BotConfig())
    controls.set_function_enabled(FIND_ANSWER_FUNCTION, False)
    sender = FakeSender()
    answer_service = FakeAnswerService({"Who created Minecraft?": "Notch"})
    bot = make_bot_with_controls(
        tmp_path,
        controls=controls,
        answer_service=answer_service,
        sender=sender,
    )

    bot.handle_line("[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft?")

    assert sender.sent == []
    assert answer_service.questions == []
    assert bot.pending_question is not None
    assert bot.pending_question.question == "Who created Minecraft?"
    assert bot.pending_question.candidate_answer is None


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


def test_bot_prints_codex_debug_when_unknown_question_has_no_answer(tmp_path, capsys):
    bot = make_bot(tmp_path, answer_service=DebugAnswerService())

    bot.handle_line("[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft?")

    output = capsys.readouterr().out
    assert "[skip] Who created Minecraft? -> no answer" in output
    assert "[codex-cli] debug details" in output


def test_math_question_clears_stale_pending_question_without_learning_reveal(tmp_path):
    sender = FakeSender()
    answer_service = FakeAnswerService({"Who created Minecraft?": "Jeb"})
    bot = make_bot(tmp_path, answer_service=answer_service, sender=sender)

    bot.handle_line("[17:40:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] Who created Minecraft?")

    assert bot.pending_question is not None
    assert sender.sent == ["Jeb"]

    bot.handle_line("[17:41:00] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] 0-(9+12+11+10) = ?")

    assert bot.pending_question is None
    assert sender.sent == ["Jeb"]

    bot.handle_line("[17:41:09] [Render thread/INFO]: [System] [CHAT] [HoloQuiz] No one got the answer! The answer was -42.")

    assert bot.memory.lookup("Who created Minecraft?") == "Jeb"


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


def test_bot_runs_chat_trigger_macro_for_matching_log_line(tmp_path, capsys):
    sender = FakeSender()
    config = BotConfig(
        chat_triggers=(
            ChatTriggerConfig(
                id="morning",
                trigger_phrase="Good Morning!",
                macro="tGood Morning{{Enter}}",
                cooldown_seconds=30.0,
                enabled=True,
            ),
        )
    )
    bot = HoloQuizBot(
        config=config,
        memory=QuizMemory.load(tmp_path / "quiz_memory.json"),
        answer_service=FakeAnswerService({}),
        sender=sender,
        clock=lambda: 100.0,
    )

    bot.handle_line(
        "[17:40:00] [Render thread/INFO]: [System] [CHAT] "
        "[Discord | Divine] !?Cat2246?! \u00bb Good Morning!"
    )

    assert sender.macros == [("tGood Morning{{Enter}}", None)]
    assert "[chat-trigger] Good Morning! -> tGood Morning{{Enter}}" in capsys.readouterr().out


def test_bot_skips_chat_trigger_when_disabled_or_in_cooldown(tmp_path):
    sender = FakeSender()
    now = 100.0
    config = BotConfig(
        chat_triggers=(
            ChatTriggerConfig(
                id="morning",
                trigger_phrase="Good Morning!",
                macro="tGood Morning{{Enter}}",
                cooldown_seconds=30.0,
                enabled=True,
            ),
            ChatTriggerConfig(
                id="night",
                trigger_phrase="Good Night!",
                macro="tGood Night{{Enter}}",
                cooldown_seconds=0.0,
                enabled=False,
            ),
        )
    )
    bot = HoloQuizBot(
        config=config,
        memory=QuizMemory.load(tmp_path / "quiz_memory.json"),
        answer_service=FakeAnswerService({}),
        sender=sender,
        clock=lambda: now,
    )

    bot.handle_line("[System] [CHAT] Good Morning!")
    now = 110.0
    bot.handle_line("[System] [CHAT] Good Morning!")
    bot.handle_line("[System] [CHAT] Good Night!")
    now = 130.0
    bot.handle_line("[System] [CHAT] Good Morning!")

    assert sender.macros == [
        ("tGood Morning{{Enter}}", None),
        ("tGood Morning{{Enter}}", None),
    ]


def test_bot_passes_chat_trigger_typing_interval_to_macro_sender(tmp_path):
    sender = FakeSender()
    config = BotConfig(
        chat_triggers=(
            ChatTriggerConfig(
                id="morning",
                trigger_phrase="Good Morning!",
                macro="tGood Morning{{Enter}}",
                cooldown_seconds=30.0,
                typing_interval_seconds=0.1,
                enabled=True,
            ),
        )
    )
    bot = HoloQuizBot(
        config=config,
        memory=QuizMemory.load(tmp_path / "quiz_memory.json"),
        answer_service=FakeAnswerService({}),
        sender=sender,
        clock=lambda: 100.0,
    )

    bot.handle_line("[System] [CHAT] Good Morning!")

    assert sender.macros == [("tGood Morning{{Enter}}", 0.1)]


def test_bot_plays_chat_trigger_sound_without_a_macro(tmp_path, capsys):
    sender = FakeSender()
    sound_player = FakeSoundPlayer()
    sound_path = tmp_path / "alarm.mp3"
    config = BotConfig(
        chat_triggers=(
            ChatTriggerConfig(
                id="alarm",
                trigger_phrase="Wake up!",
                macro="",
                cooldown_seconds=30.0,
                sound_path=sound_path,
            ),
        )
    )
    bot = HoloQuizBot(
        config=config,
        memory=QuizMemory.load(tmp_path / "quiz_memory.json"),
        answer_service=FakeAnswerService({}),
        sender=sender,
        clock=lambda: 100.0,
        chat_trigger_sound_player=sound_player,
    )

    bot.handle_line("[System] [CHAT] Wake up!")

    assert sound_player.paths == [sound_path]
    assert sender.macros == []
    assert f"sound: {sound_path}" in capsys.readouterr().out


def test_bot_runs_both_chat_trigger_actions(tmp_path):
    sender = FakeSender()
    sound_player = FakeSoundPlayer()
    sound_path = tmp_path / "greeting.wav"
    config = BotConfig(
        chat_triggers=(
            ChatTriggerConfig(
                id="greeting",
                trigger_phrase="Hello!",
                macro="tHello{{Enter}}",
                cooldown_seconds=30.0,
                sound_path=sound_path,
            ),
        )
    )
    bot = HoloQuizBot(
        config=config,
        memory=QuizMemory.load(tmp_path / "quiz_memory.json"),
        answer_service=FakeAnswerService({}),
        sender=sender,
        clock=lambda: 100.0,
        chat_trigger_sound_player=sound_player,
    )

    bot.handle_line("[System] [CHAT] Hello!")

    assert sound_player.paths == [sound_path]
    assert sender.macros == [("tHello{{Enter}}", None)]
