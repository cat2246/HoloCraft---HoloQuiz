from __future__ import annotations

from dataclasses import dataclass
import re


CHAT_MARKER = "[System] [CHAT]"
HOLOQUIZ_MARKER = "[HoloQuiz]"
TRAILING_ANSWER_PUNCTUATION = ".,!?;:"


@dataclass(frozen=True)
class QuizQuestion:
    question: str


@dataclass(frozen=True)
class AnswerReveal:
    answer: str


def parse_log_line(line: str) -> QuizQuestion | AnswerReveal | None:
    message = _holoquiz_message(line)
    if message is None:
        return None

    reveal = _parse_answer_reveal(message)
    if reveal:
        return reveal

    if not _looks_like_question(message):
        return None

    if is_math_prompt(message):
        return None

    return QuizQuestion(question=message)


def is_ignored_math_holoquiz_line(line: str) -> bool:
    message = _holoquiz_message(line)
    if message is None:
        return False

    return _looks_like_question(message) and is_math_prompt(message)


def _holoquiz_message(line: str) -> str | None:
    chat_index = line.find(CHAT_MARKER)
    if chat_index == -1:
        return None

    chat_message = line[chat_index + len(CHAT_MARKER) :].lstrip()
    if not chat_message.startswith(HOLOQUIZ_MARKER):
        return None

    message = chat_message[len(HOLOQUIZ_MARKER) :].strip()
    return message


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
    return message.endswith("?") or message.endswith("= ?") or _has_blank_marker(message)


def _has_blank_marker(message: str) -> bool:
    return bool(re.search(r"(?<!\w)(?:-{4,}|\?{4,}|_{4,})(?!\w)", message))


def _parse_answer_reveal(message: str) -> AnswerReveal | None:
    match = re.search(r"The answer was\s+(.+?)\s*$", message, flags=re.IGNORECASE)
    if not match:
        return None
    answer = match.group(1).strip().rstrip(TRAILING_ANSWER_PUNCTUATION)
    return AnswerReveal(answer=answer)
