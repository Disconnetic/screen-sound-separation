from screen_sound_separation.routing import channel_gains, normalized_position


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

