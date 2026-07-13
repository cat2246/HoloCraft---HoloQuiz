from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
import sys
import time
from typing import Callable, Protocol

from holoquiz.chat_trigger import ChatTriggerRunner
from holoquiz.chat_sender import ChatSender
from holoquiz.codex_client import CodexAnswerClient
from holoquiz.config import BotConfig, discover_default_log_path, load_config
from holoquiz.log_tailer import LogTailer
from holoquiz.memory import QuizMemory, normalize_question
from holoquiz.parser import (
    AnswerReveal,
    QuizQuestion,
    is_ignored_math_holoquiz_line,
    parse_log_line,
)
from holoquiz.runtime import FIND_ANSWER_FUNCTION, RuntimeControls
from holoquiz.sound_player import SoundPlayer


class AnswerService(Protocol):
    def ask(self, question: str) -> str | None:
        ...


class Sender(Protocol):
    def send(self, answer: str) -> None:
        ...

    def send_macro(
        self,
        macro: str,
        typing_interval_seconds: float | None = None,
    ) -> None:
        ...


@dataclass(frozen=True)
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
        runtime_controls: RuntimeControls | None = None,
        before_live_answer_send: Callable[[], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        chat_trigger_sound_player: SoundPlayer | None = None,
    ) -> None:
        self.config = config
        self.runtime_controls = runtime_controls or RuntimeControls.from_config(config)
        self.memory = memory
        self.answer_service = answer_service
        self.sender = sender
        self._before_live_answer_send = before_live_answer_send
        self.clock = clock
        self.chat_trigger_runner = ChatTriggerRunner(
            sender,
            clock=clock,
            sound_player=chat_trigger_sound_player,
        )
        self.pending_question: PendingQuestion | None = None
        self._last_question_times: dict[str, float] = {}

    def set_before_live_answer_send(self, callback: Callable[[], None] | None) -> None:
        self._before_live_answer_send = callback

    def handle_line(self, line: str) -> None:
        if not self.runtime_controls.is_program_enabled():
            return

        self.chat_trigger_runner.handle_line(
            line,
            self.runtime_controls.get_config().chat_triggers,
        )

        event = parse_log_line(line)
        if event is None:
            if is_ignored_math_holoquiz_line(line):
                self.pending_question = None
                self.runtime_controls.set_latest_question(None)
            return

        if isinstance(event, QuizQuestion):
            self._handle_question(event.question)
        elif isinstance(event, AnswerReveal):
            self._handle_answer_reveal(event.answer)

    def _handle_question(self, question: str) -> None:
        question_key = normalize_question(question)
        now = self.clock()
        last_seen_at = self._last_question_times.get(question_key)
        if (
            last_seen_at is not None
            and now - last_seen_at < self.config.question_cooldown_seconds
        ):
            return

        self._last_question_times[question_key] = now
        self.memory.record_seen(question)
        self.runtime_controls.set_latest_question(question)
        self.pending_question = PendingQuestion(
            question=question,
            candidate_answer=None,
        )

        if not self.runtime_controls.is_function_enabled(FIND_ANSWER_FUNCTION):
            print(f"[disabled] Find answer skipped: {question}")
            return

        answer = self.memory.lookup(question)
        source = "memory"
        if answer is None:
            answer = self.answer_service.ask(question)
            source = "codex"

        self.pending_question = PendingQuestion(
            question=question,
            candidate_answer=answer,
        )

        if answer:
            if source == "codex":
                if self._answer_was_revealed_while_searching(question):
                    print(f"[stale] {question} -> {answer} (answer already revealed)")
                    return

            if source == "codex":
                self.memory.record_answer(question, answer, source="codex")
            print(f"[{source}] {question} -> {answer}")
            self.sender.send(answer)
            return

        print(f"[skip] {question} -> no answer")
        debug_log = getattr(self.answer_service, "last_debug_log", None)
        if debug_log:
            print(debug_log)

    def _handle_answer_reveal(self, answer: str) -> None:
        if self.pending_question is None:
            print(f"[reveal] {answer} (no pending question)")
            self.pending_question = None
            return

        pending_question = self.pending_question
        self.memory.record_answer(
            pending_question.question,
            answer,
            source="answer_reveal",
        )
        print(f"[learned] {pending_question.question} -> {answer}")
        self.pending_question = None

    def _answer_was_revealed_while_searching(self, question: str) -> bool:
        if self.runtime_controls.get_config().dry_run:
            return False

        if self._before_live_answer_send is not None:
            self._before_live_answer_send()

        pending_question = self.pending_question
        if pending_question is None:
            return True

        return normalize_question(pending_question.question) != normalize_question(question)


def build_bot(
    config_path: Path = Path("config.json"),
    workspace: Path = Path("."),
    runtime_controls: RuntimeControls | None = None,
) -> tuple[HoloQuizBot, Path]:
    config = load_config(config_path)
    runtime_controls = runtime_controls or RuntimeControls.from_config(config)
    log_path = config.log_path or discover_default_log_path()
    if log_path is None:
        raise FileNotFoundError(
            "No Minecraft latest.log found. Set log_path in config.json."
        )
    if not log_path.exists():
        raise FileNotFoundError(
            f"Minecraft log path does not exist: {log_path}. "
            "Set log_path in config.json."
        )

    memory = QuizMemory.load(config.memory_path)
    answer_service = CodexAnswerClient(
        config=config,
        workspace=workspace,
        config_provider=runtime_controls.get_config,
    )
    sender = ChatSender(
        config=config,
        config_provider=runtime_controls.get_config,
    )
    bot = HoloQuizBot(
        config=config,
        memory=memory,
        answer_service=answer_service,
        sender=sender,
        runtime_controls=runtime_controls,
    )
    return bot, log_path


def drain_answer_reveals(
    bot: HoloQuizBot,
    tailer: LogTailer,
    pending_lines: deque[str],
) -> None:
    pending_lines.extend(tailer.read_available())
    retained_lines: deque[str] = deque()

    while pending_lines:
        line = pending_lines.popleft()
        event = parse_log_line(line)
        if is_ignored_math_holoquiz_line(line) or isinstance(event, AnswerReveal):
            bot.handle_line(line)
        else:
            retained_lines.append(line)

    pending_lines.extend(retained_lines)


def run_forever(
    config_path: Path = Path("config.json"),
    poll_seconds: float = 0.2,
    runtime_controls: RuntimeControls | None = None,
) -> int:
    try:
        bot, log_path = build_bot(
            config_path=config_path,
            runtime_controls=runtime_controls,
        )
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2

    print(f"Watching {log_path}")
    if bot.runtime_controls.get_config().dry_run:
        print("Dry-run enabled; answers will not be typed into chat.")

    tailer = LogTailer(log_path, start_at_end=True)
    pending_lines: deque[str] = deque()
    bot.set_before_live_answer_send(
        lambda: drain_answer_reveals(bot, tailer, pending_lines)
    )
    while True:
        pending_lines.extend(tailer.read_available())
        while pending_lines:
            bot.handle_line(pending_lines.popleft())
        time.sleep(poll_seconds)


def main() -> int:
    return run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
