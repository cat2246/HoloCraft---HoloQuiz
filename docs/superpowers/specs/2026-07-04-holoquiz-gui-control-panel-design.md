# HoloQuiz GUI Control Panel Design

## Goal

Add a desktop GUI that lets the user control the running HoloQuiz bot with buttons and inputs instead of editing `config.json` while the process is running.

## Recommended Approach

The GUI becomes the main launcher and control panel for the bot. It starts the log watcher in a background thread, exposes live controls, and shows bot output in the window. This is better than a settings-only editor because the requested toggles are runtime behavior: pausing the whole program, toggling answer lookup, switching dry-run, and changing send delay should take effect without a restart.

## Controls

- Whole program: pauses or resumes HoloQuiz processing. When paused, log lines are still tailed so the app stays current, but the bot does not process quiz events.
- Auto getting answer: controls whether the current answer-finding function runs for questions. This is represented as the first function in a registry, `find_answer`, so later functions can be added with the same toggle model.
- Dry-run: switches live between dry-run and real chat sending.
- Send delay seconds: minimum and maximum numeric values. `ChatSender` randomly picks a delay in that range immediately before each live send.

## Architecture

- `holoquiz.runtime` owns thread-safe runtime controls and a function registry.
- `HoloQuizBot` reads runtime controls on every log line or question instead of relying only on startup config.
- `CodexAnswerClient` and `ChatSender` receive a config provider so they can use the latest merged config each time they act.
- `holoquiz.gui` owns the Tkinter window, starts/stops the bot thread, updates runtime controls, and redirects bot log messages into a scrolling text area.
- `holoquiz_bot.py` continues to run the CLI bot for compatibility. A new `holoquiz_gui.py` launches the GUI.

## Data Flow

1. GUI loads `config.json` into a base `BotConfig`.
2. GUI creates `RuntimeControls.from_config(config)`.
3. Bot thread builds `HoloQuizBot`, `CodexAnswerClient`, and `ChatSender` with access to `RuntimeControls.get_config`.
4. GUI button clicks update `RuntimeControls`.
5. Bot checks `program_enabled` and `find_answer` before handling questions.
6. Sender reads the latest `dry_run` and `send_delay_seconds` at send time.

## Future Functions

Functions are defined by stable keys and labels in a registry. The first key is `find_answer`. A future function can be added by registering another key, checking that key where the behavior runs, and the GUI will render another toggle row.

## Testing

Tests cover:

- Runtime controls merge mutable GUI values into a frozen `BotConfig`.
- Disabled program ignores incoming quiz lines.
- Disabled `find_answer` does not ask Codex or send an answer.
- Sender and Codex client can use updated config from a provider.
- GUI can construct its controller without launching a blocking main loop.
