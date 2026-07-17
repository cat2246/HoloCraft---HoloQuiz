# HoloQuiz Module Toggle and Delay Persistence Design

## Goal

Add a persistent HoloQuiz-only master checkbox and persist the send-delay range applied from the HoloQuiz tab. The new switch must not pause unrelated HoloCraft Tools modules.

## User Experience

- Add a `HoloQuiz enabled` checkbox near the top of the `Answer automation` section.
- The checkbox is independent of the global `Program enabled` switch and the existing `Find answer` checkbox.
- Turning HoloQuiz off takes effect immediately. New HoloQuiz questions and answer reveals are ignored, so the module does not search, send, or learn answers while disabled.
- Screen Watcher, Chat Triggers, Coordinate Lock, and Activity remain available while only HoloQuiz is disabled.
- The checkbox defaults to enabled for existing configurations and keeps its last value after restart.
- Pressing `Apply` for `Send delay seconds` keeps the current validation and live update behavior, then persists the accepted minimum and maximum values. The fields restore those values after restart.
- Invalid delay input is not applied or saved, and the existing validation message remains visible.

## Architecture

Add a `holoquiz_enabled` boolean to `BotConfig`, defaulting to `True`. Mirror it in `RuntimeControls` and `RuntimeSnapshot` so the GUI and background bot share one thread-safe live value. Add a controller method for updating the value.

The HoloQuiz checkbox owns a Tk BooleanVar initialized from the runtime snapshot. Its toggle handler updates runtime controls immediately and persists `holoquiz_enabled` to `config.json` through a focused config helper that preserves unrelated keys.

`HoloQuizBot.handle_line` continues to honor the global program switch first and continues processing chat triggers while the program is running. It then checks `holoquiz_enabled` before parsing HoloQuiz events. This keeps non-HoloQuiz behavior active while preventing questions and answer reveals from reaching HoloQuiz state, memory, lookup, or sending paths.

Extend the successful delay-apply path to persist `send_delay_seconds`, `send_delay_min_seconds`, and `send_delay_max_seconds`. The compatibility value `send_delay_seconds` is saved as the accepted minimum, matching the runtime control's current range-update behavior. A focused helper updates only these keys and preserves all unrelated config values.

## Data Flow

### Module Toggle

1. `load_config` reads `holoquiz_enabled`, or uses `True` when the key is absent.
2. `RuntimeControls` initializes the live value and exposes it through snapshots and current config.
3. The GUI initializes `HoloQuiz enabled` from the snapshot.
4. A toggle updates runtime controls and persists the setting immediately.
5. The bot checks the live setting before processing HoloQuiz events.

### Send Delay

1. The GUI initializes both delay fields from the loaded minimum and maximum settings.
2. The user edits the fields and presses `Apply`.
3. The controller validates and updates the live delay range.
4. Only after a successful update, the GUI persists the accepted delay values.
5. A later launch loads the saved range into the same fields.

## Error Handling

Delay parsing and range validation retain the existing errors for non-numeric, negative, or reversed values. Persistence is skipped whenever validation fails. Config helpers retain the project's current JSON-root validation behavior and do not silently overwrite malformed configuration data.

## Testing

- Config tests verify the new default, explicit loading, compatibility with missing settings, and focused persistence for both the module toggle and delay range.
- Runtime tests verify that the HoloQuiz enabled state and delay range update snapshots and current config.
- Runner tests verify that disabling HoloQuiz suppresses question and answer-reveal processing while chat triggers still run.
- GUI/controller tests verify checkbox wiring, immediate persistence, successful delay persistence, and no persistence after invalid delay input.
- Run the full pytest suite, Python module compilation, and whitespace checks before completion.

## Out of Scope

- Removing or changing the global `Program enabled` switch.
- Removing or merging the existing `Find answer` checkbox.
- Persisting unsaved text typed into the delay fields before `Apply` is pressed.
- Changing delay behavior for Screen Watcher, Chat Triggers, or Coordinate Lock.
