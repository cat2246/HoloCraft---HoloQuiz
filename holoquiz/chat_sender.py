from __future__ import annotations

import time
from typing import Any

from holoquiz.config import BotConfig


class ChatSender:
    def __init__(self, config: BotConfig, pyautogui_module: Any | None = None):
        self.config = config
        self._pyautogui = pyautogui_module

    def send(self, answer: str) -> None:
        clean_answer = answer.strip()
        if not clean_answer:
            return

        if self.config.dry_run:
            print(f"[dry-run] Would send answer: {clean_answer}")
            return

        pyautogui = self._pyautogui or self._load_pyautogui()
        time.sleep(self.config.send_delay_seconds)
        pyautogui.press(self.config.keyboard_open_chat_key)
        pyautogui.write(clean_answer, interval=self.config.typing_interval_seconds)
        pyautogui.press("enter")

    def _load_pyautogui(self) -> Any:
        import pyautogui

        return pyautogui
