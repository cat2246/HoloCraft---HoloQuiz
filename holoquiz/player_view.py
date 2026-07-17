from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from io import BytesIO
import queue
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from PIL import Image, ImageTk

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


def health_percent(snapshot: PlayerSnapshot) -> float:
    maximum = snapshot.health.maximum or HEALTH_MAX_FALLBACK
    return min(max(snapshot.health.current / maximum * 100.0, 0.0), 100.0)


def hunger_percent(snapshot: PlayerSnapshot) -> float:
    return min(
        max(snapshot.hunger.food_level / HUNGER_MAXIMUM * 100.0, 0.0),
        100.0,
    )


@dataclass(frozen=True)
class PlayerViewData:
    snapshot: PlayerSnapshot
    icon_png_by_item_id: dict[str, bytes]


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


class ItemTooltip:
    def __init__(self, parent: tk.Misc) -> None:
        self.parent = parent
        self.window: tk.Toplevel | None = None

    def show(self, widget: tk.Widget, text: str) -> None:
        self.hide()
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

    def hide(self) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


class ItemSlotWidget:
    def __init__(self, parent: tk.Misc, tooltip: ItemTooltip) -> None:
        self.tooltip = tooltip
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
        self.canvas.bind("<Leave>", lambda _event: self.tooltip.hide())

    def grid(self, **kwargs: Any) -> None:
        self.canvas.grid(**kwargs)

    def render(
        self,
        slot: InventorySlot,
        photo: ImageTk.PhotoImage | None,
    ) -> None:
        self.slot = slot
        self.photo = photo
        self.canvas.delete("all")
        border = "#9b5de5" if slot.item.is_enchanted else "#555b64"
        self.canvas.configure(highlightbackground=border)
        if slot.item.empty or photo is None:
            return
        self.canvas.create_image(SLOT_SIZE // 2, SLOT_SIZE // 2, image=photo)
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


class PlayerTab:
    def __init__(self, parent: ttk.Frame, *, player_url: str) -> None:
        self.parent = parent
        self.player_client = PlayerOverviewClient(player_url)
        self.icon_client = ItemIconClient()
        self.status_var = tk.StringVar(value="Not connected")
        self.updated_var = tk.StringVar(value="No player data yet")
        self.health_var = tk.StringVar(value="Health: --")
        self.hunger_var = tk.StringVar(value="Hunger: --")
        self.details_var = tk.StringVar(value="")
        self.error_var = tk.StringVar(value="")
        self.tooltip = ItemTooltip(parent)
        self.photos: dict[str, ImageTk.PhotoImage] = {}
        self._build()
        self.poller = PlayerPoller(
            parent,
            self._fetch_view_data,
            self._render,
            self._show_error,
        )

    def _build(self) -> None:
        self.parent.columnconfigure(0, weight=1)
        self.parent.rowconfigure(1, weight=1)
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
        body.columnconfigure(1, weight=1)

        profile = ttk.LabelFrame(body, text="Player overview", padding=10)
        profile.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
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
            ItemSlotWidget(profile, self.tooltip) for _ in range(4)
        ]
        for row, slot in enumerate(self.armor_slots):
            slot.grid(row=row, column=0, pady=2)
        self.offhand_slot = ItemSlotWidget(profile, self.tooltip)
        self.offhand_slot.grid(row=3, column=2, padx=(8, 0))

        content = ttk.Frame(body)
        content.grid(row=0, column=1, sticky="nsew")
        stats = ttk.LabelFrame(content, text="Vitals", padding=10)
        stats.grid(row=0, column=0, sticky="ew", pady=(0, 10))
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

        inventory = ttk.LabelFrame(content, text="Inventory", padding=8)
        inventory.grid(row=1, column=0, sticky="nw")
        self.main_slots = [
            ItemSlotWidget(inventory, self.tooltip) for _ in range(27)
        ]
        for index, slot in enumerate(self.main_slots):
            slot.grid(row=index // 9, column=index % 9, padx=1, pady=1)
        self.hotbar_slots = [
            ItemSlotWidget(inventory, self.tooltip) for _ in range(9)
        ]
        for index, slot in enumerate(self.hotbar_slots):
            slot.grid(row=4, column=index, padx=1, pady=(8, 1))
        self.extra_frame = ttk.Frame(content)
        self.extra_frame.grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.extra_label = ttk.Label(
            self.extra_frame,
            text="Extra",
            style="FieldLabel.TLabel",
        )
        self.extra_label.grid(row=0, column=0, sticky="w")
        self.extra_label.grid_remove()
        self.extra_slots: list[ItemSlotWidget] = []

    def _fetch_view_data(self) -> PlayerViewData:
        snapshot = self.player_client.fetch()
        item_ids = {
            slot.item.item_id
            for slot in snapshot.inventory
            if not slot.item.empty and slot.item.item_id
        }
        icons = {
            item_id: self.icon_client.get_icon(item_id) for item_id in item_ids
        }
        return PlayerViewData(snapshot, icons)

    def _photo(self, item_id: str, png: bytes) -> ImageTk.PhotoImage:
        photo = self.photos.get(item_id)
        if photo is None:
            with Image.open(BytesIO(png)) as image:
                resized = image.convert("RGBA").resize(
                    (40, 40),
                    Image.Resampling.NEAREST,
                )
                photo = ImageTk.PhotoImage(resized)
            self.photos[item_id] = photo
        return photo

    def _render_slot(
        self,
        widget: ItemSlotWidget,
        slot: InventorySlot,
        icons: dict[str, bytes],
    ) -> None:
        photo = None
        if not slot.item.empty:
            cache_key = slot.item.item_id or f"unknown:{slot.inventory_slot}"
            png = icons.get(slot.item.item_id, self.icon_client.fallback_icon)
            photo = self._photo(cache_key, png)
        widget.render(slot, photo)

    def _clear_extra_slots(self) -> None:
        if not self.extra_slots:
            return
        self.tooltip.hide()
        for widget in self.extra_slots:
            widget.canvas.destroy()
        self.extra_slots.clear()

    def _render(self, data: PlayerViewData) -> None:
        snapshot = data.snapshot
        layout = build_inventory_layout(snapshot.inventory)
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
        for widget, slot in zip(self.main_slots, layout.main):
            self._render_slot(widget, slot, data.icon_png_by_item_id)
        for widget, slot in zip(self.hotbar_slots, layout.hotbar):
            self._render_slot(widget, slot, data.icon_png_by_item_id)
        for widget, slot in zip(self.armor_slots, layout.armor):
            self._render_slot(widget, slot, data.icon_png_by_item_id)
        self._render_slot(
            self.offhand_slot,
            layout.offhand,
            data.icon_png_by_item_id,
        )
        self._clear_extra_slots()
        if layout.extra:
            self.extra_label.grid()
        else:
            self.extra_label.grid_remove()
        for index, slot in enumerate(layout.extra):
            widget = ItemSlotWidget(self.extra_frame, self.tooltip)
            widget.grid(row=1, column=index, padx=1)
            self._render_slot(widget, slot, data.icon_png_by_item_id)
            self.extra_slots.append(widget)

    def _show_error(self, error: Exception) -> None:
        self.status_var.set("Disconnected")
        self.error_var.set(f"Refresh failed: {error}")

    def activate(self) -> None:
        self.poller.activate()

    def deactivate(self) -> None:
        self.tooltip.hide()
        self.poller.deactivate()

    def refresh(self) -> None:
        self.poller.refresh()

    def close(self) -> None:
        self.tooltip.hide()
        self.poller.close()
