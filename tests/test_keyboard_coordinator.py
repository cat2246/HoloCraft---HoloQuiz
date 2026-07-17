import threading
import time

from holoquiz.keyboard_coordinator import KeyboardInputCoordinator


def test_click_session_is_allowed_during_movement_session():
    coordinator = KeyboardInputCoordinator()

    with coordinator.movement_session() as movement_allowed:
        assert movement_allowed is True
        with coordinator.click_session() as click_allowed:
            assert click_allowed is True


def test_click_session_is_denied_during_chat_session():
    coordinator = KeyboardInputCoordinator()

    with coordinator.chat_session():
        with coordinator.click_session() as click_allowed:
            assert click_allowed is False


def test_click_session_is_denied_while_chat_is_pending():
    coordinator = KeyboardInputCoordinator()

    def send_chat():
        with coordinator.chat_session():
            pass

    with coordinator.movement_session() as movement_allowed:
        assert movement_allowed is True
        chat_thread = threading.Thread(target=send_chat)
        chat_thread.start()
        deadline = time.monotonic() + 1.0
        while True:
            with coordinator._state_lock:
                chat_is_pending = coordinator._pending_chat_sessions > 0
            if chat_is_pending:
                break
            assert time.monotonic() < deadline
            time.sleep(0.001)

        with coordinator.click_session() as click_allowed:
            assert click_allowed is False

    chat_thread.join(timeout=1.0)
    assert chat_thread.is_alive() is False


def test_item_use_session_blocks_movement_and_clicks():
    coordinator = KeyboardInputCoordinator()

    with coordinator.item_use_session() as item_use_allowed:
        assert item_use_allowed is True
        with coordinator.movement_session() as movement_allowed:
            assert movement_allowed is False
        with coordinator.click_session() as click_allowed:
            assert click_allowed is False


def test_item_use_session_is_denied_while_chat_is_pending():
    coordinator = KeyboardInputCoordinator()

    def send_chat():
        with coordinator.chat_session():
            pass

    with coordinator.movement_session() as movement_allowed:
        assert movement_allowed is True
        chat_thread = threading.Thread(target=send_chat)
        chat_thread.start()
        deadline = time.monotonic() + 1.0
        while True:
            with coordinator._state_lock:
                chat_is_pending = coordinator._pending_chat_sessions > 0
            if chat_is_pending:
                break
            assert time.monotonic() < deadline
            time.sleep(0.001)

        with coordinator.item_use_session() as item_use_allowed:
            assert item_use_allowed is False

    chat_thread.join(timeout=1.0)
    assert chat_thread.is_alive() is False
