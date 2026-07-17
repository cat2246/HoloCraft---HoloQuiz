# Player Horizontal Centering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Center the complete Player information area horizontally at every supported window width while keeping it aligned to the top of the Player tab.

**Architecture:** Keep the full-width toolbar and outer body frame unchanged. Add a non-expanding content wrapper in the middle of a three-column body grid, with equally weighted spacer columns on its left and right; keep the existing overview and Vitals/Inventory layout inside that wrapper.

**Tech Stack:** Python 3.10+, Tkinter/ttk grid geometry manager, pytest

## Global Constraints

- The Player toolbar remains full width and top-aligned.
- The combined Player overview, Vitals, and Inventory area is horizontally centered and top-aligned.
- Widget sizes, player data loading, inventory behavior, and tooltip behavior remain unchanged.
- Preserve the existing uncommitted Player icon-loading changes and unrelated runtime files.

---

### Task 1: Center the Player body with equal flexible spacers

**Files:**
- Modify: `holoquiz/player_view.py:30-33, 413-475`
- Test: `tests/test_player_view.py:344-362`

**Interfaces:**
- Consumes: Tkinter-compatible body and content objects supporting `columnconfigure`, `rowconfigure`, and `grid`.
- Produces: `center_player_body(body: Any, content: Any) -> None`, which applies the responsive centering grid contract.

- [x] **Step 1: Write the failing layout test**

Add this test to `tests/test_player_view.py`:

```python
def test_center_player_body_places_content_between_equal_spacers():
    calls = []

    class RecordingBody:
        def columnconfigure(self, index, *, weight):
            calls.append(("body-column", index, weight))

        def rowconfigure(self, index, *, weight):
            calls.append(("body-row", index, weight))

    class RecordingContent:
        def grid(self, **options):
            calls.append(("content-grid", options))

    player_view.center_player_body(RecordingBody(), RecordingContent())

    assert calls == [
        ("body-column", 0, 1),
        ("body-column", 2, 1),
        ("body-row", 0, 0),
        ("content-grid", {"row": 0, "column": 1, "sticky": "n"}),
    ]
```

- [x] **Step 2: Run the new test and verify RED**

Run:

```powershell
python -m pytest tests/test_player_view.py::test_center_player_body_places_content_between_equal_spacers -v
```

Expected: FAIL with `AttributeError` because `center_player_body` does not exist.

- [x] **Step 3: Add the centering helper**

Add this next to `configure_player_tab_grid` in `holoquiz/player_view.py`:

```python
def center_player_body(body: Any, content: Any) -> None:
    body.columnconfigure(0, weight=1)
    body.columnconfigure(2, weight=1)
    body.rowconfigure(0, weight=0)
    content.grid(row=0, column=1, sticky="n")
```

- [x] **Step 4: Move the existing Player panels into the centered wrapper**

Replace the body setup at the start of `PlayerTab._build` with:

```python
body = ttk.Frame(self.parent)
body.grid(row=1, column=0, sticky="nsew")

player_content = ttk.Frame(body)
center_player_body(body, player_content)

profile = ttk.LabelFrame(
    player_content,
    text="Player overview",
    padding=10,
)
profile.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
```

Create the existing right-hand content frame under the same wrapper:

```python
content = ttk.Frame(player_content)
content.grid(row=0, column=1, sticky="nsew")
```

Remove `body.columnconfigure(1, weight=1)`. Leave all widgets inside `profile` and `content` unchanged.

- [x] **Step 5: Run the focused Player view tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_player_view.py -v
```

Expected: all tests in `tests/test_player_view.py` PASS.

- [x] **Step 6: Run complete verification**

Run:

```powershell
python -m pytest
$files = Get-ChildItem 'holoquiz' -Filter '*.py' -File
foreach ($file in $files) {
    python -m py_compile $file.FullName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
git diff --check
```

Expected: all tests PASS, all package modules compile, and `git diff --check` exits successfully.

- [x] **Step 7: Commit the isolated layout change**

```powershell
git add -- docs/superpowers/plans/2026-07-17-player-horizontal-centering.md holoquiz/player_view.py tests/test_player_view.py
git commit -m "fix: center player overview horizontally"
```
