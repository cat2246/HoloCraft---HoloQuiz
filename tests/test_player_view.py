from concurrent.futures import Future, ThreadPoolExecutor
import threading

import pytest

import holoquiz.player_view as player_view
from holoquiz.player import InventorySlot, PlayerItem, parse_player_payload
from holoquiz.player_view import (
    ItemSlotWidget,
    ItemTooltip,
    PlayerPoller,
    PlayerTab,
    health_percent,
    hunger_percent,
)


class FakeScheduler:
    def __init__(self):
        self.callbacks = {}
        self.cancelled = []
        self.next_id = 0

    def after(self, delay_ms, callback):
        self.next_id += 1
        callback_id = f"after-{self.next_id}"
        self.callbacks[callback_id] = (delay_ms, callback)
        return callback_id

    def after_cancel(self, callback_id):
        self.cancelled.append(callback_id)
        self.callbacks.pop(callback_id, None)

    def run_delay(self, delay_ms):
        callback_id, (_, callback) = next(
            (item for item in self.callbacks.items() if item[1][0] == delay_ms)
        )
        del self.callbacks[callback_id]
        callback()


class ManualExecutor:
    def __init__(self):
        self.calls = []
        self.shutdown_calls = []

    def submit(self, function):
        future = Future()
        self.calls.append((function, future))
        return future

    def run_next(self):
        function, future = self.calls.pop(0)
        try:
            future.set_result(function())
        except Exception as error:
            future.set_exception(error)

    def shutdown(self, **kwargs):
        self.shutdown_calls.append(kwargs)


class RecordingThreadExecutor:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.futures = []

    def submit(self, function):
        future = self.executor.submit(function)
        self.futures.append(future)
        return future

    def shutdown(self, **kwargs):
        self.executor.shutdown(**kwargs)


def test_player_poller_activates_immediately_and_prevents_overlap():
    scheduler = FakeScheduler()
    executor = ManualExecutor()
    poller = PlayerPoller(
        scheduler,
        lambda: "snapshot",
        lambda _value: None,
        lambda _error: None,
        executor=executor,
    )

    poller.activate()

    assert len(executor.calls) == 1
    assert poller.refresh() is False


def test_player_poller_delivers_worker_result_on_scheduler_drain_then_waits_one_second():
    scheduler = FakeScheduler()
    executor = ManualExecutor()
    successes = []
    poller = PlayerPoller(
        scheduler,
        lambda: "snapshot",
        successes.append,
        lambda _error: None,
        executor=executor,
    )
    poller.activate()
    executor.run_next()

    assert successes == []
    scheduler.run_delay(25)

    assert successes == ["snapshot"]
    assert any(delay == 1000 for delay, _callback in scheduler.callbacks.values())


def test_player_poller_reports_error_without_discarding_view_state():
    scheduler = FakeScheduler()
    executor = ManualExecutor()
    visible = ["old snapshot"]
    errors = []

    def fail():
        raise OSError("connection refused")

    poller = PlayerPoller(
        scheduler,
        fail,
        lambda value: visible.__setitem__(0, value),
        errors.append,
        executor=executor,
    )
    poller.activate()
    executor.run_next()
    scheduler.run_delay(25)

    assert visible == ["old snapshot"]
    assert str(errors[0]) == "connection refused"


def test_player_poller_deactivate_and_close_cancel_callbacks():
    scheduler = FakeScheduler()
    executor = ManualExecutor()
    poller = PlayerPoller(
        scheduler,
        lambda: "snapshot",
        lambda _value: None,
        lambda _error: None,
        executor=executor,
    )
    poller.activate()
    poller.deactivate()
    poller.close()

    assert poller.active is False
    assert scheduler.callbacks == {}
    assert executor.shutdown_calls == [{"wait": False, "cancel_futures": True}]


def test_player_poller_reactivation_discards_hidden_result_and_fetches_fresh_immediately():
    scheduler = FakeScheduler()
    executor = ManualExecutor()
    snapshots = iter(["hidden snapshot", "fresh snapshot"])
    successes = []
    poller = PlayerPoller(
        scheduler,
        lambda: next(snapshots),
        successes.append,
        lambda _error: None,
        executor=executor,
    )
    poller.activate()
    poller.deactivate()
    executor.run_next()

    poller.activate()
    assert executor.calls == []
    scheduler.run_delay(25)

    assert successes == []
    assert len(executor.calls) == 1

    executor.run_next()
    scheduler.run_delay(25)

    assert successes == ["fresh snapshot"]


@pytest.mark.parametrize(
    "fetch",
    [
        pytest.param(lambda: "snapshot", id="success"),
        pytest.param(
            lambda: (_ for _ in ()).throw(OSError("connection refused")),
            id="error",
        ),
    ],
)
def test_player_poller_completion_after_close_never_invokes_callbacks(fetch):
    scheduler = FakeScheduler()
    executor = ManualExecutor()
    successes = []
    errors = []
    poller = PlayerPoller(
        scheduler,
        fetch,
        successes.append,
        errors.append,
        executor=executor,
    )
    poller.activate()
    poller.close()

    executor.run_next()

    assert successes == []
    assert errors == []
    assert scheduler.callbacks == {}


def test_player_poller_fetches_on_worker_but_schedules_and_delivers_on_main_thread():
    main_thread_id = threading.get_ident()
    scheduler = FakeScheduler()
    scheduler_thread_ids = []
    original_after = scheduler.after

    def record_after(delay_ms, callback):
        scheduler_thread_ids.append(threading.get_ident())
        return original_after(delay_ms, callback)

    scheduler.after = record_after
    executor = RecordingThreadExecutor()
    fetch_thread_ids = []
    callback_thread_ids = []
    poller = PlayerPoller(
        scheduler,
        lambda: fetch_thread_ids.append(threading.get_ident()) or "snapshot",
        lambda _value: callback_thread_ids.append(threading.get_ident()),
        lambda _error: callback_thread_ids.append(threading.get_ident()),
        executor=executor,
    )

    poller.activate()
    executor.futures[0].result(timeout=1)
    scheduler.run_delay(25)
    poller.close()

    assert fetch_thread_ids[0] != main_thread_id
    assert scheduler_thread_ids and set(scheduler_thread_ids) == {main_thread_id}
    assert callback_thread_ids == [main_thread_id]


def test_player_snapshot_is_delivered_while_first_icon_lookup_is_blocked():
    scheduler = FakeScheduler()
    icon_executor = RecordingThreadExecutor()
    icon_started = threading.Event()
    release_icon = threading.Event()
    delivered_icons = []

    def blocked_icon_fetch(item_id):
        icon_started.set()
        assert release_icon.wait(timeout=1)
        return item_id

    icon_loader = player_view.PlayerIconLoader(
        scheduler,
        blocked_icon_fetch,
        lambda item_id, icon: delivered_icons.append((item_id, icon)),
        executor=icon_executor,
    )
    poll_executor = ManualExecutor()
    snapshots = []
    poller = PlayerPoller(
        scheduler,
        lambda: "snapshot",
        snapshots.append,
        lambda _error: None,
        executor=poll_executor,
    )

    icon_loader.activate()
    icon_loader.queue(["minecraft:diamond"])
    assert icon_started.wait(timeout=1)
    poller.activate()
    poll_executor.run_next()
    while not snapshots:
        scheduler.run_delay(25)

    assert snapshots == ["snapshot"]
    assert delivered_icons == []

    poller.close()
    icon_loader.close()
    release_icon.set()
    icon_executor.futures[0].result(timeout=1)


def test_player_icon_loader_close_during_blocked_request_skips_remaining_ids():
    scheduler = FakeScheduler()
    executor = RecordingThreadExecutor()
    requests = []
    first_started = threading.Event()
    release_first = threading.Event()
    callbacks = []

    def fetch(item_id):
        requests.append(item_id)
        if item_id == "first":
            first_started.set()
            assert release_first.wait(timeout=1)
        return f"icon:{item_id}"

    loader = player_view.PlayerIconLoader(
        scheduler,
        fetch,
        lambda item_id, icon: callbacks.append((item_id, icon)),
        executor=executor,
    )
    loader.activate()
    loader.queue(["first", "second"])
    assert first_started.wait(timeout=1)

    loader.close()
    release_first.set()
    executor.futures[0].result(timeout=1)

    assert requests == ["first"]
    assert callbacks == []
    assert scheduler.callbacks == {}


def test_player_progress_values_are_clamped():
    payload = {
        "api_version": 1,
        "connected": True,
        "health": {"current": 33.5, "max": 42.5},
        "hunger": {"food_level": 20},
        "inventory": [],
    }
    snapshot = parse_player_payload(payload)

    assert health_percent(snapshot) == pytest.approx(78.8235, rel=0.001)
    assert hunger_percent(snapshot) == 100.0


def test_item_slot_fallback_draws_stack_count_overlay_without_tk():
    operations = []

    class RecordingTooltip:
        def hide(self, _owner):
            operations.append("tooltip")

    class RecordingCanvas:
        def delete(self, _target):
            operations.append("delete")

        def configure(self, **_kwargs):
            operations.append("configure")

        def create_rectangle(self, *_args, **_kwargs):
            operations.append("fallback rectangle")

        def create_line(self, *_args, **_kwargs):
            operations.append("fallback line")

        def create_text(self, *_args, **kwargs):
            operations.append(f"count {kwargs['text']}")

    slot = InventorySlot(
        0,
        "hotbar",
        PlayerItem(
            empty=False,
            item_id="minecraft:diamond",
            count=7,
        ),
    )
    widget = object.__new__(ItemSlotWidget)
    widget.tooltip = RecordingTooltip()
    widget.canvas = RecordingCanvas()
    widget.slot = None
    widget.photo = None

    widget.render(slot, photo=None)

    assert operations[-4:] == [
        "fallback rectangle",
        "fallback line",
        "fallback line",
        "count 7",
    ]


def test_player_tab_public_lifecycle_is_explicit():
    assert callable(PlayerTab.activate)
    assert callable(PlayerTab.deactivate)
    assert callable(PlayerTab.refresh)
    assert callable(PlayerTab.close)


def test_player_tab_deactivate_stops_icon_loader_and_hides_tooltip_and_poller():
    actions = []

    class RecordingTooltip:
        def hide(self):
            actions.append("tooltip hidden")

    class RecordingPoller:
        def deactivate(self):
            actions.append("poller deactivated")

    class RecordingIconLoader:
        def deactivate(self):
            actions.append("icons deactivated")

    tab = object.__new__(PlayerTab)
    tab.tooltip = RecordingTooltip()
    tab.poller = RecordingPoller()
    tab.icon_loader = RecordingIconLoader()

    tab.deactivate()

    assert actions == [
        "tooltip hidden",
        "poller deactivated",
        "icons deactivated",
    ]


def test_player_tab_extra_slot_cleanup_only_hides_tooltip_for_destroyed_owner():
    actions = []

    class RecordingTooltip:
        def hide(self, owner=None):
            actions.append(f"tooltip checked for {owner.name}")

    class RecordingCanvas:
        def __init__(self, name):
            self.name = name

        def destroy(self):
            actions.append(f"{self.name} destroyed")

    class ExtraSlot:
        def __init__(self, name):
            self.canvas = RecordingCanvas(name)

    tab = object.__new__(PlayerTab)
    tab.tooltip = RecordingTooltip()
    tab.extra_slots = [ExtraSlot("first"), ExtraSlot("second")]

    tab._clear_extra_slots()

    assert actions == [
        "tooltip checked for first",
        "first destroyed",
        "tooltip checked for second",
        "second destroyed",
    ]
    assert tab.extra_slots == []


def test_item_tooltip_ignores_hide_from_non_owner():
    actions = []

    class Window:
        def destroy(self):
            actions.append("destroyed")

    owner = object()
    other = object()
    tooltip = object.__new__(ItemTooltip)
    tooltip.window = Window()
    tooltip.owner = owner

    tooltip.hide(other)
    assert actions == []
    assert tooltip.window is not None

    tooltip.hide(owner)
    assert actions == ["destroyed"]
    assert tooltip.window is None
    assert tooltip.owner is None
