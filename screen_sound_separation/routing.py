"""Pure routing calculations used by the audio controller and tests."""

from __future__ import annotations


def channel_gains(position: float, separation: float) -> tuple[float, float]:
    """Return left/right gains for a position and separation in the 0..1 range.

    ``position`` ranges from -1 (left display) to +1 (right display). At zero
    separation the signal is unchanged; at full separation an edge display is
    hard-panned to its matching speaker.
    """
    position = max(-1.0, min(1.0, position))
    separation = max(0.0, min(1.0, separation))
    left = 1.0 - max(0.0, position) * separation
    right = 1.0 - max(0.0, -position) * separation
    return left, right


def normalized_position(center_x: float, left: float, right: float) -> float:
    """Map a horizontal desktop coordinate to -1..1."""
    if right <= left:
        return 0.0
    midpoint = (left + right) / 2.0
    half_width = (right - left) / 2.0
    return max(-1.0, min(1.0, (center_x - midpoint) / half_width))

