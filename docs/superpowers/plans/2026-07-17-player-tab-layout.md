# Player Tab Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Player tab as a vertically scrollable page with Player overview and Vitals on top, full-width Inventory beneath them, full-width Auto Heal last, and an Edit button beside every Remove button.

**Architecture:** Keep the fixed Player toolbar outside a canvas-backed scrolling body. Place all four sections directly in one two-column page grid, keep extra slots inside Inventory, and remove the Auto Heal-only canvas so the page owns all vertical scrolling. Reuse the existing Auto Heal dialog through a rule-oriented method shared by inventory right-click and the new Edit button.

**Tech Stack:** Python 3.10+, Tkinter/ttk, Pillow, pytest

## Global Constraints

- Work on the existing `codex/v2` branch; do not create or switch worktrees.
- Preserve the fixed toolbar, Player polling, icon loading, inventory rendering, and Auto Heal runtime/configuration behavior.
- The top row is Player overview at natural width and Vitals expanding to the right.
- Inventory and Auto Heal each span the full page width in that order.
- Only the Player page scrolls; Auto Heal has no nested scrollbar.
- Each Auto Heal rule has `Edit` immediately before `Remove`.
- Edit opens the existing dialog with the exact-name rule and saved values prefilled.
- Follow red-green-refactor for every production change.

---

## File Map

- Modify `holoquiz/player_view.py`: scrolling-body helpers, section grid, Player tab widget hierarchy, Auto Heal rule actions.
- Modify `tests/test_player_view.py`: scrolling, layout, and Edit regressions.
- Update `docs/superpowers/specs/2026-07-17-player-tab-layout-design.md` only if implementation reveals a design correction that the user approves.

### Task 1: Scrollable Player Page and Section Grid

**Files:**
- Modify: `holoquiz/player_view.py:30-110`
- Modify: `holoquiz/player_view.py:660-850`
- Test: `tests/test_player_view.py:350-510`

**Interfaces:**
- Produces: `configure_scrollable_player_body(body: Any, canvas: Any, scrollbar: Any, content: Any) -> int`
- Produces: `scroll_player_body(canvas: Any, event: Any) -> None`
- Changes: `layout_player_sections(content, profile, stats, inventory, auto_heal) -> None`
- Consumes: existing `PlayerTab._build()` widget construction and `ItemSlotWidget`

- [ ] **Step 1: Replace the old centering/layout tests with failing scrollable-page tests**

In `tests/test_player_view.py`, import `configure_scrollable_player_body` and
`scroll_player_body`, remove the old centering test, and replace the current
section-layout test with these tests:

```python
def test_scrollable_player_body_fills_body_and_tracks_content_size():
    calls = []

    class RecordingBody:
        def columnconfigure(self, index, *, weight):
            calls.append(("body-column", index, weight))

        def rowconfigure(self, index, *, weight):
            calls.append(("body-row", index, weight))

    class RecordingScrollbar:
        def set(self, first, last):
            calls.append(("scrollbar-set", first, last))

        def grid(self, **options):
            calls.append(("scrollbar-grid", options))

    class RecordingContent:
        def bind(self, event, callback):
            calls.append(("content-bind", event, callback))

    class RecordingCanvas:
        def configure(self, **options):
            calls.append(("canvas-configure", options))

        def create_window(self, position, **options):
            calls.append(("canvas-window", position, options))
            return 23

        def grid(self, **options):
            calls.append(("canvas-grid", options))

        def bind(self, event, callback):
            calls.append(("canvas-bind", event, callback))

        def bind_all(self, event, callback, add):
            calls.append(("canvas-bind-all", event, callback, add))

        def bbox(self, target):
            return (0, 0, 900, 1200)

        def itemconfigure(self, window_id, **options):
            calls.append(("canvas-itemconfigure", window_id, options))

        def coords(self, window_id, x, y):
            calls.append(("canvas-coords", window_id, x, y))

    body = RecordingBody()
    canvas = RecordingCanvas()
    scrollbar = RecordingScrollbar()
    content = RecordingContent()

    window_id = configure_scrollable_player_body(
        body, canvas, scrollbar, content
    )

    assert window_id == 23
    assert ("body-column", 0, 1) in calls
    assert ("body-row", 0, 1) in calls
    assert ("canvas-grid", {"row": 0, "column": 0, "sticky": "nsew"}) in calls
    assert ("scrollbar-grid", {"row": 0, "column": 1, "sticky": "ns"}) in calls
    assert any(entry[:2] == ("content-bind", "<Configure>") for entry in calls)
    assert any(entry[:2] == ("canvas-bind", "<Configure>") for entry in calls)
    assert any(entry[:2] == ("canvas-bind-all", "<MouseWheel>") for entry in calls)


def test_scroll_player_body_converts_windows_wheel_delta_to_units():
    calls = []
    canvas = SimpleNamespace(
        yview_scroll=lambda amount, unit: calls.append((amount, unit)),
        winfo_pointerx=lambda: 250,
        winfo_pointery=lambda: 200,
        winfo_rootx=lambda: 100,
        winfo_rooty=lambda: 100,
        winfo_width=lambda: 500,
        winfo_height=lambda: 400,
    )

    scroll_player_body(canvas, SimpleNamespace(delta=-240))

    assert calls == [(2, "units")]


def test_player_sections_follow_approved_full_width_order():
    calls = []

    class RecordingContent:
        def columnconfigure(self, index, weight):
            calls.append(("column", index, weight))

    class RecordingSection:
        def __init__(self, name):
            self.name = name

        def grid(self, **options):
            calls.append((self.name, options))

    layout_player_sections(
        RecordingContent(),
        RecordingSection("profile"),
        RecordingSection("stats"),
        RecordingSection("inventory"),
        RecordingSection("auto-heal"),
    )

    assert calls == [
        ("column", 0, 0),
        ("column", 1, 1),
        ("profile", {"row": 0, "column": 0, "sticky": "nw", "padx": (0, 12), "pady": (0, 12)}),
        ("stats", {"row": 0, "column": 1, "sticky": "nsew", "pady": (0, 12)}),
        ("inventory", {"row": 1, "column": 0, "columnspan": 2, "sticky": "ew", "pady": (0, 12)}),
        ("auto-heal", {"row": 2, "column": 0, "columnspan": 2, "sticky": "ew"}),
    ]
```

- [ ] **Step 2: Run the new tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_player_view.py::test_scrollable_player_body_fills_body_and_tracks_content_size tests/test_player_view.py::test_scroll_player_body_converts_windows_wheel_delta_to_units tests/test_player_view.py::test_player_sections_follow_approved_full_width_order -q
```

Expected: collection or assertion failures because the scrolling helpers do
not exist and the current layout places Auto Heal beside Vitals.

- [ ] **Step 3: Add the scrolling and layout helpers**

In `holoquiz/player_view.py`, remove `center_player_body`. Keep the existing
Auto Heal list helper until Task 2. Add `PLAYER_PAGE_MAX_WIDTH = 1100` and:

```python
def scroll_player_body(canvas: Any, event: Any) -> None:
    pointer_x = canvas.winfo_pointerx() - canvas.winfo_rootx()
    pointer_y = canvas.winfo_pointery() - canvas.winfo_rooty()
    if not (
        0 <= pointer_x < canvas.winfo_width()
        and 0 <= pointer_y < canvas.winfo_height()
    ):
        return
    units = -int(event.delta / 120)
    if units:
        canvas.yview_scroll(units, "units")


def configure_scrollable_player_body(
    body: Any,
    canvas: Any,
    scrollbar: Any,
    content: Any,
) -> int:
    body.columnconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)
    canvas.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")
    canvas.configure(yscrollcommand=scrollbar.set)
    window_id = canvas.create_window((0, 0), window=content, anchor="n")
    content.bind(
        "<Configure>",
        lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    def resize_content(event: Any) -> None:
        width = max(1, min(event.width - 24, PLAYER_PAGE_MAX_WIDTH))
        canvas.coords(window_id, event.width / 2, 0)
        canvas.itemconfigure(window_id, width=width)

    canvas.bind("<Configure>", resize_content)
    canvas.bind_all(
        "<MouseWheel>",
        lambda event: scroll_player_body(canvas, event),
        add="+",
    )
    return window_id


def layout_player_sections(
    content: Any,
    profile: Any,
    stats: Any,
    inventory: Any,
    auto_heal: Any,
) -> None:
    content.columnconfigure(0, weight=0)
    content.columnconfigure(1, weight=1)
    profile.grid(row=0, column=0, sticky="nw", padx=(0, 12), pady=(0, 12))
    stats.grid(row=0, column=1, sticky="nsew", pady=(0, 12))
    inventory.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
    auto_heal.grid(row=2, column=0, columnspan=2, sticky="ew")
```

- [ ] **Step 4: Rebuild `PlayerTab._build()` around the scrolling page**

Keep the toolbar code unchanged. Replace the body/content setup with:

```python
body = ttk.Frame(self.parent)
body.grid(row=1, column=0, sticky="nsew")
self.player_canvas = tk.Canvas(body, borderwidth=0, highlightthickness=0)
self.player_scrollbar = ttk.Scrollbar(
    body,
    orient="vertical",
    command=self.player_canvas.yview,
)
player_content = ttk.Frame(self.player_canvas, padding=(12, 0, 12, 12))
configure_scrollable_player_body(
    body,
    self.player_canvas,
    self.player_scrollbar,
    player_content,
)
```

Create `profile`, `stats`, `inventory`, and Auto Heal with `player_content` as
their parent. Remove the intermediate `content` frame. Create
`self.extra_frame = ttk.Frame(inventory)` and grid it below the hotbar:

```python
self.extra_frame.grid(
    row=5,
    column=0,
    columnspan=9,
    sticky="w",
    pady=(8, 0),
)
```

Call:

```python
self._build_auto_heal_section(player_content)
layout_player_sections(
    player_content,
    profile,
    stats,
    inventory,
    self.auto_heal_section,
)
```

- [ ] **Step 5: Run focused and complete Player view tests**

Run `python -m pytest tests/test_player_view.py -q`.

Expected: all Player view tests pass.

- [ ] **Step 6: Commit the scrolling layout**

```powershell
git add holoquiz/player_view.py tests/test_player_view.py
git commit -m "feat: make player tab scrollable"
```

### Task 2: Full-Width Auto Heal Rules with Edit

**Files:**
- Modify: `holoquiz/player_view.py:810-950`
- Test: `tests/test_player_view.py:620-750`

**Interfaces:**
- Produces: `layout_auto_heal_rule_actions(edit_button: Any, remove_button: Any) -> None`
- Produces: `PlayerTab._show_auto_heal_dialog(name: str, existing: AutoHealItemConfig | None = None) -> None`
- Produces: `PlayerTab._edit_auto_heal_item(item: AutoHealItemConfig) -> None`
- Consumes: `AutoHealItemDialog`, `PlayerTab._save_auto_heal_item`, and exact-name `auto_heal_items`

- [ ] **Step 1: Write failing Edit and action-layout tests**

Add to `tests/test_player_view.py` and import
`layout_auto_heal_rule_actions`:

```python
def test_auto_heal_rule_actions_place_edit_immediately_before_remove():
    calls = []

    class RecordingButton:
        def __init__(self, name):
            self.name = name

        def grid(self, **options):
            calls.append((self.name, options))

    layout_auto_heal_rule_actions(RecordingButton("edit"), RecordingButton("remove"))

    assert calls == [
        ("edit", {"row": 0, "column": 1, "padx": (8, 4)}),
        ("remove", {"row": 0, "column": 2}),
    ]


def test_player_tab_edit_opens_prefilled_exact_name_rule(monkeypatch):
    opened = []
    item = AutoHealItemConfig("Steak", 5, 2.5, 30, 15)
    tab = object.__new__(PlayerTab)
    tab.parent = object()
    tab.auto_heal_items = (item,)
    tab._save_auto_heal_item = lambda saved: None
    monkeypatch.setattr(
        player_view,
        "AutoHealItemDialog",
        lambda parent, **options: opened.append((parent, options)),
    )

    tab._edit_auto_heal_item(item)

    assert opened == [
        (
            tab.parent,
            {
                "name": "Steak",
                "existing": item,
                "on_save": tab._save_auto_heal_item,
            },
        )
    ]
```

- [ ] **Step 2: Run the new tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_player_view.py::test_auto_heal_rule_actions_place_edit_immediately_before_remove tests/test_player_view.py::test_player_tab_edit_opens_prefilled_exact_name_rule -q
```

Expected: collection failures because the helper and Edit method do not exist.

- [ ] **Step 3: Remove nested Auto Heal scrolling and add action layout**

Remove `AUTO_HEAL_LIST_HEIGHT`, `configure_auto_heal_rule_list`, their imports
in `tests/test_player_view.py`, and
`test_auto_heal_rule_list_keeps_fixed_scrollable_height_for_many_rules`.

Add near the other layout helpers:

```python
def layout_auto_heal_rule_actions(
    edit_button: Any,
    remove_button: Any,
) -> None:
    edit_button.grid(row=0, column=1, padx=(8, 4))
    remove_button.grid(row=0, column=2)
```

In `_build_auto_heal_section`, replace the canvas and scrollbar construction
with:

```python
self.auto_heal_rows_frame = ttk.Frame(section)
self.auto_heal_rows_frame.grid(row=2, column=0, sticky="ew", pady=(6, 0))
self.auto_heal_rows_frame.columnconfigure(0, weight=1)
self._refresh_auto_heal_rows()
```

In `_refresh_auto_heal_rows`, remove all references to
`auto_heal_list_canvas` and `auto_heal_scrollbar`.

- [ ] **Step 4: Reuse the dialog for right-click and Edit**

Replace `_open_auto_heal_dialog` with:

```python
def _open_auto_heal_dialog(self, slot: InventorySlot) -> None:
    self._show_auto_heal_dialog(slot.item.name)

def _show_auto_heal_dialog(
    self,
    name: str,
    existing: AutoHealItemConfig | None = None,
) -> None:
    if existing is None:
        existing = next(
            (item for item in self.auto_heal_items if item.name == name),
            None,
        )
    AutoHealItemDialog(
        self.parent,
        name=name,
        existing=existing,
        on_save=self._save_auto_heal_item,
    )

def _edit_auto_heal_item(self, item: AutoHealItemConfig) -> None:
    self._show_auto_heal_dialog(item.name, item)
```

Create both rule-row buttons and lay them out:

```python
edit_button = ttk.Button(
    row,
    text="Edit",
    command=partial(self._edit_auto_heal_item, item),
)
remove_button = ttk.Button(
    row,
    text="Remove",
    command=partial(self._remove_auto_heal_item, item.name),
)
layout_auto_heal_rule_actions(edit_button, remove_button)
```

Set the item-name label to `wraplength=480` and the detail label to
`wraplength=680` so custom Unicode names and settings use the full-width row.

- [ ] **Step 5: Run Player view and GUI integration tests**

Run `python -m pytest tests/test_player_view.py tests/test_gui.py -q`.

Expected: all selected tests pass.

Run:

```powershell
rg -n "auto_heal_list_canvas|auto_heal_scrollbar|configure_auto_heal_rule_list" holoquiz tests
```

Expected: no matches.

- [ ] **Step 6: Commit the Auto Heal presentation**

```powershell
git add holoquiz/player_view.py tests/test_player_view.py
git commit -m "feat: add auto heal rule editing"
```

### Task 3: Final Integration, Visual QA, and Review

**Files:**
- Verify: `holoquiz/player_view.py`
- Verify: `tests/test_player_view.py`
- Verify: `docs/superpowers/specs/2026-07-17-player-tab-layout-design.md`

**Interfaces:**
- Consumes: completed scrollable page and Edit behavior from Tasks 1 and 2
- Produces: reviewed, verified branch ready for user handoff

- [ ] **Step 1: Run the full automated verification**

```powershell
python -m pytest
$files = Get-ChildItem holoquiz -Filter *.py | ForEach-Object { $_.FullName }
python -m py_compile $files
git diff --check db90248..HEAD
python -m json.tool config.example.json > $null
```

Expected: the complete suite passes, compilation exits zero, the diff check
prints nothing, and JSON validation exits zero.

- [ ] **Step 2: Perform standard-window visual QA**

Launch `python holoquiz_gui.py`, open the Player tab, and verify at the standard
window size:

- The toolbar remains fixed while the body scrolls.
- Player overview is top-left and Vitals expands to its right.
- Inventory spans the next full-width row with all nine hotbar slots aligned.
- Auto Heal spans the bottom row and has no nested scrollbar.
- The page scrollbar reaches every Auto Heal rule.
- Edit is immediately before Remove.
- Edit opens the selected rule with cooldown, duration, health, and hunger values prefilled.

Close the dialog without saving and close the application so visual QA does
not mutate the user's configuration.

- [ ] **Step 3: Request independent code review**

Ask a reviewer to compare `db90248..HEAD` with
`docs/superpowers/specs/2026-07-17-player-tab-layout-design.md`, prioritizing
scroll lifecycle bugs, nested-scroll remnants, viewport behavior, and Edit
identity/persistence. Resolve every Critical or Important finding test-first.

- [ ] **Step 4: Repeat final verification after review fixes**

Run the complete commands from Step 1 again. Expected: all commands exit zero
and `git status --short` prints nothing.

- [ ] **Step 5: Use the branch-finishing workflow**

Invoke `superpowers:finishing-a-development-branch`, detect the normal-repo
environment and `master` base, and present its four required integration
options without merging, pushing, or deleting unless the user chooses one.
