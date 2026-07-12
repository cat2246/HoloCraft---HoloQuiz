from holoquiz.mouse_hotkey import Mouse4HotkeyListener


class FakeListener:
    def __init__(self, *, on_click):
        self.on_click = on_click
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def test_mouse4_press_toggles_once_and_other_mouse_events_are_ignored():
    toggles = []
    listener = Mouse4HotkeyListener(
        lambda: toggles.append(True),
        listener_factory=FakeListener,
        mouse4_button="mouse4",
    )

    listener.start()
    backend = listener._listener
    backend.on_click(0, 0, "left", True)
    backend.on_click(0, 0, "mouse4", False)
    backend.on_click(0, 0, "mouse4", True)

    assert backend.started is True
    assert toggles == [True]

    listener.stop()

    assert backend.stopped is True
