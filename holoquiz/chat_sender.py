from __future__ import annotations

import random
import time
from typing import Any, Callable

from holoquiz.config import BotConfig


class ChatSender:
    def __init__(
        self,
        config: BotConfig,
        config_provider: Callable[[], BotConfig] | None = None,
        pyautogui_module: Any | None = None,
        clipboard_module: Any | None = None,
        sound_module: Any | None = None,
    ):
        self.config = config
        self._config_provider = config_provider
        self._pyautogui = pyautogui_module
        self._clipboard = clipboard_module
        self._sound = sound_module

    def send(self, answer: str) -> None:
        config = self._current_config()
        clean_answer = answer.strip()
        if not clean_answer:
            return

        if config.dry_run:
            clipboard = self._clipboard or self._load_clipboard()
            clipboard.copy(clean_answer)
            self._play_dry_run_sound(config)
            print(f"[dry-run] Would send answer: {clean_answer}")
            return

        try:
            pyautogui = self._pyautogui or self._load_pyautogui()
        except ModuleNotFoundError:
            print(
                "[send-error] pyautogui is not installed. "
                "Run .\\.venv\\Scripts\\python.exe -m pip install -e \".[dev]\""
            )
            return

        time.sleep(_send_delay_seconds(config))
        pyautogui.press(config.keyboard_open_chat_key)
        if config.send_mode == "type":
            pyautogui.write(clean_answer, interval=config.typing_interval_seconds)
            mode = "type"
        else:
            clipboard = self._clipboard or self._load_clipboard()
            clipboard.copy(clean_answer)
            pyautogui.hotkey("ctrl", "v")
            mode = "paste"
        pyautogui.press("enter")
        print(f"[send] Sent answer via {mode}: {clean_answer}")

    def _load_pyautogui(self) -> Any:
        import pyautogui

        return pyautogui

    def _load_clipboard(self) -> Any:
        import pyperclip

        return pyperclip

    def _play_dry_run_sound(self, config: BotConfig) -> None:
        if not config.dry_run_sound_path:
            return

        try:
            sound = self._sound or self._load_sound()
            sound.PlaySound(
                str(config.dry_run_sound_path),
                sound.SND_FILENAME | sound.SND_ASYNC,
            )
        except Exception as exc:
            print(f"[sound-warning] Could not play dry-run sound: {exc}")

    def _load_sound(self) -> Any:
        import winsound

        return winsound

    def _current_config(self) -> BotConfig:
        if self._config_provider is None:
            return self.config
        return self._config_provider()


def _send_delay_seconds(config: BotConfig) -> float:
    min_seconds = config.send_delay_min_seconds
    max_seconds = config.send_delay_max_seconds
    if min_seconds == max_seconds:
        return min_seconds
    return random.uniform(min_seconds, max_seconds)
