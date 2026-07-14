from __future__ import annotations

from dataclasses import dataclass
import ctypes
import json
import math
import queue
import random
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


class ContainerDataClient:
    def __init__(
        self,
        url: str = "http://127.0.0.1:8026/data/container",
        *,
        timeout_seconds: float = 0.75,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def is_open(self) -> bool:
        with self._opener(self.url, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Container endpoint returned a non-object response.")
        open_value = payload.get("open")
        if not isinstance(open_value, bool):
            raise ValueError("Container endpoint is missing boolean open state.")
        return open_value


AUTO_HIT_TARGET_DISTANCE = 5.0


@dataclass(frozen=True)
class NearbyEntity:
    distance: float
    name: str
    custom_name: str | None = None


class NearbyEntityClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8026/data",
        *,
        timeout_seconds: float = 0.75,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def get_players(self) -> tuple[NearbyEntity, ...]:
        return self._get_entities("players")

    def get_mobs(self) -> tuple[NearbyEntity, ...]:
        return self._get_entities("mobs")

    def _get_entities(self, collection: str) -> tuple[NearbyEntity, ...]:
        url = f"{self.base_url}/{collection}"
        with self._opener(url, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(
                f"Nearby {collection} endpoint returned a non-object response."
            )
        raw_entities = payload.get(collection)
        if not isinstance(raw_entities, list):
            raise ValueError(f"Nearby endpoint is missing the {collection} list.")

        entities: list[NearbyEntity] = []
        for raw_entity in raw_entities:
            if not isinstance(raw_entity, dict):
                raise ValueError(
                    f"Nearby {collection} list contains a non-object entity."
                )
            name = raw_entity.get("name")
            if not isinstance(name, str):
                raise ValueError(
                    f"Nearby {collection} entity is missing a string name."
                )
            try:
                distance = float(raw_entity["distance"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    f"Nearby {collection} entity has an invalid distance."
                ) from error
            if not math.isfinite(distance) or distance < 0:
                raise ValueError(
                    f"Nearby {collection} entity has an invalid distance."
                )
            custom_name = raw_entity.get("custom_name")
            if custom_name is not None and not isinstance(custom_name, str):
                raise ValueError(
                    f"Nearby {collection} entity has an invalid custom_name."
                )
            entities.append(NearbyEntity(distance, name, custom_name))
        return tuple(entities)


def entity_matches_auto_hit_target(
    entity: NearbyEntity,
    *,
    target_name: str,
    name_attribute: str,
) -> bool:
    if entity.distance > AUTO_HIT_TARGET_DISTANCE:
        return False
    normalized_target = target_name.strip().casefold()
    if not normalized_target:
        return True
    candidate = getattr(entity, name_attribute)
    return candidate is not None and candidate.strip().casefold() == normalized_target


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


def auto_hit_delay_seconds(
    config: BotConfig,
    random_uniform: Callable[[float, float], float] | None = None,
) -> float:
    choose_delay = random_uniform or random.uniform
    return choose_delay(
        config.coordinate_lock_auto_hit_min_seconds,
        config.coordinate_lock_auto_hit_max_seconds,
    )


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


def heading_delta_for_target(
    position: PlayerPosition,
    lock: CoordinateLockConfig,
) -> float:
    """Return the shortest signed yaw change needed to face a lock."""
    delta_x = lock.x - position.x
    delta_z = lock.z - position.z
    if math.hypot(delta_x, delta_z) <= 0.01:
        return 0.0
    target_heading = math.degrees(math.atan2(-delta_x, delta_z))
    return (target_heading - position.heading + 180.0) % 360.0 - 180.0


def camera_turn_pixels_for_target(
    position: PlayerPosition,
    lock: CoordinateLockConfig,
    *,
    mouse_counts_per_degree: float = 64.0,
) -> int:
    """Calculate an adaptive horizontal camera correction for a target."""
    heading_delta = heading_delta_for_target(position, lock)
    absolute_angle = abs(heading_delta)
    if absolute_angle < 0.75:
        return 0

    horizontal_distance = math.hypot(lock.x - position.x, lock.z - position.z)
    # Large heading errors need decisive turns, while small errors should be gentle.
    angle_strength = 0.22 + 0.68 * min(absolute_angle / 90.0, 1.0)
    # Direction matters increasingly as the player approaches the exact coordinate.
    distance_strength = 0.72 + 0.28 / (1.0 + horizontal_distance / 12.0)
    correction_degrees = heading_delta * angle_strength * distance_strength
    # Minecraft consumes relative mouse counts rather than degrees. Around sixty-four
    # counts per degree provides a useful turn at common in-game sensitivities;
    # heading feedback on the next tick corrects any sensitivity-specific error.
    mouse_counts = correction_degrees * mouse_counts_per_degree
    return round(max(-9600.0, min(9600.0, mouse_counts)))


def move_mouse_relative(x: int, y: int) -> None:
    """Send relative mouse input that games using raw mouse capture can receive."""
    if not hasattr(ctypes, "windll"):
        raise RuntimeError("Native relative mouse input is only available on Windows.")
    ctypes.windll.user32.mouse_event(0x0001, x, y, 0, 0)


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
        container_client: ContainerDataClient | None = None,
        entity_client: NearbyEntityClient | None = None,
        pyautogui_module: Any | None = None,
        foreground_provider: Callable[[], bool] = minecraft_is_foreground,
        mouse_mover: Callable[[int, int], None] | None = None,
        poll_seconds: float = 0.08,
        key_hold_seconds: float = 0.12,
        input_coordinator: KeyboardInputCoordinator | None = None,
    ) -> None:
        self.controls = controls
        self.log_queue = log_queue
        self.player_client = player_client
        self.container_client = container_client or ContainerDataClient()
        self.entity_client = entity_client or NearbyEntityClient()
        self._pyautogui = pyautogui_module
        self._foreground_provider = foreground_provider
        self._mouse_mover = mouse_mover
        self.poll_seconds = poll_seconds
        self.key_hold_seconds = key_hold_seconds
        self._input_coordinator = input_coordinator or keyboard_input_coordinator
        self._stop_event = threading.Event()
        self._auto_hit_in_range = threading.Event()
        self._auto_hit_lock_id: str | None = None
        self._thread: threading.Thread | None = None
        self._auto_hit_thread: threading.Thread | None = None
        self._last_status = ""
        self._last_position: PlayerPosition | None = None
        self._stalled_checks = 0
        self._mouse_counts_per_degree = 64.0
        self._last_camera_command = 0
        self._last_camera_heading: float | None = None
        self._last_auto_hit_error = ""

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._clear_auto_hit_state()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._auto_hit_thread = threading.Thread(
            target=self._run_auto_hit,
            daemon=True,
        )
        self._thread.start()
        self._auto_hit_thread.start()

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
                self._clear_auto_hit_state()
            self._stop_event.wait(self.poll_seconds)

    def _run_auto_hit(self) -> None:
        while not self._stop_event.is_set():
            if not self._auto_hit_in_range.wait(timeout=0.05):
                continue
            try:
                clicked = self._auto_hit_once()
            except Exception as error:
                self._status(f"[coordinate-lock-auto-hit-error] {error}")
                clicked = False
            delay = (
                auto_hit_delay_seconds(self.controls.get_config())
                if clicked
                else self.poll_seconds
            )
            self._stop_event.wait(delay)

    def _should_check(self) -> bool:
        config = self.controls.get_config()
        return (
            config.program_enabled
            and config.coordinate_lock_enabled
            and any(lock.enabled for lock in config.coordinate_locks)
        )

    def check_once(self) -> None:
        config = self.controls.get_config()
        if not (
            config.program_enabled
            and config.coordinate_lock_enabled
            and any(lock.enabled for lock in config.coordinate_locks)
        ):
            self._clear_auto_hit_state()
            return
        try:
            if self.container_client.is_open():
                self._clear_auto_hit_state()
                self._last_position = None
                self._stalled_checks = 0
                self._status(
                    "[coordinate-lock] Paused while an inventory or container is open."
                )
                return
            position = self._client(config).get_position()
            self._update_camera_calibration(position)
            nearest = nearest_enabled_lock(position, config.coordinate_locks)
            if nearest is None:
                self._clear_auto_hit_state()
                return
            lock, distance = nearest
            if distance > lock.active_area:
                self._clear_auto_hit_state()
                self._status(
                    f"[coordinate-lock] Player is {distance:.1f} blocks from "
                    f"{lock.name or lock.id}, outside its {lock.active_area:g}-block "
                    "active area; movement stopped."
                )
                return
            if config.coordinate_lock_auto_hit_enabled:
                self._auto_hit_lock_id = lock.id
                self._auto_hit_in_range.set()
            else:
                self._clear_auto_hit_state()
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
            self._clear_auto_hit_state()
            self._status(f"[coordinate-lock-error] {error}")

    def _clear_auto_hit_state(self) -> None:
        self._auto_hit_in_range.clear()
        self._auto_hit_lock_id = None

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

    def _update_camera_calibration(self, position: PlayerPosition) -> None:
        if self._last_camera_heading is None or not self._last_camera_command:
            return
        heading_change = (
            position.heading - self._last_camera_heading + 180.0
        ) % 360.0 - 180.0
        self._last_camera_heading = None
        command = self._last_camera_command
        self._last_camera_command = 0
        # Ignore tiny/noisy readings. Otherwise learn the real mouse-count to
        # degree ratio produced by the user's Minecraft sensitivity setting.
        if abs(heading_change) < 1.0 or command * heading_change <= 0:
            return
        observed_ratio = abs(command / heading_change)
        observed_ratio = max(1.0, min(240.0, observed_ratio))
        self._mouse_counts_per_degree = (
            self._mouse_counts_per_degree * 0.65 + observed_ratio * 0.35
        )

    def _move_toward(
        self,
        position: PlayerPosition,
        lock: CoordinateLockConfig,
    ) -> None:
        look_at_lock = self.controls.get_config().coordinate_lock_look_at_enabled
        key = "w" if look_at_lock else movement_key_for_target(position, lock)
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
                mouse_x = (
                    camera_turn_pixels_for_target(
                        position,
                        lock,
                        mouse_counts_per_degree=self._mouse_counts_per_degree,
                    )
                    if look_at_lock
                    else 0
                )
                if mouse_x:
                    self._smooth_camera_turn(mouse_x, pyautogui)
                    self._last_camera_command = mouse_x
                    self._last_camera_heading = position.heading
                else:
                    self._stop_event.wait(self.key_hold_seconds)
            finally:
                for pressed_key in reversed(pressed_keys):
                    pyautogui.keyUp(pressed_key)

    def _smooth_camera_turn(self, mouse_x: int, pyautogui: Any) -> None:
        # Ease out over several relative-input events so Minecraft receives a
        # continuous turn instead of one visible camera jump.
        step_count = max(12, min(120, math.ceil(abs(mouse_x) / 18)))
        step_seconds = self.key_hold_seconds / step_count
        previous_x = 0
        for step in range(1, step_count + 1):
            progress = step / step_count
            eased_progress = 1.0 - (1.0 - progress) ** 2
            current_x = round(mouse_x * eased_progress)
            step_x = current_x - previous_x
            if step_x:
                self._turn_camera(step_x, 0, pyautogui)
            previous_x = current_x
            if self._stop_event.wait(step_seconds):
                break

    def _turn_camera(self, x: int, y: int, pyautogui: Any) -> None:
        if self._mouse_mover is not None:
            self._mouse_mover(x, y)
        elif hasattr(ctypes, "windll"):
            move_mouse_relative(x, y)
        else:
            pyautogui.moveRel(x, y, duration=0, _pause=False)

    def _auto_hit_once(self) -> bool:
        config = self.controls.get_config()
        lock = self._active_auto_hit_lock(config)
        if not (
            self._auto_hit_in_range.is_set()
            and config.program_enabled
            and config.coordinate_lock_enabled
            and config.coordinate_lock_auto_hit_enabled
            and lock is not None
        ):
            return False
        if not self._foreground_provider():
            return False
        # Re-check at the click boundary. The location polling thread may have
        # last observed a closed container just before the inventory opened.
        try:
            if self.container_client.is_open():
                self._clear_auto_hit_state()
                return False
        except Exception as error:
            # Clicking is unsafe when the current container state is unknown.
            self._status(f"[coordinate-lock-auto-hit-container-error] {error}")
            return False
        try:
            if not self._has_auto_hit_target(lock):
                return False
        except Exception as error:
            self._auto_hit_error(error)
            return False
        with self._input_coordinator.movement_session() as input_allowed:
            if not input_allowed:
                return False
            try:
                if self.container_client.is_open():
                    self._clear_auto_hit_state()
                    return False
            except Exception as error:
                self._status(f"[coordinate-lock-auto-hit-container-error] {error}")
                return False
            pyautogui = self._pyautogui or self._load_pyautogui()
            pyautogui.click(button="left", _pause=False)
            return True

    def _active_auto_hit_lock(
        self,
        config: BotConfig,
    ) -> CoordinateLockConfig | None:
        return next(
            (
                lock
                for lock in config.coordinate_locks
                if lock.enabled and lock.id == self._auto_hit_lock_id
            ),
            None,
        )

    def _has_auto_hit_target(self, lock: CoordinateLockConfig) -> bool:
        players = self.entity_client.get_players() if lock.auto_hit_players else ()
        mobs = self.entity_client.get_mobs() if lock.auto_hit_mobs else ()
        self._last_auto_hit_error = ""
        player_match = any(
            entity_matches_auto_hit_target(
                entity,
                target_name=lock.auto_hit_target_name,
                name_attribute="custom_name",
            )
            for entity in players
        )
        mob_match = any(
            entity_matches_auto_hit_target(
                entity,
                target_name=lock.auto_hit_target_name,
                name_attribute="name",
            )
            for entity in mobs
        )
        return player_match or mob_match

    def _auto_hit_error(self, error: Exception) -> None:
        message = f"[coordinate-lock-auto-hit-target-error] {error}"
        if message != self._last_auto_hit_error:
            self.log_queue.put(message)
            self._last_auto_hit_error = message

    def _load_pyautogui(self) -> Any:
        import pyautogui

        self._pyautogui = pyautogui
        return pyautogui

    def _status(self, message: str) -> None:
        if message != self._last_status:
            self.log_queue.put(message)
            self._last_status = message
