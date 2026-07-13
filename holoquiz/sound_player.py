from __future__ import annotations

import ctypes
import threading
from pathlib import Path
from typing import Protocol
from uuid import uuid4


SUPPORTED_SOUND_EXTENSIONS = frozenset({".mp3", ".wav"})


class SoundPlayer(Protocol):
    def play(self, sound_path: Path) -> None:
        ...


class WindowsSoundPlayer:
    """Play audio asynchronously through Windows Media Control Interface."""

    def play(self, sound_path: Path) -> None:
        path = Path(sound_path)
        threading.Thread(
            target=self._play_blocking,
            args=(path,),
            daemon=True,
            name="holoquiz-chat-trigger-sound",
        ).start()

    def _play_blocking(self, sound_path: Path) -> None:
        if not sound_path.is_file():
            print(f"[sound-warning] Chat trigger sound does not exist: {sound_path}")
            return
        if sound_path.suffix.lower() not in SUPPORTED_SOUND_EXTENSIONS:
            print(
                "[sound-warning] Chat trigger sound must be an MP3 or WAV: "
                f"{sound_path}"
            )
            return

        alias = f"holoquiz_{uuid4().hex}"
        media_type = (
            "mpegvideo" if sound_path.suffix.lower() == ".mp3" else "waveaudio"
        )
        try:
            self._send_mci_command(
                f'open "{sound_path.resolve()}" type {media_type} alias {alias}'
            )
            self._send_mci_command(f"play {alias} wait")
        except Exception as error:
            print(f"[sound-warning] Could not play chat trigger sound: {error}")
        finally:
            try:
                self._send_mci_command(f"close {alias}")
            except Exception:
                pass

    @staticmethod
    def _send_mci_command(command: str) -> None:
        winmm = ctypes.windll.winmm
        error_code = winmm.mciSendStringW(command, None, 0, None)
        if error_code == 0:
            return

        message_buffer = ctypes.create_unicode_buffer(256)
        if winmm.mciGetErrorStringW(error_code, message_buffer, len(message_buffer)):
            message = message_buffer.value
        else:
            message = f"MCI error {error_code}"
        raise OSError(message)
