from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ScreenPhraseRegionConfig:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class BotConfig:
    log_path: Path | None = None
    program_enabled: bool = True
    auto_answer_enabled: bool = True
    dry_run: bool = True
    dry_run_sound_path: Path | None = Path(
        r"C:\Users\limwi\Downloads\gawr-gura-a.wav"
    )
    codex_command: str = "codex"
    codex_model: str = "gpt-5.4"
    codex_reasoning_effort: str = "low"
    codex_timeout_seconds: int = 6
    codex_enable_search: bool = False
    codex_persistent_session: bool = False
    send_delay_seconds: float = 0.8
    send_delay_min_seconds: float = 0.8
    send_delay_max_seconds: float = 0.8
    question_cooldown_seconds: float = 3.0
    keyboard_open_chat_key: str = "t"
    send_mode: str = "paste"
    typing_interval_seconds: float = 0.01
    memory_path: Path = Path("quiz_memory.json")
    screen_phrase_trigger: str = ""
    screen_phrase_trigger_region: ScreenPhraseRegionConfig | None = None
    screen_phrase_result_region: ScreenPhraseRegionConfig | None = None
    screen_phrase_auto_send_result: bool = False


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

    raw_config = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw_config, dict):
        raise ValueError("Config root must be a JSON object.")

    values: dict[str, Any] = {**raw_config}
    if "log_path" in values:
        values["log_path"] = Path(values["log_path"]) if values["log_path"] else None
    if "memory_path" in values:
        values["memory_path"] = Path(values["memory_path"])
    if "dry_run_sound_path" in values:
        values["dry_run_sound_path"] = (
            Path(values["dry_run_sound_path"])
            if values["dry_run_sound_path"]
            else None
        )
    if "send_delay_min_seconds" not in values:
        values["send_delay_min_seconds"] = values.get(
            "send_delay_seconds",
            BotConfig.send_delay_seconds,
        )
    if "send_delay_max_seconds" not in values:
        values["send_delay_max_seconds"] = values.get(
            "send_delay_seconds",
            BotConfig.send_delay_seconds,
        )
    if "screen_phrase_trigger_region" in values:
        values["screen_phrase_trigger_region"] = _region_from_json(
            values["screen_phrase_trigger_region"]
        )
    if "screen_phrase_result_region" in values:
        values["screen_phrase_result_region"] = _region_from_json(
            values["screen_phrase_result_region"]
        )

    return BotConfig(**values)


def save_screen_phrase_settings(
    path: Path,
    *,
    trigger: str,
    trigger_region: ScreenPhraseRegionConfig | None,
    result_region: ScreenPhraseRegionConfig | None,
    auto_send_result: bool,
) -> None:
    raw_config: dict[str, Any] = {}
    if path.exists():
        raw_config = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw_config, dict):
            raise ValueError("Config root must be a JSON object.")

    raw_config["screen_phrase_trigger"] = trigger
    raw_config["screen_phrase_trigger_region"] = _region_to_json(trigger_region)
    raw_config["screen_phrase_result_region"] = _region_to_json(result_region)
    raw_config["screen_phrase_auto_send_result"] = auto_send_result
    path.write_text(
        json.dumps(raw_config, indent=2) + "\n",
        encoding="utf-8",
    )


def _region_from_json(value: Any) -> ScreenPhraseRegionConfig | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Screen phrase region must be an object or null.")
    return ScreenPhraseRegionConfig(
        x=int(value["x"]),
        y=int(value["y"]),
        width=int(value["width"]),
        height=int(value["height"]),
    )


def _region_to_json(region: ScreenPhraseRegionConfig | None) -> dict[str, int] | None:
    if region is None:
        return None
    return asdict(region)


def _config_to_json_dict(config: BotConfig) -> dict[str, Any]:
    values = asdict(config)
    values["log_path"] = str(config.log_path) if config.log_path else ""
    values["dry_run_sound_path"] = (
        str(config.dry_run_sound_path) if config.dry_run_sound_path else ""
    )
    values.pop("memory_path")
    return values
