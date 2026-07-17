from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
import queue
from typing import Any, Callable

from holoquiz.player import PlayerSnapshot


@dataclass(frozen=True)
class PlayerViewData:
    snapshot: PlayerSnapshot
    icon_png_by_item_id: dict[str, bytes]


class PlayerPoller:
    def __init__(
        self,
        scheduler: Any,
        fetch: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        *,
        interval_ms: int = 1000,
        drain_ms: int = 25,
        executor: Executor | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.fetch = fetch
        self.on_success = on_success
        self.on_error = on_error
        self.interval_ms = interval_ms
        self.drain_ms = drain_ms
        self.executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="player-view",
        )
        self.results: queue.Queue[tuple[bool, Any]] = queue.Queue()
        self.active = False
        self.in_flight = False
        self.closed = False
        self._poll_after_id: str | None = None
        self._drain_after_id: str | None = None

    def activate(self) -> None:
        if self.closed or self.active:
            return
        self.active = True
        self._schedule_drain()
        self.refresh()

    def deactivate(self) -> None:
        self.active = False
        self._cancel("_poll_after_id")
        self._cancel("_drain_after_id")

    def refresh(self) -> bool:
        if self.closed or not self.active or self.in_flight:
            return False
        self._cancel("_poll_after_id")
        self.in_flight = True
        self.executor.submit(self._fetch_to_queue)
        return True

    def _fetch_to_queue(self) -> None:
        try:
            self.results.put((True, self.fetch()))
        except Exception as error:
            self.results.put((False, error))

    def _schedule_drain(self) -> None:
        if self.active and not self.closed and self._drain_after_id is None:
            self._drain_after_id = self.scheduler.after(
                self.drain_ms,
                self._drain,
            )

    def _drain(self) -> None:
        self._drain_after_id = None
        delivered = False
        while True:
            try:
                ok, value = self.results.get_nowait()
            except queue.Empty:
                break
            delivered = True
            self.in_flight = False
            if not self.closed:
                if ok:
                    self.on_success(value)
                else:
                    self.on_error(value)
        if delivered and self.active and not self.closed:
            self._poll_after_id = self.scheduler.after(
                self.interval_ms,
                self._scheduled_refresh,
            )
        self._schedule_drain()

    def _scheduled_refresh(self) -> None:
        self._poll_after_id = None
        self.refresh()

    def _cancel(self, attribute: str) -> None:
        callback_id = getattr(self, attribute)
        if callback_id is not None:
            self.scheduler.after_cancel(callback_id)
            setattr(self, attribute, None)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.deactivate()
        self.executor.shutdown(wait=False, cancel_futures=True)
