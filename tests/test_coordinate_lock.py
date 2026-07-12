import json
import queue

from holoquiz.config import BotConfig, CoordinateLockConfig
from holoquiz.coordinate_lock import (
    ContainerDataClient,
    CoordinateLockWorker,
    PlayerDataClient,
    PlayerPosition,
    camera_turn_pixels_for_target,
    movement_key_for_target,
    heading_delta_for_target,
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


class FakeContainerClient:
    def __init__(self, is_open=False):
        self.open = is_open

    def is_open(self):
        return self.open


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

    def moveRel(self, x, y, duration=0, _pause=True):
        assert duration == 0
        assert _pause is False
        self.events.append(("move", x, y))


def test_player_data_client_reads_local_api_shape():
    def open_player(url, timeout):
        assert url == "http://localhost:8025/data/player"
        assert timeout == 0.75
        return FakeResponse(
            {"posX": -1.25, "posY": 64, "posZ": 8.5, "heading": -2}
        )

    position = PlayerDataClient(opener=open_player).get_position()

    assert position == PlayerPosition(-1.25, 64.0, 8.5, -2.0)


def test_container_data_client_reads_local_api_shape():
    def open_container(url, timeout):
        assert url == "http://127.0.0.1:8026/data/container"
        assert timeout == 0.75
        return FakeResponse({"api_version": 1, "open": True})

    assert ContainerDataClient(opener=open_container).is_open() is True


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


def test_heading_delta_uses_shortest_turn_toward_target():
    lock = CoordinateLockConfig("west", -10, 64, 0)

    assert heading_delta_for_target(PlayerPosition(0, 64, 0, heading=170), lock) == -80


def test_camera_turn_adapts_to_angle_and_distance():
    east = CoordinateLockConfig("east", 10, 64, 0)
    slight = abs(camera_turn_pixels_for_target(
        PlayerPosition(0, 64, 0, heading=-80), east
    ))
    large = abs(camera_turn_pixels_for_target(
        PlayerPosition(0, 64, 0, heading=0), east
    ))
    close = abs(camera_turn_pixels_for_target(
        PlayerPosition(9, 64, 0, heading=-80), east
    ))

    assert large > slight
    assert large > 400
    assert close > slight
    assert camera_turn_pixels_for_target(
        PlayerPosition(0, 64, 0, heading=-90), east
    ) == 0
    calibrated = abs(camera_turn_pixels_for_target(
        PlayerPosition(0, 64, 0, heading=-80),
        east,
        mouse_counts_per_degree=128,
    ))
    assert abs(calibrated - slight * 2) <= 1


def test_worker_learns_mouse_sensitivity_from_heading_feedback():
    controls = RuntimeControls.from_config(BotConfig())
    worker = CoordinateLockWorker(controls, queue.Queue())
    worker._last_camera_command = 400
    worker._last_camera_heading = 0

    worker._update_camera_calibration(PlayerPosition(0, 64, 0, heading=20))

    assert 16 < worker._mouse_counts_per_degree < 64


def test_worker_looks_at_lock_and_moves_forward_when_enabled():
    lock = CoordinateLockConfig("east", 10, 64, 0)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_look_at_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0, heading=0)),
        container_client=FakeContainerClient(),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        mouse_mover=lambda x, y: keys.events.append(("move", x, y)),
        key_hold_seconds=0,
    )

    worker.check_once()

    assert keys.events[0] == ("down", "w")
    assert keys.events[-1] == ("up", "w")
    movements = [event for event in keys.events if event[0] == "move"]
    assert len(movements) > 4
    assert sum(event[1] for event in movements) == camera_turn_pixels_for_target(
        PlayerPosition(0, 64, 0, heading=0), lock
    )


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
        container_client=FakeContainerClient(),
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
        container_client=FakeContainerClient(),
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
        container_client=FakeContainerClient(),
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
        container_client=FakeContainerClient(),
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
        container_client=FakeContainerClient(),
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


def test_worker_pauses_while_inventory_is_open_then_resumes():
    lock = CoordinateLockConfig("home", 0, 64, 10)
    controls = RuntimeControls.from_config(
        BotConfig(coordinate_lock_enabled=True, coordinate_locks=(lock,))
    )
    keys = FakePyAutoGui()
    container = FakeContainerClient(is_open=True)
    logs = queue.Queue()
    worker = CoordinateLockWorker(
        controls,
        logs,
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        container_client=container,
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        key_hold_seconds=0,
    )

    worker.check_once()

    assert keys.events == []
    assert "inventory or container is open" in logs.get_nowait()

    container.open = False
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
        container_client=FakeContainerClient(),
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
        container_client=FakeContainerClient(),
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
        container_client=FakeContainerClient(),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()
    worker._auto_hit_once()

    assert keys.events == []


def test_worker_rechecks_inventory_immediately_before_auto_hit():
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(CoordinateLockConfig("home", 0, 64, 0),),
        )
    )
    keys = FakePyAutoGui()
    container = FakeContainerClient()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        container_client=container,
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()
    container.open = True

    assert worker._auto_hit_once() is False
    assert keys.events == []


def test_worker_skips_auto_hit_when_inventory_check_fails():
    class FailingContainerClient:
        def is_open(self):
            raise OSError("container API unavailable")

    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(CoordinateLockConfig("home", 0, 64, 0),),
        )
    )
    keys = FakePyAutoGui()
    logs = queue.Queue()
    worker = CoordinateLockWorker(
        controls,
        logs,
        container_client=FailingContainerClient(),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )
    worker._auto_hit_in_range.set()

    assert worker._auto_hit_once() is False
    assert keys.events == []
    assert "container API unavailable" in logs.get_nowait()


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
        container_client=FakeContainerClient(),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()
    worker._auto_hit_once()
    worker._auto_hit_once()

    assert keys.events == [("click", "left"), ("click", "left")]
