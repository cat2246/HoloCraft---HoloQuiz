# Player Module Design

## Goal

Add a `Player` tab to HoloCraft Tools that displays live Minecraft player vitals and inventory data from `http://127.0.0.1:8026/data/player`. The view refreshes once per second while selected, uses remotely supplied vanilla item icons, and presents the item fields currently available from the local API in hover tooltips.

## User Experience

- Add `Player` to the existing Tkinter notebook as a first-class feature tab.
- Keep the visual language of the existing control panel while arranging the inventory in a familiar Minecraft layout.
- Show a large neutral player-skin placeholder labeled `Player skin unavailable`.
- Include an explicit code TODO for replacing the placeholder when the local API exposes a player username or UUID.
- Show health and hunger as labeled progress bars with their numeric current and maximum values. Hunger uses Minecraft's maximum food level of 20 because the endpoint currently supplies only `food_level` and `saturation`.
- Show compact text for armor, experience level and progress, position, and facing direction when those values are present.
- Arrange the standard inventory sections as follows:
  - armor in helmet, chestplate, leggings, and boots order;
  - main inventory as a 9-by-3 grid;
  - hotbar as a separate 9-slot row;
  - offhand beside the player and armor area.
- Preserve nonstandard inventory slots in an `Extra` row rather than silently discarding them. Empty extra slots do not need to be shown.
- Show an item icon and bottom-right stack count in every occupied slot. Items with `is_enchanted: true` receive a subtle highlighted border.
- Show a dark Minecraft-inspired tooltip while the pointer is over an occupied slot. The tooltip contains the available display name, namespaced item ID, count, section and inventory slot, durability, maximum stack size, and enchanted status.
- Include an explicit code TODO near tooltip construction for enchantments, lore, attributes, set bonuses, and other rich details that the local endpoint does not yet provide.
- Empty slots do not show a tooltip.
- Include a `Refresh` button, connection state, and last successful update time.

## Architecture

Create `holoquiz/player.py` as a focused boundary for the feature. It owns immutable typed models for player vitals and inventory items, validation and parsing of the local JSON payload, the player-data HTTP client, item-icon URL construction, background-safe icon retrieval, and an in-memory icon-byte cache. It must not import Tkinter.

The existing `BotConfig.player_data_url` remains the source for the player endpoint. The current coordinate-lock `PlayerDataClient` remains unchanged for coordinate behavior; the Player tab uses the richer client in `holoquiz.player` so it can return the full payload without coupling coordinate logic to the new view.

The item-icon client uses the documented BlocksItems endpoint:

```text
https://blocksitems.com/api/v1/items/{full_id}/icon?size=64
```

The namespaced ID path segment must be URL-encoded safely while preserving the colon expected by the service. The client targets 64-pixel PNG icons, uses a short timeout, validates that the response is image data, and caches bytes by namespaced item ID. A failed icon lookup returns a generated neutral fallback tile and does not fail the player refresh. The chosen service does not provide a version argument for this direct icon endpoint; Minecraft Java 1.21.10 is the target game version and must be documented next to the icon-service configuration for later compatibility work.

Create a focused Tkinter view component in `holoquiz/player_view.py`. It owns the Player tab widgets, rendering, slot-to-grid mapping, `PhotoImage` lifetime management, hover tooltip behavior, and tab-specific connection state. Separating it from the already large `holoquiz/gui.py` keeps the new feature independently testable. The main control panel creates this view, supplies the configured endpoint, starts or stops its polling based on notebook selection, and closes it during application shutdown.

The view uses a single background executor or worker thread for network work. Worker results are passed back through a thread-safe queue and applied by a short `after` callback on Tkinter's main thread. Tkinter variables, widgets, and images are never created or mutated from a worker thread.

## Data Model and Inventory Mapping

The parser accepts the current API version 1 object and treats nonessential fields as optional so a partial payload can still render. It validates required container types and converts numeric values without allowing malformed values to crash the UI loop.

Standard inventory mapping follows the live endpoint:

- slots 0 through 8: hotbar, left to right;
- slots 9 through 35: main inventory, row-major in three rows;
- slot 36: boots;
- slot 37: leggings;
- slot 38: chestplate;
- slot 39: helmet;
- slot 40: offhand.

Any occupied slot outside this range is rendered in `Extra` in ascending inventory-slot order. Section values remain available to the tooltip but do not override standard slot placement. This prevents a malformed section label from moving a standard slot unexpectedly.

Durability remaining is computed as `max(max_damage - damage, 0)` when `max_damage` is positive. Items without durability show `Not applicable` rather than `0 / 0`.

## Refresh and Concurrency

- Begin polling when the notebook selects the Player tab.
- Request fresh player data once per second while the tab remains selected.
- Stop scheduling new polls when another tab is selected.
- Do not start a new request while the previous request is still in flight.
- The `Refresh` button schedules an immediate fetch only when no request is in flight. If one is active, it leaves that request to complete.
- On success, replace the rendered snapshot, set the state to `Connected`, record the local completion time, and schedule the next one-second poll.
- On failure, retain the last successfully rendered snapshot, set the state to `Disconnected`, show a short error message, and continue retrying once per second while selected.
- Icon downloads are deduplicated by the cache. An inventory refresh reuses all previously fetched icons and requests only unseen item IDs.
- Closing the application cancels scheduled callbacks, signals the worker to stop, and prevents late results from touching destroyed widgets.

## Error Handling

The player client uses a short network timeout and reports concise connection, HTTP, JSON, and schema errors. Error text is displayed in the Player tab without adding repeated failures to modal dialogs. A malformed item is rendered as a fallback slot when its inventory position is recoverable; an invalid top-level payload is rejected and leaves the last successful snapshot visible.

Icon retrieval is isolated from player polling. Unsupported IDs, third-party service downtime, invalid image data, and Pillow decode errors all produce the neutral fallback icon for the affected item. These failures do not change the local player connection state.

The skin placeholder requires no network call. A TODO identifies the future need to obtain player identity from the local API before integrating a skin service.

## Testing

- `tests/test_player.py` covers parsing the live API shape, optional fields, empty slots, malformed top-level payloads, durability calculations, standard slot mapping, armor reordering, and preservation of occupied extra slots.
- Client tests inject fake HTTP openers and verify the configured player URL, timeouts, BlocksItems URL construction, response validation, cache reuse, and fallback behavior.
- Tooltip tests verify all currently available item details and confirm the rich-metadata TODO boundary does not invent data absent from the endpoint.
- `tests/test_player_view.py` covers refresh state independently of a real display where practical: tab activation and deactivation, one-second scheduling, immediate refresh, non-overlapping requests, stale-data retention, and clean shutdown.
- `tests/test_gui.py` verifies that `Player` appears in `FEATURE_TAB_LABELS` and that the control panel wires notebook selection and shutdown to the Player view.
- Run `python -m pytest`, `python -m py_compile holoquiz/*.py`, and a live GUI launch against the local endpoint. Visually confirm the inventory grid, counts, progress bars, placeholder, tooltip positioning, fallback icons, and disconnected state.

## Out of Scope

- Fetching or rendering the real player skin until the local player endpoint exposes a username or UUID.
- Displaying enchantments, lore, attributes, set bonuses, custom-model data, or other item details not present in the current payload.
- Reproducing custom resource-pack item models or textures. The icon service supplies vanilla icons by namespaced item ID.
- Editing, moving, equipping, dropping, or otherwise mutating inventory contents.
- Polling while the Player tab is not selected.
- Persisting item icons to disk; the first implementation uses an in-memory cache only.
