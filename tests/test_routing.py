from screen_sound_separation.routing import channel_gains, normalized_position
from screen_sound_separation.windows import MonitorInfo, WindowInfo, monitor_position


def test_zero_separation_keeps_stereo() -> None:
    assert channel_gains(-1, 0) == (1, 1)
    assert channel_gains(1, 0) == (1, 1)


def test_full_separation_hard_pans_edges() -> None:
    assert channel_gains(-1, 1) == (1, 0)
    assert channel_gains(1, 1) == (0, 1)


def test_partial_separation_and_position() -> None:
    assert channel_gains(-0.5, 0.8) == (1, 0.6)
    assert channel_gains(0.5, 0.8) == (0.6, 1)


def test_normalized_position_handles_negative_desktop_coordinates() -> None:
    assert normalized_position(-1920, -1920, 1920) == -1
    assert normalized_position(0, -1920, 1920) == 0
    assert normalized_position(1920, -1920, 1920) == 1


def test_normalized_position_clamps_and_handles_empty_width() -> None:
    assert normalized_position(-100, 0, 10) == -1
    assert normalized_position(100, 0, 10) == 1
    assert normalized_position(5, 5, 5) == 0


def test_monitor_position_uses_screen_with_most_window_area() -> None:
    monitors = [
        MonitorInfo(0, 0, 1920, 1080),
        MonitorInfo(1920, 0, 3840, 1080),
    ]
    mostly_left = WindowInfo(1, "Left", 1500, 100, 2100, 800)
    mostly_right = WindowInfo(2, "Right", 1800, 100, 2600, 800)
    assert monitor_position(mostly_left, monitors) == -1
    assert monitor_position(mostly_right, monitors) == 1


def test_monitor_position_handles_three_displays() -> None:
    monitors = [
        MonitorInfo(0, 0, 1000, 1000),
        MonitorInfo(1000, 0, 2000, 1000),
        MonitorInfo(2000, 0, 3000, 1000),
    ]
    assert monitor_position(WindowInfo(1, "L", 10, 10, 900, 900), monitors) == -1
    assert monitor_position(WindowInfo(2, "C", 1010, 10, 1900, 900), monitors) == 0
    assert monitor_position(WindowInfo(3, "R", 2010, 10, 2900, 900), monitors) == 1
