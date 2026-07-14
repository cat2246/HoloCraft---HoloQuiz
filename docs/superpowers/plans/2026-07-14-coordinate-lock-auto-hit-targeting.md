# Coordinate Lock Auto Hit Targeting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restrict Coordinate Lock Auto Hit to fresh, per-coordinate player or mob matches within five blocks.

**Architecture:** Extend each `CoordinateLockConfig` with its own target-type and optional-name settings. Add a focused nearby-entity HTTP client plus pure matching logic in `coordinate_lock.py`, and invoke it immediately before every click. Keep the existing global Auto Hit switch and interval while exposing the per-coordinate settings through the existing Tkinter editor and Saved Targets table.

**Tech Stack:** Python 3.10+, standard-library `dataclasses`, `json`, `urllib.request`, Tkinter/ttk, pytest.

## Global Constraints

- Entity data comes from `http://127.0.0.1:8026/data/players` and `http://127.0.0.1:8026/data/mobs`.
- An eligible entity has numeric `distance <= 5.0`.
- Player name filters use `custom_name`; mob name filters use `name`.
- Name matching is exact after trimming and Unicode-aware case folding.
- A blank name filter accepts any entity of a selected type.
- Both target-type flags are per coordinate, and at least one must be selected in the GUI.
- Existing coordinate JSON defaults to players enabled, mobs enabled, and a blank target name.
- Any selected endpoint or payload failure prevents the click and must not flood the Activity log.
- Existing foreground, input-coordination, container, active-area, movement, camera, and randomized-interval behavior remains in force.
- Keep source ASCII and add no new runtime dependency.

---

## File Structure

- Modify `holoquiz/config.py`: own the new per-coordinate fields and backward-compatible JSON conversion.
- Modify `holoquiz/coordinate_lock.py`: own entity response parsing, pure matching, and the click-boundary safety gate.
- Modify `holoquiz/gui.py`: own the renamed coordinate label, per-coordinate editor state and validation, and table display.
- Modify `config.example.json`: show a disabled coordinate with the new persisted fields.
- Modify `tests/test_config.py`: cover migration, round-trip persistence, and the example file.
- Modify `tests/test_coordinate_lock.py`: cover the client, matching boundary, selected endpoints, errors, and clicking.
- Modify `tests/test_gui.py`: cover form construction, validation, edit-state loading, and target-type summaries.
- No new source module is needed because entity access is private to Coordinate Lock and remains small.

---

### Task 1: Per-coordinate configuration and migration

**Files:**
- Modify: `holoquiz/config.py:28-36,310-344`
- Modify: `tests/test_config.py:62-117`
- Modify: `config.example.json:37-42`

**Interfaces:**
- Consumes: Existing `CoordinateLockConfig`, `_coordinate_locks_from_json`, `_coordinate_lock_to_json`, and `save_coordinate_lock_settings`.
- Produces: `CoordinateLockConfig.auto_hit_players: bool`, `CoordinateLockConfig.auto_hit_mobs: bool`, and `CoordinateLockConfig.auto_hit_target_name: str` for the worker and GUI.

- [ ] **Step 1: Write failing configuration migration and persistence tests**

Add explicit targeting fields to the round-trip fixture, assert legacy defaults, and verify the sample configuration documents the new schema:

```python
def test_load_and_save_coordinate_locks(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"dry_run": False}), encoding="utf-8")
    locks = [
        CoordinateLockConfig(
            id="home",
            x=1.5,
            y=64.0,
            z=-3.25,
            name="Home",
            active_area=25.0,
            auto_hit_players=True,
            auto_hit_mobs=False,
            auto_hit_target_name="[Lv 6]Tatsunoko",
        ),
        CoordinateLockConfig(
            id="afk",
            x=10.0,
            y=70.0,
            z=20.0,
            enabled=False,
            name="AFK Room",
        ),
    ]

    save_coordinate_lock_settings(
        config_path,
        locks,
        enabled=True,
        auto_hit_enabled=True,
        auto_hit_min_seconds=0.1,
        auto_hit_max_seconds=0.5,
        look_at_enabled=True,
    )

    config = load_config(config_path)

    assert config.dry_run is False
    assert config.coordinate_lock_enabled is True
    assert config.coordinate_lock_auto_hit_enabled is True
    assert config.coordinate_lock_auto_hit_min_seconds == 0.1
    assert config.coordinate_lock_auto_hit_max_seconds == 0.5
    assert config.coordinate_lock_look_at_enabled is True
    assert config.coordinate_locks == tuple(locks)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["coordinate_locks"][0]["auto_hit_players"] is True
    assert raw["coordinate_locks"][0]["auto_hit_mobs"] is False
    assert raw["coordinate_locks"][0]["auto_hit_target_name"] == "[Lv 6]Tatsunoko"


def test_load_coordinate_locks_without_targeting_fields_uses_safe_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "coordinate_lock_max_distance": 35,
                "coordinate_locks": [
                    {"id": "old-lock", "x": 1, "y": 64, "z": -2},
                ],
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    lock = config.coordinate_locks[0]
    assert lock.active_area == 35.0
    assert lock.auto_hit_players is True
    assert lock.auto_hit_mobs is True
    assert lock.auto_hit_target_name == ""


def test_example_config_documents_coordinate_auto_hit_targets():
    raw = json.loads(Path("config.example.json").read_text(encoding="utf-8"))

    example = raw["coordinate_locks"][0]
    assert example["enabled"] is False
    assert example["auto_hit_players"] is True
    assert example["auto_hit_mobs"] is True
    assert example["auto_hit_target_name"] == ""
```

- [ ] **Step 2: Run the tests to verify the new dataclass arguments fail**

Run: `python -m pytest tests/test_config.py -q`

Expected: FAIL because `CoordinateLockConfig` does not accept the three `auto_hit_*` fields and the example coordinate list is empty.

- [ ] **Step 3: Extend the dataclass and JSON conversion**

Add the fields after `active_area` so all existing positional construction remains compatible:

```python
@dataclass(frozen=True)
class CoordinateLockConfig:
    id: str
    x: float
    y: float
    z: float
    enabled: bool = True
    name: str = ""
    active_area: float = 50.0
    auto_hit_players: bool = True
    auto_hit_mobs: bool = True
    auto_hit_target_name: str = ""
```

Populate the fields when loading each coordinate:

```python
        locks.append(
            CoordinateLockConfig(
                id=str(raw_lock["id"]),
                x=float(raw_lock["x"]),
                y=float(raw_lock["y"]),
                z=float(raw_lock["z"]),
                enabled=bool(raw_lock.get("enabled", True)),
                name=str(raw_lock.get("name", "")).strip(),
                active_area=float(raw_lock.get("active_area", default_active_area)),
                auto_hit_players=bool(raw_lock.get("auto_hit_players", True)),
                auto_hit_mobs=bool(raw_lock.get("auto_hit_mobs", True)),
                auto_hit_target_name=str(
                    raw_lock.get("auto_hit_target_name", "")
                ).strip(),
            )
        )
```

Return all three fields from `_coordinate_lock_to_json`:

```python
def _coordinate_lock_to_json(lock: CoordinateLockConfig) -> dict[str, Any]:
    return {
        "id": lock.id,
        "x": lock.x,
        "y": lock.y,
        "z": lock.z,
        "enabled": lock.enabled,
        "name": lock.name,
        "active_area": lock.active_area,
        "auto_hit_players": lock.auto_hit_players,
        "auto_hit_mobs": lock.auto_hit_mobs,
        "auto_hit_target_name": lock.auto_hit_target_name,
    }
```

Replace the empty `coordinate_locks` array in `config.example.json` with a disabled example:

```json
  "coordinate_locks": [
    {
      "id": "example-farm",
      "x": 0.0,
      "y": 64.0,
      "z": 0.0,
      "enabled": false,
      "name": "Example Farm",
      "active_area": 50.0,
      "auto_hit_players": true,
      "auto_hit_mobs": true,
      "auto_hit_target_name": ""
    }
  ],
```

- [ ] **Step 4: Run configuration tests and syntax validation**

Run: `python -m pytest tests/test_config.py tests/test_runtime.py -q`

Expected: all tests PASS; runtime retains the complete immutable coordinate objects without new setters.

Run: `python -m json.tool config.example.json > $null`

Expected: exit code 0.

- [ ] **Step 5: Commit the configuration unit**

```powershell
git add holoquiz/config.py tests/test_config.py config.example.json
git commit -m "feat: persist coordinate auto hit targets"
```

---

### Task 2: Nearby-entity API client and pure matching

**Files:**
- Modify: `holoquiz/coordinate_lock.py:13-70`
- Modify: `tests/test_coordinate_lock.py:1-70`

**Interfaces:**
- Consumes: Standard-library `urlopen`, JSON endpoint objects, and `CoordinateLockConfig` from Task 1.
- Produces: `NearbyEntity`, `NearbyEntityClient.get_players()`, `NearbyEntityClient.get_mobs()`, and `entity_matches_auto_hit_target()` for Task 3.

- [ ] **Step 1: Write failing client and matching tests**

Extend imports and add these tests after `FakeResponse`:

```python
from holoquiz.coordinate_lock import (
    AUTO_HIT_TARGET_DISTANCE,
    NearbyEntity,
    NearbyEntityClient,
    entity_matches_auto_hit_target,
)


def test_nearby_entity_client_reads_players_and_mobs_from_expected_urls():
    requests = []
    payloads = {
        "http://127.0.0.1:8026/data/players": {
            "players": [
                {"distance": 4.5, "name": "Alex", "custom_name": "[Lv 6]Tatsunoko"}
            ]
        },
        "http://127.0.0.1:8026/data/mobs": {
            "mobs": [{"distance": 3.0, "name": "Zombie"}]
        },
    }

    def opener(url, *, timeout):
        requests.append((url, timeout))
        return FakeResponse(payloads[url])

    client = NearbyEntityClient(opener=opener, timeout_seconds=0.25)

    assert client.get_players() == (
        NearbyEntity(4.5, "Alex", "[Lv 6]Tatsunoko"),
    )
    assert client.get_mobs() == (NearbyEntity(3.0, "Zombie", None),)
    assert requests == [
        ("http://127.0.0.1:8026/data/players", 0.25),
        ("http://127.0.0.1:8026/data/mobs", 0.25),
    ]


def test_nearby_entity_client_rejects_malformed_payloads():
    client = NearbyEntityClient(opener=lambda *_args, **_kwargs: FakeResponse({"players": {}}))

    try:
        client.get_players()
    except ValueError as error:
        assert "players list" in str(error)
    else:
        raise AssertionError("Expected malformed players payload to fail")


def test_entity_target_matching_uses_five_block_inclusive_boundary_and_exact_casefold():
    player = NearbyEntity(5.0, "Alex", " [LV 6]TATSUNOKO ")
    farther_player = NearbyEntity(5.01, "Alex", "[Lv 6]Tatsunoko")

    assert AUTO_HIT_TARGET_DISTANCE == 5.0
    assert entity_matches_auto_hit_target(
        player,
        target_name="[Lv 6]Tatsunoko",
        name_attribute="custom_name",
    ) is True
    assert entity_matches_auto_hit_target(
        player,
        target_name="Tatsunoko",
        name_attribute="custom_name",
    ) is False
    assert entity_matches_auto_hit_target(
        farther_player,
        target_name="",
        name_attribute="custom_name",
    ) is False


def test_entity_target_matching_uses_mob_name_and_rejects_missing_player_custom_name():
    entity = NearbyEntity(2.0, "Zombie", None)

    assert entity_matches_auto_hit_target(
        entity, target_name="zOmBiE", name_attribute="name"
    ) is True
    assert entity_matches_auto_hit_target(
        entity, target_name="Zombie", name_attribute="custom_name"
    ) is False
    assert entity_matches_auto_hit_target(
        entity, target_name="", name_attribute="custom_name"
    ) is True
```

- [ ] **Step 2: Run focused tests to verify the interfaces are missing**

Run: `python -m pytest tests/test_coordinate_lock.py -q`

Expected: collection FAILS because `NearbyEntity`, `NearbyEntityClient`, `AUTO_HIT_TARGET_DISTANCE`, and `entity_matches_auto_hit_target` are not defined.

- [ ] **Step 3: Implement validated entity parsing and pure matching**

Add these definitions after `ContainerDataClient`:

```python
AUTO_HIT_TARGET_DISTANCE = 5.0


@dataclass(frozen=True)
class NearbyEntity:
    distance: float
    name: str
    custom_name: str | None = None


class NearbyEntityClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8026/data",
        *,
        timeout_seconds: float = 0.75,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def get_players(self) -> tuple[NearbyEntity, ...]:
        return self._get_entities("players")

    def get_mobs(self) -> tuple[NearbyEntity, ...]:
        return self._get_entities("mobs")

    def _get_entities(self, collection: str) -> tuple[NearbyEntity, ...]:
        url = f"{self.base_url}/{collection}"
        with self._opener(url, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Nearby {collection} endpoint returned a non-object response.")
        raw_entities = payload.get(collection)
        if not isinstance(raw_entities, list):
            raise ValueError(f"Nearby endpoint is missing the {collection} list.")

        entities: list[NearbyEntity] = []
        for raw_entity in raw_entities:
            if not isinstance(raw_entity, dict):
                raise ValueError(f"Nearby {collection} list contains a non-object entity.")
            name = raw_entity.get("name")
            if not isinstance(name, str):
                raise ValueError(f"Nearby {collection} entity is missing a string name.")
            try:
                distance = float(raw_entity["distance"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    f"Nearby {collection} entity has an invalid distance."
                ) from error
            if not math.isfinite(distance) or distance < 0:
                raise ValueError(f"Nearby {collection} entity has an invalid distance.")
            custom_name = raw_entity.get("custom_name")
            if custom_name is not None and not isinstance(custom_name, str):
                raise ValueError(
                    f"Nearby {collection} entity has an invalid custom_name."
                )
            entities.append(NearbyEntity(distance, name, custom_name))
        return tuple(entities)


def entity_matches_auto_hit_target(
    entity: NearbyEntity,
    *,
    target_name: str,
    name_attribute: str,
) -> bool:
    if entity.distance > AUTO_HIT_TARGET_DISTANCE:
        return False
    normalized_target = target_name.strip().casefold()
    if not normalized_target:
        return True
    candidate = getattr(entity, name_attribute)
    return candidate is not None and candidate.strip().casefold() == normalized_target
```

- [ ] **Step 4: Run focused client and matching tests**

Run: `python -m pytest tests/test_coordinate_lock.py -q`

Expected: all existing and new Coordinate Lock tests PASS because the new client is not yet wired into the worker.

- [ ] **Step 5: Commit the entity-query unit**

```powershell
git add holoquiz/coordinate_lock.py tests/test_coordinate_lock.py
git commit -m "feat: add nearby entity targeting"
```

---

### Task 3: Enforce fresh targets at the click boundary

**Files:**
- Modify: `holoquiz/coordinate_lock.py:173-370`
- Modify: `tests/test_coordinate_lock.py:33-70,408-558`

**Interfaces:**
- Consumes: `CoordinateLockConfig.auto_hit_players`, `.auto_hit_mobs`, `.auto_hit_target_name`, `NearbyEntityClient`, and `entity_matches_auto_hit_target()` from Tasks 1-2.
- Produces: `CoordinateLockWorker` that queries only selected entity types and clicks only for a fresh eligible target.

- [ ] **Step 1: Add a fake client and failing worker safety tests**

Add this fake near the existing API fakes:

```python
class FakeNearbyEntityClient:
    def __init__(self, *, players=(), mobs=(), error=None):
        self.players = tuple(players)
        self.mobs = tuple(mobs)
        self.error = error
        self.calls = []

    def get_players(self):
        self.calls.append("players")
        if self.error is not None:
            raise self.error
        return self.players

    def get_mobs(self):
        self.calls.append("mobs")
        if self.error is not None:
            raise self.error
        return self.mobs
```

Replace `test_worker_auto_hits_within_the_enabled_coordinate_range` with a test that proves coordinate range alone is insufficient:

```python
def test_worker_auto_hit_requires_a_nearby_entity_even_inside_coordinate_area():
    lock = CoordinateLockConfig("home", 0, 64, 0)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    entities = FakeNearbyEntityClient()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(49, 64, 0)),
        container_client=FakeContainerClient(),
        entity_client=entities,
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()

    assert worker._auto_hit_once() is False
    assert entities.calls == ["players", "mobs"]
    assert ("click", "left") not in keys.events
```

Add selection, name, success, and error-deduplication coverage:

```python
def test_worker_auto_hits_for_selected_player_custom_name():
    lock = CoordinateLockConfig(
        "home",
        0,
        64,
        0,
        auto_hit_players=True,
        auto_hit_mobs=False,
        auto_hit_target_name="[Lv 6]Tatsunoko",
    )
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    keys = FakePyAutoGui()
    entities = FakeNearbyEntityClient(
        players=(NearbyEntity(5.0, "Alex", "[LV 6]TATSUNOKO"),)
    )
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        container_client=FakeContainerClient(),
        entity_client=entities,
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()

    assert worker._auto_hit_once() is True
    assert entities.calls == ["players"]
    assert keys.events == [("click", "left")]


def test_worker_auto_hits_for_selected_mob_name_when_both_types_are_enabled():
    lock = CoordinateLockConfig(
        "home", 0, 64, 0, auto_hit_target_name="Zombie"
    )
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    entities = FakeNearbyEntityClient(
        players=(NearbyEntity(2.0, "Alex", "Not Zombie"),),
        mobs=(NearbyEntity(4.0, "zOmBiE"),),
    )
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        queue.Queue(),
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        container_client=FakeContainerClient(),
        entity_client=entities,
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()

    assert worker._auto_hit_once() is True
    assert entities.calls == ["players", "mobs"]
    assert keys.events == [("click", "left")]


def test_worker_fails_closed_and_deduplicates_nearby_api_errors():
    lock = CoordinateLockConfig("home", 0, 64, 0)
    controls = RuntimeControls.from_config(
        BotConfig(
            coordinate_lock_enabled=True,
            coordinate_lock_auto_hit_enabled=True,
            coordinate_locks=(lock,),
        )
    )
    logs = queue.Queue()
    keys = FakePyAutoGui()
    worker = CoordinateLockWorker(
        controls,
        logs,
        player_client=FakePlayerClient(PlayerPosition(0, 64, 0)),
        container_client=FakeContainerClient(),
        entity_client=FakeNearbyEntityClient(error=OSError("entity API unavailable")),
        pyautogui_module=keys,
        foreground_provider=lambda: True,
    )

    worker.check_once()
    assert worker._auto_hit_once() is False
    assert worker._auto_hit_once() is False

    messages = []
    while not logs.empty():
        messages.append(logs.get_nowait())
    assert sum("entity API unavailable" in message for message in messages) == 1
    assert keys.events == []
```

In `test_auto_hit_click_loop_is_independent_from_location_polling`, add this constructor argument so both clicks have a valid nearby target:

```python
        entity_client=FakeNearbyEntityClient(
            players=(NearbyEntity(2.0, "Alex", None),)
        ),
```

In `test_worker_skips_auto_hit_when_inventory_check_fails`, associate the manually-set event with the enabled coordinate before calling `_auto_hit_once`:

```python
    worker._auto_hit_lock_id = "home"
    worker._auto_hit_in_range.set()
```

Existing tests that return before entity lookup require no entity fake.

- [ ] **Step 2: Run worker tests to verify coordinate-only clicking and constructor gaps fail**

Run: `python -m pytest tests/test_coordinate_lock.py -q`

Expected: FAIL because `CoordinateLockWorker.__init__` has no `entity_client` argument and `_auto_hit_once` does not query entities.

- [ ] **Step 3: Track the active coordinate and inject the entity client**

Add the constructor parameter and state:

```python
        entity_client: NearbyEntityClient | None = None,
```

```python
        self.entity_client = entity_client or NearbyEntityClient()
        self._auto_hit_lock_id: str | None = None
        self._last_auto_hit_error = ""
```

Add one state-clearing helper and use it everywhere the code currently calls `self._auto_hit_in_range.clear()`:

```python
    def _clear_auto_hit_state(self) -> None:
        self._auto_hit_in_range.clear()
        self._auto_hit_lock_id = None
```

When `check_once` finds an in-area lock and Auto Hit is enabled, retain its ID before setting the event:

```python
            if config.coordinate_lock_auto_hit_enabled:
                self._auto_hit_lock_id = lock.id
                self._auto_hit_in_range.set()
            else:
                self._clear_auto_hit_state()
```

This makes a coordinate switch fail closed until the polling loop confirms the newly active coordinate is also in its active area.

- [ ] **Step 4: Add click-boundary entity lookup and matching**

Add these worker helpers:

```python
    def _active_auto_hit_lock(
        self, config: BotConfig
    ) -> CoordinateLockConfig | None:
        return next(
            (
                lock
                for lock in config.coordinate_locks
                if lock.enabled and lock.id == self._auto_hit_lock_id
            ),
            None,
        )

    def _has_auto_hit_target(self, lock: CoordinateLockConfig) -> bool:
        players = self.entity_client.get_players() if lock.auto_hit_players else ()
        mobs = self.entity_client.get_mobs() if lock.auto_hit_mobs else ()
        self._last_auto_hit_error = ""
        player_match = any(
            entity_matches_auto_hit_target(
                entity,
                target_name=lock.auto_hit_target_name,
                name_attribute="custom_name",
            )
            for entity in players
        )
        mob_match = any(
            entity_matches_auto_hit_target(
                entity,
                target_name=lock.auto_hit_target_name,
                name_attribute="name",
            )
            for entity in mobs
        )
        return player_match or mob_match

    def _auto_hit_error(self, error: Exception) -> None:
        message = f"[coordinate-lock-auto-hit-target-error] {error}"
        if message != self._last_auto_hit_error:
            self.log_queue.put(message)
            self._last_auto_hit_error = message
```

Replace `_auto_hit_once` with the following ordering so every network-dependent decision occurs before the input session and click:

```python
    def _auto_hit_once(self) -> bool:
        config = self.controls.get_config()
        lock = self._active_auto_hit_lock(config)
        if not (
            self._auto_hit_in_range.is_set()
            and config.program_enabled
            and config.coordinate_lock_enabled
            and config.coordinate_lock_auto_hit_enabled
            and lock is not None
        ):
            return False
        if not self._foreground_provider():
            return False
        try:
            if self.container_client.is_open():
                self._clear_auto_hit_state()
                return False
        except Exception as error:
            self._status(f"[coordinate-lock-auto-hit-container-error] {error}")
            return False
        try:
            if not self._has_auto_hit_target(lock):
                return False
        except Exception as error:
            self._auto_hit_error(error)
            return False
        with self._input_coordinator.movement_session() as input_allowed:
            if not input_allowed:
                return False
            pyautogui = self._pyautogui or self._load_pyautogui()
            pyautogui.click(button="left", _pause=False)
            return True
```

Change the non-click retry from `0.01` to the existing poll interval so an absent target does not generate roughly 100 HTTP checks per second:

```python
            delay = (
                auto_hit_delay_seconds(self.controls.get_config())
                if clicked
                else self.poll_seconds
            )
```

- [ ] **Step 5: Run the complete Coordinate Lock and runtime tests**

Run: `python -m pytest tests/test_coordinate_lock.py tests/test_runtime.py -q`

Expected: all tests PASS, including existing foreground, inventory, active-area, movement, and interval tests.

- [ ] **Step 6: Commit the worker safety gate**

```powershell
git add holoquiz/coordinate_lock.py tests/test_coordinate_lock.py
git commit -m "feat: gate auto hit by nearby targets"
```

---

### Task 4: Per-coordinate GUI editor and Saved Targets display

**Files:**
- Modify: `holoquiz/gui.py:744-770,1182-1335,1850-1940,2000-2025`
- Modify: `tests/test_gui.py:230-300`

**Interfaces:**
- Consumes: The three `CoordinateLockConfig` targeting fields from Task 1.
- Produces: Per-coordinate `Players`, `Mobs`, and `Target Name` form controls; `coordinate_lock_target_summary()` for table display; validated coordinate objects.

- [ ] **Step 1: Write failing form, edit, and summary tests**

Extend the existing coordinate-form test setup with the new variables and assertions:

```python
def test_coordinate_form_builds_per_coordinate_auto_hit_targeting():
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.coordinate_lock_name_var = SimpleNamespace(get=lambda: "Farm")
    panel.coordinate_lock_x_var = SimpleNamespace(get=lambda: "10")
    panel.coordinate_lock_y_var = SimpleNamespace(get=lambda: "64")
    panel.coordinate_lock_z_var = SimpleNamespace(get=lambda: "-20")
    panel.coordinate_lock_active_area_var = SimpleNamespace(get=lambda: "75")
    panel.coordinate_lock_auto_hit_players_var = SimpleNamespace(get=lambda: True)
    panel.coordinate_lock_auto_hit_mobs_var = SimpleNamespace(get=lambda: False)
    panel.coordinate_lock_target_name_var = SimpleNamespace(
        get=lambda: "  [Lv 6]Tatsunoko  "
    )
    panel.coordinate_lock_editing_id = None
    panel.controls = RuntimeControls.from_config(BotConfig())

    result = panel._build_coordinate_lock_from_form()

    assert result.ok is True
    assert result.value is not None
    assert result.value.name == "Farm"
    assert result.value.active_area == 75
    assert result.value.auto_hit_players is True
    assert result.value.auto_hit_mobs is False
    assert result.value.auto_hit_target_name == "[Lv 6]Tatsunoko"


def test_coordinate_form_requires_at_least_one_auto_hit_target_type():
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.coordinate_lock_name_var = SimpleNamespace(get=lambda: "Farm")
    panel.coordinate_lock_x_var = SimpleNamespace(get=lambda: "10")
    panel.coordinate_lock_y_var = SimpleNamespace(get=lambda: "64")
    panel.coordinate_lock_z_var = SimpleNamespace(get=lambda: "-20")
    panel.coordinate_lock_active_area_var = SimpleNamespace(get=lambda: "75")
    panel.coordinate_lock_auto_hit_players_var = SimpleNamespace(get=lambda: False)
    panel.coordinate_lock_auto_hit_mobs_var = SimpleNamespace(get=lambda: False)
    panel.coordinate_lock_target_name_var = SimpleNamespace(get=lambda: "")
    panel.coordinate_lock_editing_id = None
    panel.controls = RuntimeControls.from_config(BotConfig())

    result = panel._build_coordinate_lock_from_form()

    assert result.ok is False
    assert result.message == "Select Players, Mobs, or both for Auto Hit."


def test_coordinate_target_summary_describes_saved_settings():
    assert gui.coordinate_lock_target_summary(
        CoordinateLockConfig("both", 1, 2, 3)
    ) == "Players + Mobs"
    assert gui.coordinate_lock_target_summary(
        CoordinateLockConfig(
            "mobs", 1, 2, 3, auto_hit_players=False, auto_hit_mobs=True
        )
    ) == "Mobs"
```

Add an edit-state test with concrete recording fakes:

```python
def test_edit_coordinate_loads_per_coordinate_auto_hit_targeting():
    class RecordingVar:
        def __init__(self):
            self.value = None

        def set(self, value):
            self.value = value

    lock = CoordinateLockConfig(
        "farm",
        1,
        64,
        2,
        name="Farm",
        auto_hit_players=False,
        auto_hit_mobs=True,
        auto_hit_target_name="Zombie",
    )
    panel = object.__new__(gui.HoloQuizControlPanel)
    panel.controls = RuntimeControls.from_config(BotConfig(coordinate_locks=(lock,)))
    panel.coordinate_lock_name_var = RecordingVar()
    panel.coordinate_lock_x_var = RecordingVar()
    panel.coordinate_lock_y_var = RecordingVar()
    panel.coordinate_lock_z_var = RecordingVar()
    panel.coordinate_lock_active_area_var = RecordingVar()
    panel.coordinate_lock_auto_hit_players_var = RecordingVar()
    panel.coordinate_lock_auto_hit_mobs_var = RecordingVar()
    panel.coordinate_lock_target_name_var = RecordingVar()
    panel.coordinate_lock_submit_button = SimpleNamespace(configure=lambda **_kwargs: None)
    panel.coordinate_lock_status_var = RecordingVar()

    panel._on_edit_coordinate_lock("farm")

    assert panel.coordinate_lock_auto_hit_players_var.value is False
    assert panel.coordinate_lock_auto_hit_mobs_var.value is True
    assert panel.coordinate_lock_target_name_var.value == "Zombie"
```

Add these defaults to both existing form tests, `test_coordinate_form_builds_target_with_custom_active_area` and `test_coordinate_form_rejects_non_positive_active_area`, because the form will now read all three variables:

```python
    panel.coordinate_lock_auto_hit_players_var = SimpleNamespace(get=lambda: True)
    panel.coordinate_lock_auto_hit_mobs_var = SimpleNamespace(get=lambda: True)
    panel.coordinate_lock_target_name_var = SimpleNamespace(get=lambda: "")
```

- [ ] **Step 2: Run GUI tests to verify the new state and helper are missing**

Run: `python -m pytest tests/test_gui.py -q`

Expected: FAIL because the form does not read the new variables and `coordinate_lock_target_summary` is undefined.

- [ ] **Step 3: Add GUI state and a target summary helper**

Define the pure summary near the existing small GUI helpers:

```python
def coordinate_lock_target_summary(lock: CoordinateLockConfig) -> str:
    if lock.auto_hit_players and lock.auto_hit_mobs:
        return "Players + Mobs"
    if lock.auto_hit_players:
        return "Players"
    if lock.auto_hit_mobs:
        return "Mobs"
    return "None"
```

Initialize the form variables with defaults suitable for a new coordinate:

```python
        self.coordinate_lock_auto_hit_players_var = tk.BooleanVar(value=True)
        self.coordinate_lock_auto_hit_mobs_var = tk.BooleanVar(value=True)
        self.coordinate_lock_target_name_var = tk.StringVar(value="")
```

- [ ] **Step 4: Rename Coordinate Name and add the per-coordinate target row**

Change the existing label tuple entry to `("Coordinate Name", self.coordinate_lock_name_var)`.

Insert this row below the coordinate fields and move the status row from grid row 3 to row 4:

```python
        auto_hit_target_row = ttk.Frame(coordinate_lock_form)
        auto_hit_target_row.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(
            auto_hit_target_row,
            text="Auto hit targets",
            style="FieldLabel.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Checkbutton(
            auto_hit_target_row,
            text="Players",
            variable=self.coordinate_lock_auto_hit_players_var,
        ).grid(row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Checkbutton(
            auto_hit_target_row,
            text="Mobs",
            variable=self.coordinate_lock_auto_hit_mobs_var,
        ).grid(row=0, column=2, sticky="w", padx=(0, 18))
        ttk.Label(auto_hit_target_row, text="Target Name").grid(
            row=0, column=3, sticky="w", padx=(0, 6)
        )
        ttk.Entry(
            auto_hit_target_row,
            textvariable=self.coordinate_lock_target_name_var,
            width=30,
        ).grid(row=0, column=4, sticky="ew")
        auto_hit_target_row.columnconfigure(4, weight=1)
```

Replace the Treeview column declarations with widths that fit the existing Coordinate Lock panel while adding `Targets` and `Target Name`:

```python
        self.coordinate_lock_tree = ttk.Treeview(
            coordinate_lock_list,
            columns=(
                "status",
                "name",
                "target_types",
                "target_name",
                "x",
                "y",
                "z",
                "active_area",
            ),
            show="headings",
            selectmode="browse",
            height=6,
        )
        for column, heading, width, stretch in (
            ("status", "Status", 75, False),
            ("name", "Coordinate Name", 130, True),
            ("target_types", "Targets", 110, False),
            ("target_name", "Target Name", 170, True),
            ("x", "X", 75, False),
            ("y", "Y", 75, False),
            ("z", "Z", 75, False),
            ("active_area", "Active area", 85, False),
        ):
            self.coordinate_lock_tree.heading(column, text=heading)
            self.coordinate_lock_tree.column(
                column, width=width, minwidth=70, stretch=stretch
            )
```

Insert the target summary and display name between the saved coordinate name and X value:

```python
                    coordinate_lock_target_summary(lock),
                    lock.auto_hit_target_name or "Any",
```

- [ ] **Step 5: Build, validate, clear, and edit the targeting fields**

Read and validate flags before numeric parsing:

```python
        auto_hit_players = self.coordinate_lock_auto_hit_players_var.get()
        auto_hit_mobs = self.coordinate_lock_auto_hit_mobs_var.get()
        if not auto_hit_players and not auto_hit_mobs:
            return CoordinateLockBuildResult(
                False, "Select Players, Mobs, or both for Auto Hit."
            )
        auto_hit_target_name = self.coordinate_lock_target_name_var.get().strip()
```

Pass them into the constructed coordinate:

```python
                auto_hit_players=auto_hit_players,
                auto_hit_mobs=auto_hit_mobs,
                auto_hit_target_name=auto_hit_target_name,
```

Reset new-coordinate defaults in `_clear_coordinate_lock_form`:

```python
        self.coordinate_lock_auto_hit_players_var.set(True)
        self.coordinate_lock_auto_hit_mobs_var.set(True)
        self.coordinate_lock_target_name_var.set("")
```

Load stored settings in `_on_edit_coordinate_lock`:

```python
        self.coordinate_lock_auto_hit_players_var.set(lock.auto_hit_players)
        self.coordinate_lock_auto_hit_mobs_var.set(lock.auto_hit_mobs)
        self.coordinate_lock_target_name_var.set(lock.auto_hit_target_name)
```

- [ ] **Step 6: Run GUI and focused integration tests**

Run: `python -m pytest tests/test_gui.py tests/test_config.py tests/test_coordinate_lock.py tests/test_runtime.py -q`

Expected: all tests PASS.

- [ ] **Step 7: Commit the GUI unit**

```powershell
git add holoquiz/gui.py tests/test_gui.py
git commit -m "feat: configure auto hit targets per coordinate"
```

---

### Task 5: Full verification and handoff

**Files:**
- Verify only; modify production or tests only if a failing check exposes a regression in the approved scope.

**Interfaces:**
- Consumes: Completed configuration, API client, worker gate, and GUI units.
- Produces: Evidence that the repository is syntactically valid and all pytest behavior passes together.

- [ ] **Step 1: Run formatting and whitespace checks**

Run: `git diff --check HEAD~4..HEAD`

Expected: exit code 0 with no whitespace errors.

- [ ] **Step 2: Run the package syntax check**

Run: `python -m py_compile holoquiz/*.py`

Expected: exit code 0 with no output.

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest`

Expected: all tests PASS with no failures or errors.

- [ ] **Step 4: Inspect the final scoped diff**

Run: `git status --short` and `git diff HEAD~4..HEAD -- holoquiz/config.py holoquiz/coordinate_lock.py holoquiz/gui.py config.example.json tests/test_config.py tests/test_coordinate_lock.py tests/test_gui.py`

Expected: only the approved config, targeting, GUI, example, and test changes are present; no local `config.json`, `quiz_memory.json`, screenshots, logs, or secrets are tracked.

- [ ] **Step 5: Record any verification-only fix**

If Step 1-4 required an in-scope correction, rerun the failed command and commit only that correction:

```powershell
git add holoquiz/config.py holoquiz/coordinate_lock.py holoquiz/gui.py config.example.json tests/test_config.py tests/test_coordinate_lock.py tests/test_gui.py
git commit -m "fix: complete auto hit target verification"
```

If no correction was required, do not create an empty commit.
