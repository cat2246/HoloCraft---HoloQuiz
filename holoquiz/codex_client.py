from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from holoquiz.config import BotConfig


def build_prompt(question: str) -> str:
    return (
        "Answer this quiz question.\n"
        "Return ONLY the answer text.\n"
        "No explanation.\n"
        "No punctuation unless part of answer.\n"
        "Use shortest common answer.\n"
        "If number, digits only.\n"
        "Use live web search when available.\n"
        "Use at most 3 web searches when search is available.\n"
        "If not confident after searching, return UNKNOWN.\n"
        "Never ask for the question; it is inside <quiz_question> below.\n"
        "Do not run shell commands.\n\n"
        "Examples:\n"
        "Question: What mob explodes near players?\n"
        "Answer: Creeper\n"
        "Question: What ore is used to make a beacon base?\n"
        "Answer: Iron\n"
        "Question: Who created Minecraft?\n"
        "Answer: Notch\n\n"
        f"<quiz_question>{question}</quiz_question>\n"
        "Answer only:"
    )


def clean_answer(output: str) -> str | None:
    line = next((line.strip() for line in output.splitlines() if line.strip()), "")
    if not line:
        return None

    answer = re.sub(r"^answer\s*:\s*", "", line, flags=re.IGNORECASE).strip()
    if len(answer) >= 2 and answer[0] == answer[-1] and answer[0] in {"'", '"'}:
        answer = answer[1:-1].strip()
    if answer.endswith(".") and answer.count(".") == 1:
        answer = answer[:-1].strip()
    if _is_clarification_request(answer):
        return None
    if _is_unknown_answer(answer):
        return None

    return answer or None


@dataclass
class CodexAnswerClient:
    config: BotConfig
    workspace: Path
    last_debug_log: str | None = field(default=None, init=False)

    def ask(self, question: str) -> str | None:
        self.last_debug_log = None
        prompt = build_prompt(question)
        output_path = self._create_output_path()
        command: list[str | Path] = [_resolve_command(self.config.codex_command)]
        if self.config.codex_enable_search:
            command.append("--search")
        command.extend(["--ask-for-approval", "never"])
        command.extend(
            [
                "exec",
                "-c",
                f'model_reasoning_effort="{self.config.codex_reasoning_effort}"',
                "-m",
                self.config.codex_model,
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--color",
                "never",
                "--output-last-message",
                output_path,
                "-",
            ]
        )

        try:
            result = subprocess.run(
                command,
                timeout=self.config.codex_timeout_seconds,
                check=True,
                capture_output=True,
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            raw_output = self._read_output_file(output_path)
            answer = clean_answer(raw_output)
            if answer is None:
                self._record_debug(
                    "Codex CLI returned no answer",
                    question=question,
                    command=command,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    output_file=raw_output,
                    returncode=result.returncode,
                )
            return answer
        except subprocess.CalledProcessError as error:
            raw_output = self._read_output_file(output_path)
            answer = clean_answer(raw_output)
            if answer:
                return answer

            self._record_debug(
                f"Codex CLI failed with exit code {error.returncode}",
                question=question,
                command=command,
                stdout=_error_stdout(error),
                stderr=error.stderr,
                output_file=raw_output,
                returncode=error.returncode,
            )
            return None
        except subprocess.TimeoutExpired as error:
            raw_output = self._read_output_file(output_path)
            answer = clean_answer(raw_output)
            if answer:
                return answer

            self._record_debug(
                f"Codex CLI timed out after {error.timeout:g} seconds",
                question=question,
                command=command,
                stdout=_error_stdout(error),
                stderr=error.stderr,
                output_file=raw_output,
            )
            return None
        except OSError as error:
            self._record_debug(
                f"Codex CLI could not start: {error}",
                question=question,
                command=command,
                output_file=self._read_output_file(output_path),
            )
            return None
        finally:
            output_path.unlink(missing_ok=True)

    def _create_output_path(self) -> Path:
        self.workspace.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(
            prefix="holoquiz-codex-",
            suffix=".txt",
            dir=self.workspace,
        )
        os.close(fd)
        return Path(path)

    def _read_output_file(self, output_path: Path) -> str:
        if not output_path.exists():
            return ""
        return output_path.read_text(encoding="utf-8", errors="replace")

    def _record_debug(
        self,
        reason: str,
        *,
        question: str,
        command: list[str | Path],
        stdout: str | bytes | None = None,
        stderr: str | bytes | None = None,
        output_file: str | None = None,
        returncode: int | None = None,
    ) -> None:
        lines = [
            f"[codex-cli] {reason}",
            f"Time: {datetime.now().isoformat(timespec='seconds')}",
            f"Question: {question}",
            f"Command: {_format_command(command)}",
        ]
        if returncode is not None:
            lines.append(f"Exit code: {returncode}")
        lines.extend(
            [
                "STDOUT:",
                _format_stream(stdout),
                "STDERR:",
                _format_stream(stderr),
                "Output file:",
                _format_stream(output_file),
            ]
        )
        self.last_debug_log = "\n".join(lines)
        self._append_debug_log(self.last_debug_log)

    def _append_debug_log(self, debug_log: str) -> None:
        log_path = self.workspace / ".tmp" / "codex_cli_debug.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(debug_log)
            log_file.write("\n\n")


def _error_stdout(
    error: subprocess.CalledProcessError | subprocess.TimeoutExpired,
) -> str | bytes | None:
    return getattr(error, "stdout", None) or getattr(error, "output", None)


def _is_clarification_request(answer: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", answer.lower()).strip()
    return normalized in {
        "please provide the question",
        "provide the question",
        "please provide a question",
        "please provide the quiz question",
    }


def _is_unknown_answer(answer: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", answer.lower()).strip()
    return normalized in {"unknown", "i don t know", "not sure", "unsure"}


def _format_stream(value: str | bytes | None) -> str:
    if value is None:
        return "<empty>"
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    value = value.strip()
    return value or "<empty>"


def _format_command(command: list[str | Path]) -> str:
    parts = [str(part) for part in command]
    if parts:
        parts[-1] = "<prompt>"
    return " ".join(parts)


def _resolve_command(command: str) -> str:
    if "\\" in command or "/" in command:
        return command
    return shutil.which(command) or command
