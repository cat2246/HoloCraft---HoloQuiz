import subprocess

from holoquiz.config import BotConfig
from holoquiz.codex_client import CodexAnswerClient, build_prompt, clean_answer


def test_build_prompt_includes_examples_and_question():
    prompt = build_prompt("Who created Minecraft?")

    assert "Return ONLY the answer text." in prompt
    assert "Question: What mob explodes near players?" in prompt
    assert "Answer: Creeper" in prompt
    assert "Question: What ore is used to make a beacon base?" in prompt
    assert "Answer: Iron" in prompt
    assert "Question: Who created Minecraft?" in prompt
    assert "Answer: Notch" in prompt
    assert prompt.rstrip().endswith("Answer:")


def test_clean_answer_uses_first_non_empty_line_and_removes_prefix():
    output = "\n\nAnswer: Notch\nExtra text\n"

    assert clean_answer(output) == "Notch"


def test_clean_answer_strips_quotes_and_trailing_period():
    assert clean_answer('"Creeper."') == "Creeper"


def test_clean_answer_keeps_abbreviation_periods():
    assert clean_answer("U.S.") == "U.S."


def test_ask_builds_codex_exec_command(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, timeout, check, capture_output, text):
        calls.append(
            {
                "command": command,
                "timeout": timeout,
                "check": check,
                "capture_output": capture_output,
                "text": text,
            }
        )
        output_path = command[command.index("--output-last-message") + 1]
        output_path.write_text("Notch\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    config = BotConfig(codex_model="gpt-5.4-mini", codex_timeout_seconds=4)
    client = CodexAnswerClient(config=config, workspace=tmp_path)

    assert client.ask("Who created Minecraft?") == "Notch"

    command = calls[0]["command"]
    assert command[:3] == ["codex", "exec", "-m"]
    assert "gpt-5.4-mini" in command
    assert "--sandbox" in command
    assert "--ask-for-approval" in command
    assert "--ephemeral" in command
    assert "--color" in command
    assert "--output-last-message" in command
    assert calls[0]["timeout"] == 4


def test_ask_inserts_search_flag_before_exec(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, timeout, check, capture_output, text):
        calls.append(command)
        output_path = command[command.index("--output-last-message") + 1]
        output_path.write_text("Creeper\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = CodexAnswerClient(
        config=BotConfig(codex_enable_search=True),
        workspace=tmp_path,
    )

    assert client.ask("What mob explodes near players?") == "Creeper"
    assert calls[0][:4] == ["codex", "--search", "exec", "-m"]


def test_ask_returns_none_on_timeout(tmp_path, monkeypatch):
    def fake_run(command, timeout, check, capture_output, text):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = CodexAnswerClient(config=BotConfig(codex_timeout_seconds=1), workspace=tmp_path)

    assert client.ask("Who created Minecraft?") is None


def test_ask_returns_none_on_called_process_error(tmp_path, monkeypatch):
    def fake_run(command, timeout, check, capture_output, text):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = CodexAnswerClient(config=BotConfig(), workspace=tmp_path)

    assert client.ask("Who created Minecraft?") is None


def test_ask_returns_none_on_os_error(tmp_path, monkeypatch):
    def fake_run(command, timeout, check, capture_output, text):
        raise OSError("codex not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = CodexAnswerClient(config=BotConfig(), workspace=tmp_path)

    assert client.ask("Who created Minecraft?") is None
