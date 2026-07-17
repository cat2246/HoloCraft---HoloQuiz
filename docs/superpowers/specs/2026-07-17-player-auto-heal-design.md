# Player Auto Heal Design

## Goal

Add configurable Auto Heal behavior to the Player module. While the application
is running, Auto Heal monitors the connected player's health, hunger, and
hotbar. When a configured threshold is crossed, it uses the highest-priority
eligible item, scanning the hotbar from slot 9 to slot 1.

## Scope

Auto Heal uses only the nine hotbar slots. It does not move items between the
main inventory and hotbar, open the inventory, or use armor/offhand slots.
Users may create a rule by right-clicking any occupied item shown in the Player
inventory, but the rule can activate only when an exact-name match is present
in the hotbar.

The feature runs independently of Player-tab visibility so switching tabs does
not disable protection. Closing the application stops Auto Heal and releases
any held input.

## Configuration Model

Add an immutable `AutoHealItemConfig` value with these fields:

- `name: str`: exact displayed item name returned by `/data/player`. Matching
  is case-sensitive and preserves Unicode and formatting characters so custom
  server items remain distinct.
- `cooldown_seconds: float`: minimum time after a completed use before another
  item with the same configured name may be used. It must be zero or greater.
- `use_duration_seconds: float = 2.0`: how long right-click is held. It must be
  greater than zero.
- `health_below: float = 0.0`: the rule's health threshold. Zero disables this
  condition; positive values are not capped because custom servers can raise
  maximum health above vanilla values.
- `hunger_below: int = 0`: the rule's hunger threshold. Zero disables this
  condition; positive values must be between 1 and 20 inclusive.

A rule is valid only when its trimmed name is non-empty and at least one of
`health_below` or `hunger_below` is greater than zero. Configured rule names
must be unique. Right-clicking an already configured name edits that rule.

Extend `BotConfig` with:

- `auto_heal_enabled: bool = False`, defaulting off for input safety.
- `auto_heal_items: tuple[AutoHealItemConfig, ...] = ()`.

Store these as `auto_heal_enabled` and `auto_heal_items` in `config.json`.
Loading a configuration without these keys uses the safe defaults. Saving,
editing, removing, or toggling a rule preserves unrelated configuration keys.
`config.example.json` documents both keys and the 2-second use-duration
default.

## Runtime Architecture

Implement a dedicated `AutoHealWorker` rather than coupling automation to the
Player tab's visibility-controlled poller. The worker owns its background
thread, receives `RuntimeControls`, a player client, a container-state client,
a foreground-window predicate, an input backend, the shared input coordinator,
and a status sink. Dependencies are injectable so tests do not require a live
Minecraft client, display, or wall-clock sleeps.

The worker polls approximately four times per second. Each cycle:

1. Read the current runtime configuration.
2. Stop before fetching when the program or Auto Heal is disabled or no rules
   exist.
3. Fetch `/data/player` and require a connected snapshot.
4. Require Minecraft to be the foreground application and require that no
   inventory/container screen is open.
5. Examine hotbar slots in descending inventory-slot order, 8 through 0.
6. For each occupied slot, find the rule whose `name` exactly equals the
   item's displayed name.
7. Skip rules still on cooldown or whose enabled thresholds are not crossed.
8. Use the first eligible slot and end the scan for that cycle.

A threshold is crossed when either `current health < health_below` or
`food_level < hunger_below`; a zero threshold is ignored. Strict comparison
prevents activation when the value equals the configured boundary.

Cooldowns are tracked per exact item name with a monotonic clock and begin
after the use action completes. Restarting the application clears elapsed
cooldown state; cooldown timestamps are runtime state and are not persisted.
If a higher-priority item is cooling down, unconfigured, absent, or does not
currently meet a threshold, the scan continues left.

## Input Behavior and Coordination

For hotbar inventory slot `n` (zero-based), press key `n + 1`, hold the right
mouse button for the configured duration, and release it. The used slot remains
selected because `/data/player` does not expose the previously selected
hotbar slot.

Extend the shared keyboard input coordinator with an exclusive item-use
session. While that session is active:

- Coordinate Lock movement waits rather than injecting movement keys.
- Auto Hit skips left-click attacks so they cannot interrupt eating/drinking.
- Chat input waits until the current use completes and then retains its normal
  priority over subsequent automated sessions.

The worker rechecks foreground/container eligibility immediately before
acquiring input. Right-button release occurs in a `finally` block whenever a
press was attempted, including shutdown and backend errors. A failed or denied
input attempt does not start cooldown. Auto Heal is intentionally independent
of the bot's chat `dry_run` option; its separate enable toggle is the explicit
input-safety control.

## Player UI

Add an `Auto Heal` section beneath the rendered inventory. It contains:

- An `Enable Auto Heal` checkbox.
- A concise empty-state message when no rules exist.
- One row per configured item showing the exact name, cooldown, use duration,
  health threshold, and hunger threshold.
- A `Remove` button on each row.

Bind right-click on occupied `ItemSlotWidget` canvases to an add/edit callback.
Empty slots do nothing. Right-clicking opens a modal dialog prefilled with the
item's exact displayed name and default values, or the existing values if that
name is already configured. The name is displayed read-only because it is the
identity captured from the endpoint.

The dialog validates numeric input before saving: cooldown and thresholds must
be non-negative, use duration must be positive, hunger cannot exceed 20, and at
least one threshold must be enabled. Invalid input keeps the dialog open and
shows a specific message. A successful save closes the dialog, refreshes the
listing, updates `RuntimeControls`, and writes `config.json`. Remove performs
the same immediate runtime/persistence update without affecting other rules.

## Runtime and Application Integration

`RuntimeControls` exposes thread-safe getters/setters for the enable flag and
configured tuple, includes them in `get_config()` and `RuntimeSnapshot`, and
validates rules at its mutation boundary.

The control panel creates and starts one Auto Heal worker with the other
long-running workers, passes configuration callbacks into `PlayerTab`, and
stops Auto Heal before destroying the root window. Player-tab activation still
controls only visual polling and icon loading; it does not start or stop Auto
Heal.

Status messages use the existing runtime log. Repeated endpoint or eligibility
errors are deduplicated where practical so a four-times-per-second worker does
not flood the log. Transient failures do not terminate the worker.

## Error Handling

- Invalid JSON configuration fails through the existing configuration error
  path with field-specific validation messages.
- Disconnected or malformed player responses skip the cycle and are retried.
- Missing items, empty hotbar slots, and changed item counts are normal state.
- Foreground, container, or input-session denial skips the cycle without
  consuming cooldown.
- Input backend failures are logged, right-click is released, and later cycles
  may retry.
- Worker shutdown is idempotent and does not leave callbacks or held input.

## Testing

Use test-driven development for each behavior group:

- Configuration tests cover safe defaults, JSON loading, persistence,
  round-tripping Unicode/custom names, duplicate/invalid rules, and preservation
  of unrelated keys.
- Selection tests cover descending hotbar priority, exact-name matching,
  strict/disabled thresholds, cooldown skipping, non-hotbar exclusion, and
  fallback to the next eligible configured item.
- Worker tests cover enable/program gates, disconnected state, foreground and
  container safety, hotbar key mapping, configured hold duration, monotonic
  cooldown timing, denied sessions, error recovery, guaranteed mouse release,
  and clean shutdown.
- Input-coordinator tests prove item use excludes movement/Auto Hit while
  preserving existing concurrent movement-and-Auto-Hit behavior outside an
  item-use session.
- Player-view tests cover right-click binding, add versus edit, dialog
  validation, list formatting, per-row removal, toggle updates, and immediate
  persistence through injected callbacks.
- GUI lifecycle tests cover worker creation, startup, and shutdown.

Final verification runs `python -m pytest`,
`python -m py_compile holoquiz/*.py`, and `git diff --check`, followed by a
manual Player-tab check against the live local endpoint without placing test
items or altering the user's inventory.

## Out of Scope

- Moving items from main inventory into the hotbar.
- Using offhand, armor, or slots outside 0 through 8.
- Restoring a previously selected hotbar slot without endpoint support.
- Inspecting item lore, NBT, effects, or IDs for rule identity.
- Predicting how much health/hunger an item restores.
- Persisting in-progress cooldown timestamps across application restarts.
