import json
import queue

from holoquiz.config import BotConfig, CoordinateLockConfig
from holoquiz.coordinate_lock import (
    AUTO_HIT_TARGET_DISTANCE,
    ContainerDataClient,
    CoordinateLockWorker,
    NearbyEntity,
    NearbyEntityClient,
    PlayerDataClient,
    PlayerPosition,
    auto_hit_delay_seconds,
    camera_angle_deltas_for_entity,
    camera_turn_pixels_for_entity,
    camera_turn_pixels_for_target,
    entity_matches_auto_hit_target,
    movement_key_for_target,
    heading_delta_for_target,
    nearest_enabled_lock,
    nearest_look_target,
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


def test_nearby_entity_client_reads_players_and_mobs_from_expected_urls():
    requests = []
    payloads = {
        "http://127.0.0.1:8026/data/players": {
            "players": [
                {
                    "distance": 4.5,
                    "name": "Alex",
                    "custom_name": "[Lv 6]Tatsunoko",
                    "position": {"x": 4.0, "y": 64.0, "z": 2.0},
                }
            ]
        },
        "http://127.0.0.1:8026/data/mobs": {
            "mobs": [
                {
                    "distance": 3.0,
                    "name": "Zombie",
                    "position": {"x": -2.0, "y": 63.0, "z": 1.0},
                }
            ]
        },
    }

    def opener(url, *, timeout):
        requests.append((url, timeout))
        return FakeResponse(payloads[url])

    client = NearbyEntityClient(opener=opener, timeout_seconds=0.25)

    assert client.get_players() == (
        NearbyEntity(
            4.5,
            "Alex",
            "[Lv 6]Tatsunoko",
            x=4.0,
            y=64.0,
            z=2.0,
        ),
    )
    assert client.get_mobs() == (
        NearbyEntity(3.0, "Zombie", None, x=-2.0, y=63.0, z=1.0),
    )
    assert requests == [
        ("http://127.0.0.1:8026/data/players", 0.25),
        ("http://127.0.0.1:8026/data/mobs", 0.25),
    ]


def test_nearby_entity_client_rejects_malformed_payloads():
    client = NearbyEntityClient(
        opener=lambda *_args, **_kwargs: FakeResponse({"players": {}})
    )

    try:
        client.get_players()
    except ValueError as error:
        assert "players list" in str(error)
    else:
        raise AssertionError("Expected malformed players payload to fail")


def test_entity_target_matching_uses_five_block_inclusive_boundary_and_exact_casefold():
    player = NearbyEntity(5.0, "Alex", " [LV 6]TATSUNOKO ")
    farther_player = NearbyEntity(5.01, "Alex", "[Lv 6]Tatsunoko")

    assert AUTO_HIT_TARGET_DISTANCE == 5.0
    assert entity_matches_auto_hit_target(
        player,
        target_name="[Lv 6]Tatsunoko",
        name_attribute="custom_name",
    ) is True
    assert entity_matches_auto_hit_target(
        player,
        target_name="Tatsunoko",
        name_attribute="custom_name",
    ) is False
    assert entity_matches_auto_hit_target(
        farther_player,
        target_name="",
        name_attribute="custom_name",
    ) is False


def test_entity_target_matching_uses_mob_name_and_rejects_missing_player_custom_name():
    entity = NearbyEntity(2.0, "Zombie", None)

    assert entity_matches_auto_hit_target(
        entity, target_name="zOmBiE", name_attribute="name"
    ) is True
    assert entity_matches_auto_hit_target(
        entity, target_name="Zombie", name_attribute="custom_name"
    ) is False
    assert entity_matches_auto_hit_target(
        entity, target_name="", name_attribute="custom_name"
    ) is True


def test_auto_hit_delay_uses_configured_range():
    requested_ranges = []
    config = BotConfig(
        coordinate_lock_auto_hit_min_seconds=0.1,
        coordinate_lock_auto_hit_max_seconds=0.5,
    )

    delay = auto_hit_delay_seconds(
        config,
        lambda minimum, maximum: requested_ranges.append((minimum, maximum)) or 0.3,
    )

    assert delay == 0.3
    assert requested_ranges == [(0.1, 0.5)]


class FakePlayerClient:
    url = "http://127.0.0.1:8026/data/player"

    def __init__(self, position):
        self.position = position

    def get_position(self):
        return self.position


class FakeContainerClient:
    def __init__(self, is_open=False):
        self.open = is_open

    def is_open(self):
        return self.open


class FakeNearbyEntityClient:
    def __init__(self, *, players=(), mobs=(), error=None):
        self.players = tuple(players)
        self.mobs = tuple(mobs)
        self.error = error
        self.calls = []

    def get_players(self):
        self.calls.append("players")
        if self.error is not None:
            raise self.error
        return self.players

    def get_mobs(self):
        self.calls.append("mobs")
        if self.error is not None:
            raise self.error
        return self.mobs


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


def test_player_data_client_reads_legacy_flat_api_shape():
    def open_player(url, timeout):
        assert url == "http://127.0.0.1:8026/data/player"
        assert timeout == 0.75
        return FakeResponse(
            {"posX": -1.25, "posY": 64, "posZ": 8.5, "heading": -2}
        )

    position = PlayerDataClient(opener=open_player).get_position()

    assert position == PlayerPosition(-1.25, 64.0, 8.5, -2.0)


def test_player_data_client_reads_nested_position_and_rotation():
    client = PlayerDataClient(
        opener=lambda *_args, **_kwargs: FakeResponse(
            {
                "position": {"x": 58.25, "y": 116, "z": -181.5},
                "rotation": {"yaw": -122.5, "pitch": 3.25},
            }
        )
    )

    assert client.get_position() == PlayerPosition(
        58.25,
        116.0,
        -181.5,
        heading=-122.5,
        pitch=3.25,
    )


def test_player_data_client_rejects_non_finite_nested_rotation():
    client = PlayerDataClient(
        opener=lambda *_args, **_kwargs: FakeResponse(
            {
                "position": {"x": 1, "y": 2, "z": 3},
                "rotation": {"yaw": 4, "pitch": "nan"},
            }
        )
    )

    try:
        client.get_position()
    except ValueError as error:
        assert "pitch" in str(error)
    else:
        raise AssertionError("Expected non-finite pitch to fail")


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


def test_nearest_look_target_filters_types_name_and_active_area():
    lock = CoordinateLockConfig(
        "farm",
        0,
        64,
        0,
        active_area=20,
        auto_hit_players=True,
        auto_hit_mobs=False,
        auto_hit_target_name="Tatsunoko",
    )
    players = (
        NearbyEntity(8, "Alex", "Other", x=8, y=64, z=0),
        NearbyEntity(6, "Alex", "tatsunoko", x=6, y=64, z=0),
        NearbyEntity(21, "Alex", "Tatsunoko", x=21, y=64, z=0),
    )
    mobs = (NearbyEntity(2, "Tatsunoko", None, x=2, y=64, z=0),)

    assert nearest_look_target(lock, players=players, mobs=mobs) == players[1]


def test_nearest_look_target_chooses_closest_when_name_is_any():
    lock = CoordinateLockConfig("farm", 0, 64, 0, active_area=20)
    players = (NearbyEntity(7, "Alex", None, x=7, y=64, z=0),)
    mobs = (NearbyEntity(3, "Zombie", None, x=3, y=64, z=0),)

    assert nearest_look_target(lock, players=players, mobs=mobs) == mobs[0]


def test_camera_angle_deltas_aim_at_target_body_center():
    position = PlayerPosition(0, 64, 0, heading=0, pitch=0)
    target = NearbyEntity(10, "Zombie", None, x=10, y=64, z=0)

    yaw_delta, pitch_delta = camera_angle_deltas_for_entity(position, target)

    assert yaw_delta == -90
    assert 4.0 < pitch_delta < 4.2


def test_camera_turn_for_entity_requires_player_pitch():
    position = PlayerPosition(0, 64, 0, heading=0, pitch=None)
    target = NearbyEntity(10, "Zombie", None, x=10, y=64, z=0)

    try:
        camera_turn_pixels_for_entity(position, target)
    except ValueError as error:
        assert "pitch" in str(error).casefold()
    else:
        raise AssertionError("Expected target tracking without pitch to fail")


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
            coordinate_lock_look_mode="lock",
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


def test_worker_tracks_closest_target_while_strafing_toward_lock():
    lock = CoordinateLockConfig("home", 10, 64, 0, active_area=20)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_look_mode="target",
            coordinate_locks=(lock,),
        )
    )
    farther = NearbyEntity(8, "Zombie", None, x=0, y=64, z=8)
    closest = NearbyEntity(4, "Zombie", None, x=0, y=64, z=4)
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(
            PlayerPosition(0, 64, 0, heading=0, pitch=0)
        ),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(mobs=(farther, closest)),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        mouse_mover=lambda x, y: keys.events.append(("move", x, y)),
        key_hold_seconds=0,
    )

    worker.check_once()

    assert ("down", "a") in keys.events
    movements = [event for event in keys.events if event[0] == "move"]
    assert sum(event[1] for event in movements) == 0
    assert sum(event[2] for event in movements) > 0


def test_worker_keeps_tracking_target_when_already_at_lock():
    lock = CoordinateLockConfig("home", 0, 64, 0, active_area=20)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_look_mode="target",
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(
            PlayerPosition(0, 64, 0, heading=0, pitch=0)
        ),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(
            mobs=(NearbyEntity(4, "Zombie", None, x=4, y=64, z=0),)
        ),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        mouse_mover=lambda x, y: keys.events.append(("move", x, y)),
        key_hold_seconds=0,
    )

    worker.check_once()

    assert not any(event[0] in {"down", "up"} for event in keys.events)
    assert any(event[0] == "move" for event in keys.events)


def test_worker_target_mode_keeps_camera_direction_without_match():
    lock = CoordinateLockConfig("east", 10, 64, 0, active_area=20)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_look_mode="target",
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(
            PlayerPosition(0, 64, 0, heading=0, pitch=0)
        ),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        mouse_mover=lambda x, y: keys.events.append(("move", x, y)),
        key_hold_seconds=0,
    )

    worker.check_once()

    assert keys.events == [("down", "a"), ("up", "a")]


def test_worker_target_api_error_logs_once_and_keeps_camera_direction():
    lock = CoordinateLockConfig("east", 10, 64, 0, active_area=20)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_look_mode="target",
            coordinate_locks=(lock,),
        )
    )
    logs = queue.Queue()
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        logs,
        player_client=FakePlayerClient(
            PlayerPosition(0, 64, 0, heading=0, pitch=0)
        ),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(error=OSError("offline")),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        mouse_mover=lambda x, y: keys.events.append(("move", x, y)),
        key_hold_seconds=0,
    )

    worker.check_once()
    worker.check_once()

    messages = []
    while not logs.empty():
        messages.append(logs.get_nowait())
    assert sum("look-target-error" in message for message in messages) == 1
    assert keys.events == [
        ("down", "a"),
        ("up", "a"),
        ("down", "a"),
        ("up", "a"),
    ]


def test_worker_missing_player_pitch_keeps_camera_direction():
    lock = CoordinateLockConfig("east", 10, 64, 0, active_area=20)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_look_mode="target",
            coordinate_locks=(lock,),
        )
    )
    logs = queue.Queue()
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        logs,
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0, heading=0)),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(
            mobs=(NearbyEntity(4, "Zombie", None, x=0, y=64, z=4),)
        ),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
        mouse_mover=lambda x, y: keys.events.append(("move", x, y)),
        key_hold_seconds=0,
    )

    worker.check_once()

    assert keys.events == [("down", "a"), ("up", "a")]
    assert "pitch" in logs.get_nowait().casefold()


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


def test_worker_stops_when_target_is_outside_its_active_area():
    lock = CoordinateLockConfig("far", 21, 64, 0, active_area=20)
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
    message = logs.get_nowait()
    assert "outside its 20-block active area" in message
    assert "movement stopped" in message


def test_worker_moves_when_target_is_inside_its_custom_active_area():
    lock = CoordinateLockConfig("far", 51, 64, 0, active_area=60)
    controls = RuntimeControls.from_config(
        BotConfig(coordinate_lock_enabled=True, coordinate_locks=(lock,))
    )
    keys = FakePyAutoGui()
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

    assert keys.events == [("down", "a"), ("up", "a")]


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


def test_worker_auto_hit_requires_a_nearby_entity_even_inside_coordinate_area():
    lock = CoordinateLockConfig("home", 0, 64, 0)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    entities = FakeNearbyEntityClient()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(49, 64, 0)),
        container_client=FakeContainerClient(),
        entity_client=entities,
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()
    assert worker._auto_hit_once() is False

    assert entities.calls == ["players", "mobs"]
    assert ("click", "left") not in keys.events


def test_worker_auto_hits_for_selected_player_custom_name():
    lock = CoordinateLockConfig(
        "home",
        0,
        64,
        0,
        auto_hit_players=True,
        auto_hit_mobs=False,
        auto_hit_target_name="[Lv 6]Tatsunoko",
    )
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    entities = FakeNearbyEntityClient(
        players=(NearbyEntity(5.0, "Alex", "[LV 6]TATSUNOKO"),)
    )
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        container_client=FakeContainerClient(),
        entity_client=entities,
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()

    assert worker._auto_hit_once() is True
    assert entities.calls == ["players"]
    assert keys.events == [("click", "left")]


def test_worker_auto_hits_for_selected_mob_name_when_both_types_are_enabled():
    lock = CoordinateLockConfig(
        "home", 0, 64, 0, auto_hit_target_name="Zombie"
    )
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    entities = FakeNearbyEntityClient(
        players=(NearbyEntity(2.0, "Alex", "Not Zombie"),),
        mobs=(NearbyEntity(4.0, "zOmBiE"),),
    )
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        container_client=FakeContainerClient(),
        entity_client=entities,
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()

    assert worker._auto_hit_once() is True
    assert entities.calls == ["players", "mobs"]
    assert keys.events == [("click", "left")]


def test_worker_fails_closed_and_deduplicates_nearby_api_errors():
    lock = CoordinateLockConfig("home", 0, 64, 0)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    logs = queue.Queue()
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        logs,
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(
            error=OSError("entity API unavailable")
        ),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()
    assert worker._auto_hit_once() is False
    assert worker._auto_hit_once() is False

    messages = []
    while not logs.empty():
        messages.append(logs.get_nowait())
    assert sum("entity API unavailable" in message for message in messages) == 1
    assert keys.events == []


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


def test_worker_rechecks_inventory_after_nearby_entity_reads():
    container = FakeContainerClient()

    class OpensContainerDuringEntityRead(FakeNearbyEntityClient):
        def get_players(self):
            players = super().get_players()
            container.open = True
            return players

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
        container_client=container,
        entity_client=OpensContainerDuringEntityRead(
            players=(NearbyEntity(2.0, "Alex", None),)
        ),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()

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
    worker._auto_hit_lock_id = "home"
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
        entity_client=FakeNearbyEntityClient(
            players=(NearbyEntity(2.0, "Alex", None),)
        ),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()
    worker._auto_hit_once()
    worker._auto_hit_once()

    assert keys.events == [("click", "left"), ("click", "left")]
