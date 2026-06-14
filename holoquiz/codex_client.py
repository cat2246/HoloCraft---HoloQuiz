from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from holoquiz.config import BotConfig


def build_prompt(question: str) -> str:
    return (
        "Return ONLY the answer text.\n"
        "No explanation.\n"
        "No punctuation unless part of answer.\n"
        "Use shortest common answer.\n"
        "If number, digits only.\n"
        "If unsure, best likely answer.\n"
        "Do not run tools or commands.\n\n"
        "Examples:\n"
        "Question: What mob explodes near players?\n"
        "Answer: Creeper\n"
        "Question: What ore is used to make a beacon base?\n"
        "Answer: Iron\n"
        "Question: Who created Minecraft?\n"
        "Answer: Notch\n\n"
        f"Question: {question}\n"
        "Answer:"
    )


def clean_answer(output: str) -> str | None:
    line = next((line.strip() for line in output.splitlines() if line.strip()), "")
    if not line:
        return None

    answer = re.sub(r"^answer\s*:\s*", "", line, flags=re.IGNORECASE).strip()
    if len(answer) >= 2 and answer[0] == answer[-1] and answer[0] in {"'", '"'}:
        answer = answer[1:-1].strip()
    if answer.endswith("."):
        answer = answer[:-1].strip()

    return answer or None


@dataclass(frozen=True)
class CodexAnswerClient:
    config: BotConfig
    workspace: Path

    def ask(self, question: str) -> str | None:
        prompt = build_prompt(question)
        output_path = self._create_output_path()
        command: list[str | Path] = [self.config.codex_command]
        if self.config.codex_enable_search:
            command.append("--search")
        command.extend(
            [
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
        )

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

    def _create_output_path(self) -> Path:
        self.workspace.mkdir(parents=True, exist_ok=True)
        fd, path = tempfile.mkstemp(
            prefix="holoquiz-codex-",
            suffix=".txt",
            dir=self.workspace,
        )
        os.close(fd)
        return Path(path)
