"""Desktop interface for Screen Sound Separation."""

from __future__ import annotations

import atexit
import ctypes
import tkinter as tk
from importlib.resources import files
from tkinter import ttk

from .audio import AudioRouter, RoutedApp, WindowOption


# A small, shared palette keeps the UI consistent without introducing a theme
# dependency for what is intentionally a lightweight utility.
BG = "#090e1a"
SURFACE = "#111827"
SURFACE_RAISED = "#172033"
BORDER = "#263248"
TEXT = "#f4f7ff"
MUTED = "#94a3b8"
VIOLET = "#9b6cff"
CYAN = "#22d3ee"
GREEN = "#34d399"
RED = "#fb7185"

APP_ID = "ThatOneGuyBanks.ScreenSoundSeparation"


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


class SeparationApp(tk.Tk):
    """Small control surface for the screen-aware audio router."""

    def __init__(self) -> None:
        _set_windows_identity()
        super().__init__()

        self.title("Screen Sound Separation")
        self.geometry("800x780")
        self.minsize(700, 680)
        self.configure(bg=BG)

        self.router = AudioRouter()
        # This is a final safety net for exits that do not arrive through the
        # window's close button, such as a console interrupt or an internal error.
        atexit.register(self.router.restore)
        self.running = False
        self._after_id: str | None = None
        self.separation = tk.DoubleVar(value=75)
        self.strength_text = tk.StringVar(value="75%")
        self.left_mix_text = tk.StringVar()
        self.right_mix_text = tk.StringVar()
        self.window_choice = tk.StringVar()
        self.window_match_help = tk.StringVar(value="Select an audio app to inspect its window match.")
        self._routed_apps: dict[str, RoutedApp] = {}
        self._row_sessions: dict[str, str] = {}
        self._window_choice_handles: dict[str, int] = {}
        self._selected_session: str | None = None

        self._load_icon()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build_style()
        self._build_ui()
        self._update_mix_preview(75)

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
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure(
            "Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 22)
        )
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Surface.TLabel", background=SURFACE, foreground=TEXT)
        style.configure("SurfaceMuted.TLabel", background=SURFACE, foreground=MUTED)
        style.configure(
            "CardHeading.TLabel",
            background=SURFACE,
            foreground=TEXT,
            font=("Segoe UI Semibold", 12),
        )
        style.configure(
            "Percent.TLabel",
            background=SURFACE,
            foreground=VIOLET,
            font=("Segoe UI Semibold", 24),
        )
        style.configure(
            "MixTitle.TLabel",
            background=SURFACE_RAISED,
            foreground=MUTED,
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "MixValue.TLabel",
            background=SURFACE_RAISED,
            foreground=TEXT,
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "Separator.Horizontal.TScale",
            background=SURFACE,
            troughcolor=BORDER,
            lightcolor=VIOLET,
            darkcolor=VIOLET,
            bordercolor=SURFACE,
        )
        style.configure(
            "Treeview",
            background=SURFACE,
            fieldbackground=SURFACE,
            foreground=TEXT,
            borderwidth=0,
            rowheight=36,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background=SURFACE_RAISED,
            foreground=MUTED,
            relief="flat",
            borderwidth=0,
            font=("Segoe UI Semibold", 9),
        )
        style.map("Treeview", background=[("selected", "#273451")])
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
        style.configure(
            "Window.TCombobox",
            fieldbackground=SURFACE_RAISED,
            background=SURFACE_RAISED,
            foreground=TEXT,
            arrowcolor=CYAN,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=7,
        )
        style.map(
            "Window.TCombobox",
            fieldbackground=[("readonly", SURFACE_RAISED), ("disabled", SURFACE)],
            foreground=[("readonly", TEXT), ("disabled", MUTED)],
        )

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=(30, 26, 30, 22))
        root.pack(fill="both", expand=True)

        self._build_header(root)
        self._build_separation_card(root)
        self._build_apps_table(root)

        ttk.Label(
            root,
            text="Audio follows the monitor containing most of each app window.",
            style="Muted.TLabel",
            font=("Segoe UI", 9),
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
        ttk.Label(titles, text="Screen Sound Separation", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            titles,
            text="Place an app on a screen. Its sound follows.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        self.status_badge = tk.Label(
            header,
            text="●  READY",
            bg=SURFACE_RAISED,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
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
        self._build_mix_panel(preview, 0, "APP ON LEFT SCREEN", self.left_mix_text, VIOLET)
        self._build_mix_panel(preview, 1, "APP ON RIGHT SCREEN", self.right_mix_text, CYAN)

        self.toggle = tk.Button(
            card,
            text="▶  Start routing",
            command=self._toggle,
            bg=VIOLET,
            activebackground="#ac86ff",
            fg="white",
            activeforeground="white",
            relief="flat",
            borderwidth=0,
            cursor="hand2",
            font=("Segoe UI Semibold", 11),
            padx=20,
            pady=11,
        )
        self.toggle.pack(fill="x", pady=(18, 0))

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
            section_heading, text="Active audio apps", font=("Segoe UI Semibold", 12)
        ).pack(side="left")
        self.app_count = ttk.Label(section_heading, text="Waiting to start", style="Muted.TLabel")
        self.app_count.pack(side="right")

        match_panel = ttk.Frame(section, style="Raised.TFrame", padding=(14, 11))
        match_panel.pack(fill="x", pady=(0, 9))
        # Pack the fixed-width picker first so the explanatory copy takes only
        # the space that remains when the window becomes narrow.
        self.window_picker = ttk.Combobox(
            match_panel,
            textvariable=self.window_choice,
            state="disabled",
            width=34,
            style="Window.TCombobox",
        )
        self.window_picker.pack(side="right", padx=(14, 0))
        self.window_picker.bind("<<ComboboxSelected>>", self._window_selected)

        match_copy = ttk.Frame(match_panel, style="Raised.TFrame")
        match_copy.pack(side="left", fill="x", expand=True)
        ttk.Label(
            match_copy,
            text="FOLLOW WINDOW",
            style="MixTitle.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            match_copy,
            textvariable=self.window_match_help,
            style="MixValue.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        table_frame = ttk.Frame(section, style="Surface.TFrame")
        table_frame.pack(fill="both", expand=True)
        columns = ("app", "screen", "mix")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("app", text="APPLICATION")
        self.tree.heading("screen", text="WINDOW")
        self.tree.heading("mix", text="OUTPUT MIX")
        self.tree.column("app", width=280, minwidth=180)
        self.tree.column("screen", width=160, minwidth=120, anchor="center")
        self.tree.column("mix", width=190, minwidth=150, anchor="center")
        self.tree.tag_configure("even", background=SURFACE)
        self.tree.tag_configure("odd", background="#141d2e")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._app_selected)

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
            self.router.restore()
            self.toggle.configure(text="▶  Start routing", bg=VIOLET)
            self.status_badge.configure(text="●  READY", fg=MUTED)
            self.app_count.configure(text="Waiting to start")
            self._render([])
        else:
            self.running = True
            self.toggle.configure(text="■  Stop and restore audio", bg="#334155")
            self.status_badge.configure(text="●  ACTIVE", fg=GREEN)
            self._refresh()

    def _refresh(self) -> None:
        if not self.running:
            return
        self._apply_once()
        self._after_id = self.after(1000, self._refresh)

    def _apply_once(self) -> None:
        try:
            apps = self.router.apply(self.separation.get() / 100.0)
            self._render(apps)
            count = len(apps)
            self.status_badge.configure(text="●  ACTIVE", fg=GREEN)
            self.app_count.configure(text=f"{count} detected")
        except Exception as exc:  # Keep the UI responsive if Windows audio resets.
            self.status_badge.configure(text="●  AUDIO ERROR", fg=RED)
            self.app_count.configure(text=f"Audio unavailable: {exc}")

    def _render(self, apps: list[RoutedApp]) -> None:
        previous_session = self._selected_session
        self._routed_apps = {app.session_id: app for app in apps}
        self._row_sessions.clear()
        self.tree.delete(*self.tree.get_children())
        for index, app in enumerate(apps):
            if app.title == "No visible window":
                side = "No window"
            elif app.position < -0.2:
                side = "Left"
            elif app.position > 0.2:
                side = "Right"
            else:
                side = "Centre"
            if len(app.window_options) > 1:
                side = f"{side} · {len(app.window_options)} windows"
            mix = f"L {app.left_gain * 100:.0f}%   ·   R {app.right_gain * 100:.0f}%"
            row_id = f"audio-{index}"
            self._row_sessions[row_id] = app.session_id
            self.tree.insert(
                "",
                "end",
                iid=row_id,
                values=(app.name, side, mix),
                tags=("even" if index % 2 == 0 else "odd",),
            )

        session_to_row = {session: row for row, session in self._row_sessions.items()}
        if previous_session in session_to_row:
            row_id = session_to_row[previous_session]
        else:
            ambiguous = next(
                (app for app in apps if len(app.window_options) > 1),
                apps[0] if apps else None,
            )
            row_id = session_to_row.get(ambiguous.session_id) if ambiguous else None

        if row_id is not None:
            self.tree.selection_set(row_id)
            self._show_window_choices(self._routed_apps[self._row_sessions[row_id]])
        else:
            self._selected_session = None
            self.window_choice.set("")
            self.window_picker.configure(values=(), state="disabled")
            self.window_match_help.set("Select an audio app to inspect its window match.")

    def _app_selected(self, _event: object = None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        session_id = self._row_sessions.get(selection[0])
        app = self._routed_apps.get(session_id) if session_id else None
        if app is not None:
            self._show_window_choices(app)

    @staticmethod
    def _option_side(option: WindowOption) -> str:
        if option.position < -0.2:
            return "Left"
        if option.position > 0.2:
            return "Right"
        return "Centre"

    def _show_window_choices(self, app: RoutedApp) -> None:
        self._selected_session = app.session_id
        self._window_choice_handles.clear()

        labels: list[str] = []
        selected_label = ""
        for option in app.window_options:
            title = option.title if len(option.title) <= 48 else f"{option.title[:45]}…"
            label = f"{self._option_side(option)} — {title}"
            if label in self._window_choice_handles:
                label = f"{label} [{option.handle}]"
            labels.append(label)
            self._window_choice_handles[label] = option.handle
            if option.handle == app.selected_window:
                selected_label = label

        self.window_picker.configure(values=labels)
        self.window_choice.set(selected_label)
        if len(labels) > 1:
            self.window_picker.configure(state="readonly")
            self.window_match_help.set(f"{len(labels)} matching windows found")
        elif len(labels) == 1:
            self.window_picker.configure(state="disabled")
            self.window_match_help.set("Automatically matched to its visible window.")
        else:
            self.window_picker.configure(state="disabled")
            self.window_match_help.set("No visible window; this audio stays centred.")

    def _window_selected(self, _event: object = None) -> None:
        if self._selected_session is None:
            return
        handle = self._window_choice_handles.get(self.window_choice.get())
        if handle is None:
            return
        self.router.set_window_override(self._selected_session, handle)
        if self.running:
            self._apply_once()

    def _close(self) -> None:
        """Stop scheduled work, restore audio, and then close the window."""
        self.running = False
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        try:
            self.router.restore()
        finally:
            # The explicit restore above gives us a predictable shutdown order;
            # unregister the fallback so it does not run again during teardown.
            atexit.unregister(self.router.restore)
            self.destroy()


def main() -> None:
    app = SeparationApp()
    try:
        app.mainloop()
    finally:
        # Covers KeyboardInterrupt and unexpected errors escaping Tk's event loop.
        app.router.restore()


if __name__ == "__main__":
    main()
