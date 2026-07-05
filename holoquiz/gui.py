from __future__ import annotations

from collections import deque
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable
from urllib.parse import quote_plus
import webbrowser

from holoquiz.config import (
    BotConfig,
    ScreenPhraseRegionConfig,
    load_config,
    save_screen_phrase_settings,
)
from holoquiz.log_tailer import LogTailer
from holoquiz.minecraft_text_ocr import read_minecraft_text
from holoquiz.runner import build_bot, drain_answer_reveals
from holoquiz.runtime import RuntimeControls, SCREEN_PHRASE_WATCHER_FUNCTION
from holoquiz.screen_phrase_watcher import ScreenPhraseWatcher, ScreenReadRegion


GOOGLE_SEARCH_URL = "https://www.google.com/search?q="
BROWSER_SEARCH_STATUS_MAX_CHARS = 58
BLANK_MARKER_PATTERN = re.compile(r"(?<!\w)(?:-{4,}|\?{4,}|_{4,})(?!\w)")


@dataclass(frozen=True)
class ControlResult:
    ok: bool
    message: str = ""


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


class ScreenPhraseWorker:
    def __init__(
        self,
        controls: RuntimeControls,
        watcher: ScreenPhraseWatcher,
        log_queue: queue.Queue[str],
        poll_seconds: float = 1.0,
        debug_enabled_provider: Callable[[], bool] | None = None,
    ) -> None:
        self.controls = controls
        self.watcher = watcher
        self.log_queue = log_queue
        self.poll_seconds = poll_seconds
        self._debug_enabled_provider = debug_enabled_provider or (lambda: False)
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
            message = (
                "[screen-phrase-watcher-error] "
                f"{error}. Install Tesseract OCR and keep Minecraft visible."
            )
            if message != self._last_error:
                self.log_queue.put(message)
                self._last_error = message
            return

        self._last_error = ""
        if self._debug_enabled_provider():
            self._log_debug_result(result)

        event = result.event
        if event is not None:
            self.log_queue.put(
                "[screen-phrase-watcher] "
                f'Trigger "{event.trigger_phrase}" found; '
                f"result area read: {event.result_text}"
            )

    def _log_debug_result(self, result: object) -> None:
        trigger_region = getattr(result, "trigger_region", None)
        result_region = getattr(result, "result_region", None)
        lines = [
            "[screen-phrase-watcher-debug] "
            f"trigger area: {format_region(trigger_region) if trigger_region else 'not set'}; "
            f"result area: {format_region(result_region) if result_region else 'not set'}",
            "[screen-phrase-watcher-debug] "
            f'trigger phrase: "{format_debug_text(getattr(result, "trigger_phrase", ""))}"',
            "[screen-phrase-watcher-debug] "
            f'trigger OCR: "{format_debug_text(getattr(result, "trigger_text", ""))}"',
            "[screen-phrase-watcher-debug] "
            f"trigger match: {'yes' if getattr(result, 'trigger_matched', False) else 'no'}",
        ]
        result_text = getattr(result, "result_text", "")
        if result_text:
            lines.append(
                "[screen-phrase-watcher-debug] "
                f'result OCR: "{format_debug_text(result_text)}"'
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
        self.controller = ControlPanelController(self.controls)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker = BotWorker(config_path, self.controls, self.log_queue)
        self.screen_phrase_watcher = ScreenPhraseWatcher(OcrScreenTextReader())

        self.root.title("HoloQuiz Control Panel")
        self.root.geometry("820x620")
        self.root.minsize(680, 520)

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
        self.screen_phrase_debug_var = tk.BooleanVar(value=False)
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
        )

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.worker.start()
        self.screen_phrase_worker.start()
        self._refresh_status()
        self._drain_logs()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        status_row = ttk.Frame(outer)
        status_row.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        status_row.columnconfigure(1, weight=1)
        ttk.Label(status_row, text="Status:").grid(row=0, column=0, sticky="w")
        ttk.Label(status_row, textvariable=self.status_var).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(6, 0),
        )

        controls_row = ttk.Frame(outer)
        controls_row.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        controls_row.columnconfigure(2, weight=1)
        ttk.Checkbutton(
            controls_row,
            text="Whole program",
            variable=self.program_var,
            command=self._on_program_toggle,
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))
        ttk.Checkbutton(
            controls_row,
            text="Dry-run",
            variable=self.dry_run_var,
            command=self._on_dry_run_toggle,
        ).grid(row=0, column=1, sticky="w", padx=(0, 16))

        delay_row = ttk.Frame(outer)
        delay_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
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

        function_frame = ttk.LabelFrame(outer, text="Functions", padding=10)
        function_frame.grid(row=3, column=0, sticky="new", pady=(0, 10))
        function_frame.columnconfigure(0, weight=0)
        function_frame.columnconfigure(1, weight=1)
        for row, function in enumerate(self.controls.registry.all()):
            enabled = self.controls.is_function_enabled(function.key)
            variable = tk.BooleanVar(value=enabled)
            self.function_vars[function.key] = variable
            if function.key == SCREEN_PHRASE_WATCHER_FUNCTION:
                row_frame = ttk.Frame(function_frame)
                row_frame.grid(row=row, column=0, columnspan=2, sticky="w")
                ttk.Checkbutton(
                    row_frame,
                    text=function.label,
                    variable=variable,
                    command=lambda key=function.key: self._on_function_toggle(key),
                ).grid(row=0, column=0, sticky="w")
                ttk.Checkbutton(
                    row_frame,
                    text="Debug OCR log",
                    variable=self.screen_phrase_debug_var,
                ).grid(row=0, column=1, sticky="w", padx=(12, 0))
            else:
                ttk.Checkbutton(
                    function_frame,
                    text=function.label,
                    variable=variable,
                    command=lambda key=function.key: self._on_function_toggle(key),
                ).grid(row=row, column=0, columnspan=2, sticky="w")
        browser_row = len(self.controls.registry.all())
        ttk.Button(
            function_frame,
            text="Browser search",
            command=self._on_browser_search,
        ).grid(row=browser_row, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            function_frame,
            textvariable=self.browser_search_status_var,
            width=BROWSER_SEARCH_STATUS_MAX_CHARS,
        ).grid(row=browser_row, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        screen_phrase_row = browser_row + 1
        screen_phrase_frame = ttk.Frame(function_frame)
        screen_phrase_frame.grid(
            row=screen_phrase_row,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(10, 0),
        )
        screen_phrase_frame.columnconfigure(2, weight=1)
        ttk.Button(
            screen_phrase_frame,
            text="Set trigger area",
            command=self._on_set_screen_phrase_trigger_area,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(screen_phrase_frame, text="Trigger phrase").grid(
            row=0,
            column=1,
            sticky="w",
            padx=(8, 4),
        )
        ttk.Entry(
            screen_phrase_frame,
            textvariable=self.screen_phrase_trigger_var,
            width=34,
        ).grid(row=0, column=2, sticky="ew")
        ttk.Button(
            screen_phrase_frame,
            text="Set result area",
            command=self._on_set_screen_phrase_result_area,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(
            screen_phrase_frame,
            textvariable=self.screen_phrase_status_var,
        ).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(6, 0))

        log_frame = ttk.LabelFrame(outer, text="Log", padding=8)
        log_frame.grid(row=4, column=0, sticky="nsew")
        outer.rowconfigure(4, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            log_frame,
            orient="vertical",
            command=self.log_text.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

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

    def _load_screen_phrase_settings(self, config: BotConfig) -> None:
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
        worker = "worker active" if self.worker.is_running() else "worker stopped"
        self.status_var.set(f"{program}, {worker}")

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

    def close(self) -> None:
        self.worker.stop()
        self.screen_phrase_worker.stop()
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
