# Percentage Auto Heal and Hotbar Restoration Design

## Goal

Change Auto Heal health and hunger thresholds from absolute values to integer
percentages, and restore the hotbar slot that was selected immediately before
Auto Heal switched to a healing item.

This feature spans HoloQuiz and Minecraft Local Data API. The API supplies the
selected slot; HoloQuiz remains backward-compatible with API responses that do
not yet contain that field.

## Percentage Rule Model

Replace the absolute rule fields with:

- `health_percent_below: int = 0`
- `hunger_percent_below: int = 0`

Both fields accept integers from 0 through 100. Zero disables that condition,
and at least one condition must be greater than zero. The existing OR behavior
and strict comparison remain: a rule triggers when an enabled current
percentage is strictly less than its configured percentage.

Health percentage is:

`current health / maximum health * 100`

Absorption health is excluded. If maximum health is zero or invalid, the
health condition cannot trigger for that snapshot. Hunger percentage is:

`food level / 20 * 100`

Hunger therefore changes in five-percentage-point increments. Both calculated
percentages are clamped to the range 0 through 100 before comparison.

## Configuration Migration

Newly saved rules use `health_percent_below` and `hunger_percent_below` in
`config.json`. Loading remains compatible with old rules:

- If a new percentage key exists, use it.
- Otherwise, read the corresponding legacy `health_below` or `hunger_below`
  number as the same percentage value.
- If both forms exist, the new percentage key wins.

The user selected same-number migration: legacy `20` becomes `20%`; it is not
converted from the former absolute scale. Loading alone does not rewrite the
user's file. The next Auto Heal save serializes every rule with only the new
percentage keys while preserving unrelated configuration values.

Legacy values must still pass the new integer and 0-through-100 validation.
A fractional or out-of-range legacy threshold produces a field-specific
configuration error instead of silently rounding or clamping it.

## Player API Contract

Minecraft Local Data API adds this root field to `/data/player` v2:

- `selected_hotbar_slot`: integer 0 through 8 when connected, otherwise
  `null`.

The value comes from the Minecraft client player's selected inventory slot in
the same client-thread snapshot as health and inventory. It is zero-based and
maps directly to keyboard keys 1 through 9.

The v2 Java record, JSON serializer, disconnected response, JSON schema,
example payload, README, and unit tests all include the field. This is added to
the current undeployed v2 source contract without changing the endpoint path.

HoloQuiz adds `selected_hotbar_slot: int | None = None` to `PlayerSnapshot`.
The parser accepts the missing or JSON-null field as `None` for compatibility
with the currently installed v1 API. A supplied value outside 0 through 8 is
rejected as malformed player data.

## Auto Heal Input Sequence

Each worker cycle uses one player snapshot for threshold selection and the
original slot:

1. Read `selected_hotbar_slot` from the fresh connected snapshot.
2. Select the highest-priority eligible healing item using the existing
   right-to-left hotbar scan.
3. Recheck the foreground, container, shutdown, and input-coordinator gates.
4. Press the healing item's 1-through-9 key.
5. Hold right-click for the configured use duration.
6. Release right-click in `finally` whenever a press was attempted.
7. After release, press the original slot's 1-through-9 key when restoration
   remains safe.

Restoration is skipped when the original slot is unavailable, already equals
the healing slot, Minecraft is no longer foreground, a container is open, or
shutdown has begun. These gates prevent the restoration key from reaching a
different application or violating the worker's no-input-after-stop
guarantee.

Once Auto Heal has changed slots, it attempts safe restoration even if the
right-click backend or duration wait fails. Cooldown still begins only after a
completed, uninterrupted use. Failure to restore does not convert an otherwise
completed use into a failed use and does not cause an immediate retry loop.

## User Interface

The Auto Heal dialog labels become:

- `Use when health below (%)`
- `Use when hunger below (%)`

Both fields accept integer text only and show specific errors for fractional,
negative, or greater-than-100 values. The rule listing renders thresholds as
`Health < 50%` and `Hunger < 50%`. Existing Edit and right-click flows use the
same parsing, validation, persistence, and exact-name identity behavior.

## Error Handling and Compatibility

- An older API without `selected_hotbar_slot` continues to support Auto Heal;
  only slot restoration is unavailable.
- A disconnected API v2 payload returns `selected_hotbar_slot: null`.
- Invalid maximum health disables only the health condition for that snapshot;
  a valid hunger condition may still trigger.
- Input release remains guaranteed before any restoration attempt.
- Restoration never injects a key after shutdown or while the environment is
  unsafe.
- Existing cooldown, foreground, container, and input-coordination behavior is
  unchanged.

## Testing and Verification

Minecraft Local Data API tests cover connected serialization, disconnected
null output, the 0-through-8 schema bounds, snapshot capture, and the example
payload. Run `gradlew.bat test` and `gradlew.bat build` with the repository's
required JDK.

HoloQuiz tests cover legacy config migration, new serialization, integer
validation, percentage boundary math, missing/invalid selected-slot parsing,
restore key order, same-slot suppression, unsafe restoration suppression,
interruption/error release behavior, and shutdown safety. Update dialog and
listing tests for percentage labels. Run the complete pytest suite, package
compilation, JSON validation, and live API/UI checks.

## Out of Scope

- Restoring a slot when the selected-slot field is missing.
- Persisting the selected slot in HoloQuiz configuration.
- Including absorption in the health percentage.
- Changing hotbar priority, exact-name matching, cooldown semantics, or use
  duration.
