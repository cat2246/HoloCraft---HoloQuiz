from holoquiz.chat_sender import ChatSender
from holoquiz.config import BotConfig


class FakePyAutoGui:
    def __init__(self):
        self.calls = []

    def press(self, key):
        self.calls.append(("press", key))

    def write(self, text, interval):
        self.calls.append(("write", text, interval))


def test_dry_run_sender_prints_answer(capsys):
    sender = ChatSender(BotConfig(dry_run=True))

    sender.send("Notch")

    captured = capsys.readouterr()
    assert "[dry-run] Would send answer: Notch" in captured.out


def test_live_sender_uses_chat_key_and_enter(monkeypatch):
    fake = FakePyAutoGui()
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    sender = ChatSender(
        BotConfig(
            dry_run=False,
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
