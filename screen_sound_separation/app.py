"""Desktop interface for Screen Sound Separation."""

from __future__ import annotations

import atexit
import ctypes
import os
import tkinter as tk
import webbrowser
from ctypes import wintypes
from dataclasses import dataclass
from importlib.resources import files
from tkinter import messagebox, ttk

from .audio import AudioRouter, RoutedApp
from .browser import (
    BROWSER_PROCESSES,
    CHROME_WEB_STORE_URL,
    BrowserBridge,
    BrowserTab,
    install_native_host,
    prepare_extension_files,
)
from .presentation import (
    SOURCE_FILTERS,
    mix_label,
    pan_gains,
    position_label,
    source_is_visible,
)


BG = "#0A0C0F"
PANEL = "#11151A"
PANEL_ALT = "#151A20"
PANEL_HOVER = "#1B222A"
BORDER = "#252C35"
TEXT = "#F5F1E8"
TEXT_SOFT = "#C4C8C4"
MUTED = "#808891"
ORANGE = "#FF6846"
ORANGE_HOVER = "#FF7B5D"
SIGNAL = "#C7F464"
BLUE = "#7DA7FF"
RED = "#FF6B6B"

APP_ID = "ThatOneGuyBanks.ScreenSoundSeparation"
ERROR_ALREADY_EXISTS = 183


@dataclass(frozen=True)
class SourceView:
    """One desktop or browser source ready to display in the workspace."""

    target: tuple[str, str | int]
    source: str
    detail: str
    kind: str
    position: str
    mix: str


def _asset_path(name: str) -> str:
    return str(files("screen_sound_separation").joinpath("assets", name))


def _set_windows_identity() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass


def _acquire_instance_mutex() -> int | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.CreateMutexW(None, False, f"Local\\{APP_ID}")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


def _release_instance_mutex(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle(handle)


class SeparationApp(tk.Tk):
    """Modern control surface for the screen-aware audio router."""

    def __init__(self) -> None:
        _set_windows_identity()
        super().__init__()
        self.title("Screen Sound Separation")
        self.geometry("1120x800")
        self.minsize(920, 760)
        self.configure(bg=BG)

        self.router = AudioRouter()
        self.browser_bridge = BrowserBridge()
        self.browser_host_error: str | None = None
        self.extension_path = None
        try:
            install_native_host()
            self.extension_path = prepare_extension_files()
            self.browser_bridge.start()
        except (OSError, ValueError) as exc:
            self.browser_host_error = str(exc)

        self.router.repair_stale_balances()
        atexit.register(self.router.restore)
        atexit.register(self.browser_bridge.close)
        self.running = False
        self._after_id: str | None = None
        self._browser_after_id: str | None = None
        self._last_apps: list[RoutedApp] = []
        self.browser_tabs: dict[int, BrowserTab] = {}
        self.browser_connected = False
        self.app_position_overrides: dict[str, float] = {}
        self.tab_position_overrides: dict[int, float] = {}
        self._tree_targets: dict[str, tuple[str, str | int]] = {}
        self._view_by_target: dict[tuple[str, str | int], SourceView] = {}

        self.separation = tk.DoubleVar(value=75)
        self.strength_text = tk.StringVar(value="75%")
        self.left_mix_text = tk.StringVar()
        self.right_mix_text = tk.StringVar()
        self.source_query = tk.StringVar()
        self.source_filter = tk.StringVar(value=SOURCE_FILTERS[0])
        self.activity_text = tk.StringVar(value="Routing is off")
        self.selection_text = tk.StringVar(value="Select a source to change its position")
        self.last_update_text = tk.StringVar(value="Waiting to start")

        self._load_icon()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build_style()
        self._build_ui()
        self._bind_shortcuts()
        self._update_mix_preview(75)
        self._render([])
        self._poll_browser()

    def _load_icon(self) -> None:
        try:
            self._icon_image = tk.PhotoImage(file=_asset_path("app-icon.png"))
            self.iconphoto(True, self._icon_image)
            self.iconbitmap(_asset_path("app-icon.ico"))
        except tk.TclError:
            self._icon_image = None

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("PanelAlt.TFrame", background=PANEL_ALT)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 20))
        style.configure("Section.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 11))
        style.configure("WorkspaceTitle.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 16))
        style.configure("Eyebrow.TLabel", background=BG, foreground=ORANGE, font=("Segoe UI Semibold", 8))
        style.configure("Strength.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI Semibold", 32))
        style.configure("Mix.TLabel", background=PANEL_ALT, foreground=TEXT_SOFT, font=("Cascadia Mono", 9))
        style.configure("Separator.Horizontal.TScale", background=PANEL, troughcolor=BORDER, lightcolor=ORANGE, darkcolor=ORANGE, bordercolor=PANEL)
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, borderwidth=0, relief="flat", bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL, rowheight=42, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=PANEL_ALT, foreground=MUTED, relief="flat", borderwidth=0, font=("Segoe UI Semibold", 9), padding=(8, 10))
        style.map("Treeview", background=[("selected", "#27313B")], foreground=[("selected", TEXT)])
        style.map("Treeview.Heading", background=[("active", PANEL_HOVER)])
        style.configure("App.Vertical.TScrollbar", background=PANEL_ALT, troughcolor=PANEL, bordercolor=PANEL, arrowcolor=MUTED, lightcolor=PANEL_ALT, darkcolor=PANEL_ALT)
        style.configure("Filter.TCombobox", fieldbackground=PANEL_ALT, background=PANEL_ALT, foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(8, 7))
        style.map("Filter.TCombobox", fieldbackground=[("readonly", PANEL_ALT)], foreground=[("readonly", TEXT)], selectbackground=[("readonly", PANEL_ALT)], selectforeground=[("readonly", TEXT)])

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=(24, 20, 24, 16))
        root.pack(fill="both", expand=True)
        self._build_header(root)

        body = ttk.Frame(root)
        body.pack(fill="both", expand=True, pady=(20, 0))
        body.columnconfigure(0, weight=0, minsize=306)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        controls = ttk.Frame(body, width=306)
        controls.grid(row=0, column=0, sticky="nsw", padx=(0, 18))
        controls.grid_propagate(False)
        workspace = ttk.Frame(body)
        workspace.grid(row=0, column=1, sticky="nsew")
        self._build_routing_card(controls)
        self._build_browser_card(controls)
        self._build_workspace(workspace)

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent)
        header.pack(fill="x")
        if self._icon_image is not None:
            self._header_icon = self._icon_image.subsample(11, 11)
            ttk.Label(header, image=self._header_icon, background=BG).pack(side="left", padx=(0, 12))
        titles = ttk.Frame(header)
        titles.pack(side="left", fill="x", expand=True)
        ttk.Label(titles, text="DISCONNETIC  /  FIELD TOOL 001", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(titles, text="Screen Sound Separation", style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text="Your workspace sounds like it looks. Audio stays on this device.", style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
        self.status_badge = tk.Label(header, text="●  ROUTING OFF", bg=PANEL_ALT, fg=MUTED, font=("Segoe UI Semibold", 9), padx=13, pady=9)
        self.status_badge.pack(side="right", padx=(12, 0))
        self.toggle = self._button(header, "Start routing", self._toggle, primary=True, padx=18, pady=9)
        self.toggle.pack(side="right")

    def _build_routing_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=18)
        card.pack(fill="x")
        heading = ttk.Frame(card, style="Panel.TFrame")
        heading.pack(fill="x")
        labels = ttk.Frame(heading, style="Panel.TFrame")
        labels.pack(side="left", fill="x", expand=True)
        ttk.Label(labels, text="Spatial intensity", style="Section.TLabel").pack(anchor="w")
        ttk.Label(labels, text="How strongly audio follows each screen.", style="PanelMuted.TLabel", wraplength=190).pack(anchor="w", pady=(3, 0))
        ttk.Label(heading, textvariable=self.strength_text, style="Strength.TLabel").pack(side="right")
        scale = ttk.Scale(card, from_=0, to=100, orient="horizontal", variable=self.separation, command=self._slider_changed, style="Separator.Horizontal.TScale")
        scale.pack(fill="x", pady=(18, 6))
        endpoints = ttk.Frame(card, style="Panel.TFrame")
        endpoints.pack(fill="x")
        ttk.Label(endpoints, text="Balanced", style="PanelMuted.TLabel").pack(side="left")
        ttk.Label(endpoints, text="Fully separated", style="PanelMuted.TLabel").pack(side="right")

        presets = ttk.Frame(card, style="Panel.TFrame")
        presets.pack(fill="x", pady=(14, 0))
        for index, (label, value) in enumerate((("Off", 0), ("Soft", 35), ("Focus", 75), ("Hard", 100))):
            presets.columnconfigure(index, weight=1, uniform="preset")
            button = self._button(presets, label, lambda selected=value: self._set_strength(selected), compact=True)
            button.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 4, 0))

        mixes = ttk.Frame(card, style="Panel.TFrame")
        mixes.pack(fill="x", pady=(14, 0))
        mixes.columnconfigure((0, 1), weight=1, uniform="mix")
        self._build_mix_tile(mixes, 0, "LEFT SCREEN", self.left_mix_text, ORANGE)
        self._build_mix_tile(mixes, 1, "RIGHT SCREEN", self.right_mix_text, BLUE)
        self.restore_button = self._button(card, "Restore audio now", self._restore_now, compact=True)
        self.restore_button.pack(fill="x", pady=(16, 0))

    def _build_mix_tile(self, parent: ttk.Frame, column: int, title: str, value: tk.StringVar, accent: str) -> None:
        tile = ttk.Frame(parent, style="PanelAlt.TFrame", padding=(11, 9))
        tile.grid(row=0, column=column, sticky="ew", padx=(0, 4) if column == 0 else (4, 0))
        tk.Frame(tile, bg=accent, width=3, height=31).pack(side="left", padx=(0, 8))
        content = ttk.Frame(tile, style="PanelAlt.TFrame")
        content.pack(side="left")
        tk.Label(content, text=title, bg=PANEL_ALT, fg=MUTED, font=("Segoe UI Semibold", 7)).pack(anchor="w")
        ttk.Label(content, textvariable=value, style="Mix.TLabel").pack(anchor="w", pady=(2, 0))

    def _build_browser_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Panel.TFrame", padding=18)
        card.pack(fill="x", pady=(12, 0))
        heading = ttk.Frame(card, style="Panel.TFrame")
        heading.pack(fill="x")
        ttk.Label(heading, text="Chrome tabs", style="Section.TLabel").pack(side="left")
        self.browser_badge = tk.Label(heading, text="●  WAITING", bg=PANEL_ALT, fg=MUTED, font=("Segoe UI Semibold", 8), padx=9, pady=5)
        self.browser_badge.pack(side="right")
        self.browser_detail = ttk.Label(card, text="Waiting for the browser extension.", style="PanelMuted.TLabel", wraplength=250)
        self.browser_detail.pack(anchor="w", fill="x", pady=(8, 12))
        self.browser_setup = self._button(card, "Set up browser support", self._open_browser_setup, compact=True)
        self.browser_setup.pack(fill="x")

    def _build_workspace(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew")
        titles = ttk.Frame(header)
        titles.pack(side="left", fill="x", expand=True)
        ttk.Label(titles, text="Live sources", style="WorkspaceTitle.TLabel").pack(anchor="w")
        ttk.Label(titles, textvariable=self.activity_text, style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
        self.source_count = tk.Label(header, text="0 SOURCES", bg=PANEL_ALT, fg=MUTED, font=("Segoe UI Semibold", 8), padx=10, pady=6)
        self.source_count.pack(side="right")

        toolbar = ttk.Frame(parent)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(16, 10))
        search_shell = tk.Frame(toolbar, bg=PANEL_ALT, highlightthickness=1, highlightbackground=BORDER)
        search_shell.pack(side="left", fill="x", expand=True)
        tk.Label(search_shell, text="⌕", bg=PANEL_ALT, fg=MUTED, font=("Segoe UI", 13), padx=10).pack(side="left")
        self.search_entry = tk.Entry(search_shell, textvariable=self.source_query, bg=PANEL_ALT, fg=TEXT, insertbackground=TEXT, selectbackground="#334151", selectforeground=TEXT, relief="flat", borderwidth=0, font=("Segoe UI", 10))
        self.search_entry.pack(side="left", fill="both", expand=True, ipady=9, padx=(0, 8))
        self.source_query.trace_add("write", lambda *_args: self._render(self._last_apps))
        filter_box = ttk.Combobox(toolbar, textvariable=self.source_filter, values=SOURCE_FILTERS, state="readonly", width=15, style="Filter.TCombobox")
        filter_box.pack(side="left", padx=(8, 0))
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self._render(self._last_apps))
        self._button(toolbar, "Refresh", self._manual_refresh, compact=True).pack(side="left", padx=(8, 0))

        table_card = ttk.Frame(parent, style="Panel.TFrame")
        table_card.grid(row=2, column=0, sticky="nsew")
        columns = ("kind", "position", "mix")
        self.tree = ttk.Treeview(table_card, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="SOURCE")
        for column, heading_text in zip(columns, ("TYPE", "POSITION", "OUTPUT"), strict=True):
            self.tree.heading(column, text=heading_text)
        self.tree.column("#0", width=235, minwidth=170, anchor="w")
        self.tree.column("kind", width=105, minwidth=90)
        self.tree.column("position", width=130, minwidth=110)
        self.tree.column("mix", width=165, minwidth=150, anchor="center")
        self.tree.tag_configure("even", background=PANEL)
        self.tree.tag_configure("odd", background="#0F1317")
        self.tree.bind("<<TreeviewSelect>>", self._source_selected)
        self.tree.bind("<Double-1>", self._show_position_menu, add="+")
        self.tree.bind("<Button-3>", self._show_position_menu, add="+")
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview, style="App.Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.empty_state = tk.Label(table_card, text="No live sources yet\n\nStart routing, then play audio in an app.", bg=PANEL, fg=MUTED, font=("Segoe UI", 11), justify="center")

        action_bar = ttk.Frame(parent, style="Panel.TFrame", padding=(14, 11))
        action_bar.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(action_bar, textvariable=self.selection_text, style="PanelMuted.TLabel").pack(side="left", fill="x", expand=True)
        self.position_buttons: list[tk.Button] = []
        positions = (("Auto", None), ("Left", -1.0), ("Centre", 0.0), ("Right", 1.0))
        for label, value in reversed(positions):
            button = self._button(action_bar, label, lambda selected=value: self._set_selected_position(selected), compact=True)
            button.configure(state="disabled")
            button.pack(side="right", padx=(6, 0))
            self.position_buttons.append(button)

        status_line = ttk.Frame(parent)
        status_line.grid(row=4, column=0, sticky="ew", pady=(9, 0))
        ttk.Label(status_line, textvariable=self.last_update_text, style="Muted.TLabel").pack(side="left")
        ttk.Label(status_line, text="Double-click for options  ·  Ctrl+F search  ·  Ctrl+R refresh", style="Muted.TLabel").pack(side="right")

    def _button(self, parent: tk.Misc, text: str, command: object, *, primary: bool = False, compact: bool = False, padx: int | None = None, pady: int | None = None) -> tk.Button:
        background = ORANGE if primary else PANEL_ALT
        active = ORANGE_HOVER if primary else PANEL_HOVER
        foreground = BG if primary else TEXT_SOFT
        return tk.Button(parent, text=text, command=command, bg=background, activebackground=active, fg=foreground, activeforeground=BG if primary else TEXT, disabledforeground="#555E67", relief="flat", borderwidth=0, cursor="hand2", font=("Segoe UI Semibold", 9 if compact else 10), padx=padx if padx is not None else (12 if compact else 16), pady=pady if pady is not None else (7 if compact else 10))

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-f>", self._focus_search)
        self.bind("<Control-r>", lambda _event: self._manual_refresh())
        self.bind("<Escape>", self._clear_search)

    def _focus_search(self, _event: tk.Event) -> str:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")
        return "break"

    def _clear_search(self, _event: tk.Event) -> str:
        self.source_query.set("")
        self.source_filter.set(SOURCE_FILTERS[0])
        return "break"

    def _set_strength(self, value: int) -> None:
        self.separation.set(value)
        self._slider_changed(str(value))

    def _slider_changed(self, value: str) -> None:
        strength = round(float(value))
        self.strength_text.set(f"{strength}%")
        self._update_mix_preview(strength)
        self.browser_bridge.update(self.running, strength / 100.0)
        if self.running:
            self._apply_once()

    def _update_mix_preview(self, strength: int) -> None:
        crossover = 100 - strength
        self.left_mix_text.set(f"100 / {crossover}")
        self.right_mix_text.set(f"{crossover} / 100")

    def _toggle(self) -> None:
        if self.running:
            self._stop_routing("Routing stopped. Audio restored to centre.")
        else:
            self.running = True
            self.browser_bridge.update(True, self.separation.get() / 100.0)
            self.toggle.configure(text="Stop routing", bg=PANEL_ALT, activebackground=PANEL_HOVER, fg=SIGNAL, activeforeground=SIGNAL)
            self.status_badge.configure(text="●  ROUTING LIVE", fg=SIGNAL)
            self.activity_text.set("Following active windows across your displays")
            self._refresh()

    def _stop_routing(self, message: str) -> None:
        self.running = False
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        self.browser_bridge.update(False, self.separation.get() / 100.0)
        self.browser_bridge.release_all()
        self.router.restore()
        self.toggle.configure(text="Start routing", bg=ORANGE, activebackground=ORANGE_HOVER, fg=BG, activeforeground=BG)
        self.status_badge.configure(text="●  ROUTING OFF", fg=MUTED)
        self.activity_text.set("Routing is off")
        self.last_update_text.set(message)
        self._last_apps = []
        self.browser_tabs.clear()
        self._render([])

    def _restore_now(self) -> None:
        if self.running:
            self._stop_routing("Audio restored. Routing is off.")
            return
        self.browser_bridge.release_all()
        self.router.restore()
        self.last_update_text.set("Audio restored to neutral stereo.")

    def _refresh(self) -> None:
        if not self.running:
            return
        self._apply_once()
        self._after_id = self.after(1000, self._refresh)

    def _manual_refresh(self) -> None:
        if self.running:
            self._apply_once()
        else:
            self.last_update_text.set("Start routing to discover active audio sources.")

    def _apply_once(self) -> None:
        try:
            apps = self.router.apply(self.separation.get() / 100.0)
            if self.browser_connected:
                apps = [app for app in apps if app.name.casefold() not in BROWSER_PROCESSES]
            self._last_apps = apps
            self._render(apps)
            count = len(apps) + len(self.browser_tabs)
            noun = "source" if count == 1 else "sources"
            self.status_badge.configure(text="●  ROUTING LIVE", fg=SIGNAL)
            self.activity_text.set(f"Routing {count} active {noun}")
            self.last_update_text.set("Live · positions refresh automatically")
        except Exception as exc:
            self.status_badge.configure(text="●  AUDIO ERROR", fg=RED)
            self.activity_text.set("Windows audio is temporarily unavailable")
            self.last_update_text.set(str(exc))

    def _source_views(self, apps: list[RoutedApp]) -> list[SourceView]:
        views: list[SourceView] = []
        for app in apps:
            manual = app.name.casefold() in self.app_position_overrides
            views.append(SourceView(("app", app.name), app.name, app.title, "Desktop app", position_label(app.position, no_window=app.title == "No visible window", manual=manual), mix_label(app.left_gain, app.right_gain)))
        for tab in sorted(self.browser_tabs.values(), key=lambda item: item.title.casefold()):
            manual = tab.tab_id in self.tab_position_overrides
            left_gain, right_gain = pan_gains(tab.pan)
            views.append(SourceView(("tab", tab.tab_id), tab.title, "Captured Chrome tab", "Browser tab", f"{tab.side} · Manual" if manual else tab.side, mix_label(left_gain, right_gain)))
        return views

    def _render(self, apps: list[RoutedApp]) -> None:
        selected_target = self._selected_target()
        self.tree.delete(*self.tree.get_children())
        self._tree_targets.clear()
        all_views = self._source_views(apps)
        self._view_by_target = {view.target: view for view in all_views}
        visible = [view for view in all_views if source_is_visible(view.source, view.detail, view.position, view.kind, self.source_query.get(), self.source_filter.get())]
        selected_item: str | None = None
        for index, view in enumerate(visible):
            item_id = self.tree.insert("", "end", text=view.source, values=(view.kind, view.position, view.mix), tags=("even" if index % 2 == 0 else "odd",))
            self._tree_targets[item_id] = view.target
            if view.target == selected_target:
                selected_item = item_id
        total = len(all_views)
        self.source_count.configure(text=f"{total} {'SOURCE' if total == 1 else 'SOURCES'}")
        if selected_item is not None:
            self.tree.selection_set(selected_item)
            self.tree.focus(selected_item)
        else:
            self._update_selection_actions(None)
        if visible:
            self.empty_state.place_forget()
        else:
            if total:
                empty_text = "No sources match your search or filter."
            elif self.running:
                empty_text = "No audio detected yet\n\nPlay audio in an app to see it here."
            else:
                empty_text = "No live sources yet\n\nStart routing, then play audio in an app."
            self.empty_state.configure(text=empty_text)
            self.empty_state.place(relx=0.5, rely=0.5, anchor="center")

    def _selected_target(self) -> tuple[str, str | int] | None:
        selected = self.tree.selection() if hasattr(self, "tree") else ()
        return self._tree_targets.get(selected[0]) if selected else None

    def _source_selected(self, _event: tk.Event | None = None) -> None:
        self._update_selection_actions(self._selected_target())

    def _update_selection_actions(self, target: tuple[str, str | int] | None) -> None:
        for button in getattr(self, "position_buttons", []):
            button.configure(state="normal" if target is not None else "disabled")
        if target is None:
            self.selection_text.set("Select a source to change its position")
            return
        view = self._view_by_target.get(target)
        self.selection_text.set(f"{view.source}  ·  {view.position}" if view else "Selected source")

    def _set_selected_position(self, position: float | None) -> None:
        target = self._selected_target()
        if target is not None:
            self._set_position_override(target, position)

    def _show_position_menu(self, event: tk.Event) -> None:
        item_id = self.tree.identify_row(event.y)
        target = self._tree_targets.get(item_id)
        if target is None:
            return
        self.tree.selection_set(item_id)
        self.tree.focus(item_id)
        self._update_selection_actions(target)
        menu = tk.Menu(self, tearoff=False, bg=PANEL_ALT, fg=TEXT, activebackground=ORANGE, activeforeground=BG, borderwidth=0, font=("Segoe UI", 9))
        for label, position in (("Auto", None), ("Left", -1.0), ("Centre", 0.0), ("Right", 1.0)):
            menu.add_command(label=label, command=lambda selected=position: self._set_position_override(target, selected))
        self._position_menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _set_position_override(self, target: tuple[str, str | int], position: float | None) -> None:
        kind, key = target
        if kind == "app":
            name = str(key)
            self.router.set_position_override(name, position)
            if position is None:
                self.app_position_overrides.pop(name.casefold(), None)
            else:
                self.app_position_overrides[name.casefold()] = position
            self._apply_once() if self.running else self._render(self._last_apps)
            return
        tab_id = int(key)
        self.browser_bridge.set_tab_position(tab_id, position)
        if position is None:
            self.tab_position_overrides.pop(tab_id, None)
        else:
            self.tab_position_overrides[tab_id] = position
            tab = self.browser_tabs.get(tab_id)
            if tab is not None:
                side = "Left" if position < 0 else "Right" if position > 0 else "Centre"
                self.browser_tabs[tab_id] = BrowserTab(tab.tab_id, tab.title, side, position * (self.separation.get() / 100.0))
        self._render(self._last_apps)

    def _open_browser_setup(self) -> None:
        if CHROME_WEB_STORE_URL:
            webbrowser.open(CHROME_WEB_STORE_URL)
            return
        if self.extension_path is None:
            messagebox.showerror("Browser support", "The extension files are unavailable.")
            return
        path = str(self.extension_path)
        self.clipboard_clear()
        self.clipboard_append(path)
        os.startfile(path)
        messagebox.showinfo("Set up Chrome browser support", "The extension folder is open and its path is copied.\n\nUntil the Web Store listing is published:\n1. Remove an older Screen Sound Separation test extension, if shown.\n2. Open chrome://extensions in Chrome.\n3. Turn on Developer mode.\n4. Choose Load unpacked and select the open folder.\n\nThe public release will replace this with Add to Chrome.")

    def _poll_browser(self) -> None:
        changed = False
        for event in self.browser_bridge.poll_events():
            event_type = event.get("type")
            if event_type == "connected":
                self.browser_connected = True
                for tab_id, position in self.tab_position_overrides.items():
                    self.browser_bridge.set_tab_position(tab_id, position)
                changed = True
            elif event_type == "disconnected":
                self.browser_connected = False
                self.browser_tabs.clear()
                changed = True
            elif event_type == "request_start":
                if not self.running:
                    self._toggle()
                changed = True
            elif event_type == "tab_status":
                try:
                    tab_id = int(event["tabId"])
                    if event.get("captured"):
                        self.browser_tabs[tab_id] = BrowserTab(tab_id, str(event.get("title") or "Browser tab"), str(event.get("side") or "Centre"), max(-1.0, min(1.0, float(event.get("pan", 0.0)))))
                    else:
                        self.browser_tabs.pop(tab_id, None)
                    changed = True
                except (KeyError, TypeError, ValueError):
                    continue

        self.router.set_excluded(BROWSER_PROCESSES if self.browser_connected else set())
        if self.browser_host_error:
            self.browser_badge.configure(text="●  UNAVAILABLE", fg=RED)
            self.browser_detail.configure(text=self.browser_host_error)
        elif self.browser_connected:
            count = len(self.browser_tabs)
            noun = "tab" if count == 1 else "tabs"
            self.browser_badge.configure(text="●  CONNECTED", fg=SIGNAL)
            detail = f"{count} captured {noun}. Use the toolbar icon to add or release a tab." if self.running else "Ready. Capturing a tab can start routing automatically."
            self.browser_detail.configure(text=detail)
            self.browser_setup.configure(text="Browser support connected", state="disabled")
        else:
            self.browser_badge.configure(text="●  WAITING", fg=MUTED)
            self.browser_detail.configure(text="Waiting for the browser extension.")
            self.browser_setup.configure(text="Set up browser support", state="normal")
        if changed:
            self._render(self._last_apps)
            if self.running:
                count = len(self._last_apps) + len(self.browser_tabs)
                self.activity_text.set(f"Routing {count} active {'source' if count == 1 else 'sources'}")
        self._browser_after_id = self.after(250, self._poll_browser)

    def _close(self) -> None:
        self.running = False
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        if self._browser_after_id is not None:
            self.after_cancel(self._browser_after_id)
            self._browser_after_id = None
        try:
            self.browser_bridge.update(False, self.separation.get() / 100.0)
            self.browser_bridge.release_all()
            self.router.restore()
        finally:
            atexit.unregister(self.router.restore)
            self.browser_bridge.close()
            atexit.unregister(self.browser_bridge.close)
            self.destroy()


def main() -> None:
    mutex = _acquire_instance_mutex()
    if mutex is None:
        ctypes.windll.user32.MessageBoxW(None, "Screen Sound Separation is already running.", "Screen Sound Separation", 0x40)
        return
    app: SeparationApp | None = None
    try:
        app = SeparationApp()
        app.mainloop()
    finally:
        if app is not None:
            app.browser_bridge.close()
            app.router.restore()
        _release_instance_mutex(mutex)


if __name__ == "__main__":
    main()
