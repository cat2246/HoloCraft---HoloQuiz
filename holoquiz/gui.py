from __future__ import annotations

from collections import deque
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, replace
from pathlib import Path
import math
import queue
import re
import threading
from time import monotonic
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any, Callable
from urllib.parse import quote_plus
from uuid import uuid4
import webbrowser

from holoquiz.chat_sender import ChatSender
from holoquiz.config import (
    BotConfig,
    ChatTriggerConfig,
    CoordinateLockConfig,
    ScreenPhraseRegionConfig,
    load_config,
    save_chat_triggers_settings,
    save_coordinate_lock_settings,
    save_screen_phrase_settings,
)
from holoquiz.coordinate_lock import CoordinateLockWorker, PlayerDataClient
from holoquiz.log_tailer import LogTailer
from holoquiz.minecraft_text_ocr import read_minecraft_text
from holoquiz.mouse_hotkey import Mouse4HotkeyListener
from holoquiz.runner import build_bot, drain_answer_reveals
from holoquiz.runtime import (
    FunctionDefinition,
    RuntimeControls,
    SCREEN_PHRASE_WATCHER_FUNCTION,
)
from holoquiz.screen_phrase_watcher import (
    SCREEN_PHRASE_SOURCE_OCR,
    SCREEN_PHRASE_SOURCE_TITLE_API,
    ScreenPhraseWatcher,
    ScreenReadRegion,
    normalize_screen_text,
)
from holoquiz.sound_player import SUPPORTED_SOUND_EXTENSIONS


GOOGLE_SEARCH_URL = "https://www.google.com/search?q="
APP_TITLE = "HoloCraft Tools"
APP_SUBTITLE = "Minecraft automation control center"
WINDOW_SIZE = "1040x720"
WINDOW_MIN_SIZE = (840, 620)
FEATURE_TAB_LABELS = (
    "HoloQuiz",
    "Screen Watcher",
    "Chat Triggers",
    "Coordinate Lock",
    "Activity",
)
BROWSER_SEARCH_STATUS_MAX_CHARS = 58
BLANK_MARKER_PATTERN = re.compile(r"(?<!\w)(?:-{4,}|\?{4,}|_{4,})(?!\w)")
TRIGGER_SOUND_PATH = Path(__file__).with_name("assets") / "gura-wakeup-1.wav"
TRIGGER_SOUND_COOLDOWN_SECONDS = 30.0
AUTO_SEND_RESULT_STABLE_READS = 5
AUTO_SEND_RESULT_COOLDOWN_SECONDS = 15.0


@dataclass(frozen=True)
class ControlResult:
    ok: bool
    message: str = ""


@dataclass(frozen=True)
class ChatTriggerBuildResult:
    ok: bool
    message: str = ""
    value: ChatTriggerConfig | None = None


@dataclass(frozen=True)
class CoordinateLockBuildResult:
    ok: bool
    message: str = ""
    value: CoordinateLockConfig | None = None


def coordinate_lock_target_summary(lock: CoordinateLockConfig) -> str:
    if lock.auto_hit_players and lock.auto_hit_mobs:
        return "Players + Mobs"
    if lock.auto_hit_players:
        return "Players"
    if lock.auto_hit_mobs:
        return "Mobs"
    return "None"


class ControlPanelController:
    def __init__(
        self,
        controls: RuntimeControls,
        browser_open: Callable[[str], object] | None = None,
    ) -> None:
        self.controls = controls
        self._browser_open = browser_open or webbrowser.open

    def set_program_enabled(self, enabled: bool) -> None:
        self.controls.set_program_enabled(enabled)

    def set_dry_run(self, enabled: bool) -> None:
        self.controls.set_dry_run(enabled)

    def set_function_enabled(self, key: str, enabled: bool) -> None:
        self.controls.set_function_enabled(key, enabled)

    def set_send_delay_seconds(self, raw_value: str) -> ControlResult:
        try:
            seconds = float(raw_value)
        except ValueError:
            return ControlResult(False, "Send delay must be a number.")

        try:
            self.controls.set_send_delay_seconds(seconds)
        except ValueError as error:
            return ControlResult(False, str(error))

        return ControlResult(True, f"Send delay set to {seconds:g} seconds.")

    def set_send_delay_range(
        self,
        raw_min_value: str,
        raw_max_value: str,
    ) -> ControlResult:
        try:
            min_seconds = float(raw_min_value)
            max_seconds = float(raw_max_value)
        except ValueError:
            return ControlResult(False, "Send delay must be a number.")

        try:
            self.controls.set_send_delay_range(min_seconds, max_seconds)
        except ValueError as error:
            return ControlResult(False, str(error))

        return ControlResult(
            True,
            f"Send delay set to {min_seconds:g}-{max_seconds:g} seconds.",
        )

    def set_coordinate_lock_auto_hit_range(
        self,
        raw_min_value: str,
        raw_max_value: str,
    ) -> ControlResult:
        try:
            min_seconds = float(raw_min_value)
            max_seconds = float(raw_max_value)
        except ValueError:
            return ControlResult(False, "Auto hit times must be numbers.")

        try:
            self.controls.set_coordinate_lock_auto_hit_range(
                min_seconds,
                max_seconds,
            )
        except ValueError as error:
            return ControlResult(False, str(error))

        return ControlResult(
            True,
            f"Auto hit interval set to {min_seconds:g}-{max_seconds:g} seconds.",
        )

    def open_browser_search(self) -> ControlResult:
        question = self.controls.get_latest_question()
        if not question:
            return ControlResult(False, "No HoloQuiz question to search yet.")

        query = build_browser_search_query(question)
        if not query:
            return ControlResult(False, "No searchable HoloQuiz question text found.")

        self._browser_open(f"{GOOGLE_SEARCH_URL}{quote_plus(query)}")
        return ControlResult(
            True,
            ellipsize_text(
                f"Browser search opened: {query}",
                BROWSER_SEARCH_STATUS_MAX_CHARS,
            ),
        )


def build_browser_search_query(question: str) -> str:
    query = BLANK_MARKER_PATTERN.sub(" ", question)
    query = re.sub(r"(?i)\bfor some reason\b,?", " ", query)
    query = re.sub(r"(?i)\btrivia\b:?", " ", query)
    query = re.sub(r"(?:'|\u2019)s\b", "", query)
    query = re.sub(r"[^\w\s]+", " ", query, flags=re.UNICODE)
    return " ".join(query.split())


def ellipsize_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return "." * max_chars
    return f"{text[: max_chars - 3].rstrip()}..."


def _chat_trigger_action_text(trigger: ChatTriggerConfig) -> str:
    actions: list[str] = []
    if trigger.macro:
        actions.append(trigger.macro)
    if trigger.sound_path:
        actions.append(f"Sound: {trigger.sound_path.name}")
    return " + ".join(actions)


class QueueLogWriter:
    def __init__(self, log_queue: queue.Queue[str]) -> None:
        self._log_queue = log_queue
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                self._log_queue.put(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            self._log_queue.put(self._buffer)
            self._buffer = ""


class BotWorker:
    def __init__(
        self,
        config_path: Path,
        controls: RuntimeControls,
        log_queue: queue.Queue[str],
        poll_seconds: float = 0.2,
    ) -> None:
        self.config_path = config_path
        self.controls = controls
        self.log_queue = log_queue
        self.poll_seconds = poll_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        writer = QueueLogWriter(self.log_queue)
        with redirect_stdout(writer), redirect_stderr(writer):
            try:
                bot, log_path = build_bot(
                    config_path=self.config_path,
                    runtime_controls=self.controls,
                )
            except FileNotFoundError as error:
                print(error)
                writer.flush()
                return

            print(f"Watching {log_path}")
            if bot.runtime_controls.get_config().dry_run:
                print("Dry-run enabled; answers will not be typed into chat.")

            tailer = LogTailer(log_path, start_at_end=True)
            pending_lines: deque[str] = deque()
            bot.set_before_live_answer_send(
                lambda: drain_answer_reveals(bot, tailer, pending_lines)
            )
            while not self._stop_event.is_set():
                pending_lines.extend(tailer.read_available())
                while pending_lines:
                    bot.handle_line(pending_lines.popleft())
                self._stop_event.wait(self.poll_seconds)
            print("Bot worker stopped.")
            writer.flush()


class OcrScreenTextReader:
    def __init__(
        self,
        pyautogui_module: Any | None = None,
        pytesseract_module: Any | None = None,
    ) -> None:
        self._pyautogui = pyautogui_module
        self._pytesseract = pytesseract_module

    def __call__(self, region: ScreenReadRegion) -> str:
        pyautogui = self._pyautogui or self._load_pyautogui()
        image = pyautogui.screenshot(region=region.as_pyautogui_region())
        results: list[str] = []
        minecraft_text = read_minecraft_text(image).strip()
        if minecraft_text:
            return minecraft_text

        try:
            pytesseract = self._pytesseract or self._load_pytesseract()
        except ModuleNotFoundError:
            return "\n".join(results)

        for prepared_image in self._prepare_images_for_ocr(image):
            for config in ("--psm 7", "--psm 6"):
                text = pytesseract.image_to_string(prepared_image, config=config).strip()
                if text and text not in results:
                    results.append(text)
        return "\n".join(results)

    def _load_pyautogui(self) -> Any:
        import pyautogui

        self._pyautogui = pyautogui
        return pyautogui

    def _load_pytesseract(self) -> Any:
        import pytesseract

        self._pytesseract = pytesseract
        return pytesseract

    def _prepare_images_for_ocr(self, image: Any) -> list[Any]:
        try:
            from PIL import ImageOps
        except ModuleNotFoundError:
            return [image]

        rgb_image = image.convert("RGB")
        grayscale_image = ImageOps.autocontrast(ImageOps.grayscale(rgb_image))
        images = [
            self._upscale_for_ocr(grayscale_image, scale=3),
            self._minecraft_text_mask(rgb_image, scale=4),
            self._minecraft_text_mask(rgb_image, scale=5),
        ]
        return [ocr_image for ocr_image in images if ocr_image is not None]

    def _upscale_for_ocr(self, image: Any, scale: int) -> Any:
        from PIL import Image

        resampling = getattr(Image, "Resampling", Image).NEAREST
        return image.resize((image.width * scale, image.height * scale), resampling)

    def _minecraft_text_mask(self, image: Any, scale: int) -> Any | None:
        from PIL import Image, ImageOps

        pixels = image.load()
        mask = Image.new("L", image.size, 255)
        mask_pixels = mask.load()
        min_x = image.width
        min_y = image.height
        max_x = -1
        max_y = -1

        for y in range(image.height):
            for x in range(image.width):
                red, green, blue = pixels[x, y]
                brightness = max(red, green, blue)
                saturation = brightness - min(red, green, blue)
                is_colored_text = brightness >= 120 and saturation >= 35
                is_bright_text = red + green + blue >= 560
                if is_colored_text or is_bright_text:
                    mask_pixels[x, y] = 0
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)

        if max_x < min_x or max_y < min_y:
            return self._upscale_for_ocr(ImageOps.grayscale(image), scale=scale)

        padding = 6
        crop_box = (
            max(0, min_x - padding),
            max(0, min_y - padding),
            min(image.width, max_x + padding + 1),
            min(image.height, max_y + padding + 1),
        )
        cropped_mask = mask.crop(crop_box)
        return self._upscale_for_ocr(cropped_mask, scale=scale)


def play_trigger_sound(sound_path: Path = TRIGGER_SOUND_PATH) -> None:
    import winsound

    winsound.PlaySound(
        str(sound_path),
        winsound.SND_FILENAME | winsound.SND_ASYNC,
    )


class ScreenPhraseWorker:
    def __init__(
        self,
        controls: RuntimeControls,
        watcher: ScreenPhraseWatcher,
        log_queue: queue.Queue[str],
        poll_seconds: float = 1.0,
        debug_enabled_provider: Callable[[], bool] | None = None,
        auto_send_result_provider: Callable[[], bool] | None = None,
        result_sender: Callable[[str], None] | None = None,
        trigger_sound_player: Callable[[], None] | None = None,
        trigger_sound_cooldown_seconds: float = TRIGGER_SOUND_COOLDOWN_SECONDS,
        auto_send_cooldown_seconds: float = AUTO_SEND_RESULT_COOLDOWN_SECONDS,
        monotonic_seconds: Callable[[], float] | None = None,
    ) -> None:
        self.controls = controls
        self.watcher = watcher
        self.log_queue = log_queue
        self.poll_seconds = poll_seconds
        self._debug_enabled_provider = debug_enabled_provider or (lambda: False)
        self._auto_send_result_provider = auto_send_result_provider or (lambda: False)
        self._result_sender = result_sender
        self._trigger_sound_player = trigger_sound_player or play_trigger_sound
        self._trigger_sound_cooldown_seconds = trigger_sound_cooldown_seconds
        self._auto_send_cooldown_seconds = auto_send_cooldown_seconds
        self._monotonic_seconds = monotonic_seconds or monotonic
        self._last_trigger_sound_at: float | None = None
        self._stable_result_key = ""
        self._stable_result_text = ""
        self._stable_result_count = 0
        self._last_auto_send_at: float | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error = ""

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._should_read_screen():
                self._check_screen()
            self._stop_event.wait(self.poll_seconds)

    def _should_read_screen(self) -> bool:
        return (
            self.controls.is_program_enabled()
            and self.controls.is_function_enabled(SCREEN_PHRASE_WATCHER_FUNCTION)
            and self.watcher.is_ready()
        )

    def _check_screen(self) -> None:
        try:
            result = self.watcher.check_once_detailed()
        except Exception as error:
            hint = (
                "Check the title API service at 127.0.0.1:8026."
                if self.watcher.get_source() == SCREEN_PHRASE_SOURCE_TITLE_API
                else "Install Tesseract OCR and keep Minecraft visible."
            )
            message = (
                "[screen-phrase-watcher-error] "
                f"{error}. {hint}"
            )
            if message != self._last_error:
                self.log_queue.put(message)
                self._last_error = message
            return

        self._last_error = ""
        if self._debug_enabled_provider():
            self._log_debug_result(result)

        if result.trigger_matched:
            self._play_trigger_sound_if_ready()

        event = result.event
        if event is not None:
            self.log_queue.put(
                "[screen-phrase-watcher] "
                f'Trigger "{event.trigger_phrase}" found; '
                f"result area read: {event.result_text}"
            )
            if self._auto_send_result_provider():
                self._maybe_auto_send_result(event.result_text)
        elif self._auto_send_result_provider():
            self._maybe_auto_send_result(getattr(result, "result_text", ""))

    def _play_trigger_sound_if_ready(self) -> None:
        now = self._monotonic_seconds()
        if (
            self._last_trigger_sound_at is not None
            and now - self._last_trigger_sound_at
            < self._trigger_sound_cooldown_seconds
        ):
            return

        self._last_trigger_sound_at = now
        try:
            self._trigger_sound_player()
        except Exception as error:
            self.log_queue.put(
                "[screen-phrase-watcher-error] "
                f"Could not play trigger sound: {error}"
            )

    def _send_result_to_chat(self, result_text: str) -> None:
        try:
            sender = self._result_sender or ChatSender(
                self._trigger_chat_config(),
                config_provider=self._trigger_chat_config,
            ).send
            writer = QueueLogWriter(self.log_queue)
            with redirect_stdout(writer), redirect_stderr(writer):
                sender(result_text)
                writer.flush()
        except Exception as error:
            self.log_queue.put(
                "[screen-phrase-watcher-error] "
                f"Could not auto-send result: {error}"
            )

    def _maybe_auto_send_result(self, result_text: str) -> None:
        clean_result_text = result_text.strip()
        result_key = normalize_screen_text(clean_result_text)
        if not result_key:
            self._reset_auto_send_stability()
            return

        if result_key == self._stable_result_key:
            self._stable_result_count += 1
            self._stable_result_text = clean_result_text
        else:
            self._stable_result_key = result_key
            self._stable_result_text = clean_result_text
            self._stable_result_count = 1

        if self._stable_result_count < AUTO_SEND_RESULT_STABLE_READS:
            return
        if self._auto_send_in_cooldown():
            return

        self._last_auto_send_at = self._monotonic_seconds()
        self._send_result_to_chat(self._stable_result_text)
        if self.watcher.get_source() == SCREEN_PHRASE_SOURCE_TITLE_API:
            # A Title API send completes one stabilization sequence. Require five
            # fresh one-second reads before the same title can be sent again.
            self._reset_auto_send_stability()

    def _auto_send_in_cooldown(self) -> bool:
        if self._last_auto_send_at is None:
            return False
        return (
            self._monotonic_seconds() - self._last_auto_send_at
            < self._auto_send_cooldown_seconds
        )

    def _reset_auto_send_stability(self) -> None:
        self._stable_result_key = ""
        self._stable_result_text = ""
        self._stable_result_count = 0

    def _trigger_chat_config(self) -> BotConfig:
        return replace(self.controls.get_config(), dry_run=False)

    def _log_debug_result(self, result: object) -> None:
        using_api = self.watcher.get_source() == SCREEN_PHRASE_SOURCE_TITLE_API
        trigger_label = "subtitle" if using_api else "trigger OCR"
        result_label = "title" if using_api else "result OCR"
        trigger_region = getattr(result, "trigger_region", None)
        result_region = getattr(result, "result_region", None)
        lines = [
            "[screen-phrase-watcher-debug] "
            f"trigger area: {format_region(trigger_region) if trigger_region else 'not set'}; "
            f"result area: {format_region(result_region) if result_region else 'not set'}",
            "[screen-phrase-watcher-debug] "
            f'trigger phrase: "{format_debug_text(getattr(result, "trigger_phrase", ""))}"',
            "[screen-phrase-watcher-debug] "
            f'{trigger_label}: "{format_debug_text(getattr(result, "trigger_text", ""))}"',
            "[screen-phrase-watcher-debug] "
            f"trigger match: {'yes' if getattr(result, 'trigger_matched', False) else 'no'}",
        ]
        result_text = getattr(result, "result_text", "")
        if result_text:
            lines.append(
                "[screen-phrase-watcher-debug] "
                f'{result_label}: "{format_debug_text(result_text)}"'
            )
        lines.append(
            "[screen-phrase-watcher-debug] "
            f"reason: {getattr(result, 'reason', 'unknown')}"
        )
        for line in lines:
            self.log_queue.put(line)


class RegionSelectionOverlay:
    MIN_REGION_SIZE = 5

    def __init__(self, root: tk.Tk, title: str) -> None:
        self.root = root
        self.title = title
        self.region: ScreenReadRegion | None = None
        self._start_x = 0
        self._start_y = 0
        self._rectangle_id: int | None = None

    def select(self) -> ScreenReadRegion | None:
        overlay = tk.Toplevel(self.root)
        overlay.title(self.title)
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.35)
        overlay.configure(cursor="crosshair")
        overlay.bind("<Escape>", lambda _event: overlay.destroy())

        canvas = tk.Canvas(
            overlay,
            bg="black",
            highlightthickness=0,
            cursor="crosshair",
        )
        canvas.pack(fill="both", expand=True)
        canvas.create_text(
            24,
            24,
            anchor="nw",
            fill="white",
            text=f"{self.title}: drag to select the screen area, Esc cancels",
            font=("Segoe UI", 14, "bold"),
        )
        canvas.bind("<ButtonPress-1>", lambda event: self._start_selection(canvas, event))
        canvas.bind("<B1-Motion>", lambda event: self._update_selection(canvas, event))
        canvas.bind(
            "<ButtonRelease-1>",
            lambda event: self._finish_selection(overlay, event),
        )

        overlay.focus_force()
        self.root.wait_window(overlay)
        return self.region

    def _start_selection(self, canvas: tk.Canvas, event: tk.Event) -> None:
        self._start_x = int(event.x)
        self._start_y = int(event.y)
        if self._rectangle_id is not None:
            canvas.delete(self._rectangle_id)
        self._rectangle_id = canvas.create_rectangle(
            self._start_x,
            self._start_y,
            self._start_x,
            self._start_y,
            outline="#00e5ff",
            width=3,
        )

    def _update_selection(self, canvas: tk.Canvas, event: tk.Event) -> None:
        if self._rectangle_id is None:
            return
        canvas.coords(
            self._rectangle_id,
            self._start_x,
            self._start_y,
            int(event.x),
            int(event.y),
        )

    def _finish_selection(self, overlay: tk.Toplevel, event: tk.Event) -> None:
        end_x = int(event.x)
        end_y = int(event.y)
        x = min(self._start_x, end_x)
        y = min(self._start_y, end_y)
        width = abs(end_x - self._start_x)
        height = abs(end_y - self._start_y)
        if width >= self.MIN_REGION_SIZE and height >= self.MIN_REGION_SIZE:
            self.region = ScreenReadRegion(x, y, width, height)
        overlay.destroy()


class HoloQuizControlPanel:
    def __init__(self, root: tk.Tk, config_path: Path = Path("config.json")) -> None:
        self.root = root
        self.config_path = config_path
        config = load_config(config_path)
        self.config = config
        self.controls = RuntimeControls.from_config(config)
        if self.controls.get_coordinate_locks() != config.coordinate_locks:
            save_coordinate_lock_settings(
                config_path,
                self.controls.get_coordinate_locks(),
                enabled=config.coordinate_lock_enabled,
                auto_hit_enabled=config.coordinate_lock_auto_hit_enabled,
                auto_hit_min_seconds=config.coordinate_lock_auto_hit_min_seconds,
                auto_hit_max_seconds=config.coordinate_lock_auto_hit_max_seconds,
                look_at_enabled=config.coordinate_lock_look_at_enabled,
            )
        self.controller = ControlPanelController(self.controls)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker = BotWorker(config_path, self.controls, self.log_queue)
        self.screen_phrase_watcher = ScreenPhraseWatcher(OcrScreenTextReader())

        self.root.title(APP_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.minsize(*WINDOW_MIN_SIZE)

        snapshot = self.controls.snapshot()
        self.program_var = tk.BooleanVar(value=snapshot.program_enabled)
        self.dry_run_var = tk.BooleanVar(value=snapshot.dry_run)
        self.delay_min_var = tk.StringVar(value=f"{snapshot.send_delay_min_seconds:g}")
        self.delay_max_var = tk.StringVar(value=f"{snapshot.send_delay_max_seconds:g}")
        self.status_var = tk.StringVar(value="Starting")
        self.delay_status_var = tk.StringVar(value="")
        self.browser_search_status_var = tk.StringVar(value="")
        self.screen_phrase_trigger_var = tk.StringVar(
            value=config.screen_phrase_trigger
        )
        self.screen_phrase_status_var = tk.StringVar(value="")
        self.screen_phrase_source_var = tk.StringVar(value=config.screen_phrase_source)
        self.screen_phrase_api_status_var = tk.StringVar(value="")
        self.screen_phrase_debug_var = tk.BooleanVar(value=False)
        self.screen_phrase_auto_send_var = tk.BooleanVar(
            value=config.screen_phrase_auto_send_result
        )
        self.chat_trigger_trigger_var = tk.StringVar(value="")
        self.chat_trigger_macro_var = tk.StringVar(value="")
        self.chat_trigger_sound_var = tk.StringVar(value="")
        self.chat_trigger_cooldown_var = tk.StringVar(value="30")
        self.chat_trigger_typing_interval_var = tk.StringVar(
            value=f"{config.typing_interval_seconds:g}"
        )
        self.chat_trigger_status_var = tk.StringVar(value="")
        self.chat_trigger_dry_run_var = tk.BooleanVar(
            value=config.chat_trigger_dry_run
        )
        self.chat_trigger_editing_id: str | None = None
        self.coordinate_lock_enabled_var = tk.BooleanVar(
            value=config.coordinate_lock_enabled
        )
        self.coordinate_lock_auto_hit_var = tk.BooleanVar(
            value=config.coordinate_lock_auto_hit_enabled
        )
        self.coordinate_lock_auto_hit_min_var = tk.StringVar(
            value=f"{config.coordinate_lock_auto_hit_min_seconds:g}"
        )
        self.coordinate_lock_auto_hit_max_var = tk.StringVar(
            value=f"{config.coordinate_lock_auto_hit_max_seconds:g}"
        )
        self.coordinate_lock_look_at_var = tk.BooleanVar(
            value=config.coordinate_lock_look_at_enabled
        )
        self.coordinate_lock_name_var = tk.StringVar(value="")
        self.coordinate_lock_x_var = tk.StringVar(value="")
        self.coordinate_lock_y_var = tk.StringVar(value="")
        self.coordinate_lock_z_var = tk.StringVar(value="")
        self.coordinate_lock_active_area_var = tk.StringVar(
            value=f"{CoordinateLockConfig.active_area:g}"
        )
        self.coordinate_lock_auto_hit_players_var = tk.BooleanVar(value=True)
        self.coordinate_lock_auto_hit_mobs_var = tk.BooleanVar(value=True)
        self.coordinate_lock_target_name_var = tk.StringVar(value="")
        self.coordinate_lock_editing_id: str | None = None
        self.coordinate_lock_status_var = tk.StringVar(
            value="Select a saved coordinate or add a new coordinate."
        )
        self.function_vars: dict[str, tk.BooleanVar] = {}
        self.screen_phrase_trigger_var.trace_add(
            "write",
            lambda *_args: self._on_screen_phrase_trigger_change(),
        )
        self._load_screen_phrase_settings(config)
        self.screen_phrase_worker = ScreenPhraseWorker(
            self.controls,
            self.screen_phrase_watcher,
            self.log_queue,
            debug_enabled_provider=self.screen_phrase_debug_var.get,
            auto_send_result_provider=self.screen_phrase_auto_send_var.get,
        )
        self.coordinate_lock_worker = CoordinateLockWorker(
            self.controls,
            self.log_queue,
            player_client=PlayerDataClient(config.player_data_url),
        )
        self.mouse4_hotkey_listener = Mouse4HotkeyListener(
            self._queue_mouse4_coordinate_lock_toggle
        )

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.worker.start()
        self.screen_phrase_worker.start()
        self.coordinate_lock_worker.start()
        self.mouse4_hotkey_listener.start()
        self._refresh_status()
        self._drain_logs()

    def _build_ui(self) -> None:
        self._configure_styles()
        outer = ttk.Frame(self.root, padding=(16, 14, 16, 12))
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        status_row = ttk.Frame(outer, style="Header.TFrame", padding=(14, 10))
        status_row.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        status_row.columnconfigure(1, weight=1)
        ttk.Label(
            status_row,
            text=APP_TITLE,
            style="HeaderTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            status_row,
            text=APP_SUBTITLE,
            style="HeaderSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.status_label = ttk.Label(
            status_row, textvariable=self.status_var, style="Status.TLabel"
        )
        self.status_label.grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="e",
            padx=(12, 18),
        )
        ttk.Checkbutton(
            status_row,
            text="Program enabled",
            variable=self.program_var,
            command=self._on_program_toggle,
        ).grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 14))
        ttk.Checkbutton(
            status_row,
            text="Dry-run",
            variable=self.dry_run_var,
            command=self._on_dry_run_toggle,
        ).grid(row=0, column=3, rowspan=2, sticky="e")

        self.notebook = ttk.Notebook(outer)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        (
            holoquiz_tab,
            screen_tab,
            chat_tab,
            coordinate_tab,
            activity_tab,
        ) = (self._add_feature_tab(label) for label in FEATURE_TAB_LABELS)

        holoquiz_frame = ttk.LabelFrame(
            holoquiz_tab, text="Answer automation", padding=16
        )
        holoquiz_frame.grid(row=0, column=0, sticky="new")
        holoquiz_frame.columnconfigure(1, weight=1)

        controls_row = ttk.Frame(holoquiz_frame)
        controls_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        controls_row.columnconfigure(2, weight=1)
        ttk.Label(
            controls_row,
            text=(
                "Control quiz lookup and live chat delivery. Global switches remain "
                "available in the header on every page."
            ),
            style="Muted.TLabel",
            wraplength=720,
        ).grid(row=0, column=0, columnspan=3, sticky="w")

        delay_row = ttk.Frame(holoquiz_frame)
        delay_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        delay_row.columnconfigure(4, weight=1)
        ttk.Label(delay_row, text="Send delay seconds").grid(
            row=0,
            column=0,
            sticky="w",
        )
        min_entry = ttk.Entry(delay_row, textvariable=self.delay_min_var, width=8)
        min_entry.grid(row=0, column=1, sticky="w", padx=(8, 4))
        min_entry.bind("<Return>", lambda _event: self._on_apply_delay())
        ttk.Label(delay_row, text="to").grid(row=0, column=2, sticky="w")
        max_entry = ttk.Entry(delay_row, textvariable=self.delay_max_var, width=8)
        max_entry.grid(row=0, column=3, sticky="w", padx=(4, 6))
        max_entry.bind("<Return>", lambda _event: self._on_apply_delay())
        ttk.Button(delay_row, text="Apply", command=self._on_apply_delay).grid(
            row=0,
            column=4,
            sticky="w",
        )
        ttk.Label(delay_row, textvariable=self.delay_status_var).grid(
            row=0,
            column=5,
            sticky="w",
            padx=(8, 0),
        )

        function_definitions = {
            function.key: function for function in self.controls.registry.all()
        }
        holoquiz_function_row = 2
        for function in self.controls.registry.all():
            if function.key == SCREEN_PHRASE_WATCHER_FUNCTION:
                continue
            self._add_function_checkbutton(
                holoquiz_frame,
                function,
                row=holoquiz_function_row,
            )
            holoquiz_function_row += 1

        browser_row = holoquiz_function_row
        ttk.Button(
            holoquiz_frame,
            text="Browser search",
            command=self._on_browser_search,
        ).grid(row=browser_row, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            holoquiz_frame,
            textvariable=self.browser_search_status_var,
            width=BROWSER_SEARCH_STATUS_MAX_CHARS,
        ).grid(row=browser_row, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        trigger_phase_frame = ttk.LabelFrame(
            screen_tab, text="Screen phrase watcher", padding=16
        )
        trigger_phase_frame.grid(row=0, column=0, sticky="new")
        trigger_phase_frame.columnconfigure(0, weight=1)

        screen_phrase_function = function_definitions.get(SCREEN_PHRASE_WATCHER_FUNCTION)
        if screen_phrase_function is not None:
            enabled = self.controls.is_function_enabled(screen_phrase_function.key)
            variable = tk.BooleanVar(value=enabled)
            self.function_vars[screen_phrase_function.key] = variable
            row_frame = ttk.Frame(trigger_phase_frame)
            row_frame.grid(row=0, column=0, sticky="w")
            ttk.Checkbutton(
                row_frame,
                text=screen_phrase_function.label,
                variable=variable,
                command=lambda key=screen_phrase_function.key: self._on_function_toggle(
                    key
                ),
            ).grid(row=0, column=0, sticky="w")
            ttk.Checkbutton(
                row_frame,
                text="Debug OCR log",
                variable=self.screen_phrase_debug_var,
            ).grid(row=0, column=1, sticky="w", padx=(12, 0))
            ttk.Checkbutton(
                row_frame,
                text="Auto send result",
                variable=self.screen_phrase_auto_send_var,
                command=self._on_screen_phrase_auto_send_change,
            ).grid(row=0, column=2, sticky="w", padx=(12, 0))

        screen_phrase_frame = ttk.Frame(trigger_phase_frame)
        screen_phrase_frame.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(10, 0),
        )
        screen_phrase_frame.columnconfigure(2, weight=1)
        source_frame = ttk.Frame(screen_phrase_frame)
        source_frame.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(source_frame, text="Source:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            source_frame, text="Screen OCR", value=SCREEN_PHRASE_SOURCE_OCR,
            variable=self.screen_phrase_source_var, command=self._on_screen_phrase_source_change,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Radiobutton(
            source_frame, text="Title API", value=SCREEN_PHRASE_SOURCE_TITLE_API,
            variable=self.screen_phrase_source_var, command=self._on_screen_phrase_source_change,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Button(
            source_frame, text="Check API status", command=self._check_title_api_health,
        ).grid(row=0, column=3, sticky="w", padx=(12, 0))
        ttk.Label(source_frame, textvariable=self.screen_phrase_api_status_var).grid(
            row=0, column=4, sticky="w", padx=(8, 0)
        )
        self.screen_phrase_trigger_area_button = ttk.Button(
            screen_phrase_frame,
            text="Set trigger area",
            command=self._on_set_screen_phrase_trigger_area,
        )
        self.screen_phrase_trigger_area_button.grid(row=1, column=0, sticky="w")
        ttk.Label(screen_phrase_frame, text="Trigger phrase").grid(
            row=1,
            column=1,
            sticky="w",
            padx=(8, 4),
        )
        ttk.Entry(
            screen_phrase_frame,
            textvariable=self.screen_phrase_trigger_var,
            width=34,
        ).grid(row=1, column=2, sticky="ew")
        self.screen_phrase_result_area_button = ttk.Button(
            screen_phrase_frame,
            text="Set result area",
            command=self._on_set_screen_phrase_result_area,
        )
        self.screen_phrase_result_area_button.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(
            screen_phrase_frame,
            textvariable=self.screen_phrase_status_var,
        ).grid(row=2, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(6, 0))
        self._update_screen_phrase_source_ui()

        chat_trigger_frame = ttk.LabelFrame(
            chat_tab, text="Chat trigger rules", padding=16
        )
        chat_trigger_frame.grid(row=0, column=0, sticky="nsew")
        chat_trigger_frame.columnconfigure(0, weight=1)
        chat_trigger_frame.rowconfigure(2, weight=1)

        chat_trigger_action_row = ttk.Frame(chat_trigger_frame)
        chat_trigger_action_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        chat_trigger_action_row.columnconfigure(2, weight=1)
        ttk.Button(
            chat_trigger_action_row,
            text="New chat trigger",
            command=self._on_new_chat_trigger,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            chat_trigger_action_row,
            text="Dry-run",
            variable=self.chat_trigger_dry_run_var,
            command=self._on_chat_trigger_dry_run_toggle,
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(
            chat_trigger_action_row,
            textvariable=self.chat_trigger_status_var,
        ).grid(row=0, column=2, sticky="ew", padx=(8, 0))

        chat_trigger_form = ttk.Frame(chat_trigger_frame)
        chat_trigger_form.grid(row=1, column=0, sticky="ew")
        chat_trigger_form.columnconfigure(1, weight=1)
        chat_trigger_form.columnconfigure(3, weight=1)
        ttk.Label(chat_trigger_form, text="Trigger phrase").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Entry(
            chat_trigger_form,
            textvariable=self.chat_trigger_trigger_var,
            width=26,
        ).grid(row=0, column=1, sticky="ew", padx=(6, 10))
        ttk.Label(chat_trigger_form, text="Macro (optional)").grid(
            row=0,
            column=2,
            sticky="w",
        )
        ttk.Entry(
            chat_trigger_form,
            textvariable=self.chat_trigger_macro_var,
            width=34,
        ).grid(row=0, column=3, sticky="ew", padx=(6, 10))
        ttk.Label(chat_trigger_form, text="Cooldown").grid(
            row=1,
            column=0,
            sticky="w",
            pady=(8, 0),
        )
        ttk.Entry(
            chat_trigger_form,
            textvariable=self.chat_trigger_cooldown_var,
            width=8,
        ).grid(row=1, column=1, sticky="w", padx=(6, 10), pady=(8, 0))
        ttk.Label(chat_trigger_form, text="Typing interval").grid(
            row=1,
            column=2,
            sticky="w",
            pady=(8, 0),
        )
        ttk.Entry(
            chat_trigger_form,
            textvariable=self.chat_trigger_typing_interval_var,
            width=8,
        ).grid(row=1, column=3, sticky="w", padx=(6, 10), pady=(8, 0))
        self.chat_trigger_submit_button = ttk.Button(
            chat_trigger_form,
            text="Create",
            command=self._on_create_or_update_chat_trigger,
        )
        self.chat_trigger_submit_button.grid(row=0, column=4, sticky="w")
        ttk.Label(chat_trigger_form, text="Sound (optional)").grid(
            row=2,
            column=0,
            sticky="w",
            pady=(8, 0),
        )
        ttk.Entry(
            chat_trigger_form,
            textvariable=self.chat_trigger_sound_var,
        ).grid(
            row=2,
            column=1,
            columnspan=2,
            sticky="ew",
            padx=(6, 10),
            pady=(8, 0),
        )
        ttk.Button(
            chat_trigger_form,
            text="Browse...",
            command=self._on_browse_chat_trigger_sound,
        ).grid(row=2, column=3, sticky="w", pady=(8, 0))
        ttk.Button(
            chat_trigger_form,
            text="Clear",
            command=lambda: self.chat_trigger_sound_var.set(""),
        ).grid(row=2, column=4, sticky="w", padx=(6, 0), pady=(8, 0))

        chat_trigger_list = ttk.Frame(chat_trigger_frame)
        chat_trigger_list.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        chat_trigger_list.columnconfigure(0, weight=1)
        chat_trigger_list.rowconfigure(0, weight=1)
        self.chat_trigger_tree = ttk.Treeview(
            chat_trigger_list,
            columns=("status", "phrase", "action", "cooldown", "typing"),
            show="headings",
            selectmode="browse",
            height=6,
        )
        for column, heading, width, stretch in (
            ("status", "Status", 70, False),
            ("phrase", "Trigger phrase", 180, True),
            ("action", "Action", 220, True),
            ("cooldown", "Cooldown", 80, False),
            ("typing", "Typing", 80, False),
        ):
            self.chat_trigger_tree.heading(column, text=heading)
            self.chat_trigger_tree.column(
                column, width=width, minwidth=70, stretch=stretch
            )
        self.chat_trigger_tree.grid(row=0, column=0, sticky="nsew")
        self.chat_trigger_tree.bind(
            "<Double-1>", lambda _event: self._edit_selected_chat_trigger()
        )
        chat_trigger_scrollbar = ttk.Scrollbar(
            chat_trigger_list,
            orient="vertical",
            command=self.chat_trigger_tree.yview,
        )
        chat_trigger_scrollbar.grid(row=0, column=1, sticky="ns")
        self.chat_trigger_tree.configure(yscrollcommand=chat_trigger_scrollbar.set)
        chat_trigger_buttons = ttk.Frame(chat_trigger_list)
        chat_trigger_buttons.grid(row=1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(
            chat_trigger_buttons,
            text="Enable / disable",
            command=self._toggle_selected_chat_trigger,
        ).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(
            chat_trigger_buttons,
            text="Edit selected",
            command=self._edit_selected_chat_trigger,
        ).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(
            chat_trigger_buttons,
            text="Delete selected",
            command=self._delete_selected_chat_trigger,
        ).grid(row=0, column=2)
        self._refresh_chat_trigger_rows()

        coordinate_lock_frame = ttk.LabelFrame(
            coordinate_tab,
            text="Coordinate lock targets",
            padding=16,
        )
        coordinate_lock_frame.grid(row=0, column=0, sticky="nsew")
        coordinate_lock_frame.columnconfigure(0, weight=1)
        coordinate_lock_frame.rowconfigure(1, weight=1)

        coordinate_lock_form = ttk.Frame(coordinate_lock_frame)
        coordinate_lock_form.grid(row=0, column=0, sticky="ew")
        coordinate_lock_form.columnconfigure(0, weight=1)

        behavior_row = ttk.Frame(coordinate_lock_form)
        behavior_row.grid(row=0, column=0, sticky="ew")
        behavior_row.columnconfigure(4, weight=1)
        ttk.Label(
            behavior_row,
            text="Lock behavior",
            style="SectionLabel.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 18))
        ttk.Checkbutton(
            behavior_row,
            text="Enable coordinate lock",
            variable=self.coordinate_lock_enabled_var,
            command=self._on_coordinate_lock_master_toggle,
        ).grid(row=0, column=1, sticky="w", padx=(0, 18))
        ttk.Checkbutton(
            behavior_row,
            text="Auto Hit",
            variable=self.coordinate_lock_auto_hit_var,
            command=self._on_coordinate_lock_auto_hit_toggle,
        ).grid(row=0, column=2, sticky="w", padx=(0, 18))
        ttk.Checkbutton(
            behavior_row,
            text="Look at lock",
            variable=self.coordinate_lock_look_at_var,
            command=self._on_coordinate_lock_look_at_toggle,
        ).grid(row=0, column=3, sticky="w")
        ttk.Label(
            behavior_row,
            text="Auto hit interval",
            style="FieldLabel.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(12, 0))

        auto_hit_interval_row = ttk.Frame(behavior_row)
        auto_hit_interval_row.grid(
            row=1,
            column=1,
            columnspan=3,
            sticky="w",
            pady=(12, 0),
        )
        ttk.Label(auto_hit_interval_row, text="Min").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Entry(
            auto_hit_interval_row,
            textvariable=self.coordinate_lock_auto_hit_min_var,
            width=7,
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(auto_hit_interval_row, text="sec").grid(
            row=0, column=2, sticky="w", padx=(6, 18)
        )
        ttk.Label(auto_hit_interval_row, text="Max").grid(
            row=0, column=3, sticky="w", padx=(0, 6)
        )
        ttk.Entry(
            auto_hit_interval_row,
            textvariable=self.coordinate_lock_auto_hit_max_var,
            width=7,
        ).grid(row=0, column=4, sticky="w")
        ttk.Label(auto_hit_interval_row, text="sec").grid(
            row=0, column=5, sticky="w", padx=(6, 18)
        )
        ttk.Button(
            auto_hit_interval_row,
            text="Apply",
            command=self._on_apply_coordinate_lock_auto_hit_range,
        ).grid(row=0, column=6, sticky="w")

        ttk.Separator(coordinate_lock_form, orient="horizontal").grid(
            row=1, column=0, sticky="ew", pady=14
        )

        target_editor = ttk.Frame(coordinate_lock_form)
        target_editor.grid(row=2, column=0, sticky="ew")
        for column, weight in enumerate((3, 1, 1, 1, 1)):
            target_editor.columnconfigure(column, weight=weight)

        for column, (label, variable) in enumerate(
            (
                ("Coordinate Name", self.coordinate_lock_name_var),
                ("X", self.coordinate_lock_x_var),
                ("Y", self.coordinate_lock_y_var),
                ("Z", self.coordinate_lock_z_var),
                ("Active area", self.coordinate_lock_active_area_var),
            )
        ):
            field = ttk.Frame(target_editor)
            field.grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(0, 12 if column < 4 else 16),
            )
            field.columnconfigure(0, weight=1)
            ttk.Label(field, text=label, style="FieldLabel.TLabel").grid(
                row=0, column=0, sticky="w", pady=(0, 5)
            )
            ttk.Entry(
                field,
                textvariable=variable,
                width=24 if column == 0 else 10,
            ).grid(row=1, column=0, sticky="ew")

        target_actions = ttk.Frame(target_editor)
        target_actions.grid(row=0, column=5, sticky="se")
        self.coordinate_lock_submit_button = ttk.Button(
            target_actions,
            text="Add coordinate",
            command=self._on_add_coordinate_lock,
        )
        self.coordinate_lock_submit_button.grid(row=0, column=0, padx=(0, 6))
        ttk.Button(
            target_actions,
            text="Use current position",
            command=self._on_lock_here,
        ).grid(row=0, column=1)

        auto_hit_target_row = ttk.Frame(coordinate_lock_form)
        auto_hit_target_row.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(
            auto_hit_target_row,
            text="Auto hit targets",
            style="FieldLabel.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Checkbutton(
            auto_hit_target_row,
            text="Players",
            variable=self.coordinate_lock_auto_hit_players_var,
        ).grid(row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Checkbutton(
            auto_hit_target_row,
            text="Mobs",
            variable=self.coordinate_lock_auto_hit_mobs_var,
        ).grid(row=0, column=2, sticky="w", padx=(0, 18))
        ttk.Label(auto_hit_target_row, text="Target Name").grid(
            row=0, column=3, sticky="w", padx=(0, 6)
        )
        ttk.Entry(
            auto_hit_target_row,
            textvariable=self.coordinate_lock_target_name_var,
            width=30,
        ).grid(row=0, column=4, sticky="ew")
        auto_hit_target_row.columnconfigure(4, weight=1)

        status_row = ttk.Frame(coordinate_lock_form)
        status_row.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(
            status_row,
            text="Status",
            style="FieldLabel.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            status_row,
            textvariable=self.coordinate_lock_status_var,
            style="Muted.TLabel",
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))

        coordinate_lock_list = ttk.Frame(coordinate_lock_frame)
        coordinate_lock_list.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        coordinate_lock_list.columnconfigure(0, weight=1)
        coordinate_lock_list.rowconfigure(1, weight=1)
        ttk.Label(
            coordinate_lock_list,
            text="Saved targets",
            style="SectionLabel.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.coordinate_lock_tree = ttk.Treeview(
            coordinate_lock_list,
            columns=(
                "status",
                "name",
                "target_types",
                "target_name",
                "x",
                "y",
                "z",
                "active_area",
            ),
            show="headings",
            selectmode="browse",
            height=6,
        )
        for column, heading, width, stretch in (
            ("status", "Status", 75, False),
            ("name", "Coordinate Name", 130, True),
            ("target_types", "Targets", 110, False),
            ("target_name", "Target Name", 170, True),
            ("x", "X", 75, False),
            ("y", "Y", 75, False),
            ("z", "Z", 75, False),
            ("active_area", "Active area", 85, False),
        ):
            self.coordinate_lock_tree.heading(column, text=heading)
            self.coordinate_lock_tree.column(
                column, width=width, minwidth=70, stretch=stretch
            )
        self.coordinate_lock_tree.grid(row=1, column=0, sticky="nsew")
        self.coordinate_lock_tree.bind(
            "<Double-1>", lambda _event: self._edit_selected_coordinate_lock()
        )
        coordinate_lock_scrollbar = ttk.Scrollbar(
            coordinate_lock_list,
            orient="vertical",
            command=self.coordinate_lock_tree.yview,
        )
        coordinate_lock_scrollbar.grid(row=1, column=1, sticky="ns")
        self.coordinate_lock_tree.configure(
            yscrollcommand=coordinate_lock_scrollbar.set
        )
        self.coordinate_lock_tree.tag_configure("active", background="#eefbf3")
        coordinate_lock_buttons = ttk.Frame(coordinate_lock_list)
        coordinate_lock_buttons.grid(
            row=2, column=0, columnspan=2, sticky="e", pady=(10, 0)
        )
        ttk.Button(
            coordinate_lock_buttons,
            text="Toggle active",
            command=self._activate_selected_coordinate_lock,
        ).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(
            coordinate_lock_buttons,
            text="Edit selected",
            command=self._edit_selected_coordinate_lock,
        ).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(
            coordinate_lock_buttons,
            text="Delete target",
            command=self._delete_selected_coordinate_lock,
        ).grid(row=0, column=2)
        self._refresh_coordinate_lock_rows()

        log_frame = ttk.LabelFrame(activity_tab, text="Runtime log", padding=10)
        log_frame.grid(row=0, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        log_toolbar.columnconfigure(0, weight=1)
        ttk.Label(
            log_toolbar,
            text="Bot, watcher, and automation messages appear here.",
            style="Muted.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(log_toolbar, text="Clear log", command=self._clear_log).grid(
            row=0, column=1, sticky="e"
        )
        self.log_text = tk.Text(
            log_frame,
            height=12,
            wrap="word",
            state="disabled",
            background="#101828",
            foreground="#e4e7ec",
            insertbackground="#ffffff",
            relief="flat",
            padx=10,
            pady=10,
            font=("Consolas", 9),
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log_text.yview,
        )
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.root.configure(background="#f3f5f7")
        style.configure("TFrame", background="#ffffff")
        style.configure("TLabel", background="#ffffff", foreground="#344054")
        style.configure("TCheckbutton", background="#ffffff")
        style.configure("TRadiobutton", background="#ffffff")
        style.configure("Header.TFrame", background="#ffffff")
        style.configure(
            "HeaderTitle.TLabel",
            background="#ffffff",
            foreground="#172033",
            font=("Segoe UI Semibold", 15),
        )
        style.configure(
            "HeaderSubtitle.TLabel",
            background="#ffffff",
            foreground="#667085",
            font=("Segoe UI", 9),
        )
        style.configure(
            "Status.TLabel",
            background="#e8f5ee",
            foreground="#176b3a",
            padding=(10, 5),
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "PausedStatus.TLabel",
            background="#fff4e5",
            foreground="#9a4d00",
            padding=(10, 5),
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "StoppedStatus.TLabel",
            background="#feecec",
            foreground="#b42318",
            padding=(10, 5),
            font=("Segoe UI Semibold", 9),
        )
        style.configure("Muted.TLabel", foreground="#667085")
        style.configure(
            "SectionLabel.TLabel",
            foreground="#172033",
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "FieldLabel.TLabel",
            foreground="#475467",
            font=("Segoe UI Semibold", 9),
        )
        style.configure("TLabelframe", background="#ffffff")
        style.configure("TLabelframe.Label", font=("Segoe UI Semibold", 10))
        style.configure("TNotebook", background="#f3f5f7", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI", 9))
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 9))

    def _add_feature_tab(self, label: str) -> ttk.Frame:
        tab = ttk.Frame(self.notebook, padding=14)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.notebook.add(tab, text=label)
        return tab

    def _add_function_checkbutton(
        self,
        parent: ttk.Frame,
        function: FunctionDefinition,
        *,
        row: int,
    ) -> None:
        enabled = self.controls.is_function_enabled(function.key)
        variable = tk.BooleanVar(value=enabled)
        self.function_vars[function.key] = variable
        ttk.Checkbutton(
            parent,
            text=function.label,
            variable=variable,
            command=lambda key=function.key: self._on_function_toggle(key),
        ).grid(row=row, column=0, columnspan=2, sticky="w")

    def _on_program_toggle(self) -> None:
        self.controller.set_program_enabled(self.program_var.get())
        self._update_status_text()

    def _on_dry_run_toggle(self) -> None:
        self.controller.set_dry_run(self.dry_run_var.get())

    def _on_function_toggle(self, key: str) -> None:
        self.controller.set_function_enabled(key, self.function_vars[key].get())

    def _on_apply_delay(self) -> None:
        result = self.controller.set_send_delay_range(
            self.delay_min_var.get(),
            self.delay_max_var.get(),
        )
        self.delay_status_var.set(result.message)
        if result.ok:
            snapshot = self.controls.snapshot()
            self.delay_min_var.set(f"{snapshot.send_delay_min_seconds:g}")
            self.delay_max_var.set(f"{snapshot.send_delay_max_seconds:g}")

    def _on_browser_search(self) -> None:
        result = self.controller.open_browser_search()
        self.browser_search_status_var.set(result.message)

    def _on_set_screen_phrase_trigger_area(self) -> None:
        region = self._select_screen_region("Set trigger area")
        if region is None:
            self.screen_phrase_status_var.set("Trigger area selection cancelled.")
            return
        self.screen_phrase_watcher.set_trigger_region(region)
        self.screen_phrase_status_var.set(f"Trigger area set: {format_region(region)}")
        self._save_screen_phrase_settings()

    def _on_set_screen_phrase_result_area(self) -> None:
        region = self._select_screen_region("Set result area")
        if region is None:
            self.screen_phrase_status_var.set("Result area selection cancelled.")
            return
        self.screen_phrase_watcher.set_result_region(region)
        self.screen_phrase_status_var.set(f"Result area set: {format_region(region)}")
        self._save_screen_phrase_settings()

    def _on_screen_phrase_trigger_change(self) -> None:
        self.screen_phrase_watcher.set_trigger_phrase(
            self.screen_phrase_trigger_var.get()
        )
        self._save_screen_phrase_settings()

    def _on_screen_phrase_auto_send_change(self) -> None:
        self._save_screen_phrase_settings()

    def _on_screen_phrase_source_change(self) -> None:
        source = self.screen_phrase_source_var.get()
        self.screen_phrase_watcher.set_source(source)
        self._update_screen_phrase_source_ui()
        self._save_screen_phrase_settings()
        if source == SCREEN_PHRASE_SOURCE_TITLE_API:
            self._check_title_api_health()

    def _update_screen_phrase_source_ui(self) -> None:
        state = (
            "normal"
            if self.screen_phrase_source_var.get() == SCREEN_PHRASE_SOURCE_OCR
            else "disabled"
        )
        self.screen_phrase_trigger_area_button.configure(state=state)
        self.screen_phrase_result_area_button.configure(state=state)

    def _check_title_api_health(self) -> None:
        self.screen_phrase_api_status_var.set("Checking...")

        def check() -> None:
            try:
                health = self.screen_phrase_watcher.check_api_health()
                value = health.get("status", health.get("healthy", "OK"))
                message = f"API: {value}"
            except Exception as error:
                message = f"API unavailable: {error}"
            self.root.after(0, lambda: self.screen_phrase_api_status_var.set(message))

        threading.Thread(target=check, daemon=True).start()

    def _on_chat_trigger_dry_run_toggle(self) -> None:
        self.controls.set_chat_trigger_dry_run(self.chat_trigger_dry_run_var.get())
        self._save_chat_triggers_settings()

    def _on_new_chat_trigger(self) -> None:
        self.chat_trigger_editing_id = None
        self.chat_trigger_trigger_var.set("")
        self.chat_trigger_macro_var.set("")
        self.chat_trigger_sound_var.set("")
        self.chat_trigger_cooldown_var.set("30")
        self.chat_trigger_typing_interval_var.set(
            f"{self.controls.get_config().typing_interval_seconds:g}"
        )
        self.chat_trigger_submit_button.configure(text="Create")
        self.chat_trigger_status_var.set("")

    def _on_create_or_update_chat_trigger(self) -> None:
        result = self._build_chat_trigger_from_form()
        if not result.ok:
            self.chat_trigger_status_var.set(result.message)
            return

        trigger = result.value
        if trigger is None:
            self.chat_trigger_status_var.set("Could not build chat trigger.")
            return
        triggers = list(self.controls.get_chat_triggers())
        if self.chat_trigger_editing_id is None:
            triggers.append(trigger)
            self.chat_trigger_status_var.set("Chat trigger created.")
        else:
            triggers = [
                trigger if item.id == self.chat_trigger_editing_id else item
                for item in triggers
            ]
            self.chat_trigger_status_var.set("Chat trigger updated.")

        self.controls.set_chat_triggers(triggers)
        self._save_chat_triggers_settings()
        self._refresh_chat_trigger_rows()
        self.chat_trigger_editing_id = None
        self.chat_trigger_trigger_var.set("")
        self.chat_trigger_macro_var.set("")
        self.chat_trigger_sound_var.set("")
        self.chat_trigger_cooldown_var.set("30")
        self.chat_trigger_typing_interval_var.set(
            f"{self.controls.get_config().typing_interval_seconds:g}"
        )
        self.chat_trigger_submit_button.configure(text="Create")

    def _build_chat_trigger_from_form(self) -> ChatTriggerBuildResult:
        trigger_phrase = self.chat_trigger_trigger_var.get().strip()
        macro = self.chat_trigger_macro_var.get().strip()
        sound_path_text = self.chat_trigger_sound_var.get().strip()
        if not trigger_phrase:
            return ChatTriggerBuildResult(False, message="Trigger phrase is required.")
        if not macro and not sound_path_text:
            return ChatTriggerBuildResult(
                False,
                message="Macro or sound file is required.",
            )

        sound_path = Path(sound_path_text) if sound_path_text else None
        if sound_path is not None:
            if sound_path.suffix.lower() not in SUPPORTED_SOUND_EXTENSIONS:
                return ChatTriggerBuildResult(
                    False,
                    message="Sound file must be an MP3 or WAV.",
                )
            if not sound_path.is_file():
                return ChatTriggerBuildResult(
                    False,
                    message="Sound file does not exist.",
                )

        try:
            cooldown_seconds = float(self.chat_trigger_cooldown_var.get())
        except ValueError:
            return ChatTriggerBuildResult(False, message="Cooldown must be a number.")
        if cooldown_seconds < 0:
            return ChatTriggerBuildResult(
                False,
                message="Cooldown must be 0 or greater.",
            )
        try:
            typing_interval_seconds = float(
                self.chat_trigger_typing_interval_var.get()
            )
        except ValueError:
            return ChatTriggerBuildResult(
                False,
                message="Typing interval must be a number.",
            )
        if typing_interval_seconds < 0:
            return ChatTriggerBuildResult(
                False,
                message="Typing interval must be 0 or greater.",
            )

        existing = self._chat_trigger_by_id(self.chat_trigger_editing_id)
        return ChatTriggerBuildResult(
            True,
            value=ChatTriggerConfig(
                id=existing.id if existing is not None else uuid4().hex,
                trigger_phrase=trigger_phrase,
                macro=macro,
                cooldown_seconds=cooldown_seconds,
                typing_interval_seconds=typing_interval_seconds,
                enabled=existing.enabled if existing is not None else True,
                sound_path=sound_path,
            ),
        )

    def _on_browse_chat_trigger_sound(self) -> None:
        sound_path = filedialog.askopenfilename(
            parent=self.root,
            title="Select chat trigger sound",
            filetypes=(
                ("Audio files", "*.mp3 *.wav"),
                ("MP3 files", "*.mp3"),
                ("WAV files", "*.wav"),
            ),
        )
        if sound_path:
            self.chat_trigger_sound_var.set(sound_path)

    def _on_chat_trigger_toggle(self, trigger_id: str) -> None:
        triggers = [
            replace(trigger, enabled=not trigger.enabled)
            if trigger.id == trigger_id
            else trigger
            for trigger in self.controls.get_chat_triggers()
        ]
        self.controls.set_chat_triggers(triggers)
        self._save_chat_triggers_settings()
        self._refresh_chat_trigger_rows()

    def _on_edit_chat_trigger(self, trigger_id: str) -> None:
        trigger = self._chat_trigger_by_id(trigger_id)
        if trigger is None:
            return
        self.chat_trigger_editing_id = trigger.id
        self.chat_trigger_trigger_var.set(trigger.trigger_phrase)
        self.chat_trigger_macro_var.set(trigger.macro)
        self.chat_trigger_sound_var.set(
            str(trigger.sound_path) if trigger.sound_path else ""
        )
        self.chat_trigger_cooldown_var.set(f"{trigger.cooldown_seconds:g}")
        typing_interval_seconds = (
            self.controls.get_config().typing_interval_seconds
            if trigger.typing_interval_seconds is None
            else trigger.typing_interval_seconds
        )
        self.chat_trigger_typing_interval_var.set(f"{typing_interval_seconds:g}")
        self.chat_trigger_submit_button.configure(text="Save")
        self.chat_trigger_status_var.set("Editing chat trigger.")

    def _on_delete_chat_trigger(self, trigger_id: str) -> None:
        triggers = [
            trigger
            for trigger in self.controls.get_chat_triggers()
            if trigger.id != trigger_id
        ]
        self.controls.set_chat_triggers(triggers)
        self._save_chat_triggers_settings()
        self._refresh_chat_trigger_rows()
        if self.chat_trigger_editing_id == trigger_id:
            self._on_new_chat_trigger()
        self.chat_trigger_status_var.set("Chat trigger deleted.")

    def _refresh_chat_trigger_rows(self) -> None:
        selection = self.chat_trigger_tree.selection()
        selected_id = selection[0] if selection else None
        for item_id in self.chat_trigger_tree.get_children():
            self.chat_trigger_tree.delete(item_id)
        for trigger in self.controls.get_chat_triggers():
            typing_interval_seconds = (
                self.controls.get_config().typing_interval_seconds
                if trigger.typing_interval_seconds is None
                else trigger.typing_interval_seconds
            )
            self.chat_trigger_tree.insert(
                "",
                "end",
                iid=trigger.id,
                values=(
                    "Enabled" if trigger.enabled else "Disabled",
                    trigger.trigger_phrase,
                    _chat_trigger_action_text(trigger),
                    f"{trigger.cooldown_seconds:g}s",
                    f"{typing_interval_seconds:g}s/key",
                ),
            )
        if selected_id and self.chat_trigger_tree.exists(selected_id):
            self.chat_trigger_tree.selection_set(selected_id)

    def _selected_chat_trigger_id(self) -> str | None:
        selection = self.chat_trigger_tree.selection()
        if not selection:
            self.chat_trigger_status_var.set("Select a chat trigger first.")
            return None
        return selection[0]

    def _toggle_selected_chat_trigger(self) -> None:
        trigger_id = self._selected_chat_trigger_id()
        if trigger_id is not None:
            self._on_chat_trigger_toggle(trigger_id)

    def _edit_selected_chat_trigger(self) -> None:
        trigger_id = self._selected_chat_trigger_id()
        if trigger_id is not None:
            self._on_edit_chat_trigger(trigger_id)

    def _delete_selected_chat_trigger(self) -> None:
        trigger_id = self._selected_chat_trigger_id()
        if trigger_id is not None:
            self._on_delete_chat_trigger(trigger_id)

    def _save_chat_triggers_settings(self) -> None:
        save_chat_triggers_settings(
            self.config_path,
            self.controls.get_chat_triggers(),
            dry_run=self.chat_trigger_dry_run_var.get(),
        )

    def _on_coordinate_lock_master_toggle(self) -> None:
        enabled = self.coordinate_lock_enabled_var.get()
        self.controls.set_coordinate_lock_enabled(enabled)
        self._save_coordinate_lock_settings()
        self.coordinate_lock_status_var.set("Enabled." if enabled else "Disabled.")

    def _queue_mouse4_coordinate_lock_toggle(self) -> None:
        self.root.after(0, self._toggle_coordinate_lock_from_mouse4)

    def _toggle_coordinate_lock_from_mouse4(self) -> None:
        enabled = not self.coordinate_lock_enabled_var.get()
        self.coordinate_lock_enabled_var.set(enabled)
        self._on_coordinate_lock_master_toggle()
        state = "enabled" if enabled else "disabled"
        self.coordinate_lock_status_var.set(f"Coordinate lock {state} by Mouse 4.")

    def _on_coordinate_lock_auto_hit_toggle(self) -> None:
        self.controls.set_coordinate_lock_auto_hit_enabled(
            self.coordinate_lock_auto_hit_var.get()
        )
        self._save_coordinate_lock_settings()

    def _on_apply_coordinate_lock_auto_hit_range(self) -> None:
        result = self.controller.set_coordinate_lock_auto_hit_range(
            self.coordinate_lock_auto_hit_min_var.get(),
            self.coordinate_lock_auto_hit_max_var.get(),
        )
        self.coordinate_lock_status_var.set(result.message)
        if result.ok:
            config = self.controls.get_config()
            self.coordinate_lock_auto_hit_min_var.set(
                f"{config.coordinate_lock_auto_hit_min_seconds:g}"
            )
            self.coordinate_lock_auto_hit_max_var.set(
                f"{config.coordinate_lock_auto_hit_max_seconds:g}"
            )
            self._save_coordinate_lock_settings()

    def _on_coordinate_lock_look_at_toggle(self) -> None:
        self.controls.set_coordinate_lock_look_at_enabled(
            self.coordinate_lock_look_at_var.get()
        )
        self._save_coordinate_lock_settings()

    def _on_add_coordinate_lock(self) -> None:
        result = self._build_coordinate_lock_from_form()
        if not result.ok or result.value is None:
            self.coordinate_lock_status_var.set(result.message)
            return
        locks = list(self.controls.get_coordinate_locks())
        if self.coordinate_lock_editing_id is None:
            locks = [replace(lock, enabled=False) for lock in locks]
            locks.append(result.value)
            message = "Coordinate added."
        else:
            locks = [
                result.value if lock.id == self.coordinate_lock_editing_id else lock
                for lock in locks
            ]
            message = "Coordinate updated."
        self.controls.set_coordinate_locks(locks)
        self._save_coordinate_lock_settings()
        self._refresh_coordinate_lock_rows()
        self._clear_coordinate_lock_form()
        self.coordinate_lock_status_var.set(message)

    def _clear_coordinate_lock_form(self) -> None:
        self.coordinate_lock_editing_id = None
        self.coordinate_lock_name_var.set("")
        self.coordinate_lock_x_var.set("")
        self.coordinate_lock_y_var.set("")
        self.coordinate_lock_z_var.set("")
        self.coordinate_lock_active_area_var.set(
            f"{CoordinateLockConfig.active_area:g}"
        )
        self.coordinate_lock_auto_hit_players_var.set(True)
        self.coordinate_lock_auto_hit_mobs_var.set(True)
        self.coordinate_lock_target_name_var.set("")
        self.coordinate_lock_submit_button.configure(text="Add coordinate")

    def _build_coordinate_lock_from_form(self) -> CoordinateLockBuildResult:
        name = self.coordinate_lock_name_var.get().strip()
        if not name:
            return CoordinateLockBuildResult(False, "Enter a name for this coordinate.")
        auto_hit_players = self.coordinate_lock_auto_hit_players_var.get()
        auto_hit_mobs = self.coordinate_lock_auto_hit_mobs_var.get()
        if not auto_hit_players and not auto_hit_mobs:
            return CoordinateLockBuildResult(
                False, "Select Players, Mobs, or both for Auto Hit."
            )
        auto_hit_target_name = self.coordinate_lock_target_name_var.get().strip()
        try:
            x = float(self.coordinate_lock_x_var.get().strip())
            y = float(self.coordinate_lock_y_var.get().strip())
            z = float(self.coordinate_lock_z_var.get().strip())
            active_area = float(self.coordinate_lock_active_area_var.get().strip())
        except ValueError:
            return CoordinateLockBuildResult(
                False, "X, Y, Z, and active area must be numbers."
            )
        if not math.isfinite(active_area) or active_area <= 0:
            return CoordinateLockBuildResult(
                False, "Active area must be greater than 0."
            )
        existing = self._coordinate_lock_by_id(self.coordinate_lock_editing_id)
        return CoordinateLockBuildResult(
            True,
            value=CoordinateLockConfig(
                id=existing.id if existing is not None else uuid4().hex,
                x=x,
                y=y,
                z=z,
                enabled=existing.enabled if existing is not None else True,
                name=name,
                active_area=active_area,
                auto_hit_players=auto_hit_players,
                auto_hit_mobs=auto_hit_mobs,
                auto_hit_target_name=auto_hit_target_name,
            ),
        )

    def _coordinate_lock_by_id(
        self, lock_id: str | None
    ) -> CoordinateLockConfig | None:
        return next(
            (
                lock
                for lock in self.controls.get_coordinate_locks()
                if lock.id == lock_id
            ),
            None,
        )

    def _on_edit_coordinate_lock(self, lock_id: str) -> None:
        lock = self._coordinate_lock_by_id(lock_id)
        if lock is None:
            return
        self.coordinate_lock_editing_id = lock.id
        self.coordinate_lock_name_var.set(lock.name)
        self.coordinate_lock_x_var.set(f"{lock.x:g}")
        self.coordinate_lock_y_var.set(f"{lock.y:g}")
        self.coordinate_lock_z_var.set(f"{lock.z:g}")
        self.coordinate_lock_active_area_var.set(f"{lock.active_area:g}")
        self.coordinate_lock_auto_hit_players_var.set(lock.auto_hit_players)
        self.coordinate_lock_auto_hit_mobs_var.set(lock.auto_hit_mobs)
        self.coordinate_lock_target_name_var.set(lock.auto_hit_target_name)
        self.coordinate_lock_submit_button.configure(text="Save coordinate")
        self.coordinate_lock_status_var.set("Editing coordinate.")

    def _on_lock_here(self) -> None:
        self.coordinate_lock_status_var.set("Reading player position...")
        self.root.update_idletasks()
        try:
            position = PlayerDataClient(
                self.controls.get_config().player_data_url
            ).get_position()
        except Exception as error:
            self.coordinate_lock_status_var.set(f"Could not read position: {error}")
            return
        self.coordinate_lock_x_var.set(f"{position.x:.3f}")
        self.coordinate_lock_y_var.set(f"{position.y:.3f}")
        self.coordinate_lock_z_var.set(f"{position.z:.3f}")
        self.coordinate_lock_status_var.set("Current position loaded; click Add coordinate.")

    def _on_coordinate_lock_toggle(self, lock_id: str) -> None:
        selected = next(
            (lock for lock in self.controls.get_coordinate_locks() if lock.id == lock_id),
            None,
        )
        if selected is None:
            return
        enabled = not selected.enabled
        locks = [
            replace(lock, enabled=(enabled if lock.id == lock_id else False))
            for lock in self.controls.get_coordinate_locks()
        ]
        self.controls.set_coordinate_locks(locks)
        self._save_coordinate_lock_settings()
        self._refresh_coordinate_lock_rows()

    def _on_delete_coordinate_lock(self, lock_id: str) -> None:
        locks = [
            lock for lock in self.controls.get_coordinate_locks() if lock.id != lock_id
        ]
        self.controls.set_coordinate_locks(locks)
        self._save_coordinate_lock_settings()
        self._refresh_coordinate_lock_rows()
        if self.coordinate_lock_editing_id == lock_id:
            self._clear_coordinate_lock_form()
        self.coordinate_lock_status_var.set("Coordinate deleted.")

    def _refresh_coordinate_lock_rows(self) -> None:
        selection = self.coordinate_lock_tree.selection()
        selected_id = selection[0] if selection else None
        for item_id in self.coordinate_lock_tree.get_children():
            self.coordinate_lock_tree.delete(item_id)
        for lock in self.controls.get_coordinate_locks():
            self.coordinate_lock_tree.insert(
                "",
                "end",
                iid=lock.id,
                values=(
                    "Active" if lock.enabled else "Inactive",
                    lock.name or "Unnamed coordinate",
                    coordinate_lock_target_summary(lock),
                    lock.auto_hit_target_name or "Any",
                    f"{lock.x:g}",
                    f"{lock.y:g}",
                    f"{lock.z:g}",
                    f"{lock.active_area:g}",
                ),
                tags=("active",) if lock.enabled else (),
            )
        if selected_id and self.coordinate_lock_tree.exists(selected_id):
            self.coordinate_lock_tree.selection_set(selected_id)

    def _selected_coordinate_lock_id(self) -> str | None:
        selection = self.coordinate_lock_tree.selection()
        if not selection:
            self.coordinate_lock_status_var.set("Select a coordinate first.")
            return None
        return selection[0]

    def _activate_selected_coordinate_lock(self) -> None:
        lock_id = self._selected_coordinate_lock_id()
        if lock_id is not None:
            self._on_coordinate_lock_toggle(lock_id)

    def _edit_selected_coordinate_lock(self) -> None:
        lock_id = self._selected_coordinate_lock_id()
        if lock_id is not None:
            self._on_edit_coordinate_lock(lock_id)

    def _delete_selected_coordinate_lock(self) -> None:
        lock_id = self._selected_coordinate_lock_id()
        if lock_id is not None:
            self._on_delete_coordinate_lock(lock_id)

    def _save_coordinate_lock_settings(self) -> None:
        save_coordinate_lock_settings(
            self.config_path,
            self.controls.get_coordinate_locks(),
            enabled=self.coordinate_lock_enabled_var.get(),
            auto_hit_enabled=self.coordinate_lock_auto_hit_var.get(),
            auto_hit_min_seconds=(
                self.controls.get_config().coordinate_lock_auto_hit_min_seconds
            ),
            auto_hit_max_seconds=(
                self.controls.get_config().coordinate_lock_auto_hit_max_seconds
            ),
            look_at_enabled=self.coordinate_lock_look_at_var.get(),
        )

    def _chat_trigger_by_id(self, trigger_id: str | None) -> ChatTriggerConfig | None:
        if trigger_id is None:
            return None
        for trigger in self.controls.get_chat_triggers():
            if trigger.id == trigger_id:
                return trigger
        return None

    def _load_screen_phrase_settings(self, config: BotConfig) -> None:
        self.screen_phrase_watcher.set_source(config.screen_phrase_source)
        self.screen_phrase_watcher.set_trigger_phrase(config.screen_phrase_trigger)
        if config.screen_phrase_trigger_region is not None:
            region = region_config_to_screen_region(config.screen_phrase_trigger_region)
            self.screen_phrase_watcher.set_trigger_region(region)
            self.screen_phrase_status_var.set(
                f"Trigger area loaded: {format_region(region)}"
            )
        if config.screen_phrase_result_region is not None:
            region = region_config_to_screen_region(config.screen_phrase_result_region)
            self.screen_phrase_watcher.set_result_region(region)
            self.screen_phrase_status_var.set(
                f"Result area loaded: {format_region(region)}"
            )

    def _save_screen_phrase_settings(self) -> None:
        save_screen_phrase_settings(
            self.config_path,
            trigger=self.screen_phrase_trigger_var.get().strip(),
            trigger_region=screen_region_to_config(
                self.screen_phrase_watcher.get_trigger_region()
            ),
            result_region=screen_region_to_config(
                self.screen_phrase_watcher.get_result_region()
            ),
            auto_send_result=self.screen_phrase_auto_send_var.get(),
            source=self.screen_phrase_source_var.get(),
        )

    def _select_screen_region(self, title: str) -> ScreenReadRegion | None:
        self.root.withdraw()
        self.root.update_idletasks()
        try:
            return RegionSelectionOverlay(self.root, title).select()
        finally:
            self.root.deiconify()
            self.root.lift()

    def _refresh_status(self) -> None:
        self._update_status_text()
        self.root.after(500, self._refresh_status)

    def _update_status_text(self) -> None:
        snapshot = self.controls.snapshot()
        program = "Running" if snapshot.program_enabled else "Paused"
        worker_running = self.worker.is_running()
        worker = "worker active" if worker_running else "worker stopped"
        self.status_var.set(f"{program}, {worker}")
        if not worker_running:
            self.status_label.configure(style="StoppedStatus.TLabel")
        elif not snapshot.program_enabled:
            self.status_label.configure(style="PausedStatus.TLabel")
        else:
            self.status_label.configure(style="Status.TLabel")

    def _drain_logs(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(line)
        self.root.after(200, self._drain_logs)

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{line}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def close(self) -> None:
        self.mouse4_hotkey_listener.stop()
        self.worker.stop()
        self.screen_phrase_worker.stop()
        self.coordinate_lock_worker.stop()
        self.root.after(100, self.root.destroy)


def format_region(region: ScreenReadRegion) -> str:
    return f"{region.width}x{region.height} at {region.x},{region.y}"


def screen_region_to_config(
    region: ScreenReadRegion | None,
) -> ScreenPhraseRegionConfig | None:
    if region is None:
        return None
    return ScreenPhraseRegionConfig(
        x=region.x,
        y=region.y,
        width=region.width,
        height=region.height,
    )


def region_config_to_screen_region(region: ScreenPhraseRegionConfig) -> ScreenReadRegion:
    return ScreenReadRegion(
        x=region.x,
        y=region.y,
        width=region.width,
        height=region.height,
    )


def format_debug_text(text: str) -> str:
    return " ".join(str(text).split())


def main() -> int:
    root = tk.Tk()
    HoloQuizControlPanel(root)
    root.mainloop()
    return 0
