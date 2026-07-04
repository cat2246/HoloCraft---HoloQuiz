import subprocess
import shutil

from holoquiz.config import BotConfig
from holoquiz.codex_client import CodexAnswerClient, build_prompt, clean_answer
from holoquiz.runtime import RuntimeControls


def test_build_prompt_includes_examples_and_question():
    prompt = build_prompt("Who created Minecraft?")

    assert "Return ONLY the answer text." in prompt
    assert "Question: What mob explodes near players?" in prompt
    assert "Answer: Creeper" in prompt
    assert "Question: What ore is used to make a beacon base?" in prompt
    assert "Answer: Iron" in prompt
    assert "Question: Who created Minecraft?" in prompt
    assert "Answer: Notch" in prompt
    assert "Never ask for the question" in prompt
    assert "Use live web search when available" in prompt
    assert "Use at most 3 web searches" in prompt
    assert "Do not run shell commands" in prompt
    assert "<quiz_question>Who created Minecraft?</quiz_question>" in prompt
    assert prompt.rstrip().endswith("Answer only:")


def test_clean_answer_uses_first_non_empty_line_and_removes_prefix():
    output = "\n\nAnswer: Notch\nExtra text\n"

    assert clean_answer(output) == "Notch"


def test_clean_answer_strips_quotes_and_trailing_period():
    assert clean_answer('"Creeper."') == "Creeper"


def test_clean_answer_keeps_abbreviation_periods():
    assert clean_answer("U.S.") == "U.S."


def test_clean_answer_rejects_clarification_request():
    assert clean_answer("Please provide the question.") is None


def test_clean_answer_rejects_unknown_answer():
    assert clean_answer("UNKNOWN") is None


def test_ask_builds_codex_exec_command_and_sends_prompt_on_stdin(tmp_path, monkeypatch):
    calls = []

    def fake_run(
        command,
        timeout,
        check,
        capture_output,
        text,
        input,
        encoding,
        errors,
    ):
        calls.append(
            {
                "command": command,
                "timeout": timeout,
                "check": check,
                "capture_output": capture_output,
                "text": text,
                "input": input,
                "encoding": encoding,
                "errors": errors,
            }
        )
        output_path = command[command.index("--output-last-message") + 1]
        output_path.write_text("Notch\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda command: None)
    config = BotConfig(codex_model="gpt-5.4-mini", codex_timeout_seconds=4)
    client = CodexAnswerClient(config=config, workspace=tmp_path)

    assert client.ask("Who created Minecraft?") == "Notch"

    command = calls[0]["command"]
    assert command[:4] == ["codex", "--ask-for-approval", "never", "exec"]
    assert "gpt-5.4-mini" in command
    assert "-c" in command
    assert 'model_reasoning_effort="low"' in command
    assert "--sandbox" in command
    assert "--ask-for-approval" in command
    assert command.index("--ask-for-approval") < command.index("exec")
    assert "--ephemeral" in command
    assert "--color" in command
    assert "--output-last-message" in command
    assert command[-1] == "-"
    assert calls[0]["timeout"] == 4
    assert calls[0]["input"] == build_prompt("Who created Minecraft?")
    assert calls[0]["encoding"] == "utf-8"
    assert calls[0]["errors"] == "replace"


def test_ask_inserts_search_flag_before_exec(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, timeout, check, capture_output, text, input, **kwargs):
        calls.append(command)
        output_path = command[command.index("--output-last-message") + 1]
        output_path.write_text("Creeper\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda command: None)
    client = CodexAnswerClient(
        config=BotConfig(codex_enable_search=True),
        workspace=tmp_path,
    )

    assert client.ask("What mob explodes near players?") == "Creeper"
    assert calls[0][:5] == ["codex", "--search", "--ask-for-approval", "never", "exec"]


def test_ask_uses_live_runtime_config(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, timeout, check, capture_output, text, input, **kwargs):
        calls.append({"command": command, "timeout": timeout})
        output_path = command[command.index("--output-last-message") + 1]
        output_path.write_text("Creeper\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda command: None)
    live_config = BotConfig(codex_enable_search=False, codex_timeout_seconds=6)
    client = CodexAnswerClient(
        config=live_config,
        workspace=tmp_path,
        config_provider=lambda: live_config,
    )

    live_config = BotConfig(codex_enable_search=True, codex_timeout_seconds=6)

    assert client.ask("What mob explodes near players?") == "Creeper"
    assert calls[0]["command"][:5] == [
        "codex",
        "--search",
        "--ask-for-approval",
        "never",
        "exec",
    ]
    assert calls[0]["timeout"] == 6


def test_ask_uses_resolved_codex_command_path(tmp_path, monkeypatch):
    calls = []
    resolved_command = r"C:\nvm4w\nodejs\codex.CMD"

    def fake_which(command):
        assert command == "codex"
        return resolved_command

    def fake_run(command, timeout, check, capture_output, text, input, **kwargs):
        calls.append(command)
        output_path = command[command.index("--output-last-message") + 1]
        output_path.write_text("Notch\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(shutil, "which", fake_which)
    monkeypatch.setattr(subprocess, "run", fake_run)
    client = CodexAnswerClient(config=BotConfig(), workspace=tmp_path)

    assert client.ask("Who created Minecraft?") == "Notch"
    assert calls[0][0] == resolved_command


def test_ask_returns_none_on_timeout(tmp_path, monkeypatch):
    def fake_run(command, timeout, check, capture_output, text, input, **kwargs):
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = CodexAnswerClient(config=BotConfig(codex_timeout_seconds=1), workspace=tmp_path)

    assert client.ask("Who created Minecraft?") is None
    assert client.last_debug_log is not None
    assert "Codex CLI timed out after 1 seconds" in client.last_debug_log
    assert "partial stdout" in client.last_debug_log
    assert "partial stderr" in client.last_debug_log

    debug_log = tmp_path / ".tmp" / "codex_cli_debug.log"
    assert debug_log.exists()
    assert "Who created Minecraft?" in debug_log.read_text(encoding="utf-8")


def test_ask_returns_none_on_called_process_error(tmp_path, monkeypatch):
    def fake_run(command, timeout, check, capture_output, text, input, **kwargs):
        output_path = command[command.index("--output-last-message") + 1]
        raise subprocess.CalledProcessError(
            1,
            command,
            output="codex stdout",
            stderr="codex stderr",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = CodexAnswerClient(config=BotConfig(), workspace=tmp_path)

    assert client.ask("Who created Minecraft?") is None
    assert client.last_debug_log is not None
    assert "Codex CLI failed with exit code 1" in client.last_debug_log
    assert "codex stdout" in client.last_debug_log
    assert "codex stderr" in client.last_debug_log


def test_ask_uses_output_file_answer_even_when_codex_exits_nonzero(tmp_path, monkeypatch):
    def fake_run(command, timeout, check, capture_output, text, input, **kwargs):
        output_path = command[command.index("--output-last-message") + 1]
        output_path.write_text("Chloe\n", encoding="utf-8")
        raise subprocess.CalledProcessError(
            1,
            command,
            output="codex stdout",
            stderr="auth plugin failed",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = CodexAnswerClient(config=BotConfig(), workspace=tmp_path)

    assert client.ask("Who is Fixers Broom inspired by?") == "Chloe"
    assert client.last_debug_log is None


def test_ask_uses_output_file_answer_even_when_codex_times_out(tmp_path, monkeypatch):
    def fake_run(command, timeout, check, capture_output, text, input, **kwargs):
        output_path = command[command.index("--output-last-message") + 1]
        output_path.write_text("Ramadan\n", encoding="utf-8")
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = CodexAnswerClient(config=BotConfig(codex_timeout_seconds=1), workspace=tmp_path)

    assert client.ask("Mamah Moona happens during which month?") == "Ramadan"
    assert client.last_debug_log is None


def test_ask_returns_none_on_os_error(tmp_path, monkeypatch):
    def fake_run(command, timeout, check, capture_output, text, input, **kwargs):
        raise OSError("codex not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = CodexAnswerClient(config=BotConfig(), workspace=tmp_path)

    assert client.ask("Who created Minecraft?") is None
    assert client.last_debug_log is not None
    assert "Codex CLI could not start: codex not found" in client.last_debug_log
