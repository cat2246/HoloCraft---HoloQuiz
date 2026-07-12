import json
import queue

from holoquiz.config import BotConfig, CoordinateLockConfig
from holoquiz.coordinate_lock import (
    CoordinateLockWorker,
    PlayerDataClient,
    PlayerPosition,
    movement_key_for_target,
    nearest_enabled_lock,
)
from holoquiz.keyboard_coordinator import KeyboardInputCoordinator
from holoquiz.runtime import RuntimeControls


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakePlayerClient:
    url = "http://localhost:8025/data/player"

    def __init__(self, position):
        self.position = position

    def get_position(self):
        return self.position


class FakePyAutoGui:
    def __init__(self):
        self.events = []

    def keyDown(self, key):
        self.events.append(("down", key))

    def keyUp(self, key):
        self.events.append(("up", key))

    def click(self, button, _pause=True):
        assert _pause is False
        self.events.append(("click", button))


def test_player_data_client_reads_local_api_shape():
    def open_player(url, timeout):
        assert url == "http://localhost:8025/data/player"
        assert timeout == 0.75
        return FakeResponse(
            {"posX": -1.25, "posY": 64, "posZ": 8.5, "heading": -2}
        )

    position = PlayerDataClient(opener=open_player).get_position()

    assert position == PlayerPosition(-1.25, 64.0, 8.5, -2.0)


def test_nearest_enabled_lock_ignores_disabled_points():
    position = PlayerPosition(0, 64, 0)
    locks = [
        CoordinateLockConfig("disabled", 1, 64, 0, enabled=False),
        CoordinateLockConfig("near", 5, 64, 0),
        CoordinateLockConfig("far", 20, 64, 0),
    ]

    lock, distance = nearest_enabled_lock(position, locks)

    assert lock.id == "near"
    assert distance == 5


def test_movement_key_uses_player_heading():
    position = PlayerPosition(0, 64, 0, heading=0)

    assert movement_key_for_target(
        position, CoordinateLockConfig("south", 0, 64, 10)
    ) == "w"
    assert movement_key_for_target(
        position, CoordinateLockConfig("east", 10, 64, 0)
    ) == "a"


def test_worker_ignores_holoquiz_dry_run_and_moves_toward_nearby_lock():
    lock = CoordinateLockConfig("home", 0, 66, 10)
    controls = RuntimeControls.from_config(
        BotConfig(
            dry_run=True,
            coordinate_lock_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0, heading=0)),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        key_hold_seconds=0,
    )

    worker.check_once()

    assert keys.events == [
        ("down", "w"),
        ("down", "space"),
        ("up", "space"),
        ("up", "w"),
    ]


def test_worker_releases_pressed_keys_when_an_input_fails():
    class FailingPyAutoGui(FakePyAutoGui):
        def keyDown(self, key):
            if key == "space":
                raise RuntimeError("input failed")
            super().keyDown(key)

    lock = CoordinateLockConfig("home", 0, 66, 10)
    controls = RuntimeControls.from_config(
        BotConfig(
            dry_run=False,
            coordinate_lock_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    keys = FailingPyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        key_hold_seconds=0,
    )

    worker.check_once()

    assert keys.events == [("down", "w"), ("up", "w")]


def test_worker_stops_when_nearest_lock_is_over_fifty_blocks_away():
    lock = CoordinateLockConfig("far", 51, 64, 0)
    controls = RuntimeControls.from_config(
        BotConfig(
            dry_run=False,
            coordinate_lock_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    logs = queue.Queue()
    worker = CoordinateLockWorker(
        controls,
        logs,
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        key_hold_seconds=0,
    )

    worker.check_once()

    assert keys.events == []
    assert "movement stopped" in logs.get_nowait()


def test_worker_waits_until_minecraft_is_foreground():
    lock = CoordinateLockConfig("home", 5, 64, 0)
    controls = RuntimeControls.from_config(
        BotConfig(
            dry_run=False,
            coordinate_lock_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    logs = queue.Queue()
    worker = CoordinateLockWorker(
        controls,
        logs,
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        pyautogui_module=keys,
        foreground_provider=lambda: False,
    )

    worker.check_once()

    assert keys.events == []
    assert "active window" in logs.get_nowait()


def test_worker_pauses_movement_while_chat_is_typing_then_resumes():
    lock = CoordinateLockConfig("home", 0, 64, 10)
    controls = RuntimeControls.from_config(
        BotConfig(
            dry_run=True,
            coordinate_lock_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    coordinator = KeyboardInputCoordinator()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        key_hold_seconds=0,
        input_coordinator=coordinator,
    )

    with coordinator.chat_session():
        worker.check_once()

    assert keys.events == []

    worker.check_once()

    assert keys.events == [("down", "w"), ("up", "w")]


def test_worker_auto_hits_within_the_enabled_coordinate_range():
    lock = CoordinateLockConfig("home", 0, 64, 0)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(49, 64, 0)),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()
    worker._auto_hit_once()

    assert keys.events == [("down", "d"), ("up", "d"), ("click", "left")]


def test_worker_does_not_auto_hit_outside_the_coordinate_range():
    lock = CoordinateLockConfig("home", 0, 64, 0)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(51, 64, 0)),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()
    worker._auto_hit_once()

    assert keys.events == []


def test_worker_does_not_auto_hit_when_coordinate_lock_is_disabled():
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(CoordinateLockConfig("home", 0, 64, 0),),
        )
    )
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()
    worker._auto_hit_once()

    assert keys.events == []


def test_auto_hit_click_loop_is_independent_from_location_polling():
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(CoordinateLockConfig("home", 0, 64, 0),),
        )
    )
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()
    worker._auto_hit_once()
    worker._auto_hit_once()

    assert keys.events == [("click", "left"), ("click", "left")]
