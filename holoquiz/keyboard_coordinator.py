from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Iterator


class KeyboardInputCoordinator:
    """Serializes chat typing and movement, giving pending chat sends priority."""

    def __init__(self) -> None:
        self._input_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending_chat_sessions = 0
        self._item_use_active = False

    @contextmanager
    def chat_session(self) -> Iterator[None]:
        with self._state_lock:
            self._pending_chat_sessions += 1
        self._input_lock.acquire()
        try:
            yield
        finally:
            self._input_lock.release()
            with self._state_lock:
                self._pending_chat_sessions -= 1

    @contextmanager
    def movement_session(self) -> Iterator[bool]:
        with self._state_lock:
            chat_is_pending = self._pending_chat_sessions > 0

        acquired = False
        if not chat_is_pending:
            acquired = self._input_lock.acquire(blocking=False)
            if acquired:
                with self._state_lock:
                    chat_is_pending = self._pending_chat_sessions > 0
                if chat_is_pending:
                    self._input_lock.release()
                    acquired = False

        try:
            yield acquired
        finally:
            if acquired:
                self._input_lock.release()

    @contextmanager
    def click_session(self) -> Iterator[bool]:
        self._state_lock.acquire()
        try:
            yield (
                self._pending_chat_sessions == 0
                and not self._item_use_active
            )
        finally:
            self._state_lock.release()

    @contextmanager
    def item_use_session(self) -> Iterator[bool]:
        with self._state_lock:
            denied = self._pending_chat_sessions > 0

        acquired = False
        if not denied:
            acquired = self._input_lock.acquire(blocking=False)
        if acquired:
            with self._state_lock:
                if self._pending_chat_sessions > 0:
                    self._input_lock.release()
                    acquired = False
                else:
                    self._item_use_active = True

        try:
            yield acquired
        finally:
            if acquired:
                with self._state_lock:
                    self._item_use_active = False
                self._input_lock.release()


keyboard_input_coordinator = KeyboardInputCoordinator()
