import json
from pathlib import Path

from holoquiz.config import BotConfig, discover_default_log_path, load_config


def test_load_config_creates_default_when_missing(tmp_path):
    config_path = tmp_path / "config.json"

    config = load_config(config_path)

    assert config == BotConfig()
    assert config_path.exists()
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "log_path": "",
        "dry_run": True,
        "codex_command": "codex",
        "codex_model": "gpt-5.4",
        "codex_reasoning_effort": "low",
        "codex_timeout_seconds": 6,
        "codex_enable_search": False,
        "codex_persistent_session": False,
        "send_delay_seconds": 0.8,
        "question_cooldown_seconds": 3.0,
        "keyboard_open_chat_key": "t",
        "send_mode": "paste",
        "typing_interval_seconds": 0.01,
        "dry_run_sound_path": "C:\\Users\\limwi\\Downloads\\gawr-gura-a.wav",
    }


def test_load_config_overrides_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
{
  "log_path": "C:/Minecraft/logs/latest.log",
  "dry_run": false,
  "codex_model": "gpt-5.4-nano",
  "codex_timeout_seconds": 3,
  "send_delay_seconds": 0.2,
  "dry_run_sound_path": "C:/Sounds/answer.wav",
  "memory_path": "custom_memory.json"
}
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.log_path == Path("C:/Minecraft/logs/latest.log")
    assert config.dry_run is False
    assert config.codex_model == "gpt-5.4-nano"
    assert config.codex_timeout_seconds == 3
    assert config.send_delay_seconds == 0.2
    assert config.dry_run_sound_path == Path("C:/Sounds/answer.wav")
    assert config.codex_command == "codex"
    assert config.memory_path == Path("custom_memory.json")


def test_load_config_accepts_utf8_sig_config_file(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "log_path": "C:/Minecraft/logs/latest.log",
                "dry_run": False,
                "codex_model": "gpt-5.4-nano",
                "memory_path": "custom_memory.json",
            }
        ),
        encoding="utf-8-sig",
    )

    config = load_config(config_path)

    assert config.log_path == Path("C:/Minecraft/logs/latest.log")
    assert config.dry_run is False
    assert config.codex_model == "gpt-5.4-nano"
    assert config.memory_path == Path("custom_memory.json")


def test_discover_default_log_path_prefers_existing_latest_log(tmp_path, monkeypatch):
    appdata = tmp_path / "AppData" / "Roaming"
    userprofile = tmp_path / "User"
    expected = appdata / ".minecraft" / "logs" / "latest.log"
    userprofile_minecraft = (
        userprofile / "AppData" / "Roaming" / ".minecraft" / "logs" / "latest.log"
    )
    tlauncher = (
        userprofile
        / ".tlauncher"
        / "legacy"
        / "Minecraft"
        / "game"
        / "logs"
        / "latest.log"
    )
    for candidate in (expected, userprofile_minecraft, tlauncher):
        candidate.parent.mkdir(parents=True)
        candidate.write_text("", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("USERPROFILE", str(userprofile))

    assert discover_default_log_path() == expected
