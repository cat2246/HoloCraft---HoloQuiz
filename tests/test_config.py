import json
from pathlib import Path

import pytest

from holoquiz.config import (
    AutoHealItemConfig,
    BotConfig,
    ChatTriggerConfig,
    COORDINATE_LOCK_LOOK_LOCK,
    COORDINATE_LOCK_LOOK_NONE,
    COORDINATE_LOCK_LOOK_TARGET,
    CoordinateLockConfig,
    ScreenPhraseRegionConfig,
    discover_default_log_path,
    load_config,
    save_answer_sound_setting,
    save_auto_heal_settings,
    save_chat_triggers_settings,
    save_coordinate_lock_settings,
    save_holoquiz_enabled_setting,
    save_screen_phrase_settings,
    save_send_delay_settings,
    validate_auto_heal_items,
)


def test_load_config_creates_default_when_missing(tmp_path):
    config_path = tmp_path / "config.json"

    config = load_config(config_path)

    assert config == BotConfig()
    assert config_path.exists()
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "log_path": "",
        "program_enabled": True,
        "holoquiz_enabled": True,
        "auto_answer_enabled": True,
        "dry_run": True,
        "answer_sound_enabled": True,
        "codex_command": "codex",
        "codex_model": "gpt-5.4",
        "codex_reasoning_effort": "low",
        "codex_timeout_seconds": 6,
        "codex_enable_search": False,
        "codex_persistent_session": False,
        "send_delay_seconds": 0.8,
        "send_delay_min_seconds": 0.8,
        "send_delay_max_seconds": 0.8,
        "question_cooldown_seconds": 3.0,
        "keyboard_open_chat_key": "t",
        "send_mode": "paste",
        "typing_interval_seconds": 0.01,
        "dry_run_sound_path": "C:\\Users\\limwi\\Downloads\\gawr-gura-a.wav",
        "screen_phrase_trigger": "",
        "screen_phrase_trigger_region": None,
        "screen_phrase_result_region": None,
        "screen_phrase_auto_send_result": False,
        "screen_phrase_source": "ocr",
        "chat_trigger_dry_run": True,
        "chat_triggers": [],
        "coordinate_lock_enabled": False,
        "coordinate_lock_auto_hit_enabled": False,
        "coordinate_lock_auto_hit_min_seconds": 0.3,
        "coordinate_lock_auto_hit_max_seconds": 0.8,
        "coordinate_lock_look_mode": "none",
        "coordinate_locks": [],
        "coordinate_lock_max_distance": 50.0,
        "coordinate_lock_tolerance": 0.75,
        "player_data_url": "http://127.0.0.1:8026/data/player",
        "auto_heal_enabled": False,
        "auto_heal_items": [],
        "auto_heal_return_item_name": "",
    }


def test_auto_heal_defaults_are_safe():
    config = BotConfig()

    assert config.auto_heal_enabled is False
    assert config.auto_heal_items == ()


@pytest.mark.parametrize("value", ["false", 1, None])
def test_load_config_rejects_non_boolean_auto_heal_enabled(tmp_path, value):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"auto_heal_enabled": value}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="auto_heal_enabled must be a boolean"):
        load_config(config_path)


def test_load_config_preserves_exact_unicode_auto_heal_name(tmp_path):
    config_path = tmp_path / "config.json"
    name = ".｡*ﾟ+.*.｡ ʜᴏʟᴏ ᴀɴɴɪᴠ ᴄᴀᴋᴇ ｡+..｡*ﾟ"
    config_path.write_text(
        json.dumps(
            {
                "auto_heal_enabled": True,
                "auto_heal_items": [
                    {
                        "name": name,
                        "cooldown_seconds": 30,
                        "use_duration_seconds": 2.5,
                        "health_below": 20,
                        "hunger_below": 8,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    before = config_path.read_text(encoding="utf-8")
    config = load_config(config_path)

    assert config.auto_heal_enabled is True
    assert config.auto_heal_items == (
        AutoHealItemConfig(name, 30.0, 2.5, 20, 8),
    )
    assert config_path.read_text(encoding="utf-8") == before


def test_load_auto_heal_prefers_new_percentage_keys(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "auto_heal_items": [
                    {
                        "name": "Steak",
                        "cooldown_seconds": 5,
                        "health_percent_below": 45,
                        "hunger_percent_below": 30,
                        "health_below": 10,
                        "hunger_below": 5,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    item = load_config(config_path).auto_heal_items[0]

    assert item.health_percent_below == 45
    assert item.hunger_percent_below == 30


def test_load_auto_heal_accepts_integral_legacy_numbers(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "auto_heal_items": [
                    {
                        "name": "Steak",
                        "cooldown_seconds": 5,
                        "health_below": 10.0,
                        "hunger_below": 25.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert load_config(config_path).auto_heal_items[0] == AutoHealItemConfig(
        "Steak", 5.0, 2.0, 10, 25
    )


def test_save_auto_heal_settings_preserves_unrelated_values(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"dry_run": false}\n', encoding="utf-8")
    item = AutoHealItemConfig("Steak", 5.0, 2.0, 50, 30)

    save_auto_heal_settings(
        config_path,
        enabled=True,
        items=(item,),
        return_item_name=".｡*ﾟ+.*.｡ Sword ｡+..｡*ﾟ",
    )

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["dry_run"] is False
    assert raw["auto_heal_enabled"] is True
    assert raw["auto_heal_return_item_name"] == ".｡*ﾟ+.*.｡ Sword ｡+..｡*ﾟ"
    assert raw["auto_heal_items"] == [
        {
            "name": "Steak",
            "cooldown_seconds": 5.0,
            "use_duration_seconds": 2.0,
            "health_percent_below": 50,
            "hunger_percent_below": 30,
        }
    ]


def test_load_config_defaults_missing_return_item_to_empty_string(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}\n", encoding="utf-8")

    assert load_config(config_path).auto_heal_return_item_name == ""


def test_load_config_preserves_return_item_name_exactly(tmp_path):
    name = "  .｡*ﾟ+.*.｡ Sword ｡+..｡*ﾟ  "
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"auto_heal_return_item_name": name}),
        encoding="utf-8",
    )

    assert load_config(config_path).auto_heal_return_item_name == name


def test_load_config_rejects_non_string_return_item_name(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"auto_heal_return_item_name": 7}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="return item name"):
        load_config(config_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("health_percent_below", 10.5, "health percentage"),
        ("health_percent_below", 10**400, "health percentage"),
        ("health_below", 10.5, "health percentage"),
        ("hunger_percent_below", -1, "hunger percentage"),
        ("hunger_below", 101, "hunger percentage"),
    ],
)
def test_load_auto_heal_rejects_invalid_percentage_values(
    tmp_path,
    field,
    value,
    message,
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "auto_heal_items": [
                    {
                        "name": "Steak",
                        "cooldown_seconds": 5,
                        field: value,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_config(config_path)


@pytest.mark.parametrize(
    "item",
    [
        AutoHealItemConfig("", 1.0, 2.0, 5, 0),
        AutoHealItemConfig("Steak", -1.0, 2.0, 5, 0),
        AutoHealItemConfig("Steak", 1.0, 0.0, 5, 0),
        AutoHealItemConfig("Steak", 1.0, 2.0, 0, 0),
        AutoHealItemConfig("Steak", 1.0, 2.0, 10.5, 0),
        AutoHealItemConfig("Steak", 1.0, 2.0, -1, 0),
        AutoHealItemConfig("Steak", 1.0, 2.0, 101, 0),
        AutoHealItemConfig("Steak", 1.0, 2.0, True, 0),
        AutoHealItemConfig("Steak", 1.0, 2.0, 5, 101),
    ],
)
def test_validate_auto_heal_items_rejects_invalid_rules(item):
    with pytest.raises(ValueError):
        validate_auto_heal_items((item,))


def test_validate_auto_heal_items_rejects_duplicate_exact_names():
    item = AutoHealItemConfig("Steak", 1.0, 2.0, 5, 0)

    with pytest.raises(ValueError, match="unique"):
        validate_auto_heal_items((item, item))


def test_load_and_save_coordinate_locks(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dry_run": False}), encoding="utf-8")
    locks = [
        CoordinateLockConfig(
            id="home",
            x=1.5,
            y=64.0,
            z=-3.25,
            name="Home",
            active_area=25.0,
            auto_hit_players=True,
            auto_hit_mobs=False,
            auto_hit_target_name="[Lv 6]Tatsunoko",
        ),
        CoordinateLockConfig(
            id="afk", x=10.0, y=70.0, z=20.0, enabled=False, name="AFK Room"
        ),
    ]

    save_coordinate_lock_settings(
        config_path,
        locks,
        enabled=True,
        auto_hit_enabled=True,
        auto_hit_min_seconds=0.1,
        auto_hit_max_seconds=0.5,
        look_mode=COORDINATE_LOCK_LOOK_TARGET,
    )
    config = load_config(config_path)

    assert config.dry_run is False
    assert config.coordinate_lock_enabled is True
    assert config.coordinate_lock_auto_hit_enabled is True
    assert config.coordinate_lock_auto_hit_min_seconds == 0.1
    assert config.coordinate_lock_auto_hit_max_seconds == 0.5
    assert config.coordinate_lock_look_mode == COORDINATE_LOCK_LOOK_TARGET
    assert config.coordinate_locks == tuple(locks)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["coordinate_locks"][0]["auto_hit_players"] is True
    assert raw["coordinate_locks"][0]["auto_hit_mobs"] is False
    assert (
        raw["coordinate_locks"][0]["auto_hit_target_name"]
        == "[Lv 6]Tatsunoko"
    )


def test_load_config_migrates_legacy_coordinate_look_and_player_url(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "coordinate_lock_look_at_enabled": True,
                "player_data_url": "http://localhost:8025/data/player",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.coordinate_lock_look_mode == COORDINATE_LOCK_LOOK_LOCK
    assert config.player_data_url == "http://127.0.0.1:8026/data/player"


def test_load_config_migrates_false_legacy_coordinate_look_to_none(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"coordinate_lock_look_at_enabled": False}),
        encoding="utf-8",
    )

    assert (
        load_config(config_path).coordinate_lock_look_mode
        == COORDINATE_LOCK_LOOK_NONE
    )


def test_new_coordinate_look_mode_takes_precedence_over_legacy_boolean(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "coordinate_lock_look_mode": "target",
                "coordinate_lock_look_at_enabled": True,
            }
        ),
        encoding="utf-8",
    )

    assert (
        load_config(config_path).coordinate_lock_look_mode
        == COORDINATE_LOCK_LOOK_TARGET
    )


def test_save_coordinate_locks_persists_mode_without_legacy_boolean(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"coordinate_lock_look_at_enabled": True}),
        encoding="utf-8",
    )

    save_coordinate_lock_settings(
        config_path,
        [],
        enabled=True,
        look_mode=COORDINATE_LOCK_LOOK_TARGET,
    )

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["coordinate_lock_look_mode"] == "target"
    assert "coordinate_lock_look_at_enabled" not in raw


def test_load_coordinate_locks_without_new_fields_keeps_backward_compatibility(
    tmp_path,
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "coordinate_lock_max_distance": 35,
                "coordinate_locks": [
                    {"id": "old-lock", "x": 1, "y": 64, "z": -2},
                ]
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.coordinate_locks == (
        CoordinateLockConfig(
            id="old-lock", x=1.0, y=64.0, z=-2.0, active_area=35.0
        ),
    )
    lock = config.coordinate_locks[0]
    assert lock.auto_hit_players is True
    assert lock.auto_hit_mobs is True
    assert lock.auto_hit_target_name == ""


def test_example_config_documents_coordinate_auto_hit_targets():
    raw = json.loads(Path("config.example.json").read_text(encoding="utf-8"))

    example = raw["coordinate_locks"][0]
    assert example["enabled"] is False
    assert example["auto_hit_players"] is True
    assert example["auto_hit_mobs"] is True
    assert example["auto_hit_target_name"] == ""


def test_load_config_overrides_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        """
{
  "log_path": "C:/Minecraft/logs/latest.log",
  "program_enabled": false,
  "holoquiz_enabled": false,
  "auto_answer_enabled": false,
  "dry_run": false,
  "answer_sound_enabled": false,
  "codex_model": "gpt-5.4-nano",
  "codex_timeout_seconds": 3,
  "send_delay_seconds": 0.2,
  "send_delay_min_seconds": 1.0,
  "send_delay_max_seconds": 3.0,
  "dry_run_sound_path": "C:/Sounds/answer.wav",
  "memory_path": "custom_memory.json"
}
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.log_path == Path("C:/Minecraft/logs/latest.log")
    assert config.program_enabled is False
    assert config.holoquiz_enabled is False
    assert config.auto_answer_enabled is False
    assert config.dry_run is False
    assert config.answer_sound_enabled is False
    assert config.codex_model == "gpt-5.4-nano"
    assert config.codex_timeout_seconds == 3
    assert config.send_delay_seconds == 0.2
    assert config.send_delay_min_seconds == 1.0
    assert config.send_delay_max_seconds == 3.0
    assert config.dry_run_sound_path == Path("C:/Sounds/answer.wav")
    assert config.codex_command == "codex"
    assert config.memory_path == Path("custom_memory.json")


def test_load_config_without_answer_sound_setting_defaults_enabled(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dry_run": True}), encoding="utf-8")

    config = load_config(config_path)

    assert config.answer_sound_enabled is True


def test_load_config_without_holoquiz_setting_defaults_enabled(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dry_run": True}), encoding="utf-8")

    assert load_config(config_path).holoquiz_enabled is True


def test_save_holoquiz_enabled_setting_preserves_other_values(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"dry_run": True, "send_delay_min_seconds": 0.5}),
        encoding="utf-8",
    )

    save_holoquiz_enabled_setting(config_path, enabled=False)

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dry_run": True,
        "send_delay_min_seconds": 0.5,
        "holoquiz_enabled": False,
    }


def test_save_send_delay_settings_preserves_other_values(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"dry_run": True, "holoquiz_enabled": False}),
        encoding="utf-8",
    )

    save_send_delay_settings(config_path, min_seconds=1.0, max_seconds=3.0)

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dry_run": True,
        "holoquiz_enabled": False,
        "send_delay_seconds": 1.0,
        "send_delay_min_seconds": 1.0,
        "send_delay_max_seconds": 3.0,
    }


def test_save_answer_sound_setting_preserves_other_config_values(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"dry_run": True, "codex_model": "gpt-5.4"}),
        encoding="utf-8",
    )

    save_answer_sound_setting(config_path, enabled=False)

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dry_run": True,
        "codex_model": "gpt-5.4",
        "answer_sound_enabled": False,
    }


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


def test_load_config_uses_single_delay_for_missing_delay_range(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"send_delay_seconds": 1.5}),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.send_delay_seconds == 1.5
    assert config.send_delay_min_seconds == 1.5
    assert config.send_delay_max_seconds == 1.5


def test_load_config_reads_screen_phrase_settings(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "screen_phrase_trigger": "Afk, again?",
                "screen_phrase_trigger_region": {
                    "x": 100,
                    "y": 200,
                    "width": 300,
                    "height": 40,
                },
                "screen_phrase_result_region": {
                    "x": 110,
                    "y": 260,
                    "width": 320,
                    "height": 50,
                },
                "screen_phrase_auto_send_result": True,
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.screen_phrase_trigger == "Afk, again?"
    assert config.screen_phrase_trigger_region == ScreenPhraseRegionConfig(
        x=100,
        y=200,
        width=300,
        height=40,
    )
    assert config.screen_phrase_result_region == ScreenPhraseRegionConfig(
        x=110,
        y=260,
        width=320,
        height=50,
    )
    assert config.screen_phrase_auto_send_result is True


def test_save_screen_phrase_settings_preserves_existing_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "dry_run": False,
                "screen_phrase_trigger": "",
                "screen_phrase_trigger_region": None,
                "screen_phrase_result_region": None,
            }
        ),
        encoding="utf-8",
    )

    save_screen_phrase_settings(
        config_path,
        trigger="Afk, again?",
        trigger_region=ScreenPhraseRegionConfig(100, 200, 300, 40),
        result_region=ScreenPhraseRegionConfig(110, 260, 320, 50),
        auto_send_result=True,
    )

    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw_config["dry_run"] is False
    assert raw_config["screen_phrase_trigger"] == "Afk, again?"
    assert raw_config["screen_phrase_trigger_region"] == {
        "x": 100,
        "y": 200,
        "width": 300,
        "height": 40,
    }
    assert raw_config["screen_phrase_result_region"] == {
        "x": 110,
        "y": 260,
        "width": 320,
        "height": 50,
    }
    assert raw_config["screen_phrase_auto_send_result"] is True


def test_load_config_reads_chat_triggers(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "chat_triggers": [
                    {
                        "id": "morning",
                        "trigger_phrase": "Good Morning!",
                        "macro": "tGood Morning{{Enter}}",
                        "cooldown_seconds": 12.5,
                        "typing_interval_seconds": 0.08,
                        "enabled": True,
                        "sound_path": "C:/Sounds/morning.mp3",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.chat_triggers == (
        ChatTriggerConfig(
            id="morning",
            trigger_phrase="Good Morning!",
            macro="tGood Morning{{Enter}}",
            cooldown_seconds=12.5,
            typing_interval_seconds=0.08,
            enabled=True,
            sound_path=Path("C:/Sounds/morning.mp3"),
        ),
    )


def test_save_chat_triggers_settings_preserves_existing_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"dry_run": False, "screen_phrase_trigger": "AFK"}),
        encoding="utf-8",
    )

    save_chat_triggers_settings(
        config_path,
        [
            ChatTriggerConfig(
                id="morning",
                trigger_phrase="Good Morning!",
                macro="tGood Morning{{Enter}}",
                cooldown_seconds=12.5,
                typing_interval_seconds=0.08,
                enabled=False,
                sound_path=Path("C:/Sounds/morning.wav"),
            )
        ],
        dry_run=False,
    )

    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw_config["dry_run"] is False
    assert raw_config["screen_phrase_trigger"] == "AFK"
    assert raw_config["chat_trigger_dry_run"] is False
    assert raw_config["chat_triggers"] == [
        {
            "id": "morning",
            "trigger_phrase": "Good Morning!",
            "macro": "tGood Morning{{Enter}}",
            "cooldown_seconds": 12.5,
            "typing_interval_seconds": 0.08,
            "enabled": False,
            "sound_path": "C:\\Sounds\\morning.wav",
        }
    ]


def test_load_config_keeps_missing_chat_trigger_typing_interval_as_fallback(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "chat_triggers": [
                    {
                        "id": "legacy",
                        "trigger_phrase": "Good Morning!",
                        "macro": "tGood Morning{{Enter}}",
                        "cooldown_seconds": 12.5,
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.chat_triggers[0].typing_interval_seconds is None
    assert config.chat_triggers[0].sound_path is None


def test_load_config_accepts_sound_only_chat_trigger(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "chat_triggers": [
                    {
                        "id": "alarm",
                        "trigger_phrase": "Wake up!",
                        "sound_path": "C:/Sounds/alarm.wav",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.chat_triggers[0].macro == ""
    assert config.chat_triggers[0].sound_path == Path("C:/Sounds/alarm.wav")


def test_load_config_reads_chat_trigger_dry_run(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"dry_run": True, "chat_trigger_dry_run": False}),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.dry_run is True
    assert config.chat_trigger_dry_run is False
