from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from threading import Event, Thread, current_thread
from time import monotonic
from typing import Any, Callable

from holoquiz.config import AutoHealItemConfig, BotConfig
from holoquiz.coordinate_lock import ContainerDataClient, minecraft_is_foreground
from holoquiz.keyboard_coordinator import (
    KeyboardInputCoordinator,
    keyboard_input_coordinator,
)
from holoquiz.player import (
    PlayerOverviewClient,
    PlayerSnapshot,
    build_inventory_layout,
)
from holoquiz.runtime import RuntimeControls


@dataclass(frozen=True)
class AutoHealSelection:
    hotbar_slot: int
    item_name: str
    rule: AutoHealItemConfig


def auto_heal_threshold_met(
    snapshot: PlayerSnapshot,
    rule: AutoHealItemConfig,
) -> bool:
    health_triggered = False
    maximum = snapshot.health.maximum
    current = snapshot.health.current
    if (
        rule.health_percent_below > 0
        and math.isfinite(maximum)
        and maximum > 0
        and math.isfinite(current)
    ):
        health_percent = min(
            max(current / maximum * 100.0, 0.0),
            100.0,
        )
        health_triggered = health_percent < rule.health_percent_below

    hunger_percent = min(
        max(snapshot.hunger.food_level / 20.0 * 100.0, 0.0),
        100.0,
    )
    hunger_triggered = (
        rule.hunger_percent_below > 0
        and hunger_percent < rule.hunger_percent_below
    )
    return health_triggered or hunger_triggered


def find_return_hotbar_slot(
    snapshot: PlayerSnapshot,
    return_item_name: str,
) -> int | None:
    if not return_item_name:
        return None
    hotbar = build_inventory_layout(snapshot.inventory).hotbar
    for slot in reversed(hotbar):
        if not slot.item.empty and slot.item.name == return_item_name:
            return slot.inventory_slot
    return None


def select_auto_heal_item(
    snapshot: PlayerSnapshot,
    rules: Sequence[AutoHealItemConfig],
    last_used_at: Mapping[str, float],
    now: float,
) -> AutoHealSelection | None:
    by_name = {rule.name: rule for rule in rules}
    hotbar = build_inventory_layout(snapshot.inventory).hotbar
    for slot in reversed(hotbar):
        if slot.item.empty:
            continue
        rule = by_name.get(slot.item.name)
        if rule is None or not auto_heal_threshold_met(snapshot, rule):
            continue
        previous = last_used_at.get(rule.name)
        if previous is not None and now - previous < rule.cooldown_seconds:
            continue
        return AutoHealSelection(
            hotbar_slot=slot.inventory_slot,
            item_name=slot.item.name,
            rule=rule,
        )
    return None


class AutoHealWorker:
    def __init__(
        self,
        controls: RuntimeControls,
        status: Callable[[str], None],
        *,
        player_client: PlayerOverviewClient | None = None,
        container_client: ContainerDataClient | None = None,
        pyautogui_module: Any | None = None,
        foreground_provider: Callable[[], bool] = minecraft_is_foreground,
        input_coordinator: KeyboardInputCoordinator | None = None,
        poll_seconds: float = 0.25,
        clock: Callable[[], float] = monotonic,
        waiter: Callable[[float], bool] | None = None,
    ) -> None:
        self.controls = controls
        self._status_sink = status
        player_url = controls.get_config().player_data_url
        container_url = f"{player_url.rsplit('/', 1)[0]}/container"
        self.player_client = player_client or PlayerOverviewClient(player_url)
        self.container_client = container_client or ContainerDataClient(
            container_url
        )
        self._pyautogui = pyautogui_module
        self._foreground_provider = foreground_provider
        self._input_coordinator = input_coordinator or keyboard_input_coordinator
        self.poll_seconds = poll_seconds
        self._clock = clock
        self._stop_event = Event()
        self._waiter = waiter or self._stop_event.wait
        self._thread: Thread | None = None
        self._last_used_at: dict[str, float] = {}
        self._last_status = ""

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run,
            daemon=True,
            name="auto-heal",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.check_once()
            except Exception as error:
                self._status(f"[auto-heal-error] {error}")
            self._stop_event.wait(self.poll_seconds)

    def _client(self, config: BotConfig) -> PlayerOverviewClient:
        if self.player_client.url != config.player_data_url:
            self.player_client = PlayerOverviewClient(config.player_data_url)
        return self.player_client

    def check_once(self) -> bool:
        if self._stop_event.is_set():
            return False
        config = self.controls.get_config()
        if not (
            config.program_enabled
            and config.auto_heal_enabled
            and config.auto_heal_items
        ):
            return False
        snapshot = self._client(config).fetch()
        if (
            self._stop_event.is_set()
            or not snapshot.connected
            or not self._environment_is_safe()
            or self._stop_event.is_set()
        ):
            return False
        selection = select_auto_heal_item(
            snapshot,
            config.auto_heal_items,
            self._last_used_at,
            self._clock(),
        )
        if selection is None:
            return False
        return self._use(selection)

    def _environment_is_safe(self) -> bool:
        return (
            self._foreground_provider()
            and not self.container_client.is_open()
        )

    def _use(self, selection: AutoHealSelection) -> bool:
        if self._stop_event.is_set() or not self._environment_is_safe():
            return False
        with self._input_coordinator.item_use_session() as allowed:
            if not allowed or self._stop_event.is_set():
                return False
            pyautogui = self._pyautogui or self._load_pyautogui()
            pyautogui.press(str(selection.hotbar_slot + 1))
            right_press_attempted = False
            interrupted = False
            try:
                right_press_attempted = True
                pyautogui.mouseDown(button="right")
                interrupted = self._waiter(
                    selection.rule.use_duration_seconds
                )
            finally:
                if right_press_attempted:
                    pyautogui.mouseUp(button="right")
            if interrupted:
                return False
            self._last_used_at[selection.item_name] = self._clock()
            self._last_status = ""
            self._status_sink(
                f"[auto-heal] Used {selection.item_name} from hotbar "
                f"slot {selection.hotbar_slot + 1}."
            )
            return True

    def _load_pyautogui(self) -> Any:
        import pyautogui

        self._pyautogui = pyautogui
        return pyautogui

    def _status(self, message: str) -> None:
        if message == self._last_status:
            return
        self._last_status = message
        self._status_sink(message)
