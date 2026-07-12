from __future__ import annotations

from typing import Any, Callable


class Mouse4HotkeyListener:
    """Runs a global Mouse 4 listener and calls back once per button press."""

    def __init__(
        self,
        callback: Callable[[], None],
        *,
        listener_factory: Callable[..., Any] | None = None,
        mouse4_button: Any | None = None,
    ) -> None:
        self._callback = callback
        self._listener_factory = listener_factory
        self._mouse4_button = mouse4_button
        self._listener: Any | None = None

    def start(self) -> None:
        if self._listener is not None:
            return
        if self._listener_factory is None:
            from pynput import mouse

            self._listener_factory = mouse.Listener
            self._mouse4_button = mouse.Button.x1
        self._listener = self._listener_factory(on_click=self._on_click)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is None:
            return
        self._listener.stop()
        self._listener = None

    def _on_click(
        self,
        _x: int,
        _y: int,
        button: Any,
        pressed: bool,
    ) -> None:
        if pressed and button == self._mouse4_button:
            self._callback()
