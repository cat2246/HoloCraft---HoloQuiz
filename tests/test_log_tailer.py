from holoquiz.log_tailer import LogTailer


def test_tailer_reads_only_appended_lines(tmp_path):
    log_path = tmp_path / "latest.log"
    log_path.write_text("old line\n", encoding="utf-8")
    tailer = LogTailer(log_path, start_at_end=True)

    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("new line 1\nnew line 2\n")

    assert tailer.read_available() == ["new line 1\n", "new line 2\n"]


def test_tailer_reads_existing_lines_when_not_starting_at_end(tmp_path):
    log_path = tmp_path / "latest.log"
    log_path.write_text("line 1\nline 2\n", encoding="utf-8")
    tailer = LogTailer(log_path, start_at_end=False)

    assert tailer.read_available() == ["line 1\n", "line 2\n"]


def test_tailer_resets_after_truncation(tmp_path):
    log_path = tmp_path / "latest.log"
    log_path.write_text("old line\n", encoding="utf-8")
    tailer = LogTailer(log_path, start_at_end=True)

    log_path.write_text("fresh line\n", encoding="utf-8")

    assert tailer.read_available() == ["fresh line\n"]
