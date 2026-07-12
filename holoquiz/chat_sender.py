from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from holoquiz.config import BotConfig
from holoquiz.keyboard_coordinator import (
    KeyboardInputCoordinator,
    keyboard_input_coordinator,
)


MACRO_TOKEN_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
MACRO_KEY_ALIASES = {
    "enter": "enter",
    "return": "enter",
    "esc": "escape",
    "escape": "escape",
    "space": "space",
    "tab": "tab",
    "backspace": "backspace",
    "delete": "delete",
}
MACRO_CLICK_ALIASES = {
    "lbutton": "left",
    "leftbutton": "left",
    "rbutton": "right",
    "rightbutton": "right",
    "mbutton": "middle",
    "middlebutton": "middle",
}


@dataclass(frozen=True)
class MacroTextStep:
    text: str


@dataclass(frozen=True)
class MacroKeyStep:
    key: str


@dataclass(frozen=True)
class MacroHotkeyStep:
    keys: tuple[str, ...]


@dataclass(frozen=True)
class MacroClickStep:
    button: str


MacroStep = MacroTextStep | MacroKeyStep | MacroHotkeyStep | MacroClickStep


class ChatSender:
    def __init__(
        self,
        config: BotConfig,
        config_provider: Callable[[], BotConfig] | None = None,
        pyautogui_module: Any | None = None,
        clipboard_module: Any | None = None,
        sound_module: Any | None = None,
        input_coordinator: KeyboardInputCoordinator | None = None,
    ):
        self.config = config
        self._config_provider = config_provider
        self._pyautogui = pyautogui_module
        self._clipboard = clipboard_module
        self._sound = sound_module
        self._input_coordinator = input_coordinator or keyboard_input_coordinator

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

        with self._input_coordinator.chat_session():
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

    def send_macro(
        self,
        macro: str,
        typing_interval_seconds: float | None = None,
    ) -> None:
        config = self._current_config()
        clean_macro = macro.strip()
        if not clean_macro:
            return

        if config.chat_trigger_dry_run:
            print(f"[dry-run] Would run macro: {clean_macro}")
            return

        try:
            pyautogui = self._pyautogui or self._load_pyautogui()
        except ModuleNotFoundError:
            print(
                "[send-error] pyautogui is not installed. "
                "Run .\\.venv\\Scripts\\python.exe -m pip install -e \".[dev]\""
            )
            return

        with self._input_coordinator.chat_session():
            time.sleep(_send_delay_seconds(config))
            typing_interval = (
                config.typing_interval_seconds
                if typing_interval_seconds is None
                else typing_interval_seconds
            )
            steps = parse_macro(clean_macro)
            for index, step in enumerate(steps):
                if isinstance(step, MacroTextStep):
                    pyautogui.write(step.text, interval=typing_interval)
                elif isinstance(step, MacroKeyStep):
                    pyautogui.press(step.key)
                elif isinstance(step, MacroHotkeyStep):
                    pyautogui.hotkey(*step.keys)
                elif isinstance(step, MacroClickStep):
                    pyautogui.click(button=step.button)
                if index < len(steps) - 1:
                    time.sleep(typing_interval)
        print(f"[macro] Ran macro: {clean_macro}")

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


def parse_macro(macro: str) -> list[MacroStep]:
    steps: list[MacroStep] = []
    position = 0
    for match in MACRO_TOKEN_PATTERN.finditer(macro):
        if match.start() > position:
            steps.append(MacroTextStep(macro[position : match.start()]))
        token = match.group(1).strip()
        if token:
            steps.append(_macro_token_to_step(token))
        position = match.end()

    if position < len(macro):
        steps.append(MacroTextStep(macro[position:]))
    return steps


def _macro_token_to_step(token: str) -> MacroStep:
    if "+" in token:
        return MacroHotkeyStep(
            tuple(_normalize_macro_key(part) for part in token.split("+"))
        )

    click_button = MACRO_CLICK_ALIASES.get(token.lower())
    if click_button is not None:
        return MacroClickStep(click_button)

    return MacroKeyStep(_normalize_macro_key(token))


def _normalize_macro_key(key: str) -> str:
    clean_key = key.strip()
    return MACRO_KEY_ALIASES.get(clean_key.lower(), clean_key.lower())
