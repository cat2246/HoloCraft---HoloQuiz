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
class ChatTriggerConfig:
    id: str
    trigger_phrase: str
    macro: str
    cooldown_seconds: float
    typing_interval_seconds: float | None = None
    enabled: bool = True


@dataclass(frozen=True)
class CoordinateLockConfig:
    id: str
    x: float
    y: float
    z: float
    enabled: bool = True
    name: str = ""


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
    screen_phrase_source: str = "ocr"
    chat_trigger_dry_run: bool = True
    chat_triggers: tuple[ChatTriggerConfig, ...] = ()
    coordinate_lock_enabled: bool = False
    coordinate_lock_auto_hit_enabled: bool = False
    coordinate_lock_look_at_enabled: bool = False
    coordinate_locks: tuple[CoordinateLockConfig, ...] = ()
    coordinate_lock_max_distance: float = 50.0
    coordinate_lock_tolerance: float = 0.75
    player_data_url: str = "http://localhost:8025/data/player"


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
    if "chat_triggers" in values:
        values["chat_triggers"] = _chat_triggers_from_json(values["chat_triggers"])
    if "coordinate_locks" in values:
        values["coordinate_locks"] = _coordinate_locks_from_json(
            values["coordinate_locks"]
        )

    return BotConfig(**values)


def save_screen_phrase_settings(
    path: Path,
    *,
    trigger: str,
    trigger_region: ScreenPhraseRegionConfig | None,
    result_region: ScreenPhraseRegionConfig | None,
    auto_send_result: bool,
    source: str = "ocr",
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
    raw_config["screen_phrase_source"] = source
    path.write_text(
        json.dumps(raw_config, indent=2) + "\n",
        encoding="utf-8",
    )


def save_chat_triggers_settings(
    path: Path,
    triggers: list[ChatTriggerConfig] | tuple[ChatTriggerConfig, ...],
    dry_run: bool | None = None,
) -> None:
    raw_config: dict[str, Any] = {}
    if path.exists():
        raw_config = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw_config, dict):
            raise ValueError("Config root must be a JSON object.")

    raw_config["chat_triggers"] = [
        _chat_trigger_to_json(trigger) for trigger in triggers
    ]
    if dry_run is not None:
        raw_config["chat_trigger_dry_run"] = dry_run
    path.write_text(
        json.dumps(raw_config, indent=2) + "\n",
        encoding="utf-8",
    )


def save_coordinate_lock_settings(
    path: Path,
    locks: list[CoordinateLockConfig] | tuple[CoordinateLockConfig, ...],
    *,
    enabled: bool,
    auto_hit_enabled: bool = False,
    look_at_enabled: bool = False,
) -> None:
    raw_config: dict[str, Any] = {}
    if path.exists():
        raw_config = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(raw_config, dict):
            raise ValueError("Config root must be a JSON object.")

    raw_config["coordinate_lock_enabled"] = enabled
    raw_config["coordinate_lock_auto_hit_enabled"] = auto_hit_enabled
    raw_config["coordinate_lock_look_at_enabled"] = look_at_enabled
    raw_config["coordinate_locks"] = [
        _coordinate_lock_to_json(lock) for lock in locks
    ]
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


def _chat_triggers_from_json(value: Any) -> tuple[ChatTriggerConfig, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("chat_triggers must be a list.")

    triggers: list[ChatTriggerConfig] = []
    for raw_trigger in value:
        if not isinstance(raw_trigger, dict):
            raise ValueError("Each chat trigger must be an object.")
        triggers.append(
            ChatTriggerConfig(
                id=str(raw_trigger["id"]),
                trigger_phrase=str(raw_trigger["trigger_phrase"]),
                macro=str(raw_trigger["macro"]),
                cooldown_seconds=float(raw_trigger.get("cooldown_seconds", 0.0)),
                typing_interval_seconds=_optional_float(
                    raw_trigger.get("typing_interval_seconds")
                ),
                enabled=bool(raw_trigger.get("enabled", True)),
            )
        )
    return tuple(triggers)


def _chat_trigger_to_json(trigger: ChatTriggerConfig) -> dict[str, Any]:
    return {
        "id": trigger.id,
        "trigger_phrase": trigger.trigger_phrase,
        "macro": trigger.macro,
        "cooldown_seconds": trigger.cooldown_seconds,
        "typing_interval_seconds": trigger.typing_interval_seconds,
        "enabled": trigger.enabled,
    }


def _coordinate_locks_from_json(value: Any) -> tuple[CoordinateLockConfig, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("coordinate_locks must be a list.")

    locks: list[CoordinateLockConfig] = []
    for raw_lock in value:
        if not isinstance(raw_lock, dict):
            raise ValueError("Each coordinate lock must be an object.")
        locks.append(
            CoordinateLockConfig(
                id=str(raw_lock["id"]),
                x=float(raw_lock["x"]),
                y=float(raw_lock["y"]),
                z=float(raw_lock["z"]),
                enabled=bool(raw_lock.get("enabled", True)),
                name=str(raw_lock.get("name", "")).strip(),
            )
        )
    return tuple(locks)


def _coordinate_lock_to_json(lock: CoordinateLockConfig) -> dict[str, Any]:
    return {
        "id": lock.id,
        "x": lock.x,
        "y": lock.y,
        "z": lock.z,
        "enabled": lock.enabled,
        "name": lock.name,
    }


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _config_to_json_dict(config: BotConfig) -> dict[str, Any]:
    values = asdict(config)
    values["log_path"] = str(config.log_path) if config.log_path else ""
    values["dry_run_sound_path"] = (
        str(config.dry_run_sound_path) if config.dry_run_sound_path else ""
    )
    values["chat_triggers"] = [
        _chat_trigger_to_json(trigger) for trigger in config.chat_triggers
    ]
    values["coordinate_locks"] = [
        _coordinate_lock_to_json(lock) for lock in config.coordinate_locks
    ]
    values.pop("memory_path")
    return values
