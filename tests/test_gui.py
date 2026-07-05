import queue

from holoquiz.config import BotConfig
from holoquiz.gui import (
    BROWSER_SEARCH_STATUS_MAX_CHARS,
    ControlPanelController,
    OcrScreenTextReader,
    ScreenPhraseWorker,
    build_browser_search_query,
)
from holoquiz.runtime import (
    FIND_ANSWER_FUNCTION,
    SCREEN_PHRASE_WATCHER_FUNCTION,
    RuntimeControls,
)
from holoquiz.screen_phrase_watcher import ScreenPhraseWatcher, ScreenReadRegion


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
    controller.set_dry_run(False)
    controller.set_function_enabled(FIND_ANSWER_FUNCTION, False)
    result = controller.set_send_delay_range("1", "3")

    assert result.ok is True
    assert controls.snapshot().program_enabled is False
    assert controls.get_config().dry_run is False
    assert controls.is_function_enabled(FIND_ANSWER_FUNCTION) is False
    assert controls.get_config().send_delay_min_seconds == 1.0
    assert controls.get_config().send_delay_max_seconds == 3.0


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
