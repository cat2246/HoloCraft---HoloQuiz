from contextlib import contextmanager
import threading

import pytest

from holoquiz.auto_heal import (
    AutoHealWorker,
    auto_heal_threshold_met,
    find_return_hotbar_slot,
    select_auto_heal_item,
)
from holoquiz.config import AutoHealItemConfig, BotConfig
from holoquiz.player import parse_player_payload
from holoquiz.runtime import RuntimeControls


def player_snapshot(
    *,
    health,
    hunger,
    maximum_health=20,
    hotbar=None,
    main=None,
    connected=True,
):
    inventory = []
    for slot, name in (hotbar or {}).items():
        inventory.append(
            {
                "inventory_slot": slot,
                "section": "hotbar",
                "item": {
                    "empty": False,
                    "id": "minecraft:test_item",
                    "name": name,
                    "count": 1,
                },
            }
        )
    for slot, name in (main or {}).items():
        inventory.append(
            {
                "inventory_slot": slot,
                "section": "main",
                "item": {
                    "empty": False,
                    "id": "minecraft:test_item",
                    "name": name,
                    "count": 1,
                },
            }
        )
    return parse_player_payload(
        {
            "api_version": 1,
            "timestamp_ms": 1,
            "connected": connected,
            "health": {
                "current": health,
                "max": maximum_health,
                "absorption": 0,
            },
            "hunger": {"food_level": hunger, "saturation": 0},
            "inventory": inventory,
        }
    )


def test_select_auto_heal_item_prioritizes_rightmost_hotbar_match():
    snapshot = player_snapshot(
        health=5,
        hunger=20,
        hotbar={7: "Steak", 8: "Potion"},
    )
    rules = (
        AutoHealItemConfig("Steak", 5, 2, 50, 0),
        AutoHealItemConfig("Potion", 5, 2, 50, 0),
    )

    selection = select_auto_heal_item(snapshot, rules, {}, now=100.0)

    assert selection is not None
    assert selection.hotbar_slot == 8
    assert selection.item_name == "Potion"


def test_select_auto_heal_item_skips_rightmost_item_on_cooldown():
    snapshot = player_snapshot(
        health=5,
        hunger=20,
        hotbar={7: "Steak", 8: "Potion"},
    )
    rules = (
        AutoHealItemConfig("Steak", 5, 2, 50, 0),
        AutoHealItemConfig("Potion", 30, 2, 50, 0),
    )

    selection = select_auto_heal_item(
        snapshot,
        rules,
        {"Potion": 90.0},
        now=100.0,
    )

    assert selection is not None
    assert selection.item_name == "Steak"


def test_health_percentage_is_strict_and_uses_maximum_health():
    rule = AutoHealItemConfig("Steak", 0, 2, 50, 0)

    assert auto_heal_threshold_met(
        player_snapshot(health=9.9, maximum_health=20, hunger=20),
        rule,
    )
    assert not auto_heal_threshold_met(
        player_snapshot(health=10, maximum_health=20, hunger=20),
        rule,
    )


def test_hunger_percentage_is_strict_and_clamped():
    rule = AutoHealItemConfig("Steak", 0, 2, 0, 50)

    assert auto_heal_threshold_met(player_snapshot(health=20, hunger=9), rule)
    assert not auto_heal_threshold_met(
        player_snapshot(health=20, hunger=10), rule
    )
    assert auto_heal_threshold_met(player_snapshot(health=20, hunger=-5), rule)
    assert not auto_heal_threshold_met(
        player_snapshot(health=20, hunger=25), rule
    )


@pytest.mark.parametrize("maximum", [0, -1, float("nan"), float("inf")])
def test_invalid_maximum_health_disables_only_health_condition(maximum):
    health_only = AutoHealItemConfig("Potion", 0, 2, 50, 0)
    hunger_fallback = AutoHealItemConfig("Potion", 0, 2, 50, 50)
    snapshot = player_snapshot(
        health=0,
        maximum_health=maximum,
        hunger=5,
    )

    assert not auto_heal_threshold_met(snapshot, health_only)
    assert auto_heal_threshold_met(snapshot, hunger_fallback)


def test_return_item_resolver_uses_rightmost_exact_hotbar_name():
    snapshot = player_snapshot(
        health=20,
        hunger=20,
        hotbar={0: "Sword", 5: "Sword", 8: "sword"},
    )

    assert find_return_hotbar_slot(snapshot, "Sword") == 5


def test_return_item_resolver_ignores_empty_name_and_main_inventory():
    snapshot = player_snapshot(
        health=20,
        hunger=20,
        hotbar={0: "Sword"},
        main={20: "Main Sword"},
    )

    assert find_return_hotbar_slot(snapshot, "") is None
    assert find_return_hotbar_slot(snapshot, "Main Sword") is None
    assert find_return_hotbar_slot(snapshot, "Missing") is None


def test_select_auto_heal_item_matches_exact_name_only():
    snapshot = player_snapshot(
        health=1,
        hunger=20,
        hotbar={8: "steak"},
    )
    rules = (AutoHealItemConfig("Steak", 0, 2, 10, 0),)

    assert select_auto_heal_item(snapshot, rules, {}, now=0) is None


def test_select_auto_heal_item_ignores_configured_match_outside_hotbar():
    snapshot = player_snapshot(
        health=1,
        hunger=20,
        main={35: "Steak"},
    )
    rules = (AutoHealItemConfig("Steak", 0, 2, 10, 0),)

    assert select_auto_heal_item(snapshot, rules, {}, now=0) is None


def test_select_auto_heal_item_skips_rule_without_crossed_threshold():
    snapshot = player_snapshot(
        health=4,
        hunger=20,
        hotbar={7: "Steak", 8: "Potion"},
    )
    rules = (
        AutoHealItemConfig("Steak", 0, 2, 21, 0),
        AutoHealItemConfig("Potion", 0, 2, 10, 0),
    )

    selection = select_auto_heal_item(snapshot, rules, {}, now=0)

    assert selection is not None
    assert selection.item_name == "Steak"


class FakeInput:
    def __init__(self):
        self.events = []

    def press(self, key):
        self.events.append(("press", key))

    def mouseDown(self, *, button):
        self.events.append(("mouseDown", button))

    def mouseUp(self, *, button):
        self.events.append(("mouseUp", button))


class FakePlayerClient:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.url = "http://127.0.0.1:8026/data/player"
        self.fetch_count = 0

    def fetch(self):
        self.fetch_count += 1
        return self.snapshot


class FakeContainerClient:
    def __init__(self, is_open=False):
        self.open = is_open

    def is_open(self):
        return self.open


class BlockingPlayerClient(FakePlayerClient):
    def __init__(self, snapshot):
        super().__init__(snapshot)
        self.fetch_started = threading.Event()
        self.release_fetch = threading.Event()

    def fetch(self):
        self.fetch_started.set()
        self.release_fetch.wait()
        return super().fetch()


class DeniedInputCoordinator:
    @contextmanager
    def item_use_session(self):
        yield False


def auto_heal_worker(
    *,
    snapshot,
    rule=None,
    backend=None,
    foreground=True,
    container_open=False,
    clock=lambda: 100.0,
    wait_error=None,
    interrupted=False,
    input_coordinator=None,
):
    configured_rule = rule or AutoHealItemConfig(
        "Potion",
        30,
        2,
        50,
        0,
    )
    controls = RuntimeControls.from_config(
        BotConfig(
            program_enabled=True,
            auto_heal_enabled=True,
            auto_heal_items=(configured_rule,),
        )
    )
    input_backend = backend or FakeInput()

    def waiter(seconds):
        input_backend.events.append(("wait", seconds))
        if wait_error is not None:
            raise wait_error
        return interrupted

    return AutoHealWorker(
        controls,
        lambda _message: None,
        player_client=FakePlayerClient(snapshot),
        container_client=FakeContainerClient(container_open),
        pyautogui_module=input_backend,
        foreground_provider=lambda: foreground,
        input_coordinator=input_coordinator,
        clock=clock,
        waiter=waiter,
    )


def test_worker_uses_selected_hotbar_item_for_configured_duration():
    backend = FakeInput()
    worker = auto_heal_worker(
        snapshot=player_snapshot(
            health=5,
            hunger=20,
            hotbar={8: "Potion"},
        ),
        rule=AutoHealItemConfig("Potion", 30, 2.5, 50, 0),
        backend=backend,
        clock=lambda: 100.0,
    )

    assert worker.check_once() is True
    assert backend.events == [
        ("press", "9"),
        ("mouseDown", "right"),
        ("wait", 2.5),
        ("mouseUp", "right"),
    ]
    assert worker._last_used_at == {"Potion": 100.0}


@pytest.mark.parametrize(
    "foreground,container_open",
    [(False, False), (True, True)],
)
def test_worker_does_not_inject_when_environment_is_unsafe(
    foreground,
    container_open,
):
    backend = FakeInput()
    worker = auto_heal_worker(
        snapshot=player_snapshot(
            health=1,
            hunger=20,
            hotbar={8: "Potion"},
        ),
        backend=backend,
        foreground=foreground,
        container_open=container_open,
    )

    assert worker.check_once() is False
    assert backend.events == []


def test_worker_releases_right_button_when_wait_raises():
    backend = FakeInput()
    worker = auto_heal_worker(
        snapshot=player_snapshot(
            health=1,
            hunger=20,
            hotbar={8: "Potion"},
        ),
        backend=backend,
        wait_error=RuntimeError("stopped"),
    )

    with pytest.raises(RuntimeError, match="stopped"):
        worker.check_once()

    assert backend.events[-1] == ("mouseUp", "right")
    assert worker._last_used_at == {}


def test_worker_interruption_releases_button_without_starting_cooldown():
    backend = FakeInput()
    worker = auto_heal_worker(
        snapshot=player_snapshot(
            health=1,
            hunger=20,
            hotbar={8: "Potion"},
        ),
        backend=backend,
        interrupted=True,
    )

    assert worker.check_once() is False
    assert backend.events[-1] == ("mouseUp", "right")
    assert worker._last_used_at == {}


def test_worker_disabled_gate_avoids_player_fetch():
    snapshot = player_snapshot(
        health=1,
        hunger=20,
        hotbar={8: "Potion"},
    )
    client = FakePlayerClient(snapshot)
    worker = AutoHealWorker(
        RuntimeControls.from_config(BotConfig(auto_heal_enabled=False)),
        lambda _message: None,
        player_client=client,
    )

    assert worker.check_once() is False
    assert client.fetch_count == 0


def test_worker_skips_disconnected_snapshot_and_denied_input_session():
    disconnected_backend = FakeInput()
    disconnected = auto_heal_worker(
        snapshot=player_snapshot(
            health=1,
            hunger=20,
            hotbar={8: "Potion"},
            connected=False,
        ),
        backend=disconnected_backend,
    )
    denied_backend = FakeInput()
    denied = auto_heal_worker(
        snapshot=player_snapshot(
            health=1,
            hunger=20,
            hotbar={8: "Potion"},
        ),
        backend=denied_backend,
        input_coordinator=DeniedInputCoordinator(),
    )

    assert disconnected.check_once() is False
    assert denied.check_once() is False
    assert disconnected_backend.events == []
    assert denied_backend.events == []


def test_worker_records_cooldown_after_completed_use():
    times = iter((100.0, 102.5))
    worker = auto_heal_worker(
        snapshot=player_snapshot(
            health=1,
            hunger=20,
            hotbar={8: "Potion"},
        ),
        clock=lambda: next(times),
    )

    assert worker.check_once() is True
    assert worker._last_used_at == {"Potion": 102.5}


def test_worker_start_and_stop_are_idempotent():
    worker = AutoHealWorker(
        RuntimeControls.from_config(BotConfig(auto_heal_enabled=False)),
        lambda _message: None,
        poll_seconds=0.01,
    )

    worker.start()
    first_thread = worker._thread
    worker.start()
    assert worker._thread is first_thread
    worker.stop()
    worker.stop()

    assert worker.is_running() is False


def test_worker_stop_during_fetch_waits_and_never_injects_input():
    snapshot = player_snapshot(
        health=1,
        hunger=20,
        hotbar={8: "Potion"},
    )
    player_client = BlockingPlayerClient(snapshot)
    backend = FakeInput()
    worker = AutoHealWorker(
        RuntimeControls.from_config(
            BotConfig(
                program_enabled=True,
                auto_heal_enabled=True,
                auto_heal_items=(
                    AutoHealItemConfig("Potion", 30, 2, 10, 0),
                ),
            )
        ),
        lambda _message: None,
        player_client=player_client,
        container_client=FakeContainerClient(),
        pyautogui_module=backend,
        foreground_provider=lambda: True,
        poll_seconds=0.01,
    )

    worker.start()
    assert player_client.fetch_started.wait(timeout=1)
    stopped = threading.Event()
    stop_thread = threading.Thread(
        target=lambda: (worker.stop(), stopped.set())
    )
    stop_thread.start()

    assert not stopped.wait(timeout=0.05)
    player_client.release_fetch.set()
    stop_thread.join(timeout=1)

    assert stopped.is_set()
    assert worker.is_running() is False
    assert backend.events == []
