from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BotConfig:
    log_path: Path | None = None
    dry_run: bool = True
    codex_command: str = "codex"
    codex_model: str = "gpt-5.4-mini"
    codex_timeout_seconds: int = 6
    codex_enable_search: bool = False
    codex_persistent_session: bool = False
    send_delay_seconds: float = 0.8
    question_cooldown_seconds: float = 3.0
    keyboard_open_chat_key: str = "t"
    typing_interval_seconds: float = 0.01
    memory_path: Path = Path("quiz_memory.json")


def discover_default_log_path() -> Path | None:
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    userprofile = os.environ.get("USERPROFILE")

    if appdata:
        candidates.append(Path(appdata) / ".minecraft" / "logs" / "latest.log")
    if userprofile:
        userprofile_path = Path(userprofile)
        candidates.append(
            userprofile_path
            / "AppData"
            / "Roaming"
            / ".minecraft"
            / "logs"
            / "latest.log"
        )
        candidates.append(
            userprofile_path
            / ".tlauncher"
            / "legacy"
            / "Minecraft"
            / "game"
            / "logs"
            / "latest.log"
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_config(path: Path = Path("config.json")) -> BotConfig:
    if not path.exists():
        path.write_text(
            json.dumps(_config_to_json_dict(BotConfig()), indent=2) + "\n",
            encoding="utf-8",
        )
        return BotConfig()

    raw_config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_config, dict):
        raise ValueError("Config root must be a JSON object.")

    values: dict[str, Any] = {**raw_config}
    if "log_path" in values:
        values["log_path"] = Path(values["log_path"]) if values["log_path"] else None
    if "memory_path" in values:
        values["memory_path"] = Path(values["memory_path"])

    return BotConfig(**values)


def _config_to_json_dict(config: BotConfig) -> dict[str, Any]:
    values = asdict(config)
    values["log_path"] = str(config.log_path) if config.log_path else ""
    values["memory_path"] = str(config.memory_path)
    return values
