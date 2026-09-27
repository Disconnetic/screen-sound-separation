"""Desktop interface for Screen Sound Separation."""

from __future__ import annotations

import atexit
import ctypes
import os
import tkinter as tk
import webbrowser
from ctypes import wintypes
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


# Disconnetic's site palette: night, chalk, flare, and signal. Slightly raised
# near-black surfaces retain the brand contrast without flattening the UI.
BG = "#090A0A"
SURFACE = "#101211"
SURFACE_RAISED = "#181B19"
BORDER = "#343936"
TEXT = "#F1EEE5"
MUTED = "#96978F"
ORANGE = "#FD5F39"
SIGNAL = "#C9FF35"
RED = ORANGE

APP_ID = "ThatOneGuyBanks.ScreenSoundSeparation"
ERROR_ALREADY_EXISTS = 183


def _asset_path(name: str) -> str:
    """Return an absolute path to a packaged application asset."""
    return str(files("screen_sound_separation").joinpath("assets", name))


def _set_windows_identity() -> None:
    """Give Windows a stable identity so the taskbar uses our icon, not Python's."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        # Keeping this harmless makes importing the UI possible on non-Windows
        # machines, even though audio routing itself remains Windows-only.
        pass


def _acquire_instance_mutex() -> int | None:
    """Return a Windows mutex handle, or ``None`` when the app is already open."""
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
    """Release the single-instance guard created at startup."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle(handle)


class SeparationApp(tk.Tk):
    """Small control surface for the screen-aware audio router."""

    def __init__(self) -> None:
        _set_windows_identity()
        super().__init__()

        self.title("Screen Sound Separation")
        self.geometry("820x780")
        self.minsize(720, 680)
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
        # Repair balance left behind by a previous forced termination before the
        # user starts a new routing session. This does not change master volume.
        self.router.repair_stale_balances()
        # This is a final safety net for exits that do not arrive through the
        # window's close button, such as a console interrupt or an internal error.
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
        self.separation = tk.DoubleVar(value=75)
        self.strength_text = tk.StringVar(value="75%")
        self.left_mix_text = tk.StringVar()
        self.right_mix_text = tk.StringVar()

        self._load_icon()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build_style()
        self._build_ui()
        self._update_mix_preview(75)
        self._poll_browser()

    def _load_icon(self) -> None:
        """Apply both icon formats used by Tk and the Windows taskbar."""
        try:
            self._icon_image = tk.PhotoImage(file=_asset_path("app-icon.png"))
            self.iconphoto(True, self._icon_image)
            self.iconbitmap(_asset_path("app-icon.ico"))
        except tk.TclError:
            # A missing asset should never prevent the audio tool from opening.
            self._icon_image = None

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("TFrame", background=BG)
        style.configure("Surface.TFrame", background=SURFACE)
        style.configure("Raised.TFrame", background=SURFACE_RAISED)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Arial", 10))
        style.configure(
            "Title.TLabel", background=BG, foreground=TEXT, font=("Arial", 22, "bold")
        )
        style.configure(
            "Eyebrow.TLabel",
            background=BG,
            foreground=ORANGE,
            font=("Consolas", 8, "bold"),
        )
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Surface.TLabel", background=SURFACE, foreground=TEXT)
        style.configure("SurfaceMuted.TLabel", background=SURFACE, foreground=MUTED)
        style.configure(
            "CardHeading.TLabel",
            background=SURFACE,
            foreground=TEXT,
            font=("Arial", 12, "bold"),
        )
        style.configure(
            "Percent.TLabel",
            background=SURFACE,
            foreground=ORANGE,
            font=("Arial", 24, "bold"),
        )
        style.configure(
            "MixTitle.TLabel",
            background=SURFACE_RAISED,
            foreground=MUTED,
            font=("Consolas", 9, "bold"),
        )
        style.configure(
            "MixValue.TLabel",
            background=SURFACE_RAISED,
            foreground=TEXT,
            font=("Consolas", 11, "bold"),
        )
        style.configure(
            "Separator.Horizontal.TScale",
            background=SURFACE,
            troughcolor=BORDER,
            lightcolor=ORANGE,
            darkcolor=ORANGE,
            bordercolor=SURFACE,
        )
        style.configure(
            "Treeview",
            background=SURFACE,
            fieldbackground=SURFACE,
            foreground=TEXT,
            borderwidth=0,
            rowheight=36,
            font=("Arial", 10),
        )
        style.configure(
            "Treeview.Heading",
            background=SURFACE_RAISED,
            foreground=ORANGE,
            relief="flat",
            borderwidth=0,
            font=("Consolas", 9, "bold"),
        )
        style.map("Treeview", background=[("selected", "#29311E")])
        style.map("Treeview.Heading", background=[("active", SURFACE_RAISED)])
        style.configure(
            "App.Vertical.TScrollbar",
            background=SURFACE_RAISED,
            troughcolor=SURFACE,
            bordercolor=SURFACE,
            arrowcolor=MUTED,
            lightcolor=SURFACE_RAISED,
            darkcolor=SURFACE_RAISED,
        )

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=(30, 26, 30, 22))
        root.pack(fill="both", expand=True)

        self._build_header(root)
        self._build_separation_card(root)
        self._build_browser_card(root)
        self._build_apps_table(root)

        ttk.Label(
            root,
            text="LOCAL AUDIO ONLY  ·  NOTHING LEAVES THIS DEVICE",
            style="Muted.TLabel",
            font=("Consolas", 8, "bold"),
        ).pack(anchor="w", pady=(12, 0))

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent)
        header.pack(fill="x", pady=(0, 20))

        if self._icon_image is not None:
            compact_icon = self._icon_image.subsample(10, 10)
            self._header_icon = compact_icon
            ttk.Label(header, image=compact_icon, background=BG).pack(side="left", padx=(0, 14))

        titles = ttk.Frame(header)
        titles.pack(side="left", fill="x", expand=True)
        ttk.Label(
            titles,
            text="DISCONNETIC  /  FIELD TOOL 001",
            style="Eyebrow.TLabel",
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(titles, text="SCREEN SOUND SEPARATION", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            titles,
            text="Place a window. Shape the signal. Hear the space.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        self.status_badge = tk.Label(
            header,
            text="●  STANDBY",
            bg=SURFACE_RAISED,
            fg=ORANGE,
            font=("Consolas", 9, "bold"),
            padx=12,
            pady=7,
        )
        self.status_badge.pack(side="right")

    def _build_separation_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Surface.TFrame", padding=20)
        card.pack(fill="x", pady=(0, 20))

        heading = ttk.Frame(card, style="Surface.TFrame")
        heading.pack(fill="x")
        labels = ttk.Frame(heading, style="Surface.TFrame")
        labels.pack(side="left", fill="x", expand=True)
        ttk.Label(labels, text="Separation strength", style="CardHeading.TLabel").pack(anchor="w")
        ttk.Label(
            labels,
            text="Choose how much sound crosses over to the opposite speaker.",
            style="SurfaceMuted.TLabel",
        ).pack(anchor="w", pady=(3, 0))
        ttk.Label(heading, textvariable=self.strength_text, style="Percent.TLabel").pack(side="right")

        scale = ttk.Scale(
            card,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.separation,
            command=self._slider_changed,
            style="Separator.Horizontal.TScale",
        )
        scale.pack(fill="x", pady=(18, 5))

        endpoints = ttk.Frame(card, style="Surface.TFrame")
        endpoints.pack(fill="x")
        ttk.Label(endpoints, text="Balanced stereo", style="SurfaceMuted.TLabel").pack(side="left")
        ttk.Label(endpoints, text="Hard left / right", style="SurfaceMuted.TLabel").pack(side="right")

        preview = ttk.Frame(card, style="Surface.TFrame")
        preview.pack(fill="x", pady=(18, 0))
        preview.columnconfigure((0, 1), weight=1, uniform="mix")
        self._build_mix_panel(preview, 0, "LEFT DISPLAY", self.left_mix_text, ORANGE)
        self._build_mix_panel(preview, 1, "RIGHT DISPLAY", self.right_mix_text, SIGNAL)

        self.toggle = tk.Button(
            card,
            text="START SIGNAL  →",
            command=self._toggle,
            bg=ORANGE,
            activebackground="#FF6942",
            fg=BG,
            activeforeground=BG,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=("Consolas", 11, "bold"),
            padx=20,
            pady=11,
        )
        self.toggle.pack(fill="x", pady=(18, 0))

    def _build_browser_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Surface.TFrame", padding=(18, 14))
        card.pack(fill="x", pady=(0, 20))

        copy = ttk.Frame(card, style="Surface.TFrame")
        copy.pack(side="left", fill="x", expand=True)
        ttk.Label(copy, text="Browser tabs", style="CardHeading.TLabel").pack(anchor="w")
        self.browser_detail = ttk.Label(
            copy,
            text="Waiting for the Chrome extension.",
            style="SurfaceMuted.TLabel",
        )
        self.browser_detail.pack(anchor="w", pady=(3, 0))

        self.browser_badge = tk.Label(
            card,
            text="●  WAITING",
            bg=SURFACE_RAISED,
            fg=MUTED,
            font=("Consolas", 9, "bold"),
            padx=11,
            pady=6,
        )
        self.browser_badge.pack(side="right", padx=(12, 0))
        self.browser_setup = tk.Button(
            card,
            text="Set up extension",
            command=self._open_browser_setup,
            bg=SURFACE_RAISED,
            activebackground=BORDER,
            fg=TEXT,
            activeforeground=TEXT,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=("Consolas", 9, "bold"),
            padx=12,
            pady=6,
        )
        self.browser_setup.pack(side="right", padx=(12, 0))

    def _open_browser_setup(self) -> None:
        """Offer the Web Store build, or development files before publication."""
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
        messagebox.showinfo(
            "Set up Chrome browser support",
            "The extension folder is open and its path is copied.\n\n"
            "Until the Web Store listing is published:\n"
            "1. Remove an older Screen Sound Separation test extension, if shown.\n"
            "2. Open chrome://extensions in Chrome.\n"
            "3. Turn on Developer mode.\n"
            "4. Choose Load unpacked and select the open folder.\n\n"
            "The public release will replace this with Add to Chrome.",
        )

    def _build_mix_panel(
        self,
        parent: ttk.Frame,
        column: int,
        title: str,
        value: tk.StringVar,
        accent: str,
    ) -> None:
        panel = ttk.Frame(parent, style="Raised.TFrame", padding=(14, 11))
        panel.grid(row=0, column=column, sticky="ew", padx=(0, 6) if column == 0 else (6, 0))
        tk.Frame(panel, bg=accent, width=3, height=34).pack(side="left", padx=(0, 11))
        content = ttk.Frame(panel, style="Raised.TFrame")
        content.pack(side="left")
        ttk.Label(content, text=title, style="MixTitle.TLabel").pack(anchor="w")
        ttk.Label(content, textvariable=value, style="MixValue.TLabel").pack(anchor="w", pady=(2, 0))

    def _build_apps_table(self, parent: ttk.Frame) -> None:
        section = ttk.Frame(parent)
        section.pack(fill="both", expand=True)

        section_heading = ttk.Frame(section)
        section_heading.pack(fill="x", pady=(0, 8))
        ttk.Label(
            section_heading, text="ACTIVE SIGNALS", font=("Arial", 12, "bold")
        ).pack(side="left")
        self.app_count = ttk.Label(section_heading, text="Waiting to start", style="Muted.TLabel")
        self.app_count.pack(side="right")

        table_frame = ttk.Frame(section, style="Surface.TFrame")
        table_frame.pack(fill="both", expand=True)
        columns = ("app", "screen", "mix")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="none")
        self.tree.heading("app", text="APPLICATION")
        self.tree.heading("screen", text="WINDOW  ▾")
        self.tree.heading("mix", text="OUTPUT MIX")
        self.tree.column("app", width=280, minwidth=180)
        self.tree.column("screen", width=130, minwidth=100, anchor="center")
        self.tree.column("mix", width=190, minwidth=150, anchor="center")
        self.tree.tag_configure("even", background=SURFACE)
        self.tree.tag_configure("odd", background="#0C0F0D")
        self.tree.bind("<Button-1>", self._show_position_menu, add="+")
        self.tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.tree.yview,
            style="App.Vertical.TScrollbar",
        )
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

    def _slider_changed(self, value: str) -> None:
        strength = round(float(value))
        self.strength_text.set(f"{strength}%")
        self._update_mix_preview(strength)
        self.browser_bridge.update(self.running, strength / 100.0)
        if self.running:
            self._apply_once()

    def _update_mix_preview(self, strength: int) -> None:
        crossover = 100 - strength
        self.left_mix_text.set(f"L 100%   ·   R {crossover}%")
        self.right_mix_text.set(f"L {crossover}%   ·   R 100%")

    def _toggle(self) -> None:
        if self.running:
            self.running = False
            if self._after_id is not None:
                self.after_cancel(self._after_id)
                self._after_id = None
            self.browser_bridge.update(False, self.separation.get() / 100.0)
            self.browser_bridge.release_all()
            self.router.restore()
            self.toggle.configure(text="START SIGNAL  →", bg=ORANGE, fg=BG)
            self.status_badge.configure(text="●  STANDBY", fg=ORANGE)
            self.app_count.configure(text="Waiting to start")
            self._render([])
        else:
            self.running = True
            self.browser_bridge.update(True, self.separation.get() / 100.0)
            self.toggle.configure(text="STOP + RESTORE", bg=SURFACE_RAISED, fg=SIGNAL)
            self.status_badge.configure(text="●  LIVE", fg=SIGNAL)
            self._refresh()

    def _refresh(self) -> None:
        if not self.running:
            return
        self._apply_once()
        self._after_id = self.after(1000, self._refresh)

    def _apply_once(self) -> None:
        try:
            apps = self.router.apply(self.separation.get() / 100.0)
            if self.browser_connected:
                apps = [app for app in apps if app.name.casefold() not in BROWSER_PROCESSES]
            self._last_apps = apps
            self._render(apps)
            count = len(apps) + len(self.browser_tabs)
            self.status_badge.configure(text="●  LIVE", fg=SIGNAL)
            self.app_count.configure(text=f"{count} detected")
        except Exception as exc:  # Keep the UI responsive if Windows audio resets.
            self.status_badge.configure(text="●  AUDIO ERROR", fg=RED)
            self.app_count.configure(text=f"Audio unavailable: {exc}")

    def _render(self, apps: list[RoutedApp]) -> None:
        self.tree.delete(*self.tree.get_children())
        self._tree_targets.clear()
        rows: list[tuple[tuple[str, str, str], tuple[str, str | int]]] = []
        for app in apps:
            if app.title == "No visible window":
                side = "No window"
            elif app.position < -0.2:
                side = "Left"
            elif app.position > 0.2:
                side = "Right"
            else:
                side = "Centre"
            if app.name.casefold() in self.app_position_overrides:
                side += " · Manual"
            mix = f"L {app.left_gain * 100:.0f}%   ·   R {app.right_gain * 100:.0f}%"
            rows.append(((app.name, side, mix), ("app", app.name)))

        for tab in sorted(self.browser_tabs.values(), key=lambda item: item.title.casefold()):
            if tab.pan < 0:
                gains = (1.0, 1.0 - abs(tab.pan))
            else:
                gains = (1.0 - abs(tab.pan), 1.0)
            mix = f"L {gains[0] * 100:.0f}%   ·   R {gains[1] * 100:.0f}%"
            side = tab.side + (" · Manual" if tab.tab_id in self.tab_position_overrides else "")
            rows.append(((f"Chrome tab · {tab.title}", side, mix), ("tab", tab.tab_id)))

        for index, (values, target) in enumerate(rows):
            item_id = self.tree.insert(
                "",
                "end",
                values=values,
                tags=("even" if index % 2 == 0 else "odd",),
            )
            self._tree_targets[item_id] = target

    def _show_position_menu(self, event: tk.Event) -> None:
        """Offer a manual side when the WINDOW column is selected."""
        if self.tree.identify_column(event.x) != "#2":
            return
        item_id = self.tree.identify_row(event.y)
        target = self._tree_targets.get(item_id)
        if target is None:
            return

        menu = tk.Menu(
            self,
            tearoff=False,
            bg=SURFACE_RAISED,
            fg=TEXT,
            activebackground=ORANGE,
            activeforeground=BG,
            borderwidth=0,
            font=("Consolas", 9),
        )
        for label, position in (("Auto", None), ("Left", -1.0), ("Right", 1.0), ("Centre", 0.0)):
            menu.add_command(
                label=label,
                command=lambda selected=position: self._set_position_override(target, selected),
            )
        self._position_menu = menu
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _set_position_override(
        self, target: tuple[str, str | int], position: float | None
    ) -> None:
        kind, key = target
        if kind == "app":
            name = str(key)
            self.router.set_position_override(name, position)
            if position is None:
                self.app_position_overrides.pop(name.casefold(), None)
            else:
                self.app_position_overrides[name.casefold()] = position
            if self.running:
                self._apply_once()
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
                self.browser_tabs[tab_id] = BrowserTab(
                    tab_id=tab.tab_id,
                    title=tab.title,
                    side=side,
                    pan=position * (self.separation.get() / 100.0),
                )
        self._render(self._last_apps)

    def _poll_browser(self) -> None:
        """Apply extension status messages on Tk's UI thread."""
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
                        self.browser_tabs[tab_id] = BrowserTab(
                            tab_id=tab_id,
                            title=str(event.get("title") or "Browser tab"),
                            side=str(event.get("side") or "Centre"),
                            pan=max(-1.0, min(1.0, float(event.get("pan", 0.0)))),
                        )
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
            self.browser_badge.configure(text="●  LINKED", fg=SIGNAL)
            if self.running:
                detail = f"{count} managed {noun}. Click the extension icon on a tab to toggle it."
            else:
                detail = "Ready. Clicking the extension on a tab starts routing automatically."
            self.browser_detail.configure(text=detail)
            self.browser_setup.configure(text="Extension connected", state="disabled")
        else:
            self.browser_badge.configure(text="●  WAITING", fg=MUTED)
            self.browser_detail.configure(text="Waiting for the Chrome extension.")
            self.browser_setup.configure(text="Set up extension", state="normal")

        if changed:
            self._render(self._last_apps)
            if self.running:
                self.app_count.configure(text=f"{len(self._last_apps) + len(self.browser_tabs)} detected")
        self._browser_after_id = self.after(250, self._poll_browser)

    def _close(self) -> None:
        """Stop scheduled work, restore audio, and then close the window."""
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
            # The explicit restore above gives us a predictable shutdown order;
            # unregister the fallback so it does not run again during teardown.
            atexit.unregister(self.router.restore)
            self.browser_bridge.close()
            atexit.unregister(self.browser_bridge.close)
            self.destroy()


def main() -> None:
    mutex = _acquire_instance_mutex()
    if mutex is None:
        ctypes.windll.user32.MessageBoxW(
            None,
            "Screen Sound Separation is already running.",
            "Screen Sound Separation",
            0x40,  # MB_ICONINFORMATION
        )
        return

    app: SeparationApp | None = None
    try:
        app = SeparationApp()
        app.mainloop()
    finally:
        if app is not None:
            # Covers KeyboardInterrupt and unexpected errors escaping Tk's event loop.
            app.browser_bridge.close()
            app.router.restore()
        _release_instance_mutex(mutex)


if __name__ == "__main__":
    main()
