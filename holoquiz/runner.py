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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.memory = memory
        self.answer_service = answer_service
        self.sender = sender
        self.clock = clock
        self.pending_question: PendingQuestion | None = None
        self._last_question_times: dict[str, float] = {}

    def handle_line(self, line: str) -> None:
        event = parse_log_line(line)
        if event is None:
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
                self.memory.record_answer(question, answer, source="codex")
            print(f"[{source}] {question} -> {answer}")
            self.sender.send(answer)
            return

        print(f"[skip] {question} -> no answer")

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


def build_bot(
    config_path: Path = Path("config.json"),
    workspace: Path = Path("."),
) -> tuple[HoloQuizBot, Path]:
    config = load_config(config_path)
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
    answer_service = CodexAnswerClient(config=config, workspace=workspace)
    sender = ChatSender(config=config)
    bot = HoloQuizBot(
        config=config,
        memory=memory,
        answer_service=answer_service,
        sender=sender,
    )
    return bot, log_path


def run_forever(
    config_path: Path = Path("config.json"),
    poll_seconds: float = 0.2,
) -> int:
    try:
        bot, log_path = build_bot(config_path=config_path)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 2

    print(f"Watching {log_path}")
    if bot.config.dry_run:
        print("Dry-run enabled; answers will not be typed into chat.")

    tailer = LogTailer(log_path, start_at_end=True)
    while True:
        for line in tailer.read_available():
            bot.handle_line(line)
        time.sleep(poll_seconds)


def main() -> int:
    return run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
