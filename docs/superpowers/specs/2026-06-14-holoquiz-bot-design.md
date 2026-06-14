# HoloQuiz Bot Design

## Goal

Build a Windows Python helper that watches Minecraft Java Edition chat logs from a TLauncher-based client, detects non-math `[HoloQuiz]` questions in real time, answers them from a local JSON memory when possible, falls back to Codex CLI for unknown questions, and optionally types the answer into Minecraft chat.

The first implementation should be conservative: it should default to dry-run mode so the user can verify detection and answers before enabling automatic chat sending.

## Scope

In scope:

- Watch a Minecraft `latest.log` file in real time.
- Detect chat lines containing `[System] [CHAT] [HoloQuiz]`.
- Extract quiz questions from those lines.
- Ignore arithmetic/math-expression prompts such as `(2+3-0/5)+13 = ?`.
- Store known correct answers in `quiz_memory.json`.
- Reuse stored answers before calling Codex CLI.
- Call Codex CLI for unknown non-math trivia, Minecraft, HoloCraft, or general quiz questions.
- Watch later HoloQuiz result lines such as `The answer was X` and use them to correct or add the answer in memory.
- Type answers into Minecraft chat with an AHK-style sequence: `t`, answer text, `Enter`.
- Provide a dry-run mode that prints intended answers without sending keystrokes.

Out of scope for the first version:

- Screen scraping the Developer Console window.
- Direct Minecraft protocol injection.
- Fabric, Forge, or server-side plugins.
- Web search as a separate feature outside Codex CLI.
- Solving math-expression questions.
- Anti-cheat bypasses or attempts to hide automation.

## Assumptions

- The game is Minecraft Java Edition launched through TLauncher on Windows.
- Minecraft writes chat output to a normal log file, usually under a `.minecraft/logs/latest.log` path.
- The user can provide the exact log path in `config.json` if auto-detection fails.
- Codex CLI is installed and callable from PowerShell with a configurable command.
- Minecraft is the active foreground window when automatic sending is enabled.
- The user is responsible for only using automation where it is allowed by the server rules.

## Architecture

The project will be a small Python command-line app with five main responsibilities:

1. `LogTailer`
   Watches the configured Minecraft log file and yields new lines as they are appended.

2. `HoloQuizParser`
   Identifies HoloQuiz question lines, answer-reveal lines, and irrelevant chat lines. It also rejects math-expression prompts.

3. `QuizMemory`
   Loads, searches, and updates `quiz_memory.json`. It normalizes question text so repeated questions can be matched even if whitespace or punctuation changes slightly.

4. `AnswerService`
   Looks up an answer from memory first. If no answer exists, it asks Codex CLI for a short answer and returns that candidate.

5. `ChatSender`
   Sends the chosen answer through keyboard automation only when `dry_run` is false. The sender should support a small configurable delay before sending.

The main loop connects these pieces: log line -> parsed event -> memory lookup or Codex fallback -> dry-run print or keyboard send -> later answer reveal updates memory.

## Data Flow

For a new HoloQuiz question:

1. A new log line appears.
2. The parser extracts the question text.
3. The parser checks whether it is a math-expression prompt.
4. If it is math, the app logs `ignored_math` and does nothing.
5. If it is non-math, the app normalizes the question.
6. The memory checks for an exact normalized match.
7. If found, the memory answer is used.
8. If not found, Codex CLI is asked for a concise answer.
9. The app records the pending question and candidate answer.
10. In dry-run mode, the app prints the answer. In live mode, it types the answer into Minecraft chat.

For an answer reveal:

1. A log line says no one got the answer or otherwise reveals `The answer was X`.
2. If there is a recent pending question, the app saves or corrects that question's answer in `quiz_memory.json`.
3. If the answer reveals that the Codex candidate was wrong, the stored answer becomes the revealed answer.

## JSON Memory Format

`quiz_memory.json` should be simple and editable:

```json
{
  "version": 1,
  "questions": {
    "what block is required to make an enchantment table": {
      "question": "What block is required to make an enchantment table?",
      "answer": "obsidian",
      "source": "answer_reveal",
      "times_seen": 3,
      "times_used": 2,
      "last_seen": "2026-06-14T18:00:00+08:00",
      "last_corrected": "2026-06-14T18:01:00+08:00"
    }
  }
}
```

The key is the normalized question. The original question remains stored for readability.

## Configuration

`config.json` should include:

```json
{
  "log_path": "",
  "dry_run": true,
  "codex_command": "codex",
  "codex_model": "gpt-5.4-mini",
  "codex_timeout_seconds": 6,
  "codex_enable_search": false,
  "codex_persistent_session": false,
  "send_delay_seconds": 0.8,
  "question_cooldown_seconds": 3.0,
  "keyboard_open_chat_key": "t",
  "typing_interval_seconds": 0.01
}
```

If `log_path` is empty, the app can try common TLauncher and `.minecraft` locations and show a clear error if none is found.

`gpt-5.4-mini` is the default fallback model because the bot needs low latency but still needs enough accuracy for Minecraft and trivia questions. `gpt-5.4-nano` can be tested later as a faster, cheaper option if accuracy is acceptable. `codex_enable_search` defaults to false because web search adds latency and the JSON memory should be the main speed layer.

`codex_persistent_session` is included for future experimentation, but the first version should keep it false and use one `codex exec` subprocess per unknown question. This is easier to make reliable than driving an interactive terminal session from Python.

## Codex CLI Call

For unknown non-math questions, the first version should call Codex CLI non-interactively:

```powershell
codex exec -m gpt-5.4-mini --sandbox read-only --ask-for-approval never --ephemeral --color never --output-last-message <temp-answer-file> "<prompt>"
```

If `codex_enable_search` is true, append `--search`. Search should stay off by default for speed.

The app should read the final answer from `<temp-answer-file>` rather than parsing terminal output. It should enforce `codex_timeout_seconds`; if Codex does not answer in time, the app should skip sending an answer for that question instead of sending late or uncertain text.

## Codex CLI Prompt

For unknown non-math questions, the app should call Codex CLI with a constrained prompt:

```text
You answer Minecraft server quiz questions.

Return ONLY the answer text.
No explanation.
No punctuation unless it is part of the answer.
Use the shortest common answer.
If the question asks for a number, return digits only.
If unsure, return the best likely answer.
Do not run tools or commands.

Examples:
Question: What mob explodes near players?
Answer: Creeper

Question: What ore is used to make a beacon base?
Answer: Iron

Question: Who created Minecraft?
Answer: Notch

Question: <question>
Answer:
```

The app should trim whitespace and use only the first non-empty output line as the candidate answer. If the first non-empty line starts with `Answer:`, the app should remove that prefix before sending.

## Keyboard Sender

The first version will use Python keyboard automation, most likely `pyautogui`, because it is simple and close to the desired AHK behavior.

Live-send sequence:

1. Wait `send_delay_seconds`.
2. Press the configured chat key, usually `t`.
3. Type the answer.
4. Press `Enter`.

Dry-run mode must be the default. The app should print exactly what it would send so the user can test safely.

## Error Handling

- Missing log file: print likely paths and ask the user to set `log_path`.
- Invalid JSON memory: create a timestamped backup and start with an empty memory file.
- Codex CLI failure: log the error and skip sending rather than sending a bad answer.
- Keyboard automation failure: print the failure and continue watching logs.
- Duplicate question spam: ignore repeated questions within `question_cooldown_seconds`.
- File rotation or log truncation: reopen the log when the file size becomes smaller than the current read position.

## Testing

The first implementation should include focused tests for the parser and memory behavior:

- Extract HoloQuiz questions from sample log lines.
- Ignore non-HoloQuiz chat.
- Ignore math-expression prompts.
- Extract `The answer was X` reveal lines.
- Normalize repeated question variants to the same key.
- Save and reload JSON memory.

Manual verification:

- Run the app in dry-run mode against a sample log file.
- Append sample HoloQuiz lines and confirm expected output.
- Enable live mode only after dry-run detection is correct.

## Risks

- TLauncher log path may vary by installation.
- Some HoloQuiz lines may wrap visually in the Developer Console but still be complete in `latest.log`.
- Codex CLI may be slower than the quiz timer for unknown questions.
- Keyboard sending depends on Minecraft being focused.
- Server rules may disallow automation; the tool should not attempt to evade detection or bypass restrictions.

## Recommended First Milestone

Build a dry-run watcher first:

- Load config and memory.
- Watch the log file.
- Detect and print answers without keyboard sending.
- Update memory from answer reveals.

After this works, enable the keyboard sender behind `dry_run: false`.
