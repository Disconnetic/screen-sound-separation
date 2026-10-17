from screen_sound_separation.presentation import (
    mix_label,
    pan_gains,
    position_label,
    source_is_visible,
)


def test_position_label_handles_auto_and_manual_sources() -> None:
    assert position_label(-1) == "Left"
    assert position_label(0) == "Centre"
    assert position_label(1, manual=True) == "Right · Manual"
    assert position_label(0, no_window=True) == "No window"
    assert position_label(-1, no_window=True, manual=True) == "Left · Manual"


def test_pan_gains_and_mix_label_match_browser_panning() -> None:
    assert pan_gains(-0.75) == (1.0, 0.25)
    assert pan_gains(0.75) == (0.25, 1.0)
    assert pan_gains(5) == (0.0, 1.0)
    assert mix_label(1.0, 0.25) == "L 100%  ·  R 25%"


def test_source_filter_matches_kind_and_searchable_details() -> None:
    values = ("Music Player", "Now playing", "Left", "Desktop app")
    assert source_is_visible(*values, "", "All sources")
    assert source_is_visible(*values, "playing", "All sources")
    assert source_is_visible(*values, "left", "Desktop apps")
    assert not source_is_visible(*values, "", "Browser tabs")
    assert not source_is_visible(*values, "video", "All sources")
