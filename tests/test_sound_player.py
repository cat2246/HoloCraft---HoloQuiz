import pytest

from holoquiz.sound_player import WindowsSoundPlayer


@pytest.mark.parametrize(
    ("extension", "media_type"),
    [(".mp3", "mpegvideo"), (".wav", "waveaudio")],
)
def test_windows_sound_player_uses_mci_for_supported_audio(
    tmp_path,
    monkeypatch,
    extension,
    media_type,
):
    sound_path = tmp_path / f"trigger sound{extension}"
    sound_path.write_bytes(b"audio fixture")
    commands = []
    player = WindowsSoundPlayer()
    monkeypatch.setattr(player, "_send_mci_command", commands.append)

    player._play_blocking(sound_path)

    assert commands[0].startswith(f'open "{sound_path.resolve()}" type {media_type}')
    assert commands[1].startswith("play holoquiz_")
    assert commands[1].endswith(" wait")
    assert commands[2].startswith("close holoquiz_")


def test_windows_sound_player_rejects_unsupported_file(tmp_path, monkeypatch, capsys):
    sound_path = tmp_path / "trigger.ogg"
    sound_path.write_bytes(b"audio fixture")
    commands = []
    player = WindowsSoundPlayer()
    monkeypatch.setattr(player, "_send_mci_command", commands.append)

    player._play_blocking(sound_path)

    assert commands == []
    assert "must be an MP3 or WAV" in capsys.readouterr().out
