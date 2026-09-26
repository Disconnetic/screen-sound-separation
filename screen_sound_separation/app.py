"""Tk desktop interface for Screen Sound Separation."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .audio import AudioRouter, RoutedApp


BG = "#111318"
PANEL = "#1b1f27"
TEXT = "#f4f6fb"
MUTED = "#9ba3b5"
ACCENT = "#7467f0"


class SeparationApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Screen Sound Separation")
        self.geometry("720x540")
        self.minsize(620, 440)
        self.configure(bg=BG)
        self.router = AudioRouter()
        self.running = False
        self._after_id: str | None = None
        self.separation = tk.DoubleVar(value=75)
        self.status = tk.StringVar(value="Routing is off")
        self.strength_text = tk.StringVar(value="75%")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build_style()
        self._build_ui()

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 23), foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Card.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Strength.TLabel", background=PANEL, foreground=ACCENT, font=("Segoe UI Semibold", 16))
        style.configure("TButton", font=("Segoe UI Semibold", 10), padding=(18, 10))
        style.configure("Accent.TButton", background=ACCENT, foreground="white")
        style.map("Accent.TButton", background=[("active", "#8a80f5")])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=30, borderwidth=0)
        style.configure("Treeview.Heading", background="#242a35", foreground=TEXT, relief="flat")
        style.map("Treeview", background=[("selected", "#343052")])

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=28)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="Screen Sound Separation", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            root,
            text="Hear each app from the side of your desk where its window lives.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(3, 22))

        card = ttk.Frame(root, style="Card.TFrame", padding=20)
        card.pack(fill="x")
        header = ttk.Frame(card, style="Card.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="Separation", style="Card.TLabel", font=("Segoe UI Semibold", 12)).pack(side="left")
        ttk.Label(header, textvariable=self.strength_text, style="Strength.TLabel").pack(side="right")

        scale = tk.Scale(
            card, from_=0, to=100, orient="horizontal", variable=self.separation,
            command=self._slider_changed, showvalue=False, bg=PANEL, fg=TEXT,
            troughcolor="#343946", activebackground=ACCENT, highlightthickness=0,
            sliderrelief="flat", sliderlength=22,
        )
        scale.pack(fill="x", pady=(12, 2))
        labels = ttk.Frame(card, style="Card.TFrame")
        labels.pack(fill="x")
        ttk.Label(labels, text="Shared stereo", style="Card.TLabel").pack(side="left")
        ttk.Label(labels, text="Hard left / right", style="Card.TLabel").pack(side="right")

        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=18)
        self.toggle = ttk.Button(actions, text="Start routing", style="Accent.TButton", command=self._toggle)
        self.toggle.pack(side="left")
        ttk.Label(actions, textvariable=self.status, style="Muted.TLabel").pack(side="left", padx=14)

        ttk.Label(root, text="Active audio apps", font=("Segoe UI Semibold", 12)).pack(anchor="w", pady=(4, 8))
        columns = ("app", "screen", "mix")
        self.tree = ttk.Treeview(root, columns=columns, show="headings", selectmode="none")
        self.tree.heading("app", text="APP")
        self.tree.heading("screen", text="POSITION")
        self.tree.heading("mix", text="OUTPUT MIX")
        self.tree.column("app", width=240)
        self.tree.column("screen", width=120, anchor="center")
        self.tree.column("mix", width=180, anchor="center")
        self.tree.pack(fill="both", expand=True)

    def _slider_changed(self, value: str) -> None:
        self.strength_text.set(f"{round(float(value))}%")
        if self.running:
            self._apply_once()

    def _toggle(self) -> None:
        if self.running:
            self.running = False
            if self._after_id is not None:
                self.after_cancel(self._after_id)
                self._after_id = None
            self.router.restore()
            self.toggle.configure(text="Start routing")
            self.status.set("Routing is off · original balance restored")
            self._render([])
        else:
            self.running = True
            self.toggle.configure(text="Stop routing")
            self.status.set("Routing is active")
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
            self.status.set(f"Routing {len(apps)} audio app{'s' if len(apps) != 1 else ''}")
        except Exception as exc:  # keep the UI responsive if Windows audio resets
            self.status.set(f"Audio unavailable: {exc}")

    def _render(self, apps: list[RoutedApp]) -> None:
        self.tree.delete(*self.tree.get_children())
        for app in apps:
            if app.position < -0.2:
                side = "Left"
            elif app.position > 0.2:
                side = "Right"
            else:
                side = "Center"
            mix = f"L {app.left_gain * 100:.0f}%  ·  R {app.right_gain * 100:.0f}%"
            self.tree.insert("", "end", values=(app.name, side, mix))

    def _close(self) -> None:
        self.running = False
        if self._after_id is not None:
            self.after_cancel(self._after_id)
        self.router.restore()
        self.destroy()


def main() -> None:
    app = SeparationApp()
    app.mainloop()


if __name__ == "__main__":
    main()
