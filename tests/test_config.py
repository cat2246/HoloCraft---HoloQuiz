from pathlib import Path

from holoquiz.config import BotConfig, discover_default_log_path, load_config


def test_load_config_creates_default_when_missing(tmp_path):
    config_path = tmp_path / "config.json"

    config = load_config(config_path)

    assert config == BotConfig()
    assert config_path.exists()
    assert '"dry_run": true' in config_path.read_text(encoding="utf-8")


def test_load_config_overrides_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
{
  "log_path": "C:/Minecraft/logs/latest.log",
  "dry_run": false,
  "codex_model": "gpt-5.4-nano",
  "codex_timeout_seconds": 3,
  "send_delay_seconds": 0.2
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
    assert config.codex_command == "codex"


def test_discover_default_log_path_prefers_existing_latest_log(tmp_path, monkeypatch):
    appdata = tmp_path / "AppData" / "Roaming"
    expected = appdata / ".minecraft" / "logs" / "latest.log"
    expected.parent.mkdir(parents=True)
    expected.write_text("", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "User"))

    assert discover_default_log_path() == expected
