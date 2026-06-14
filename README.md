# HoloQuiz Bot

HoloQuiz Bot watches Minecraft Java Edition logs, detects non-math `[HoloQuiz]` questions, answers from `quiz_memory.json`, asks Codex CLI for unknown questions, and can type the answer into Minecraft chat.

Use this only where server rules allow automation.

## Setup

```powershell
python -m pip install -e ".[dev]"
```

The first run creates `config.json` if it is missing. The bot creates `quiz_memory.json` once it successfully resolves a Minecraft log path and starts building the bot.

## Configure

Copy the example config:

```powershell
Copy-Item config.example.json config.json
```

Set `log_path` if automatic discovery cannot find your Minecraft or TLauncher log:

```json
{
  "log_path": "C:/Users/you/AppData/Roaming/.minecraft/logs/latest.log",
  "dry_run": true
}
```

Keep `dry_run` as `true` until you confirm the bot detects the correct questions. If the bot prints `No Minecraft latest.log found`, set `log_path` to the real `latest.log` path before running again.

## Run

```powershell
python holoquiz_bot.py
```

In dry-run mode the bot prints answers:

```text
[memory] Who created Minecraft? -> Notch
[dry-run] Would send answer: Notch
```

## Enable Live Sending

After dry-run works, edit `config.json`:

```json
{
  "dry_run": false
}
```

Put Minecraft in the foreground. The bot sends answers with:

```text
t -> answer -> Enter
```

## Codex CLI

Unknown questions use:

```powershell
codex exec -m gpt-5.4-mini --sandbox read-only --ask-for-approval never --ephemeral --color never --output-last-message <temp-answer-file> "<prompt>"
```

Change `codex_model` in `config.json` if your Codex CLI does not have access to the default model.

## Memory

Known answers are stored in `quiz_memory.json`. The bot updates this file when Minecraft reveals:

```text
The answer was Notch.
```

The JSON file is editable, so you can correct answers manually.

## Safety Notes

Start in dry-run mode, watch the console output, and only enable live sending after you are confident the detected questions and answers are correct. Keep Minecraft focused while live sending is enabled, because the bot types into the active window.
