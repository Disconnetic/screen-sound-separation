"""Pure presentation helpers for the desktop interface."""

from __future__ import annotations


SOURCE_FILTERS = ("All sources", "Desktop apps", "Browser tabs")


def position_label(position: float, no_window: bool = False, manual: bool = False) -> str:
    """Return the concise position label shown in the live-source table."""
    if no_window and not manual:
        label = "No window"
    elif position < -0.2:
        label = "Left"
    elif position > 0.2:
        label = "Right"
    else:
        label = "Centre"
    return f"{label} · Manual" if manual else label


def pan_gains(pan: float) -> tuple[float, float]:
    """Convert a Web Audio pan value to the UI's left/right gain summary."""
    pan = max(-1.0, min(1.0, pan))
    if pan < 0:
        return 1.0, 1.0 - abs(pan)
    return 1.0 - abs(pan), 1.0


def mix_label(left_gain: float, right_gain: float) -> str:
    """Format channel multipliers as a compact human-readable label."""
    return f"L {left_gain * 100:.0f}%  ·  R {right_gain * 100:.0f}%"


def source_is_visible(
    source: str,
    detail: str,
    position: str,
    kind: str,
    query: str,
    selected_filter: str,
) -> bool:
    """Return whether a source row matches the search and kind controls."""
    if selected_filter == "Desktop apps" and kind != "Desktop app":
        return False
    if selected_filter == "Browser tabs" and kind != "Browser tab":
        return False
    needle = query.strip().casefold()
    if not needle:
        return True
    haystack = " ".join((source, detail, position, kind)).casefold()
    return needle in haystack
