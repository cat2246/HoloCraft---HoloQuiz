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

## Run With GUI

```powershell
python holoquiz_gui.py
```

Or double-click `run_bot.bat`.

The control panel starts the bot in the background and lets you change live behavior:

- `Whole program` pauses or resumes quiz processing.
- `Dry-run` switches between previewing answers and sending them to Minecraft chat.
- `Send delay seconds` accepts a minimum and maximum. If you enter `1` to `3`, each answer waits for a random delay between 1 and 3 seconds before live sending.
- `HoloQuiz > Find answer` toggles the current auto answer function. Other quiz actions, such as browser search, live in this section.
- `Trigger Phase > Screen phrase watcher` supports `Screen OCR` and `Title API` sources. Screen OCR reads the selected trigger and result areas. Title API reads `http://127.0.0.1:8026/data/title`, treating `subtitle` as the trigger text and `title` as the result; `Check API status` queries `http://127.0.0.1:8026/health`. In either mode, the configured `Trigger phrase` must match the trigger text. With `Auto send result` enabled, Title API polls once per second and only sends after the same title is read 5 consecutive times; a changed title restarts the count. Each API send requires a fresh 5-read sequence. Trigger result sending ignores HoloQuiz dry-run and has a 15-second cooldown.
- `Chat Trigger` lets you create log-line triggers with a `Trigger Phase`, `Micro`, cooldown, and per-trigger typing interval. Its `Dry-run` checkbox is separate from the main HoloQuiz dry-run. For example, trigger on `Good Morning!` and use `tGood Morning{{Enter}}` to open chat, type the message, and press Enter. Set `Typing interval` to `0.1` if you want typed characters or repeated macro tokens to wait 0.1 seconds before the next input. Tokens use double braces, such as `{{Enter}}`, `{{Escape}}`, `{{Ctrl+V}}`, `{{LButton}}`, `{{RButton}}`, and `{{MButton}}`.

The screen phrase watcher's trigger phrase, selected trigger/result areas, and chat triggers are saved in `config.json`, so reopening the GUI restores them automatically.

The screen phrase watcher uses Tesseract OCR. Install the Tesseract app on Windows and make sure it is available on `PATH`; then reinstall the Python package with `python -m pip install -e ".[dev]"` so `pytesseract` and `pillow` are available.

## Run Without GUI

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
t -> Ctrl+V answer -> Enter
```

Clipboard paste is the default because it is faster and more reliable in Minecraft than typing each character. Set `"send_mode": "type"` in `config.json` if you want the older character-by-character sender.

## Codex CLI

Unknown questions use:

```powershell
<prompt> | codex --ask-for-approval never exec -c 'model_reasoning_effort="low"' -m gpt-5.4 --sandbox read-only --ephemeral --color never --output-last-message <temp-answer-file> -
```

Change `codex_model` in `config.json` if your Codex CLI does not have access to the default model.
The bot also sets `codex_reasoning_effort` to `low` by default, which reduces reasoning tokens while keeping the stronger default model. For lower token use, set `codex_enable_search` to `false` or switch `codex_model` to a smaller model such as `gpt-5.4-mini`, but both can reduce answer accuracy.

On Windows, the bot resolves `codex` through `PATH` before launching it, so npm shims such as `codex.cmd` work correctly. If the debug log still says Codex cannot start, set `codex_command` in `config.json` to the full path of your Codex executable or `.cmd` shim.

If Codex returns no usable answer, the bot prints the Codex CLI debug details in the console and appends them to:

```text
.tmp/codex_cli_debug.log
```

## Memory

Known answers are stored in `quiz_memory.json`. The bot updates this file when Minecraft reveals:

```text
The answer was Notch.
```

The JSON file is editable, so you can correct answers manually.

## Safety Notes

Start in dry-run mode, watch the console output, and only enable live sending after you are confident the detected questions and answers are correct. Keep Minecraft focused while live sending is enabled, because the bot types into the active window.
