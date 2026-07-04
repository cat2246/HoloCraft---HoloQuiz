from __future__ import annotations

import time
from typing import Any

from holoquiz.config import BotConfig


class ChatSender:
    def __init__(
        self,
        config: BotConfig,
        pyautogui_module: Any | None = None,
        clipboard_module: Any | None = None,
        sound_module: Any | None = None,
    ):
        self.config = config
        self._pyautogui = pyautogui_module
        self._clipboard = clipboard_module
        self._sound = sound_module

    def send(self, answer: str) -> None:
        clean_answer = answer.strip()
        if not clean_answer:
            return

        if self.config.dry_run:
            clipboard = self._clipboard or self._load_clipboard()
            clipboard.copy(clean_answer)
            self._play_dry_run_sound()
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

        time.sleep(self.config.send_delay_seconds)
        pyautogui.press(self.config.keyboard_open_chat_key)
        if self.config.send_mode == "type":
            pyautogui.write(clean_answer, interval=self.config.typing_interval_seconds)
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

    def _play_dry_run_sound(self) -> None:
        if not self.config.dry_run_sound_path:
            return

        try:
            sound = self._sound or self._load_sound()
            sound.PlaySound(
                str(self.config.dry_run_sound_path),
                sound.SND_FILENAME | sound.SND_ASYNC,
            )
        except Exception as exc:
            print(f"[sound-warning] Could not play dry-run sound: {exc}")

    def _load_sound(self) -> Any:
        import winsound

        return winsound
