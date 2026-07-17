from __future__ import annotations

from collections import deque
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from datetime import datetime
from functools import partial
from io import BytesIO
import queue
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Sequence

from PIL import Image, ImageTk

from holoquiz.config import AutoHealItemConfig, validate_auto_heal_item
from holoquiz.player import (
    InventorySlot,
    ItemIconClient,
    PlayerOverviewClient,
    PlayerSnapshot,
    build_inventory_layout,
    format_item_tooltip,
)


SLOT_SIZE = 48
HEALTH_MAX_FALLBACK = 1.0
HUNGER_MAXIMUM = 20
PLAYER_PAGE_MAX_WIDTH = 1100
RETURN_ITEM_BORDER = "#d4a017"


def configure_player_tab_grid(parent: Any) -> None:
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=0)
    parent.rowconfigure(1, weight=1)


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
    window_id = canvas.create_window(
        (0, 0),
        window=content,
        anchor="n",
    )
    content.bind(
        "<Configure>",
        lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
    )

    def resize_content(event: Any) -> None:
        width = max(1, min(event.width - 24, PLAYER_PAGE_MAX_WIDTH))
        canvas.coords(window_id, event.width / 2, 0)
        canvas.itemconfigure(window_id, width=width)

    canvas.bind("<Configure>", resize_content)
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
    profile.grid(
        row=0,
        column=0,
        sticky="nw",
        padx=(0, 12),
        pady=(0, 12),
    )
    stats.grid(row=0, column=1, sticky="nsew", pady=(0, 12))
    inventory.grid(
        row=1,
        column=0,
        columnspan=2,
        sticky="ew",
        pady=(0, 12),
    )
    auto_heal.grid(
        row=2,
        column=0,
        columnspan=2,
        sticky="ew",
    )


def layout_auto_heal_rule_actions(
    edit_button: Any,
    remove_button: Any,
) -> None:
    edit_button.grid(row=0, column=1, padx=(8, 4))
    remove_button.grid(row=0, column=2)


def health_percent(snapshot: PlayerSnapshot) -> float:
    maximum = snapshot.health.maximum or HEALTH_MAX_FALLBACK
    return min(max(snapshot.health.current / maximum * 100.0, 0.0), 100.0)


def hunger_percent(snapshot: PlayerSnapshot) -> float:
    return min(
        max(snapshot.hunger.food_level / HUNGER_MAXIMUM * 100.0, 0.0),
        100.0,
    )


def inventory_item_action_labels(
    slot: InventorySlot,
    auto_heal_items: Sequence[AutoHealItemConfig],
) -> tuple[str, ...]:
    configured_names = {item.name for item in auto_heal_items}
    auto_heal_label = (
        "Edit Auto Heal Item"
        if slot.item.name in configured_names
        else "Add Auto Heal Item"
    )
    labels = [auto_heal_label]
    if slot.section == "hotbar":
        labels.append("Set as Return Item")
    return tuple(labels)


def item_slot_border(
    slot: InventorySlot,
    *,
    is_return_item: bool,
) -> str:
    if is_return_item:
        return RETURN_ITEM_BORDER
    if slot.item.is_enchanted:
        return "#9b5de5"
    return "#555b64"


def _parse_auto_heal_percent(value: str, label: str) -> int:
    try:
        return int(value.strip() or "0")
    except ValueError as error:
        raise ValueError(
            f"Auto Heal {label} percentage must be an integer "
            "between 0 and 100."
        ) from error


def parse_auto_heal_form(
    name: str,
    cooldown: str,
    duration: str,
    health: str,
    hunger: str,
) -> AutoHealItemConfig:
    try:
        cooldown_seconds = float(cooldown)
        use_duration_seconds = (
            float(duration) if duration.strip() else 2.0
        )
    except ValueError as error:
        raise ValueError("Auto Heal values must be numeric.") from error
    item = AutoHealItemConfig(
        name=name,
        cooldown_seconds=cooldown_seconds,
        use_duration_seconds=use_duration_seconds,
        health_percent_below=_parse_auto_heal_percent(health, "health"),
        hunger_percent_below=_parse_auto_heal_percent(hunger, "hunger"),
    )
    return validate_auto_heal_item(item)


def format_auto_heal_rule(item: AutoHealItemConfig) -> str:
    return (
        f"Cooldown: {item.cooldown_seconds:g}s   "
        f"Use: {item.use_duration_seconds:g}s   "
        f"Health < {item.health_percent_below}%   "
        f"Hunger < {item.hunger_percent_below}%"
    )


class PlayerPoller:
    def __init__(
        self,
        scheduler: Any,
        fetch: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        *,
        interval_ms: int = 1000,
        drain_ms: int = 25,
        executor: Executor | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.fetch = fetch
        self.on_success = on_success
        self.on_error = on_error
        self.interval_ms = interval_ms
        self.drain_ms = drain_ms
        self.executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="player-view",
        )
        self.results: queue.Queue[tuple[int, bool, Any]] = queue.Queue()
        self.active = False
        self.in_flight = False
        self.closed = False
        self._activation_generation = 0
        self._poll_after_id: str | None = None
        self._drain_after_id: str | None = None

    def activate(self) -> None:
        if self.closed or self.active:
            return
        self.active = True
        self._activation_generation += 1
        self._schedule_drain()
        self.refresh()

    def deactivate(self) -> None:
        self.active = False
        self._cancel("_poll_after_id")
        self._cancel("_drain_after_id")

    def refresh(self) -> bool:
        if self.closed or not self.active or self.in_flight:
            return False
        self._cancel("_poll_after_id")
        self.in_flight = True
        self.executor.submit(
            partial(self._fetch_to_queue, self._activation_generation)
        )
        return True

    def _fetch_to_queue(self, generation: int) -> None:
        try:
            self.results.put((generation, True, self.fetch()))
        except Exception as error:
            self.results.put((generation, False, error))

    def _schedule_drain(self) -> None:
        if self.active and not self.closed and self._drain_after_id is None:
            self._drain_after_id = self.scheduler.after(
                self.drain_ms,
                self._drain,
            )

    def _drain(self) -> None:
        self._drain_after_id = None
        delivered_current = False
        retired_stale = False
        while True:
            try:
                generation, ok, value = self.results.get_nowait()
            except queue.Empty:
                break
            self.in_flight = False
            if generation != self._activation_generation:
                retired_stale = True
                continue
            delivered_current = True
            if not self.closed:
                if ok:
                    self.on_success(value)
                else:
                    self.on_error(value)
        if self.active and not self.closed:
            if retired_stale:
                self.refresh()
            elif delivered_current:
                self._poll_after_id = self.scheduler.after(
                    self.interval_ms,
                    self._scheduled_refresh,
                )
        self._schedule_drain()

    def _scheduled_refresh(self) -> None:
        self._poll_after_id = None
        self.refresh()

    def _cancel(self, attribute: str) -> None:
        callback_id = getattr(self, attribute)
        if callback_id is not None:
            self.scheduler.after_cancel(callback_id)
            setattr(self, attribute, None)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.deactivate()
        self.executor.shutdown(wait=False, cancel_futures=True)


class PlayerIconLoader:
    """Serial, cooperatively cancellable icon work drained on Tk's thread."""

    def __init__(
        self,
        scheduler: Any,
        fetch: Callable[[str], Any],
        on_success: Callable[[str, Any], None],
        *,
        drain_ms: int = 25,
        executor: Executor | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.fetch = fetch
        self.on_success = on_success
        self.drain_ms = drain_ms
        self.executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="player-icons",
        )
        self.results: queue.Queue[tuple[int, str, bool, Any]] = queue.Queue()
        self.active = False
        self.closed = False
        self._generation = 0
        self._queued: deque[str] = deque()
        self._pending: set[str] = set()
        self._current: tuple[int, str, Future[Any]] | None = None
        self._drain_after_id: str | None = None

    def activate(self) -> None:
        if self.closed or self.active:
            return
        self.active = True
        self._generation += 1
        self._schedule_drain()
        self._start_next()

    def deactivate(self) -> None:
        self.active = False
        self._generation += 1
        self._queued.clear()
        self._pending.clear()
        self._cancel_drain()
        if self._current is not None and self._current[2].cancel():
            self._current = None

    def queue(self, item_ids: list[str] | set[str] | tuple[str, ...]) -> None:
        if self.closed or not self.active:
            return
        for item_id in item_ids:
            if item_id and item_id not in self._pending:
                self._pending.add(item_id)
                self._queued.append(item_id)
        self._start_next()
        self._schedule_drain()

    def _start_next(self) -> None:
        if self.closed or not self.active or self._current is not None:
            return
        if not self._queued:
            return
        item_id = self._queued.popleft()
        generation = self._generation
        future = self.executor.submit(
            partial(self._fetch_to_queue, generation, item_id)
        )
        self._current = (generation, item_id, future)

    def _fetch_to_queue(self, generation: int, item_id: str) -> None:
        try:
            value = self.fetch(item_id)
            self.results.put((generation, item_id, True, value))
        except Exception as error:
            self.results.put((generation, item_id, False, error))

    def _schedule_drain(self) -> None:
        if self.active and not self.closed and self._drain_after_id is None:
            self._drain_after_id = self.scheduler.after(
                self.drain_ms,
                self._drain,
            )

    def _drain(self) -> None:
        self._drain_after_id = None
        while True:
            try:
                generation, item_id, ok, value = self.results.get_nowait()
            except queue.Empty:
                break
            if (
                self._current is not None
                and self._current[:2] == (generation, item_id)
            ):
                self._current = None
            if (
                generation != self._generation
                or not self.active
                or self.closed
            ):
                continue
            self._pending.discard(item_id)
            if ok:
                self.on_success(item_id, value)
        self._start_next()
        self._schedule_drain()

    def _cancel_drain(self) -> None:
        if self._drain_after_id is not None:
            self.scheduler.after_cancel(self._drain_after_id)
            self._drain_after_id = None

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.deactivate()
        self.executor.shutdown(wait=False, cancel_futures=True)


class ItemTooltip:
    def __init__(self, parent: tk.Misc) -> None:
        self.parent = parent
        self.window: tk.Toplevel | None = None
        self.owner: tk.Widget | None = None

    def show(self, widget: tk.Widget, text: str) -> None:
        self.hide()
        self.owner = widget
        self.window = tk.Toplevel(self.parent)
        self.window.wm_overrideredirect(True)
        label = tk.Label(
            self.window,
            text=text,
            justify="left",
            background="#130016",
            foreground="#f2e9ff",
            borderwidth=2,
            relief="solid",
            padx=9,
            pady=7,
            font=("Segoe UI", 9),
        )
        label.pack()
        self.window.geometry(
            f"+{widget.winfo_pointerx() + 14}+{widget.winfo_pointery() + 14}"
        )

    def hide(self, owner: tk.Widget | None = None) -> None:
        if owner is not None and owner is not self.owner:
            return
        if self.window is not None:
            self.window.destroy()
            self.window = None
        self.owner = None


class ItemSlotWidget:
    def __init__(
        self,
        parent: tk.Misc,
        tooltip: ItemTooltip,
        *,
        on_right_click: Callable[
            [InventorySlot, tk.Event | None],
            None,
        ]
        | None = None,
    ) -> None:
        self.tooltip = tooltip
        self.on_right_click = on_right_click
        self.canvas = tk.Canvas(
            parent,
            width=SLOT_SIZE,
            height=SLOT_SIZE,
            background="#8b8f94",
            highlightthickness=2,
            highlightbackground="#555b64",
        )
        self.slot: InventorySlot | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.canvas.bind("<Enter>", self._show_tooltip)
        self.canvas.bind(
            "<Leave>",
            lambda _event: self.tooltip.hide(self.canvas),
        )
        self.canvas.bind("<Button-3>", self._on_right_click)

    def grid(self, **kwargs: Any) -> None:
        self.canvas.grid(**kwargs)

    def render(
        self,
        slot: InventorySlot,
        photo: ImageTk.PhotoImage | None,
        *,
        is_return_item: bool = False,
    ) -> None:
        if self.slot != slot:
            self.tooltip.hide(self.canvas)
        self.slot = slot
        self.photo = photo
        self.canvas.delete("all")
        border = item_slot_border(slot, is_return_item=is_return_item)
        self.canvas.configure(highlightbackground=border)
        if slot.item.empty:
            return
        if photo is None:
            self.canvas.create_rectangle(
                9,
                9,
                SLOT_SIZE - 9,
                SLOT_SIZE - 9,
                outline="#68707c",
                width=2,
            )
            self.canvas.create_line(15, 15, SLOT_SIZE - 15, SLOT_SIZE - 15)
            self.canvas.create_line(SLOT_SIZE - 15, 15, 15, SLOT_SIZE - 15)
        else:
            self.canvas.create_image(
                SLOT_SIZE // 2,
                SLOT_SIZE // 2,
                image=photo,
            )
        if slot.item.count > 1:
            self.canvas.create_text(
                SLOT_SIZE - 4,
                SLOT_SIZE - 3,
                text=str(slot.item.count),
                anchor="se",
                fill="white",
                font=("Segoe UI Semibold", 9),
            )

    def _show_tooltip(self, _event: tk.Event) -> None:
        if self.slot is not None and not self.slot.item.empty:
            self.tooltip.show(self.canvas, format_item_tooltip(self.slot))

    def _on_right_click(self, event: tk.Event | None) -> None:
        if (
            self.on_right_click is not None
            and self.slot is not None
            and not self.slot.item.empty
        ):
            self.on_right_click(self.slot, event)


class AutoHealItemDialog:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        name: str,
        existing: AutoHealItemConfig | None,
        on_save: Callable[[AutoHealItemConfig], None],
    ) -> None:
        self.on_save = on_save
        self.window = tk.Toplevel(parent)
        self.window.title("Auto Heal item")
        self.window.transient(parent.winfo_toplevel())
        self.window.resizable(False, False)
        self.name = name
        self.cooldown_var = tk.StringVar(
            value=f"{existing.cooldown_seconds:g}" if existing else "0"
        )
        self.duration_var = tk.StringVar(
            value=f"{existing.use_duration_seconds:g}" if existing else "2"
        )
        self.health_var = tk.StringVar(
            value=str(existing.health_percent_below) if existing else "0"
        )
        self.hunger_var = tk.StringVar(
            value=str(existing.hunger_percent_below) if existing else "0"
        )
        self.error_var = tk.StringVar(value="")

        frame = ttk.Frame(self.window, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text="Item").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text=name, wraplength=420).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(8, 0),
        )
        fields = (
            ("Cooldown time (seconds)", self.cooldown_var),
            ("Use duration (seconds)", self.duration_var),
            ("Use when health below (%)", self.health_var),
            ("Use when hunger below (%)", self.hunger_var),
        )
        for row, (label, variable) in enumerate(fields, start=1):
            ttk.Label(frame, text=label).grid(
                row=row,
                column=0,
                sticky="w",
            )
            ttk.Entry(frame, textvariable=variable, width=14).grid(
                row=row,
                column=1,
                sticky="w",
                padx=(8, 0),
                pady=2,
            )
        ttk.Label(
            frame,
            textvariable=self.error_var,
            foreground="#b42318",
        ).grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(6, 0),
        )
        buttons = ttk.Frame(frame)
        buttons.grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="e",
            pady=(10, 0),
        )
        ttk.Button(
            buttons,
            text="Cancel",
            command=self.window.destroy,
        ).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="Save", command=self._save).grid(
            row=0,
            column=1,
        )
        self.window.grab_set()

    def _save(self) -> None:
        try:
            item = parse_auto_heal_form(
                self.name,
                self.cooldown_var.get(),
                self.duration_var.get(),
                self.health_var.get(),
                self.hunger_var.get(),
            )
        except ValueError as error:
            self.error_var.set(str(error))
            return
        self.on_save(item)
        self.window.destroy()


class PlayerTab:
    def __init__(
        self,
        parent: ttk.Frame,
        *,
        player_url: str,
        auto_heal_enabled: bool = False,
        auto_heal_items: Sequence[AutoHealItemConfig] = (),
        auto_heal_return_item_name: str = "",
        on_auto_heal_enabled_changed: Callable[[bool], None] | None = None,
        on_auto_heal_items_changed: Callable[
            [tuple[AutoHealItemConfig, ...]],
            None,
        ]
        | None = None,
        on_auto_heal_return_item_changed: Callable[[str], None] | None = None,
    ) -> None:
        self.parent = parent
        self.player_client = PlayerOverviewClient(player_url)
        self.icon_client = ItemIconClient()
        self.status_var = tk.StringVar(value="Not connected")
        self.updated_var = tk.StringVar(value="No player data yet")
        self.health_var = tk.StringVar(value="Health: --")
        self.hunger_var = tk.StringVar(value="Hunger: --")
        self.details_var = tk.StringVar(value="")
        self.error_var = tk.StringVar(value="")
        self.auto_heal_items = tuple(auto_heal_items)
        self.auto_heal_return_item_name = auto_heal_return_item_name
        self.on_auto_heal_enabled_changed = (
            on_auto_heal_enabled_changed or (lambda _enabled: None)
        )
        self.on_auto_heal_items_changed = (
            on_auto_heal_items_changed or (lambda _items: None)
        )
        self.on_auto_heal_return_item_changed = (
            on_auto_heal_return_item_changed or (lambda _name: None)
        )
        self.auto_heal_enabled_var = tk.BooleanVar(
            value=auto_heal_enabled
        )
        self.tooltip = ItemTooltip(parent)
        self.photos: dict[str, ImageTk.PhotoImage] = {}
        self._prepared_icons: dict[str, Image.Image] = {}
        self._snapshot: PlayerSnapshot | None = None
        self._mousewheel_binding_id: str | None = None
        self._build()
        self.icon_loader = PlayerIconLoader(
            parent,
            self._load_icon,
            self._apply_icon,
        )
        self.poller = PlayerPoller(
            parent,
            self.player_client.fetch,
            self._render,
            self._show_error,
        )

    def _build(self) -> None:
        configure_player_tab_grid(self.parent)
        toolbar = ttk.Frame(self.parent)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(
            toolbar,
            text="Player",
            style="SectionLabel.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(toolbar, textvariable=self.status_var).grid(
            row=0,
            column=1,
            sticky="e",
            padx=8,
        )
        ttk.Button(toolbar, text="Refresh", command=self.refresh).grid(
            row=0,
            column=2,
            sticky="e",
        )
        ttk.Label(
            toolbar,
            textvariable=self.updated_var,
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Label(
            toolbar,
            textvariable=self.error_var,
            foreground="#b42318",
        ).grid(row=2, column=0, columnspan=3, sticky="w")

        body = ttk.Frame(self.parent)
        body.grid(row=1, column=0, sticky="nsew")
        self.player_canvas = tk.Canvas(
            body,
            borderwidth=0,
            highlightthickness=0,
        )
        self.player_scrollbar = ttk.Scrollbar(
            body,
            orient="vertical",
            command=self.player_canvas.yview,
        )
        player_content = ttk.Frame(
            self.player_canvas,
            padding=(12, 0, 12, 12),
        )
        configure_scrollable_player_body(
            body,
            self.player_canvas,
            self.player_scrollbar,
            player_content,
        )

        profile = ttk.LabelFrame(
            player_content,
            text="Player overview",
            padding=10,
        )
        # TODO: Replace this placeholder when /data/player exposes a player
        # username or UUID that can be resolved to a real skin.
        skin = tk.Canvas(
            profile,
            width=150,
            height=220,
            background="#2b2f36",
            highlightthickness=0,
        )
        skin.grid(row=0, column=1, rowspan=4, padx=8)
        skin.create_text(
            75,
            110,
            text="Player skin\nunavailable",
            fill="#98a2b3",
            justify="center",
        )
        self.armor_slots = [
            ItemSlotWidget(
                profile,
                self.tooltip,
                on_right_click=self._open_item_actions,
            )
            for _ in range(4)
        ]
        for row, slot in enumerate(self.armor_slots):
            slot.grid(row=row, column=0, pady=2)
        self.offhand_slot = ItemSlotWidget(
            profile,
            self.tooltip,
            on_right_click=self._open_item_actions,
        )
        self.offhand_slot.grid(row=3, column=2, padx=(8, 0))

        stats = ttk.LabelFrame(
            player_content,
            text="Vitals",
            padding=10,
        )
        stats.columnconfigure(0, weight=1)
        ttk.Label(stats, textvariable=self.health_var).grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.health_bar = ttk.Progressbar(stats, maximum=100)
        self.health_bar.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        ttk.Label(stats, textvariable=self.hunger_var).grid(
            row=2,
            column=0,
            sticky="w",
        )
        self.hunger_bar = ttk.Progressbar(stats, maximum=100)
        self.hunger_bar.grid(row=3, column=0, sticky="ew", pady=(2, 6))
        ttk.Label(
            stats,
            textvariable=self.details_var,
            justify="left",
        ).grid(row=4, column=0, sticky="w")

        inventory = ttk.LabelFrame(
            player_content,
            text="Inventory",
            padding=8,
        )
        self.main_slots = [
            ItemSlotWidget(
                inventory,
                self.tooltip,
                on_right_click=self._open_item_actions,
            )
            for _ in range(27)
        ]
        for index, slot in enumerate(self.main_slots):
            slot.grid(row=index // 9, column=index % 9, padx=1, pady=1)
        self.hotbar_slots = [
            ItemSlotWidget(
                inventory,
                self.tooltip,
                on_right_click=self._open_item_actions,
            )
            for _ in range(9)
        ]
        for index, slot in enumerate(self.hotbar_slots):
            slot.grid(row=4, column=index, padx=1, pady=(8, 1))
        self.extra_frame = ttk.Frame(inventory)
        self.extra_frame.grid(
            row=5,
            column=0,
            columnspan=9,
            sticky="w",
            pady=(8, 0),
        )
        self.extra_label = ttk.Label(
            self.extra_frame,
            text="Extra",
            style="FieldLabel.TLabel",
        )
        self.extra_label.grid(row=0, column=0, sticky="w")
        self.extra_label.grid_remove()
        self.extra_slots: list[ItemSlotWidget] = []
        self._build_auto_heal_section(player_content)
        layout_player_sections(
            player_content,
            profile,
            stats,
            inventory,
            self.auto_heal_section,
        )

    def _build_auto_heal_section(self, content: ttk.Frame) -> None:
        section = ttk.LabelFrame(content, text="Auto Heal", padding=8)
        self.auto_heal_section = section
        section.columnconfigure(0, weight=1)
        ttk.Checkbutton(
            section,
            text="Enable Auto Heal",
            variable=self.auto_heal_enabled_var,
            command=self._on_auto_heal_toggle,
        ).grid(row=0, column=0, sticky="w")
        self.return_item_var = tk.StringVar()
        return_row = ttk.Frame(section)
        return_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        return_row.columnconfigure(0, weight=1)
        ttk.Label(return_row, textvariable=self.return_item_var).grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.return_item_clear_button = ttk.Button(
            return_row,
            text="Clear",
            command=self._clear_return_item,
        )
        self.return_item_clear_button.grid(
            row=0,
            column=1,
            padx=(8, 0),
        )
        self.auto_heal_empty_label = ttk.Label(
            section,
            text="Right-click an inventory item to add an Auto Heal rule.",
            style="Muted.TLabel",
        )
        self.auto_heal_empty_label.grid(
            row=2,
            column=0,
            sticky="w",
            pady=(6, 0),
        )
        self.auto_heal_rows_frame = ttk.Frame(section)
        self.auto_heal_rows_frame.grid(
            row=3,
            column=0,
            sticky="ew",
            pady=(6, 0),
        )
        self.auto_heal_rows_frame.columnconfigure(0, weight=1)
        self._refresh_return_item_state()
        self._refresh_auto_heal_rows()

    def _on_auto_heal_toggle(self) -> None:
        self.on_auto_heal_enabled_changed(
            self.auto_heal_enabled_var.get()
        )

    def _open_item_actions(
        self,
        slot: InventorySlot,
        event: tk.Event | None,
    ) -> None:
        menu = tk.Menu(self.parent, tearoff=False)
        labels = inventory_item_action_labels(slot, self.auto_heal_items)
        menu.add_command(
            label=labels[0],
            command=partial(self._show_auto_heal_dialog, slot.item.name),
        )
        if slot.section == "hotbar":
            menu.add_separator()
            menu.add_command(
                label="Set as Return Item",
                command=partial(self._set_return_item, slot.item.name),
            )
        if event is None:
            return
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _refresh_return_item_state(self) -> None:
        name = self.auto_heal_return_item_name
        self.return_item_var.set(f"Return Item: {name or 'None'}")
        self.return_item_clear_button.configure(
            state="normal" if name else "disabled"
        )

    def _set_return_item(self, name: str) -> None:
        self.auto_heal_return_item_name = name
        self._refresh_return_item_state()
        self._rerender_inventory()
        self.on_auto_heal_return_item_changed(name)

    def _clear_return_item(self) -> None:
        self.auto_heal_return_item_name = ""
        self._refresh_return_item_state()
        self._rerender_inventory()
        self.on_auto_heal_return_item_changed("")

    def _rerender_inventory(self) -> None:
        if self._snapshot is not None:
            self._render_inventory(self._snapshot)

    def _show_auto_heal_dialog(
        self,
        name: str,
        existing: AutoHealItemConfig | None = None,
    ) -> None:
        if existing is None:
            existing = next(
                (
                    item
                    for item in self.auto_heal_items
                    if item.name == name
                ),
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

    def _save_auto_heal_item(self, item: AutoHealItemConfig) -> None:
        updated = []
        replaced = False
        for existing in self.auto_heal_items:
            if existing.name == item.name:
                updated.append(item)
                replaced = True
            else:
                updated.append(existing)
        if not replaced:
            updated.append(item)
        self.auto_heal_items = tuple(updated)
        self._refresh_auto_heal_rows()
        self.on_auto_heal_items_changed(self.auto_heal_items)

    def _remove_auto_heal_item(self, name: str) -> None:
        self.auto_heal_items = tuple(
            item for item in self.auto_heal_items if item.name != name
        )
        self._refresh_auto_heal_rows()
        self.on_auto_heal_items_changed(self.auto_heal_items)

    def _refresh_auto_heal_rows(self) -> None:
        for child in self.auto_heal_rows_frame.winfo_children():
            child.destroy()
        if not self.auto_heal_items:
            self.auto_heal_empty_label.grid()
            return
        self.auto_heal_empty_label.grid_remove()
        for row_index, item in enumerate(self.auto_heal_items):
            row = ttk.Frame(self.auto_heal_rows_frame)
            row.grid(row=row_index, column=0, sticky="ew", pady=2)
            row.columnconfigure(0, weight=1)
            ttk.Label(row, text=item.name, wraplength=480).grid(
                row=0,
                column=0,
                sticky="w",
            )
            ttk.Label(
                row,
                text=format_auto_heal_rule(item),
                style="Muted.TLabel",
                wraplength=680,
            ).grid(row=1, column=0, sticky="w")
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

    def _load_icon(self, item_id: str) -> Image.Image:
        png = self.icon_client.get_icon(item_id)
        with Image.open(BytesIO(png)) as image:
            image.load()
            return image.convert("RGBA").resize(
                (40, 40),
                Image.Resampling.NEAREST,
            )

    def _photo(
        self,
        item_id: str,
        image: Image.Image,
    ) -> ImageTk.PhotoImage:
        photo = self.photos.get(item_id)
        if photo is None:
            photo = ImageTk.PhotoImage(image)
            self.photos[item_id] = photo
        return photo

    def _render_slot(
        self,
        widget: ItemSlotWidget,
        slot: InventorySlot,
    ) -> None:
        photo = None
        if not slot.item.empty and slot.item.item_id in self._prepared_icons:
            photo = self._photo(
                slot.item.item_id,
                self._prepared_icons[slot.item.item_id],
            )
        widget.render(
            slot,
            photo,
            is_return_item=(
                slot.section == "hotbar"
                and not slot.item.empty
                and slot.item.name == self.auto_heal_return_item_name
            ),
        )

    def _clear_extra_slots(self) -> None:
        if not self.extra_slots:
            return
        for widget in self.extra_slots:
            self.tooltip.hide(widget.canvas)
            widget.canvas.destroy()
        self.extra_slots.clear()

    def _render_inventory(self, snapshot: PlayerSnapshot) -> None:
        layout = build_inventory_layout(snapshot.inventory)
        missing_icons = {
            slot.item.item_id
            for slot in snapshot.inventory
            if (
                not slot.item.empty
                and slot.item.item_id
                and slot.item.item_id not in self._prepared_icons
            )
        }
        for widget, slot in zip(self.main_slots, layout.main):
            self._render_slot(widget, slot)
        for widget, slot in zip(self.hotbar_slots, layout.hotbar):
            self._render_slot(widget, slot)
        for widget, slot in zip(self.armor_slots, layout.armor):
            self._render_slot(widget, slot)
        self._render_slot(self.offhand_slot, layout.offhand)
        self._clear_extra_slots()
        if layout.extra:
            self.extra_label.grid()
        else:
            self.extra_label.grid_remove()
        for index, slot in enumerate(layout.extra):
            widget = ItemSlotWidget(
                self.extra_frame,
                self.tooltip,
                on_right_click=self._open_item_actions,
            )
            widget.grid(row=1, column=index, padx=1)
            self._render_slot(widget, slot)
            self.extra_slots.append(widget)
        self.icon_loader.queue(missing_icons)

    def _apply_icon(self, item_id: str, image: Image.Image) -> None:
        self._prepared_icons[item_id] = image
        self.photos.pop(item_id, None)
        if self._snapshot is not None and any(
            slot.item.item_id == item_id for slot in self._snapshot.inventory
        ):
            self._render_inventory(self._snapshot)

    def _render(self, snapshot: PlayerSnapshot) -> None:
        self._snapshot = snapshot
        self.status_var.set("Connected" if snapshot.connected else "Disconnected")
        self.updated_var.set(f"Updated {datetime.now().strftime('%H:%M:%S')}")
        self.error_var.set("")
        self.health_var.set(
            f"Health: {snapshot.health.current:g} / {snapshot.health.maximum:g}"
        )
        self.hunger_var.set(
            f"Hunger: {snapshot.hunger.food_level} / {HUNGER_MAXIMUM}  "
            f"Saturation: {snapshot.hunger.saturation:g}"
        )
        self.health_bar.configure(value=health_percent(snapshot))
        self.hunger_bar.configure(value=hunger_percent(snapshot))
        self.details_var.set(
            f"Armor: {snapshot.armor}\n"
            f"Level: {snapshot.level.experience_level} "
            f"({snapshot.level.experience_progress * 100:.0f}%)\n"
            f"Position: {snapshot.location.x:.1f}, "
            f"{snapshot.location.y:.1f}, {snapshot.location.z:.1f}\n"
            f"Facing: {snapshot.facing_direction.title()}"
        )
        self._render_inventory(snapshot)

    def _show_error(self, error: Exception) -> None:
        self.status_var.set("Disconnected")
        self.error_var.set(f"Refresh failed: {error}")

    def activate(self) -> None:
        self._bind_player_mousewheel()
        self.icon_loader.activate()
        self.poller.activate()

    def deactivate(self) -> None:
        self._unbind_player_mousewheel()
        self.tooltip.hide()
        self.poller.deactivate()
        self.icon_loader.deactivate()

    def _bind_player_mousewheel(self) -> None:
        if self._mousewheel_binding_id is not None:
            return
        root = self.parent.winfo_toplevel()
        self._mousewheel_binding_id = root.bind(
            "<MouseWheel>",
            lambda event: scroll_player_body(self.player_canvas, event),
            add="+",
        )

    def _unbind_player_mousewheel(self) -> None:
        binding_id = getattr(self, "_mousewheel_binding_id", None)
        if binding_id is None:
            return
        self.parent.winfo_toplevel().unbind("<MouseWheel>", binding_id)
        self._mousewheel_binding_id = None

    def refresh(self) -> None:
        self.poller.refresh()

    def close(self) -> None:
        self._unbind_player_mousewheel()
        self.tooltip.hide()
        self.poller.close()
        self.icon_loader.close()
