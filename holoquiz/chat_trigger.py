from __future__ import annotations

import time
from typing import Callable, Protocol

from holoquiz.config import ChatTriggerConfig
from holoquiz.sound_player import SoundPlayer, WindowsSoundPlayer


class MacroSender(Protocol):
    def send_macro(
        self,
        macro: str,
        typing_interval_seconds: float | None = None,
    ) -> None:
        ...


class ChatTriggerRunner:
    def __init__(
        self,
        sender: MacroSender,
        clock: Callable[[], float] = time.monotonic,
        sound_player: SoundPlayer | None = None,
    ) -> None:
        self.sender = sender
        self.clock = clock
        self.sound_player = sound_player or WindowsSoundPlayer()
        self._last_triggered_at: dict[str, float] = {}

    def handle_line(
        self,
        line: str,
        triggers: tuple[ChatTriggerConfig, ...],
    ) -> None:
        now = self.clock()
        for trigger in triggers:
            if not _should_run_trigger(trigger, line):
                continue
            if self._is_in_cooldown(trigger, now):
                continue

            self._last_triggered_at[trigger.id] = now
            actions: list[str] = []
            if trigger.sound_path is not None:
                try:
                    self.sound_player.play(trigger.sound_path)
                    actions.append(f"sound: {trigger.sound_path}")
                except Exception as error:
                    print(f"[sound-warning] Could not start chat trigger sound: {error}")

            if trigger.macro.strip():
                self.sender.send_macro(
                    trigger.macro,
                    typing_interval_seconds=trigger.typing_interval_seconds,
                )
                actions.append(trigger.macro)

            print(f"[chat-trigger] {trigger.trigger_phrase} -> {' + '.join(actions)}")

    def _is_in_cooldown(self, trigger: ChatTriggerConfig, now: float) -> bool:
        last_triggered_at = self._last_triggered_at.get(trigger.id)
        if last_triggered_at is None:
            return False
        return now - last_triggered_at < trigger.cooldown_seconds


def _should_run_trigger(trigger: ChatTriggerConfig, line: str) -> bool:
    trigger_phrase = trigger.trigger_phrase.strip()
    return trigger.enabled and bool(trigger_phrase) and trigger_phrase in line
