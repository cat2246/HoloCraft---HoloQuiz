# Answer Sound Toggle Design

## Goal

Add a persistent checkbox to the HoloQuiz panel that lets the user mute or unmute the notification sound played when HoloQuiz finds an answer in dry-run mode.

## User Experience

- Add a `Mute answer sound` checkbox beside the existing `Find answer` control.
- The checkbox is unchecked by default, so existing installations continue to play the configured answer sound.
- Checking it takes effect immediately and persists to `config.json`.
- Restarting the application restores the saved checkbox state.
- Muting affects only the answer-found sound. It does not disable answer lookup, copying answers in dry-run mode, live answer delivery, browser search, screen-watcher sounds, or chat-trigger sounds.

## Architecture

Add an `answer_sound_enabled` boolean to `BotConfig`, defaulting to `True`. Existing config files that omit the field inherit this default. Include the value in runtime state so GUI changes are visible immediately to the worker without restarting.

The GUI owns an `answer_sound_muted_var` whose value is the inverse of `answer_sound_enabled`. Its toggle handler updates runtime controls and writes the new setting to `config.json` immediately through a focused config persistence helper.

`ChatSender` already reads the latest runtime config before sending an answer. Its dry-run sound method will return without playing when `answer_sound_enabled` is false. Answer copying and logging remain unchanged.

## Data Flow

1. `load_config` reads `answer_sound_enabled`, or uses `True` when the field is absent.
2. `RuntimeControls` initializes and exposes the setting through snapshots/current config.
3. The GUI initializes `Mute answer sound` as `not answer_sound_enabled`.
4. Toggling the checkbox updates runtime controls and persists `answer_sound_enabled`.
5. When a dry-run answer is found, `ChatSender` obtains current config and plays the configured sound only when the setting is enabled.

## Error Handling

Config persistence follows the project's existing JSON validation behavior. If the config root is invalid, the existing error is allowed to surface rather than silently overwriting user data. Sound playback retains its current warning behavior for missing files or playback failures.

## Testing

- Config tests verify the default field, loading explicit false, saving the toggle, and compatibility with config files that omit it.
- Runtime tests verify that toggling the setting updates both the snapshot and current config.
- GUI/controller tests verify that the mute action updates runtime state and persists the inverse enabled value.
- Chat sender tests verify that a dry-run answer still copies normally while muted and does not invoke sound playback.
- Run the complete pytest suite and Python module compilation before completion.

## Out of Scope

- Selecting or changing the answer sound file.
- Muting screen-watcher or chat-trigger sounds.
- Adding a master mute for every HoloCraft Tools feature.
