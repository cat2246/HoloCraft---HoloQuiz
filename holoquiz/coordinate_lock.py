from __future__ import annotations

from dataclasses import dataclass
import ctypes
import json
import math
import queue
import threading
from typing import Any, Callable
from urllib.request import urlopen

from holoquiz.config import BotConfig, CoordinateLockConfig
from holoquiz.keyboard_coordinator import (
    KeyboardInputCoordinator,
    keyboard_input_coordinator,
)
from holoquiz.runtime import RuntimeControls


@dataclass(frozen=True)
class PlayerPosition:
    x: float
    y: float
    z: float
    heading: float = 0.0


class PlayerDataClient:
    def __init__(
        self,
        url: str = "http://localhost:8025/data/player",
        *,
        timeout_seconds: float = 0.75,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def get_position(self) -> PlayerPosition:
        with self._opener(self.url, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Player endpoint returned a non-object response.")
        return PlayerPosition(
            x=_coordinate(payload, "posX", "x"),
            y=_coordinate(payload, "posY", "y"),
            z=_coordinate(payload, "posZ", "z"),
            heading=float(payload.get("heading", payload.get("yaw", 0.0))),
        )


def _coordinate(payload: dict[str, Any], primary: str, fallback: str) -> float:
    value = payload.get(primary, payload.get(fallback))
    if value is None:
        raise ValueError(f"Player endpoint is missing {primary}.")
    return float(value)


def distance_to_lock(position: PlayerPosition, lock: CoordinateLockConfig) -> float:
    return math.sqrt(
        (lock.x - position.x) ** 2
        + (lock.y - position.y) ** 2
        + (lock.z - position.z) ** 2
    )


def nearest_enabled_lock(
    position: PlayerPosition,
    locks: tuple[CoordinateLockConfig, ...] | list[CoordinateLockConfig],
) -> tuple[CoordinateLockConfig, float] | None:
    candidates = [
        (lock, distance_to_lock(position, lock)) for lock in locks if lock.enabled
    ]
    return min(candidates, key=lambda candidate: candidate[1], default=None)


def movement_key_for_target(
    position: PlayerPosition,
    lock: CoordinateLockConfig,
) -> str | None:
    delta_x = lock.x - position.x
    delta_z = lock.z - position.z
    horizontal_distance = math.hypot(delta_x, delta_z)
    if horizontal_distance <= 0.01:
        return None

    # Minecraft yaw is expressed in degrees: 0 faces +Z and 90 faces -X.
    yaw = math.radians(position.heading)
    directions = {
        "w": (-math.sin(yaw), math.cos(yaw)),
        "s": (math.sin(yaw), -math.cos(yaw)),
        "a": (math.cos(yaw), math.sin(yaw)),
        "d": (-math.cos(yaw), -math.sin(yaw)),
    }
    target = (delta_x / horizontal_distance, delta_z / horizontal_distance)
    return max(
        directions,
        key=lambda key: directions[key][0] * target[0]
        + directions[key][1] * target[1],
    )


def minecraft_is_foreground() -> bool:
    if not hasattr(ctypes, "windll"):
        return True
    user32 = ctypes.windll.user32
    window = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(window)
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(window, title, length + 1)
    return "minecraft" in title.value.casefold()


class CoordinateLockWorker:
    def __init__(
        self,
        controls: RuntimeControls,
        log_queue: queue.Queue[str],
        *,
        player_client: PlayerDataClient | None = None,
        pyautogui_module: Any | None = None,
        foreground_provider: Callable[[], bool] = minecraft_is_foreground,
        poll_seconds: float = 0.35,
        key_hold_seconds: float = 0.18,
        input_coordinator: KeyboardInputCoordinator | None = None,
    ) -> None:
        self.controls = controls
        self.log_queue = log_queue
        self.player_client = player_client
        self._pyautogui = pyautogui_module
        self._foreground_provider = foreground_provider
        self.poll_seconds = poll_seconds
        self.key_hold_seconds = key_hold_seconds
        self._input_coordinator = input_coordinator or keyboard_input_coordinator
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_status = ""
        self._last_position: PlayerPosition | None = None
        self._stalled_checks = 0

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
            if self._should_check():
                self.check_once()
            else:
                self._last_position = None
                self._stalled_checks = 0
            self._stop_event.wait(self.poll_seconds)

    def _should_check(self) -> bool:
        config = self.controls.get_config()
        return (
            config.program_enabled
            and config.coordinate_lock_enabled
            and any(lock.enabled for lock in config.coordinate_locks)
        )

    def check_once(self) -> None:
        config = self.controls.get_config()
        try:
            position = self._client(config).get_position()
            nearest = nearest_enabled_lock(position, config.coordinate_locks)
            if nearest is None:
                return
            lock, distance = nearest
            if distance > config.coordinate_lock_max_distance:
                self._status(
                    "[coordinate-lock] Player is "
                    f"{distance:.1f} blocks from the nearest lock; movement stopped."
                )
                return
            if distance <= config.coordinate_lock_tolerance:
                self._status(
                    "[coordinate-lock] Position locked at "
                    f"{lock.x:g}, {lock.y:g}, {lock.z:g}."
                )
                self._last_position = position
                self._stalled_checks = 0
                return
            if not self._foreground_provider():
                self._status(
                    "[coordinate-lock] Waiting for Minecraft to be the active window."
                )
                return

            self._update_stall_state(position)
            self._move_toward(position, lock)
            self._last_position = position
            self._last_status = ""
        except Exception as error:
            self._status(f"[coordinate-lock-error] {error}")

    def _client(self, config: BotConfig) -> PlayerDataClient:
        if self.player_client is None or self.player_client.url != config.player_data_url:
            self.player_client = PlayerDataClient(config.player_data_url)
        return self.player_client

    def _update_stall_state(self, position: PlayerPosition) -> None:
        if self._last_position is None:
            self._stalled_checks = 0
            return
        horizontal_change = math.hypot(
            position.x - self._last_position.x,
            position.z - self._last_position.z,
        )
        if horizontal_change < 0.03:
            self._stalled_checks += 1
        else:
            self._stalled_checks = 0

    def _move_toward(
        self,
        position: PlayerPosition,
        lock: CoordinateLockConfig,
    ) -> None:
        key = movement_key_for_target(position, lock)
        should_jump = lock.y - position.y > 0.6 or self._stalled_checks >= 3
        keys = ([key] if key else []) + (["space"] if should_jump else [])
        if not keys:
            return

        with self._input_coordinator.movement_session() as movement_allowed:
            if not movement_allowed:
                return
            pyautogui = self._pyautogui or self._load_pyautogui()
            pressed_keys: list[str] = []
            try:
                for pressed_key in keys:
                    pyautogui.keyDown(pressed_key)
                    pressed_keys.append(pressed_key)
                self._stop_event.wait(self.key_hold_seconds)
            finally:
                for pressed_key in reversed(pressed_keys):
                    pyautogui.keyUp(pressed_key)

    def _load_pyautogui(self) -> Any:
        import pyautogui

        self._pyautogui = pyautogui
        return pyautogui

    def _status(self, message: str) -> None:
        if message != self._last_status:
            self.log_queue.put(message)
            self._last_status = message
