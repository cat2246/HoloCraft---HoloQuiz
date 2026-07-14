# Coordinate Lock Auto Hit Targeting Design

## Goal

Prevent Coordinate Lock's Auto Hit feature from clicking continuously when no intended entity is nearby. Each saved coordinate will define which entity types may trigger Auto Hit and may optionally restrict triggering to one exact entity name.

## User Interface

The existing coordinate editor label `Target Name` will be renamed to `Coordinate Name` because that value identifies the saved coordinate rather than an attack target.

The coordinate editor will add these per-coordinate Auto Hit fields:

- `Players`: include nearby players as eligible targets.
- `Mobs`: include nearby mobs as eligible targets.
- `Target Name`: optionally restrict eligible entities by name.

At least one of `Players` or `Mobs` must be selected when a coordinate is saved. The Saved Targets table will display the configured target types and target name so users can distinguish targeting behavior without opening the editor.

The existing global `Auto Hit` checkbox remains the master switch. Auto Hit interval settings also remain global. Editing a saved coordinate loads its entity targeting settings into the form, and saving writes them back to that coordinate.

## Configuration

`CoordinateLockConfig` will gain three fields:

- `auto_hit_players: bool`
- `auto_hit_mobs: bool`
- `auto_hit_target_name: str`

Existing configurations that do not contain these fields will load with both entity types enabled and a blank target name. This preserves a useful default while applying the new five-block safety gate. Serialization will include the new fields, and `config.example.json` will contain a disabled sample coordinate that demonstrates them without enabling automation.

## Entity Data and Matching

The worker will query these local endpoints immediately before each potential click:

- `http://127.0.0.1:8026/data/players`
- `http://127.0.0.1:8026/data/mobs`

Only endpoints selected by the active coordinate will be queried. An entity is eligible when its numeric `distance` is less than or equal to `5.0` blocks.

When the coordinate's Target Name is blank, any eligible entity of a selected type may trigger Auto Hit. When Target Name is populated, surrounding whitespace is removed and matching is exact and case-insensitive using Unicode-aware case folding:

- Players match against `custom_name`. A missing or null `custom_name` does not match a populated filter.
- Mobs match against `name`.

When both types are selected, a match from either endpoint is sufficient.

## Runtime Flow

All current Coordinate Lock prerequisites remain in force: the program and Coordinate Lock must be enabled, one saved coordinate must be active, the player must be inside that coordinate's active area, Auto Hit must be enabled, Minecraft must be foreground, input coordination must allow the action, and no inventory or container may be open.

Immediately before issuing each left click, the worker will retrieve fresh data for the active coordinate's selected target types and evaluate the five-block and optional-name rules. This click-boundary check avoids acting on cached entity data after a target has moved away.

If no eligible entity is present, the worker will not click and will wait for the normal coordinate polling interval before checking again. Once an entity becomes eligible, clicking resumes with the configured randomized Auto Hit interval. Coordinate movement and camera behavior are unchanged.

## Error Handling

Auto Hit will fail closed. A selected endpoint that is unavailable, returns a non-object response, omits its expected entity list, or contains invalid entity data will prevent that click. The worker will place a concise error in the Activity log and reuse the existing duplicate-status suppression to avoid flooding it.

An unselected endpoint has no effect and is not queried. Empty entity lists are valid and simply prevent clicking.

## Components

- `holoquiz.config`: extend the per-coordinate model, loading, saving, and backward-compatible defaults.
- `holoquiz.runtime`: continue transporting complete coordinate objects; no separate global entity-target state is required.
- `holoquiz.coordinate_lock`: add a small nearby-entity API client and pure matching helpers, then enforce them at the click boundary.
- `holoquiz.gui`: rename the coordinate field, add per-coordinate controls and validation, load them during editing, and expose them in the Saved Targets table.
- `config.example.json`: document the new per-coordinate fields with a disabled sample coordinate.

## Test Coverage

Focused tests will verify:

- Existing coordinate JSON migrates to both target types with no name filter.
- New targeting fields round-trip through configuration persistence.
- Players use `custom_name` and mobs use `name`.
- Name matching is exact, trimmed, and case-insensitive.
- Entities at exactly five blocks qualify; entities farther away do not.
- Blank names allow any selected entity.
- Only selected endpoints are queried.
- A match from either selected type permits a click.
- Missing targets and endpoint or payload errors prevent clicks.
- The GUI builds and edits coordinates with their per-coordinate targeting settings and rejects a coordinate with neither type selected.

The focused Coordinate Lock, config, runtime, and GUI tests will run first, followed by the complete pytest suite and a package syntax check.
