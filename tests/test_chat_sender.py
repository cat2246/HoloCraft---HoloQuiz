from holoquiz.chat_sender import ChatSender
from holoquiz.config import BotConfig
from holoquiz.runtime import RuntimeControls


class FakePyAutoGui:
    def __init__(self):
        self.calls = []

    def press(self, key):
        self.calls.append(("press", key))

    def hotkey(self, *keys):
        self.calls.append(("hotkey", *keys))

    def write(self, text, interval):
        self.calls.append(("write", text, interval))


class FakeClipboard:
    def __init__(self):
        self.values = []

    def copy(self, text):
        self.values.append(text)


class FakeSound:
    SND_FILENAME = 131072
    SND_ASYNC = 1

    def __init__(self):
        self.calls = []

    def PlaySound(self, sound_path, flags):
        self.calls.append((sound_path, flags))


def test_dry_run_sender_copies_answer_without_pasting(capsys):
    fake = FakePyAutoGui()
    clipboard = FakeClipboard()
    sound = FakeSound()
    sender = ChatSender(
        BotConfig(dry_run=True),
        pyautogui_module=fake,
        clipboard_module=clipboard,
        sound_module=sound,
    )

    sender.send(" Notch ")

    captured = capsys.readouterr()
    assert "[dry-run] Would send answer: Notch" in captured.out
    assert clipboard.values == ["Notch"]
    assert sound.calls == [
        (
            "C:\\Users\\limwi\\Downloads\\gawr-gura-a.wav",
            sound.SND_FILENAME | sound.SND_ASYNC,
        )
    ]
    assert fake.calls == []


def test_dry_run_sender_copies_answer_without_sound_when_muted(capsys):
    clipboard = FakeClipboard()
    sound = FakeSound()
    sender = ChatSender(
        BotConfig(dry_run=True, answer_sound_enabled=False),
        clipboard_module=clipboard,
        sound_module=sound,
    )

    sender.send("Notch")

    assert clipboard.values == ["Notch"]
    assert sound.calls == []
    assert "[dry-run] Would send answer: Notch" in capsys.readouterr().out


def test_live_sender_pastes_answer_by_default(monkeypatch, capsys):
    fake = FakePyAutoGui()
    clipboard = FakeClipboard()
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    sender = ChatSender(
        BotConfig(
            dry_run=False,
            send_delay_seconds=0.1,
            keyboard_open_chat_key="t",
        ),
        pyautogui_module=fake,
        clipboard_module=clipboard,
    )

    sender.send("Creeper")

    assert clipboard.values == ["Creeper"]
    assert fake.calls == [
        ("press", "t"),
        ("hotkey", "ctrl", "v"),
        ("press", "enter"),
    ]
    assert "[send] Sent answer via paste: Creeper" in capsys.readouterr().out


def test_sender_uses_live_runtime_config(monkeypatch, capsys):
    fake = FakePyAutoGui()
    clipboard = FakeClipboard()
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleep_calls.append(seconds))
    controls = RuntimeControls.from_config(
        BotConfig(dry_run=True, send_delay_seconds=0.8)
    )
    sender = ChatSender(
        controls.get_config(),
        config_provider=controls.get_config,
        pyautogui_module=fake,
        clipboard_module=clipboard,
    )

    controls.set_dry_run(False)
    controls.set_send_delay_seconds(1.5)
    sender.send("Creeper")

    assert sleep_calls == [1.5]
    assert clipboard.values == ["Creeper"]
    assert fake.calls == [
        ("press", "t"),
        ("hotkey", "ctrl", "v"),
        ("press", "enter"),
    ]
    assert "[send] Sent answer via paste: Creeper" in capsys.readouterr().out


def test_live_sender_uses_random_delay_range(monkeypatch):
    fake = FakePyAutoGui()
    clipboard = FakeClipboard()
    sleep_calls = []
    random_calls = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleep_calls.append(seconds))

    def fake_uniform(min_seconds, max_seconds):
        random_calls.append((min_seconds, max_seconds))
        return 2.25

    monkeypatch.setattr("holoquiz.chat_sender.random.uniform", fake_uniform)
    sender = ChatSender(
        BotConfig(
            dry_run=False,
            send_delay_min_seconds=1.0,
            send_delay_max_seconds=3.0,
        ),
        pyautogui_module=fake,
        clipboard_module=clipboard,
    )

    sender.send("Creeper")

    assert random_calls == [(1.0, 3.0)]
    assert sleep_calls == [2.25]
    assert fake.calls == [
        ("press", "t"),
        ("hotkey", "ctrl", "v"),
        ("press", "enter"),
    ]


def test_live_sender_can_type_answer(monkeypatch):
    fake = FakePyAutoGui()
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    sender = ChatSender(
        BotConfig(
            dry_run=False,
            send_mode="type",
            send_delay_seconds=0.1,
            keyboard_open_chat_key="t",
            typing_interval_seconds=0.02,
        ),
        pyautogui_module=fake,
    )

    sender.send("Creeper")

    assert fake.calls == [
        ("press", "t"),
        ("write", "Creeper", 0.02),
        ("press", "enter"),
    ]


def test_live_sender_ignores_empty_answer():
    fake = FakePyAutoGui()
    sender = ChatSender(BotConfig(dry_run=False), pyautogui_module=fake)

    sender.send("   ")

    assert fake.calls == []


def test_live_sender_reports_missing_pyautogui(monkeypatch, capsys):
    def fail_import():
        raise ModuleNotFoundError("No module named 'pyautogui'")

    sender = ChatSender(BotConfig(dry_run=False))
    monkeypatch.setattr(sender, "_load_pyautogui", fail_import)

    sender.send("Creeper")

    assert "[send-error] pyautogui is not installed" in capsys.readouterr().out


def test_live_sender_runs_macro_text_and_enter_token(monkeypatch, capsys):
    fake = FakePyAutoGui()
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    sender = ChatSender(
        BotConfig(
            dry_run=False,
            chat_trigger_dry_run=False,
            typing_interval_seconds=0.02,
        ),
        pyautogui_module=fake,
    )

    sender.send_macro("tGood Morning{{Enter}}")

    assert fake.calls == [
        ("write", "tGood Morning", 0.02),
        ("press", "enter"),
    ]
    assert "[macro] Ran macro: tGood Morning{{Enter}}" in capsys.readouterr().out


def test_live_sender_runs_macro_with_interval_override(monkeypatch):
    fake = FakePyAutoGui()
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    sender = ChatSender(
        BotConfig(
            dry_run=False,
            chat_trigger_dry_run=False,
            typing_interval_seconds=0.01,
        ),
        pyautogui_module=fake,
    )

    sender.send_macro("123", typing_interval_seconds=0.1)

    assert fake.calls == [
        ("write", "123", 0.1),
    ]


def test_live_sender_runs_macro_mouse_and_hotkey_tokens(monkeypatch):
    class ClickPyAutoGui(FakePyAutoGui):
        def click(self, button):
            self.calls.append(("click", button))

    fake = ClickPyAutoGui()
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    sender = ChatSender(
        BotConfig(dry_run=False, chat_trigger_dry_run=False),
        pyautogui_module=fake,
    )

    sender.send_macro("{{LButton}}{{Ctrl+V}}{{Escape}}")

    assert fake.calls == [
        ("click", "left"),
        ("hotkey", "ctrl", "v"),
        ("press", "escape"),
    ]


def test_live_sender_pauses_between_macro_button_tokens(monkeypatch):
    class ClickPyAutoGui(FakePyAutoGui):
        def click(self, button):
            self.calls.append(("click", button))

    fake = ClickPyAutoGui()
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleep_calls.append(seconds))
    sender = ChatSender(
        BotConfig(
            dry_run=False,
            chat_trigger_dry_run=False,
            send_delay_min_seconds=0.0,
            send_delay_max_seconds=0.0,
            typing_interval_seconds=0.01,
        ),
        pyautogui_module=fake,
    )

    sender.send_macro(
        "{{LButton}}{{LButton}}{{LButton}}",
        typing_interval_seconds=0.1,
    )

    assert fake.calls == [
        ("click", "left"),
        ("click", "left"),
        ("click", "left"),
    ]
    assert sleep_calls == [0.0, 0.1, 0.1]


def test_dry_run_sender_reports_macro_without_running(capsys):
    fake = FakePyAutoGui()
    sender = ChatSender(BotConfig(dry_run=True), pyautogui_module=fake)

    sender.send_macro("tGood Morning{{Enter}}")

    assert fake.calls == []
    assert "[dry-run] Would run macro: tGood Morning{{Enter}}" in capsys.readouterr().out


def test_macro_dry_run_is_independent_from_holoquiz_dry_run(monkeypatch, capsys):
    fake = FakePyAutoGui()
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    sender = ChatSender(
        BotConfig(dry_run=True, chat_trigger_dry_run=False),
        pyautogui_module=fake,
    )

    sender.send_macro("tHi{{Enter}}")

    assert fake.calls == [
        ("write", "tHi", 0.01),
        ("press", "enter"),
    ]
    assert "[macro] Ran macro: tHi{{Enter}}" in capsys.readouterr().out
