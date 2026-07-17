# Player Tab Layout Redesign

## Goal

Rearrange the Player tab into a clean, vertically ordered layout that follows
the approved mockup while preserving all existing inventory and Auto Heal
behavior. The toolbar remains visible while the Player content can scroll
vertically when it is taller than the window.

## Page Structure

The Player tab keeps its existing toolbar at the top, including the Player
heading, update time, connection status, error message, and Refresh button.
Only the content beneath the toolbar scrolls.

The scrollable content uses three rows:

1. `Player overview` occupies the left side of the top row at its natural
   width. `Vitals` occupies the right side and expands to use the remaining
   content width.
2. `Inventory` spans the full content width beneath the top row. The existing
   27 main slots and nine hotbar slots keep their current arrangement. Any
   extra slots appear directly beneath the normal slots as part of this
   inventory area.
3. `Auto Heal` spans the full content width beneath Inventory.

The content is horizontally centered when the window is wider than its
requested size. A vertical scrollbar appears at the right edge of the content
area and scrolls the complete Player page. The mouse wheel scrolls this page
while the pointer is over it.

## Auto Heal Presentation

Auto Heal no longer owns a nested scrolling canvas. Its section contains the
existing enable checkbox, empty-state message, and one compact row for each
configured rule. The page-level scrollbar handles long rule lists.

Each populated rule row contains:

- The exact configured item name.
- Cooldown, use duration, health threshold, and hunger threshold.
- An `Edit` button.
- A `Remove` button immediately beside Edit.

Edit opens the existing Auto Heal item dialog with the selected rule's exact
name and saved values prefilled. Saving replaces that exact-name rule, updates
runtime state, persists the configuration, and refreshes the row. Remove keeps
its existing confirmation-free behavior and persistence path.

Right-clicking an occupied inventory slot remains an alternative way to add or
edit an exact-name rule. No Auto Heal selection, threshold, cooldown, input,
or safety behavior changes as part of this redesign.

## Implementation Boundaries

The scrolling page is a reusable Tk canvas containing a ttk content frame and
a vertical ttk scrollbar. Canvas and inner-frame configure events keep the
scroll region current and make the embedded frame follow the available page
width. The fixed toolbar remains outside this canvas.

The layout helper places Player overview and Vitals directly in the shared
content grid, then places Inventory and Auto Heal with a two-column span. The
previous nested content frame and Auto Heal-only scrolling canvas are removed.

The Edit button calls a rule-oriented dialog method rather than constructing a
fake inventory slot. Both right-click editing and button editing reuse the same
dialog-opening path so validation and persistence stay identical.

## Testing and Verification

Automated tests cover:

- The top-row and full-width section grid positions.
- The fixed toolbar and scrollable-body grid relationship.
- Page canvas scroll-region and embedded-width synchronization.
- Mouse-wheel page scrolling.
- The absence of the Auto Heal nested scrollbar.
- Edit opening the selected exact-name rule and saving through the existing
  update callback.
- Edit and Remove button placement in each rule row.

Run the full pytest suite, compile all package modules, validate the example
configuration JSON, and perform a visual check at the standard application
window size. The visual check confirms the approved hierarchy, alignment,
page scrollbar, full hotbar visibility while scrolled to Inventory, and the
Edit/Remove controls.
