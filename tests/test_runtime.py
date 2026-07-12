from holoquiz.config import BotConfig, CoordinateLockConfig
from holoquiz.runtime import (
    FIND_ANSWER_FUNCTION,
    SCREEN_PHRASE_WATCHER_FUNCTION,
    RuntimeControls,
    default_function_registry,
)


def test_default_function_registry_contains_find_answer():
    registry = default_function_registry()

    functions = registry.all()

    assert [function.key for function in functions] == [
        FIND_ANSWER_FUNCTION,
        SCREEN_PHRASE_WATCHER_FUNCTION,
    ]
    assert functions[0].label == "Find answer"
    assert functions[0].enabled_by_default is True
    assert functions[1].label == "Screen phrase watcher"
    assert functions[1].enabled_by_default is False


def test_runtime_controls_merge_live_values_into_config():
    controls = RuntimeControls.from_config(
        BotConfig(
            dry_run=True,
            codex_enable_search=False,
            auto_answer_enabled=False,
            send_delay_seconds=0.8,
        )
    )

    controls.set_dry_run(False)
    controls.set_auto_answer_enabled(True)
    controls.set_send_delay_seconds(1.25)

    config = controls.get_config()

    assert config.dry_run is False
    assert config.auto_answer_enabled is True
    assert config.codex_enable_search is False
    assert config.send_delay_seconds == 1.25
    assert config.send_delay_min_seconds == 1.25
    assert config.send_delay_max_seconds == 1.25


def test_runtime_controls_merge_live_delay_range_into_config():
    controls = RuntimeControls.from_config(BotConfig(send_delay_seconds=0.8))

    controls.set_send_delay_range(1.0, 3.0)

    config = controls.get_config()
    assert config.send_delay_seconds == 1.0
    assert config.send_delay_min_seconds == 1.0
    assert config.send_delay_max_seconds == 3.0
    assert controls.snapshot().send_delay_min_seconds == 1.0
    assert controls.snapshot().send_delay_max_seconds == 3.0


def test_runtime_controls_track_chat_trigger_dry_run_separately():
    controls = RuntimeControls.from_config(BotConfig(dry_run=True))

    controls.set_chat_trigger_dry_run(False)

    config = controls.get_config()
    assert config.dry_run is True
    assert config.chat_trigger_dry_run is False
    assert controls.snapshot().chat_trigger_dry_run is False


def test_runtime_controls_track_coordinate_lock_settings():
    controls = RuntimeControls.from_config(BotConfig())
    lock = CoordinateLockConfig("home", 1, 2, 3)

    controls.set_coordinate_lock_enabled(True)
    controls.set_coordinate_locks([lock])

    assert controls.get_config().coordinate_lock_enabled is True
    assert controls.get_coordinate_locks() == (lock,)
    assert controls.snapshot().coordinate_locks == (lock,)


def test_runtime_controls_allow_only_one_enabled_coordinate_lock():
    first = CoordinateLockConfig("first", 1, 2, 3)
    second = CoordinateLockConfig("second", 4, 5, 6)

    controls = RuntimeControls.from_config(
        BotConfig(coordinate_locks=(first, second))
    )

    assert controls.get_coordinate_locks() == (
        first,
        CoordinateLockConfig("second", 4, 5, 6, enabled=False),
    )


def test_runtime_controls_reject_invalid_delay_range():
    controls = RuntimeControls.from_config(BotConfig(send_delay_seconds=0.8))

    try:
        controls.set_send_delay_range(3.0, 1.0)
    except ValueError as error:
        assert "less than or equal" in str(error)
    else:
        raise AssertionError("Expected invalid delay range to raise ValueError")


def test_runtime_controls_track_program_enabled():
    controls = RuntimeControls.from_config(BotConfig())

    controls.set_program_enabled(False)

    assert controls.is_program_enabled() is False
    assert controls.snapshot().program_enabled is False


def test_runtime_controls_track_function_enabled_by_key():
    controls = RuntimeControls.from_config(BotConfig())

    controls.set_function_enabled("find_answer", False)

    assert controls.is_function_enabled("find_answer") is False
    assert controls.snapshot().auto_answer_enabled is False
    assert controls.snapshot().functions["find_answer"] is False


def test_runtime_controls_auto_answer_toggle_updates_find_answer_function():
    controls = RuntimeControls.from_config(BotConfig())

    controls.set_auto_answer_enabled(False)

    assert controls.is_function_enabled("find_answer") is False
    assert controls.get_config().auto_answer_enabled is False


def test_runtime_controls_reject_unknown_function_key():
    controls = RuntimeControls.from_config(BotConfig())

    try:
        controls.set_function_enabled("missing", False)
    except KeyError as error:
        assert "missing" in str(error)
    else:
        raise AssertionError("Expected unknown function key to raise KeyError")
