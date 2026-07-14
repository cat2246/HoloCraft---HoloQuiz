# Coordinate Lock Look at Target Design

## Goal

Add a mutually exclusive `Look at target` mode to Coordinate Lock. The mode keeps the camera aimed at the closest eligible player or mob while movement continues returning the player to the active saved coordinate.

## User Interface and Configuration

The Coordinate Lock behavior row will show `Look at lock` and `Look at target` beside each other. Selecting one deselects the other. Deselecting the selected option leaves both off, preserving the existing free-look behavior.

The runtime will represent this state as one look mode with the values `none`, `lock`, and `target`. When `coordinate_lock_look_mode` is absent, configuration loading will migrate the legacy `coordinate_lock_look_at_enabled` boolean: `true` becomes `lock` and `false` becomes `none`. The new mode takes precedence when both fields are present. Saved configuration and `config.example.json` will document the new mode and stop writing the legacy boolean. The known legacy player endpoint at either `http://localhost:8025/data/player` or `http://127.0.0.1:8025/data/player` will migrate to the updated local endpoint at `http://127.0.0.1:8026/data/player`, which provides position, yaw, and pitch.

## Player and Entity Data

`PlayerDataClient` will support the new nested player payload:

- `position.x`, `position.y`, and `position.z`
- `rotation.yaw` and `rotation.pitch`

It will retain support for the existing flat position/yaw payload so explicitly configured alternative endpoints remain usable for Coordinate Lock modes that do not require pitch.

`NearbyEntityClient` will retain each entity's world-space `position.x`, `position.y`, and `position.z` in addition to distance and names. Invalid or missing coordinates will be rejected rather than producing unsafe camera movements.

## Target Selection

Target selection uses the active coordinate's saved settings:

- `Players` and `Mobs` determine the eligible entity types.
- A non-empty Target Name requires the existing exact, trimmed, case-insensitive match. Player matching uses `custom_name`; mob matching uses `name`.
- An empty Target Name (`Any` in the table) accepts every entity of the selected types.
- An entity is eligible only when its API-reported distance from the player is less than or equal to the active coordinate's Active area.
- The eligible entity with the smallest reported distance is selected on every polling cycle. Stable input order resolves exact distance ties.

The selection radius is independent of the five-block Auto Hit radius. Auto Hit continues to use its existing five-block boundary.

## Camera and Movement Behavior

Target mode calculates a 3D aim vector from the player's eye position to the target's body center. The player's eye position is its world position plus a 1.62-block standing eye-height offset. Because the entity API does not expose bounding-box dimensions, the target body center is its position plus a fixed 0.9-block vertical offset.

Minecraft yaw and pitch conventions will be converted into shortest signed angular corrections. Camera motion will use the existing adaptive mouse sensitivity calibration and smooth relative-input path, extended to apply horizontal and vertical corrections together. Fresh yaw and pitch readings on every polling cycle provide closed-loop feedback, so no camera sweep or estimated pitch state is needed.

Movement remains directed toward the saved lock coordinate:

- In `target` mode with an eligible target, the worker selects forward, backward, left, or right from the current yaw and moves toward the lock while the camera tracks the entity.
- In `target` mode without an eligible target, the worker falls back to `lock` behavior: it turns toward the lock and moves forward.
- In `lock` mode, existing Look at lock behavior is preserved.
- In `none` mode, existing free-look movement behavior is preserved.

Jump and stall-recovery behavior remains unchanged.

## Failure Handling

If the target entity endpoint fails, returns malformed data, or has no eligible target, Coordinate Lock will continue safely by looking at the lock. Repeated entity API errors will be logged without flooding the Activity view. Existing safeguards for disabled automation, open containers, inactive Minecraft windows, and input coordination remain in force.

If the configured player endpoint lacks pitch while target mode is selected, the worker will log a specific error and fall back to Look at lock instead of guessing the vertical camera angle.

## Testing

Automated tests will cover:

- configuration migration and persistence for `none`, `lock`, and `target`;
- parsing new nested player position/rotation data and legacy flat payloads;
- parsing entity world positions and rejecting malformed positions;
- filtering by Players/Mobs, Target Name, and Active area;
- selecting the closest eligible entity;
- yaw and pitch calculations toward body center;
- simultaneous smooth horizontal and vertical camera movement;
- moving toward the lock while facing a tracked target;
- falling back to Look at lock when no target matches or entity data fails;
- mutually exclusive GUI controls and persisted selection;
- preservation of existing Auto Hit and Look at lock behavior.

The full `python -m pytest` suite and `python -m py_compile holoquiz/*.py` will be run before handoff.
