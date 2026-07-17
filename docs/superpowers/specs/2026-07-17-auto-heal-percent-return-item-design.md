# Percentage Auto Heal and Return Item Design

## Goal

Change Auto Heal health and hunger thresholds from absolute values to integer
percentages, and add one global Return Item that Auto Heal selects after it
finishes using a healing item.

This design uses the inventory data already available from Minecraft Local Data
API. It does not extend the API and does not attempt to detect the slot that was
selected before Auto Heal started.

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

The selected migration is same-number migration: legacy `20` becomes `20%`;
it is not converted from the former absolute scale. Loading alone does not
rewrite the user's file. The next Auto Heal save serializes every rule with
only the new percentage keys while preserving unrelated configuration values.

Legacy whole-number JSON values such as `20.0` are accepted as `20`. Fractional
or out-of-range values produce a field-specific configuration error instead of
being rounded or clamped.

## Global Return Item

Add one global setting:

`auto_heal_return_item_name: str = ""`

An empty string means no Return Item is configured. The value is the item's
exact display name, including Unicode and formatting characters already
returned by the player inventory endpoint. This follows the same exact-name
identity behavior as healing items and supports custom names such as
`.｡*ﾟ+.*.｡ ʜᴏʟᴏ ᴀɴɴɪᴠ ᴄᴀᴋᴇ ｡+..｡*ﾟ`.

Only an occupied hotbar slot can be selected as the Return Item. The setting is
global rather than per healing rule. Selecting another item replaces the
previous Return Item; clearing it stores an empty string.

At each Auto Heal cycle, the worker searches the fresh player snapshot's
hotbar for the configured exact name. If duplicate exact names exist, the
rightmost hotbar match wins. The resolved slot from that snapshot is retained
for the current use sequence. If the Return Item is absent or outside the
hotbar, healing still proceeds and restoration is skipped.

This feature deliberately returns to the configured item. It does not promise
to restore whichever item the player happened to be holding before Auto Heal.

## Auto Heal Input Sequence

Each worker cycle uses one fresh player snapshot for threshold selection,
healing-item priority, and Return Item resolution:

1. Select the highest-priority eligible healing item using the existing
   right-to-left hotbar scan.
2. Resolve the rightmost exact-name Return Item hotbar slot, if configured.
3. Recheck the foreground, container, shutdown, and input-coordinator gates.
4. Press the healing item's 1-through-9 key.
5. Hold right-click for the configured use duration.
6. Release right-click in `finally` whenever a press was attempted.
7. After release, press the resolved Return Item's 1-through-9 key when doing
   so remains safe.

Return selection is skipped when it is unavailable, equals the healing slot,
Minecraft is no longer foreground, a container is open, or shutdown has
begun. These gates prevent the return key from reaching another application or
violating the worker's no-input-after-stop guarantee.

Once Auto Heal has changed slots, it attempts a safe return even if the
right-click backend or duration wait fails. Cooldown still begins only after a
completed, uninterrupted use. Failure to press the Return Item key does not
convert an otherwise completed use into a failed use and does not cause an
immediate retry loop.

## User Interface

Right-clicking an occupied inventory item opens an item action menu. Every
occupied item offers `Add/Edit Auto Heal Item`. An occupied hotbar item also
offers `Set as Return Item`; this action is not offered for main inventory,
armor, offhand, or extra slots.

The Auto Heal panel shows the global selection as:

`Return Item: <exact item name>    [Clear]`

When no item is configured, it shows `Return Item: None`. The Clear button is
disabled in that state. The selected Return Item has a gold inventory-slot
outline distinct from the existing purple enchanted-item outline. Gold takes
visual precedence when the Return Item is also enchanted; any Auto Heal rule
for that item remains visible in the Auto Heal listing.

The Auto Heal item dialog labels become:

- `Use when health below (%)`
- `Use when hunger below (%)`

Both fields accept integer text only and show specific errors for fractional,
negative, or greater-than-100 values. The rule listing renders thresholds as
`Health < 50%` and `Hunger < 50%`. Existing Edit, Remove, persistence, and
exact-name behavior remain.

## Error Handling and Compatibility

- No Minecraft Local Data API change or deployment is required.
- An empty or missing `auto_heal_return_item_name` loads as no Return Item.
- A configured Return Item may remain saved while temporarily absent; healing
  continues without the return key.
- Invalid maximum health disables only the health condition for that snapshot;
  a valid hunger condition may still trigger.
- Input release is attempted before any Return Item key press.
- No return key is injected after shutdown or while the environment is unsafe.
- Existing cooldown, foreground, container, input-coordination, right-to-left
  healing priority, and exact-name behavior are unchanged.

## Testing and Verification

Configuration tests cover legacy percentage migration, new-key precedence,
new serialization, unrelated-value preservation, Return Item persistence,
Unicode exact names, clearing, and integer validation.

Worker tests cover percentage boundary math, rightmost Return Item resolution,
missing Return Item behavior, release-before-return ordering, same-slot
suppression, unsafe return suppression, interruption/error release behavior,
non-fatal return-key failure, cooldown timing, and shutdown safety.

UI tests cover the hotbar-only action, action-menu routing, global replacement,
Clear behavior, gold marker state, percentage labels, integer form parsing,
and percentage listing text. Run the complete pytest suite, package
compilation, JSON validation, and live Player UI checks.

## Out of Scope

- Detecting or restoring the player's actual pre-heal selected slot.
- Extending Minecraft Local Data API with selected-slot data.
- More than one global Return Item or a separate Return Item per healing rule.
- Moving a Return Item from the main inventory into the hotbar.
- Including absorption in the health percentage.
- Changing healing-item priority, exact-name matching, cooldown semantics, or
  use duration.
