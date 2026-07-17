import json
import queue
from types import SimpleNamespace

import holoquiz.gui as gui
from holoquiz.config import BotConfig, ChatTriggerConfig, CoordinateLockConfig
from holoquiz.gui import (
    BROWSER_SEARCH_STATUS_MAX_CHARS,
    ControlPanelController,
    HoloQuizControlPanel,
    OcrScreenTextReader,
    ScreenPhraseWorker,
    build_browser_search_query,
)
from holoquiz.runtime import (
    FIND_ANSWER_FUNCTION,
    SCREEN_PHRASE_WATCHER_FUNCTION,
    RuntimeControls,
)
from holoquiz.screen_phrase_watcher import (
    SCREEN_PHRASE_SOURCE_TITLE_API,
    ScreenPhraseWatcher,
    ScreenReadRegion,
)


class RecordingVar:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def test_gui_app_title_is_holocraft_tools():
    assert getattr(gui, "APP_TITLE", None) == "HoloCraft Tools"


def test_build_browser_search_query_removes_holoquiz_prompt_noise():
    query = build_browser_search_query(
        "Hololive - Trivia: For some reason, Kronii's -------- is listed "
        "officially on Urban Dictionary."
    )

    assert query == "Hololive Kronii is listed officially on Urban Dictionary"


def test_control_panel_controller_opens_browser_search_for_latest_question():
    controls = RuntimeControls.from_config(BotConfig())
    controls.set_latest_question(
        "Hololive - Trivia: For some reason, Kronii's -------- is listed "
        "officially on Urban Dictionary."
    )
    opened_urls = []
    controller = ControlPanelController(controls, browser_open=opened_urls.append)

    result = controller.open_browser_search()

    assert result.ok is True
    assert opened_urls == [
        "https://www.google.com/search?q=Hololive+Kronii+is+listed+officially+on+Urban+Dictionary"
    ]


def test_control_panel_controller_ellipsizes_long_browser_search_status():
    controls = RuntimeControls.from_config(BotConfig())
    controls.set_latest_question(
        "Minecraft What is the first mob that had its own attack animation "
        "with moving appendages and a very long extra phrase for search"
    )
    opened_urls = []
    controller = ControlPanelController(controls, browser_open=opened_urls.append)

    result = controller.open_browser_search()

    assert result.ok is True
    assert len(result.message) <= BROWSER_SEARCH_STATUS_MAX_CHARS
    assert result.message.endswith("...")
    assert "moving+appendages+and+a+very+long+extra+phrase" in opened_urls[0]


def test_control_panel_controller_reports_missing_browser_search_question():
    controls = RuntimeControls.from_config(BotConfig())
    opened_urls = []
    controller = ControlPanelController(controls, browser_open=opened_urls.append)

    result = controller.open_browser_search()

    assert result.ok is False
    assert "No HoloQuiz question" in result.message
    assert opened_urls == []


def test_control_panel_controller_updates_runtime_controls():
    controls = RuntimeControls.from_config(BotConfig(dry_run=True))
    controller = ControlPanelController(controls)

    controller.set_program_enabled(False)
    controller.set_holoquiz_enabled(False)
    controller.set_dry_run(False)
    controller.set_answer_sound_enabled(False)
    controller.set_function_enabled(FIND_ANSWER_FUNCTION, False)
    result = controller.set_send_delay_range("1", "3")

    assert result.ok is True
    assert controls.snapshot().program_enabled is False
    assert controls.get_config().holoquiz_enabled is False
    assert controls.get_config().dry_run is False
    assert controls.get_config().answer_sound_enabled is False
    assert controls.is_function_enabled(FIND_ANSWER_FUNCTION) is False
    assert controls.get_config().send_delay_min_seconds == 1.0
    assert controls.get_config().send_delay_max_seconds == 3.0


def test_answer_sound_mute_toggle_updates_runtime_and_persists(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"answer_sound_enabled": True}),
        encoding="utf-8",
    )
    controls = RuntimeControls.from_config(BotConfig(answer_sound_enabled=True))
    panel = object.__new__(HoloQuizControlPanel)
    panel.config_path = config_path
    panel.controls = controls
    panel.controller = ControlPanelController(controls)
    panel.answer_sound_muted_var = RecordingVar(True)

    panel._on_answer_sound_mute_toggle()

    assert controls.get_config().answer_sound_enabled is False
    assert json.loads(config_path.read_text(encoding="utf-8"))[
        "answer_sound_enabled"
    ] is False


def test_holoquiz_toggle_updates_runtime_and_persists(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dry_run": True}), encoding="utf-8")
    controls = RuntimeControls.from_config(BotConfig(holoquiz_enabled=True))
    panel = object.__new__(HoloQuizControlPanel)
    panel.config_path = config_path
    panel.controls = controls
    panel.controller = ControlPanelController(controls)
    panel.holoquiz_enabled_var = RecordingVar(False)

    panel._on_holoquiz_toggle()

    assert controls.is_holoquiz_enabled() is False
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dry_run": True,
        "holoquiz_enabled": False,
    }


def test_control_panel_controller_rejects_invalid_send_delay():
    controls = RuntimeControls.from_config(BotConfig(send_delay_seconds=0.8))
    controller = ControlPanelController(controls)

    result = controller.set_send_delay_range("-1", "3")

    assert result.ok is False
    assert "0 or greater" in result.message
    assert controls.get_config().send_delay_seconds == 0.8


def test_control_panel_controller_rejects_non_numeric_send_delay():
    controls = RuntimeControls.from_config(BotConfig(send_delay_seconds=0.8))
    controller = ControlPanelController(controls)

    result = controller.set_send_delay_range("slow", "3")

    assert result.ok is False
    assert "number" in result.message
    assert controls.get_config().send_delay_seconds == 0.8


def test_control_panel_controller_rejects_reversed_send_delay_range():
    controls = RuntimeControls.from_config(BotConfig(send_delay_seconds=0.8))
    controller = ControlPanelController(controls)

    result = controller.set_send_delay_range("3", "1")

    assert result.ok is False
    assert "less than or equal" in result.message
    assert controls.get_config().send_delay_seconds == 0.8


def test_apply_delay_persists_successful_range(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dry_run": True}), encoding="utf-8")
    controls = RuntimeControls.from_config(BotConfig())
    panel = object.__new__(HoloQuizControlPanel)
    panel.config_path = config_path
    panel.controls = controls
    panel.controller = ControlPanelController(controls)
    panel.delay_min_var = RecordingVar("1")
    panel.delay_max_var = RecordingVar("3")
    panel.delay_status_var = RecordingVar()

    panel._on_apply_delay()

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dry_run": True,
        "send_delay_seconds": 1.0,
        "send_delay_min_seconds": 1.0,
        "send_delay_max_seconds": 3.0,
    }


def test_apply_delay_does_not_persist_invalid_range(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dry_run": True}), encoding="utf-8")
    controls = RuntimeControls.from_config(BotConfig())
    panel = object.__new__(HoloQuizControlPanel)
    panel.config_path = config_path
    panel.controls = controls
    panel.controller = ControlPanelController(controls)
    panel.delay_min_var = RecordingVar("3")
    panel.delay_max_var = RecordingVar("1")
    panel.delay_status_var = RecordingVar()

    panel._on_apply_delay()

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dry_run": True,
    }


def test_control_panel_controller_updates_auto_hit_range():
    controls = RuntimeControls.from_config(BotConfig())
    controller = ControlPanelController(controls)

    result = controller.set_coordinate_lock_auto_hit_range("0.1", "0.5")

    assert result.ok is True
    assert controls.get_config().coordinate_lock_auto_hit_min_seconds == 0.1
    assert controls.get_config().coordinate_lock_auto_hit_max_seconds == 0.5


def test_control_panel_controller_rejects_invalid_auto_hit_range():
    controls = RuntimeControls.from_config(BotConfig())
    controller = ControlPanelController(controls)

    non_numeric = controller.set_coordinate_lock_auto_hit_range("fast", "0.5")
    reversed_range = controller.set_coordinate_lock_auto_hit_range("0.5", "0.1")

    assert non_numeric.ok is False
    assert "numbers" in non_numeric.message
    assert reversed_range.ok is False
    assert "less than or equal" in reversed_range.message


def test_gui_feature_tabs_group_growing_toolset():
    assert gui.FEATURE_TAB_LABELS == (
        "HoloQuiz",
        "Screen Watcher",
        "Chat Triggers",
        "Coordinate Lock",
        "Activity",
    )


def test_chat_trigger_form_requires_macro_or_sound():
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.chat_trigger_trigger_var = SimpleNamespace(get=lambda: "Wake up!")
    panel.chat_trigger_macro_var = SimpleNamespace(get=lambda: "")
    panel.chat_trigger_sound_var = SimpleNamespace(get=lambda: "")

    result = panel._build_chat_trigger_from_form()

    assert result.ok is False
    assert result.message == "Macro or sound file is required."


def test_chat_trigger_form_accepts_sound_without_macro(tmp_path):
    sound_path = tmp_path / "alarm.mp3"
    sound_path.write_bytes(b"audio fixture")
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.chat_trigger_trigger_var = SimpleNamespace(get=lambda: "Wake up!")
    panel.chat_trigger_macro_var = SimpleNamespace(get=lambda: "")
    panel.chat_trigger_sound_var = SimpleNamespace(get=lambda: str(sound_path))
    panel.chat_trigger_cooldown_var = SimpleNamespace(get=lambda: "30")
    panel.chat_trigger_typing_interval_var = SimpleNamespace(get=lambda: "0.05")
    panel.chat_trigger_editing_id = None
    panel.controls = RuntimeControls.from_config(BotConfig())

    result = panel._build_chat_trigger_from_form()

    assert result.ok is True
    assert result.value is not None
    assert result.value.macro == ""
    assert result.value.sound_path == sound_path


def test_chat_trigger_table_action_toggles_selected_rule():
    trigger = ChatTriggerConfig(
        id="wake-up",
        trigger_phrase="Wake up!",
        macro="Hello",
        cooldown_seconds=30,
        enabled=True,
    )
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.controls = RuntimeControls.from_config(BotConfig(chat_triggers=(trigger,)))
    panel._save_chat_triggers_settings = lambda: None
    panel._refresh_chat_trigger_rows = lambda: None

    panel._on_chat_trigger_toggle(trigger.id)

    assert panel.controls.get_chat_triggers()[0].enabled is False


def test_coordinate_table_action_makes_only_selected_target_active():
    first = CoordinateLockConfig(id="first", name="First", x=1, y=2, z=3)
    second = CoordinateLockConfig(
        id="second", name="Second", x=4, y=5, z=6, enabled=False
    )
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.controls = RuntimeControls.from_config(
        BotConfig(coordinate_locks=(first, second))
    )
    panel._save_coordinate_lock_settings = lambda: None
    panel._refresh_coordinate_lock_rows = lambda: None

    panel._on_coordinate_lock_toggle(second.id)

    locks = panel.controls.get_coordinate_locks()
    assert [lock.enabled for lock in locks] == [False, True]


def test_selecting_look_at_target_deselects_look_at_lock_and_persists():
    saved = []
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.controls = RuntimeControls.from_config(BotConfig())
    panel.coordinate_lock_look_at_lock_var = RecordingVar(True)
    panel.coordinate_lock_look_at_target_var = RecordingVar(True)
    panel._save_coordinate_lock_settings = lambda: saved.append(True)

    panel._on_coordinate_lock_look_mode_toggle("target")

    assert panel.coordinate_lock_look_at_lock_var.value is False
    assert panel.coordinate_lock_look_at_target_var.value is True
    assert panel.controls.get_config().coordinate_lock_look_mode == "target"
    assert saved == [True]


def test_selecting_look_at_lock_deselects_look_at_target():
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.controls = RuntimeControls.from_config(
        BotConfig(coordinate_lock_look_mode="target")
    )
    panel.coordinate_lock_look_at_lock_var = RecordingVar(True)
    panel.coordinate_lock_look_at_target_var = RecordingVar(True)
    panel._save_coordinate_lock_settings = lambda: None

    panel._on_coordinate_lock_look_mode_toggle("lock")

    assert panel.coordinate_lock_look_at_lock_var.value is True
    assert panel.coordinate_lock_look_at_target_var.value is False
    assert panel.controls.get_config().coordinate_lock_look_mode == "lock"


def test_deselecting_active_look_mode_returns_to_none():
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.controls = RuntimeControls.from_config(
        BotConfig(coordinate_lock_look_mode="lock")
    )
    panel.coordinate_lock_look_at_lock_var = RecordingVar(False)
    panel.coordinate_lock_look_at_target_var = RecordingVar(False)
    panel._save_coordinate_lock_settings = lambda: None

    panel._on_coordinate_lock_look_mode_toggle("lock")

    assert panel.controls.get_config().coordinate_lock_look_mode == "none"


def test_coordinate_form_builds_target_with_custom_active_area():
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.coordinate_lock_name_var = SimpleNamespace(get=lambda: "Farm")
    panel.coordinate_lock_x_var = SimpleNamespace(get=lambda: "10")
    panel.coordinate_lock_y_var = SimpleNamespace(get=lambda: "64")
    panel.coordinate_lock_z_var = SimpleNamespace(get=lambda: "-20")
    panel.coordinate_lock_active_area_var = SimpleNamespace(get=lambda: "75")
    panel.coordinate_lock_auto_hit_players_var = SimpleNamespace(get=lambda: True)
    panel.coordinate_lock_auto_hit_mobs_var = SimpleNamespace(get=lambda: True)
    panel.coordinate_lock_target_name_var = SimpleNamespace(get=lambda: "")
    panel.coordinate_lock_editing_id = None
    panel.controls = RuntimeControls.from_config(BotConfig())

    result = panel._build_coordinate_lock_from_form()

    assert result.ok is True
    assert result.value is not None
    assert result.value.active_area == 75


def test_coordinate_form_rejects_non_positive_active_area():
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.coordinate_lock_name_var = SimpleNamespace(get=lambda: "Farm")
    panel.coordinate_lock_x_var = SimpleNamespace(get=lambda: "10")
    panel.coordinate_lock_y_var = SimpleNamespace(get=lambda: "64")
    panel.coordinate_lock_z_var = SimpleNamespace(get=lambda: "-20")
    panel.coordinate_lock_active_area_var = SimpleNamespace(get=lambda: "0")
    panel.coordinate_lock_auto_hit_players_var = SimpleNamespace(get=lambda: True)
    panel.coordinate_lock_auto_hit_mobs_var = SimpleNamespace(get=lambda: True)
    panel.coordinate_lock_target_name_var = SimpleNamespace(get=lambda: "")
    panel.coordinate_lock_editing_id = None
    panel.controls = RuntimeControls.from_config(BotConfig())

    result = panel._build_coordinate_lock_from_form()

    assert result.ok is False
    assert result.message == "Active area must be greater than 0."


def test_coordinate_form_builds_per_coordinate_auto_hit_targeting():
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.coordinate_lock_name_var = SimpleNamespace(get=lambda: "Farm")
    panel.coordinate_lock_x_var = SimpleNamespace(get=lambda: "10")
    panel.coordinate_lock_y_var = SimpleNamespace(get=lambda: "64")
    panel.coordinate_lock_z_var = SimpleNamespace(get=lambda: "-20")
    panel.coordinate_lock_active_area_var = SimpleNamespace(get=lambda: "75")
    panel.coordinate_lock_auto_hit_players_var = SimpleNamespace(get=lambda: True)
    panel.coordinate_lock_auto_hit_mobs_var = SimpleNamespace(get=lambda: False)
    panel.coordinate_lock_target_name_var = SimpleNamespace(
        get=lambda: "  [Lv 6]Tatsunoko  "
    )
    panel.coordinate_lock_editing_id = None
    panel.controls = RuntimeControls.from_config(BotConfig())

    result = panel._build_coordinate_lock_from_form()

    assert result.ok is True
    assert result.value is not None
    assert result.value.name == "Farm"
    assert result.value.active_area == 75
    assert result.value.auto_hit_players is True
    assert result.value.auto_hit_mobs is False
    assert result.value.auto_hit_target_name == "[Lv 6]Tatsunoko"


def test_coordinate_form_requires_at_least_one_auto_hit_target_type():
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.coordinate_lock_name_var = SimpleNamespace(get=lambda: "Farm")
    panel.coordinate_lock_x_var = SimpleNamespace(get=lambda: "10")
    panel.coordinate_lock_y_var = SimpleNamespace(get=lambda: "64")
    panel.coordinate_lock_z_var = SimpleNamespace(get=lambda: "-20")
    panel.coordinate_lock_active_area_var = SimpleNamespace(get=lambda: "75")
    panel.coordinate_lock_auto_hit_players_var = SimpleNamespace(get=lambda: False)
    panel.coordinate_lock_auto_hit_mobs_var = SimpleNamespace(get=lambda: False)
    panel.coordinate_lock_target_name_var = SimpleNamespace(get=lambda: "")
    panel.coordinate_lock_editing_id = None
    panel.controls = RuntimeControls.from_config(BotConfig())

    result = panel._build_coordinate_lock_from_form()

    assert result.ok is False
    assert result.message == "Select Players, Mobs, or both for Auto Hit."


def test_coordinate_target_summary_describes_saved_settings():
    assert gui.coordinate_lock_target_summary(
        CoordinateLockConfig("both", 1, 2, 3)
    ) == "Players + Mobs"
    assert gui.coordinate_lock_target_summary(
        CoordinateLockConfig(
            "mobs", 1, 2, 3, auto_hit_players=False, auto_hit_mobs=True
        )
    ) == "Mobs"


def test_edit_coordinate_loads_per_coordinate_auto_hit_targeting():
    class RecordingVar:
        def __init__(self):
            self.value = None

        def set(self, value):
            self.value = value

    lock = CoordinateLockConfig(
        "farm",
        1,
        64,
        2,
        name="Farm",
        auto_hit_players=False,
        auto_hit_mobs=True,
        auto_hit_target_name="Zombie",
    )
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.controls = RuntimeControls.from_config(BotConfig(coordinate_locks=(lock,)))
    panel.coordinate_lock_name_var = RecordingVar()
    panel.coordinate_lock_x_var = RecordingVar()
    panel.coordinate_lock_y_var = RecordingVar()
    panel.coordinate_lock_z_var = RecordingVar()
    panel.coordinate_lock_active_area_var = RecordingVar()
    panel.coordinate_lock_auto_hit_players_var = RecordingVar()
    panel.coordinate_lock_auto_hit_mobs_var = RecordingVar()
    panel.coordinate_lock_target_name_var = RecordingVar()
    panel.coordinate_lock_submit_button = SimpleNamespace(
        configure=lambda **_kwargs: None
    )
    panel.coordinate_lock_status_var = RecordingVar()

    panel._on_edit_coordinate_lock("farm")

    assert panel.coordinate_lock_auto_hit_players_var.value is False
    assert panel.coordinate_lock_auto_hit_mobs_var.value is True
    assert panel.coordinate_lock_target_name_var.value == "Zombie"


def test_screen_phrase_worker_debug_logs_ocr_details():
    controls = RuntimeControls.from_config(BotConfig())
    controls.set_function_enabled(SCREEN_PHRASE_WATCHER_FUNCTION, True)
    reads = {
        ScreenReadRegion(10, 20, 300, 40): "You are now AEK",
    }
    watcher = ScreenPhraseWatcher(text_reader=reads.__getitem__)
    watcher.set_trigger_region(ScreenReadRegion(10, 20, 300, 40))
    watcher.set_result_region(ScreenReadRegion(30, 80, 420, 60))
    watcher.set_trigger_phrase("You are now AFK")
    log_queue: queue.Queue[str] = queue.Queue()
    worker = ScreenPhraseWorker(
        controls,
        watcher,
        log_queue,
        debug_enabled_provider=lambda: True,
    )

    worker._check_screen()

    lines = []
    while not log_queue.empty():
        lines.append(log_queue.get_nowait())
    debug_log = "\n".join(lines)
    assert "trigger area: 300x40 at 10,20" in debug_log
    assert 'trigger phrase: "You are now AFK"' in debug_log
    assert 'trigger OCR: "You are now AEK"' in debug_log
    assert "trigger match: no" in debug_log
    assert "reason: trigger phrase not found" in debug_log


def test_screen_phrase_worker_plays_trigger_sound_once_per_cooldown():
    controls = RuntimeControls.from_config(BotConfig())
    controls.set_function_enabled(SCREEN_PHRASE_WATCHER_FUNCTION, True)
    reads = {
        ScreenReadRegion(10, 20, 300, 40): "You are now AFK",
        ScreenReadRegion(30, 80, 420, 60): "Don't eat too much cookies",
    }
    watcher = ScreenPhraseWatcher(text_reader=reads.__getitem__)
    watcher.set_trigger_region(ScreenReadRegion(10, 20, 300, 40))
    watcher.set_result_region(ScreenReadRegion(30, 80, 420, 60))
    watcher.set_trigger_phrase("You are now AFK")
    log_queue: queue.Queue[str] = queue.Queue()
    now = 100.0
    sound_calls = []
    worker = ScreenPhraseWorker(
        controls,
        watcher,
        log_queue,
        trigger_sound_player=lambda: sound_calls.append(now),
        trigger_sound_cooldown_seconds=30.0,
        monotonic_seconds=lambda: now,
    )

    worker._check_screen()
    now = 110.0
    worker._check_screen()
    now = 130.0
    worker._check_screen()

    assert sound_calls == [100.0, 130.0]


def test_screen_phrase_worker_auto_sends_result_after_five_stable_reads():
    controls = RuntimeControls.from_config(BotConfig())
    controls.set_function_enabled(SCREEN_PHRASE_WATCHER_FUNCTION, True)
    reads = {
        ScreenReadRegion(10, 20, 300, 40): "You are now AFK",
        ScreenReadRegion(30, 80, 420, 60): "Good Morning!",
    }
    watcher = ScreenPhraseWatcher(text_reader=reads.__getitem__)
    watcher.set_trigger_region(ScreenReadRegion(10, 20, 300, 40))
    watcher.set_result_region(ScreenReadRegion(30, 80, 420, 60))
    watcher.set_trigger_phrase("You are now AFK")
    log_queue: queue.Queue[str] = queue.Queue()
    sent_results = []
    worker = ScreenPhraseWorker(
        controls,
        watcher,
        log_queue,
        auto_send_result_provider=lambda: True,
        result_sender=sent_results.append,
    )

    for _ in range(4):
        worker._check_screen()
    assert sent_results == []

    worker._check_screen()

    assert sent_results == ["Good Morning!"]


def test_title_api_auto_send_resets_five_read_check_when_title_changes():
    controls = RuntimeControls.from_config(BotConfig())
    controls.set_function_enabled(SCREEN_PHRASE_WATCHER_FUNCTION, True)

    class TitleClient:
        def __init__(self):
            self.titles = iter(
                ["Poki Moki"] * 4 + ["Hello World!"] * 5
            )

        def read_title(self):
            return "Hi! Good Morning Sir!", next(self.titles)

        def health(self):
            return {"status": "ok"}

    watcher = ScreenPhraseWatcher(lambda _region: "", TitleClient())
    watcher.set_source(SCREEN_PHRASE_SOURCE_TITLE_API)
    watcher.set_trigger_phrase("Good Morning Sir")
    sent_results = []
    worker = ScreenPhraseWorker(
        controls,
        watcher,
        queue.Queue(),
        auto_send_result_provider=lambda: True,
        result_sender=sent_results.append,
    )

    for _ in range(8):
        worker._check_screen()
    assert sent_results == []

    worker._check_screen()
    assert sent_results == ["Hello World!"]


def test_title_api_requires_five_fresh_reads_after_a_send():
    controls = RuntimeControls.from_config(BotConfig())

    class TitleClient:
        def read_title(self):
            return "Trigger", "Hello World!"

        def health(self):
            return {"status": "ok"}

    watcher = ScreenPhraseWatcher(lambda _region: "", TitleClient())
    watcher.set_source(SCREEN_PHRASE_SOURCE_TITLE_API)
    watcher.set_trigger_phrase("Trigger")
    sent_results = []
    worker = ScreenPhraseWorker(
        controls,
        watcher,
        queue.Queue(),
        auto_send_result_provider=lambda: True,
        result_sender=sent_results.append,
        auto_send_cooldown_seconds=0,
    )

    for _ in range(9):
        worker._check_screen()
    assert sent_results == ["Hello World!"]

    worker._check_screen()
    assert sent_results == ["Hello World!", "Hello World!"]


def test_screen_phrase_worker_does_not_auto_send_result_when_disabled():
    controls = RuntimeControls.from_config(BotConfig())
    controls.set_function_enabled(SCREEN_PHRASE_WATCHER_FUNCTION, True)
    reads = {
        ScreenReadRegion(10, 20, 300, 40): "You are now AFK",
        ScreenReadRegion(30, 80, 420, 60): "Good Morning!",
    }
    watcher = ScreenPhraseWatcher(text_reader=reads.__getitem__)
    watcher.set_trigger_region(ScreenReadRegion(10, 20, 300, 40))
    watcher.set_result_region(ScreenReadRegion(30, 80, 420, 60))
    watcher.set_trigger_phrase("You are now AFK")
    log_queue: queue.Queue[str] = queue.Queue()
    sent_results = []
    worker = ScreenPhraseWorker(
        controls,
        watcher,
        log_queue,
        auto_send_result_provider=lambda: False,
        result_sender=sent_results.append,
    )

    worker._check_screen()

    assert sent_results == []


def test_screen_phrase_worker_auto_send_waits_for_cooldown_after_stable_send():
    controls = RuntimeControls.from_config(BotConfig())
    controls.set_function_enabled(SCREEN_PHRASE_WATCHER_FUNCTION, True)
    reads = {
        ScreenReadRegion(10, 20, 300, 40): "You are now AFK",
        ScreenReadRegion(30, 80, 420, 60): "I Love HoloCraft",
    }
    watcher = ScreenPhraseWatcher(text_reader=reads.__getitem__)
    watcher.set_trigger_region(ScreenReadRegion(10, 20, 300, 40))
    watcher.set_result_region(ScreenReadRegion(30, 80, 420, 60))
    watcher.set_trigger_phrase("You are now AFK")
    log_queue: queue.Queue[str] = queue.Queue()
    sent_results = []
    now = 100.0
    worker = ScreenPhraseWorker(
        controls,
        watcher,
        log_queue,
        auto_send_result_provider=lambda: True,
        result_sender=sent_results.append,
        auto_send_cooldown_seconds=15.0,
        monotonic_seconds=lambda: now,
    )

    for _ in range(5):
        worker._check_screen()
    now = 110.0
    worker._check_screen()
    now = 115.0
    worker._check_screen()

    assert sent_results == ["I Love HoloCraft", "I Love HoloCraft"]


def test_screen_phrase_worker_auto_send_ignores_holoquiz_dry_run(monkeypatch):
    controls = RuntimeControls.from_config(BotConfig(dry_run=True))
    controls.set_function_enabled(SCREEN_PHRASE_WATCHER_FUNCTION, True)
    reads = {
        ScreenReadRegion(10, 20, 300, 40): "You are now AFK",
        ScreenReadRegion(30, 80, 420, 60): "Good Morning!",
    }
    watcher = ScreenPhraseWatcher(text_reader=reads.__getitem__)
    watcher.set_trigger_region(ScreenReadRegion(10, 20, 300, 40))
    watcher.set_result_region(ScreenReadRegion(30, 80, 420, 60))
    watcher.set_trigger_phrase("You are now AFK")
    log_queue: queue.Queue[str] = queue.Queue()
    sender_configs = []

    class FakeChatSender:
        def __init__(self, config, config_provider):
            self._config_provider = config_provider

        def send(self, result_text):
            sender_configs.append((result_text, self._config_provider().dry_run))

    monkeypatch.setattr("holoquiz.gui.ChatSender", FakeChatSender)
    worker = ScreenPhraseWorker(
        controls,
        watcher,
        log_queue,
        auto_send_result_provider=lambda: True,
    )

    for _ in range(5):
        worker._check_screen()

    assert sender_configs == [("Good Morning!", False)]


def test_ocr_screen_text_reader_returns_unique_text_from_multiple_passes():
    from PIL import Image

    class FakePyAutoGui:
        def screenshot(self, region):
            assert region == (1, 2, 300, 40)
            return Image.new("RGB", (12, 8), "black")

    class FakePytesseract:
        def __init__(self):
            self.calls = 0

        def image_to_string(self, image, config):
            self.calls += 1
            if self.calls == 1:
                return "T-:-I_I are ru:-In FIFH"
            if self.calls == 2:
                return "You are now AFK"
            return "You are now AFK"

    fake_tesseract = FakePytesseract()
    reader = OcrScreenTextReader(
        pyautogui_module=FakePyAutoGui(),
        pytesseract_module=fake_tesseract,
    )

    text = reader(ScreenReadRegion(1, 2, 300, 40))

    assert "T-:-I_I are ru:-In FIFH" in text
    assert "You are now AFK" in text
    assert text.count("You are now AFK") == 1
    assert fake_tesseract.calls > 1


def test_ocr_screen_text_reader_includes_minecraft_font_fallback():
    from pathlib import Path

    from PIL import Image

    class FakePyAutoGui:
        def screenshot(self, region):
            assert region == (1, 2, 300, 40)
            return Image.open(
                Path(__file__).parent
                / "fixtures"
                / "minecraft-you-are-now-afk.png"
            )

    class FakePytesseract:
        def image_to_string(self, image, config):
            return "T-:-I_I are in-:-In FIFH"

    reader = OcrScreenTextReader(
        pyautogui_module=FakePyAutoGui(),
        pytesseract_module=FakePytesseract(),
    )

    text = reader(ScreenReadRegion(1, 2, 300, 40))

    assert text == "You are now AFK"


def test_ocr_screen_text_reader_prefers_minecraft_font_fallback_for_result_crop():
    from pathlib import Path

    from PIL import Image

    class FakePyAutoGui:
        def screenshot(self, region):
            assert region == (1, 2, 550, 58)
            return Image.open(
                Path(__file__).parent
                / "fixtures"
                / "minecraft-dont-eat-to-much-cookies.png"
            )

    class FakePytesseract:
        def image_to_string(self, image, config):
            return "El-:un't eat t-:u HUGH -3-:u:uki-as!"

    reader = OcrScreenTextReader(
        pyautogui_module=FakePyAutoGui(),
        pytesseract_module=FakePytesseract(),
    )

    text = reader(ScreenReadRegion(1, 2, 550, 58))

    assert text == "Don't eat to much cookies!"
