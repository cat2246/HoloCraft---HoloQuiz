from concurrent.futures import Future

from holoquiz.player_view import PlayerPoller


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
