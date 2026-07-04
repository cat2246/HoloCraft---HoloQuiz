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
from typing import Callable
from urllib.parse import quote_plus
import webbrowser

from holoquiz.config import load_config
from holoquiz.log_tailer import LogTailer
from holoquiz.runner import build_bot, drain_answer_reveals
from holoquiz.runtime import RuntimeControls


GOOGLE_SEARCH_URL = "https://www.google.com/search?q="
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
        return ControlResult(True, f"Browser search opened: {query}")


def build_browser_search_query(question: str) -> str:
    query = BLANK_MARKER_PATTERN.sub(" ", question)
    query = re.sub(r"(?i)\bfor some reason\b,?", " ", query)
    query = re.sub(r"(?i)\btrivia\b:?", " ", query)
    query = re.sub(r"[’']s\b", "", query)
    query = re.sub(r"[^\w\s]+", " ", query, flags=re.UNICODE)
    return " ".join(query.split())


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


class HoloQuizControlPanel:
    def __init__(self, root: tk.Tk, config_path: Path = Path("config.json")) -> None:
        self.root = root
        self.config_path = config_path
        config = load_config(config_path)
        self.controls = RuntimeControls.from_config(config)
        self.controller = ControlPanelController(self.controls)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker = BotWorker(config_path, self.controls, self.log_queue)

        self.root.title("HoloQuiz Control Panel")
        self.root.geometry("720x520")
        self.root.minsize(560, 420)

        snapshot = self.controls.snapshot()
        self.program_var = tk.BooleanVar(value=snapshot.program_enabled)
        self.dry_run_var = tk.BooleanVar(value=snapshot.dry_run)
        self.delay_min_var = tk.StringVar(value=f"{snapshot.send_delay_min_seconds:g}")
        self.delay_max_var = tk.StringVar(value=f"{snapshot.send_delay_max_seconds:g}")
        self.status_var = tk.StringVar(value="Starting")
        self.delay_status_var = tk.StringVar(value="")
        self.browser_search_status_var = tk.StringVar(value="")
        self.function_vars: dict[str, tk.BooleanVar] = {}

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.worker.start()
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
        function_frame.columnconfigure(0, weight=1)
        function_frame.columnconfigure(1, weight=1)
        for row, function in enumerate(self.controls.registry.all()):
            enabled = self.controls.is_function_enabled(function.key)
            variable = tk.BooleanVar(value=enabled)
            self.function_vars[function.key] = variable
            ttk.Checkbutton(
                function_frame,
                text=function.label,
                variable=variable,
                command=lambda key=function.key: self._on_function_toggle(key),
            ).grid(row=row, column=0, sticky="w")
        browser_row = len(self.controls.registry.all())
        ttk.Button(
            function_frame,
            text="Browser search",
            command=self._on_browser_search,
        ).grid(row=browser_row, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            function_frame,
            textvariable=self.browser_search_status_var,
        ).grid(row=browser_row, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

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
        self.root.after(100, self.root.destroy)


def main() -> int:
    root = tk.Tk()
    HoloQuizControlPanel(root)
    root.mainloop()
    return 0
