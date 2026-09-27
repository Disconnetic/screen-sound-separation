from screen_sound_separation.routing import channel_gains, normalized_position
from screen_sound_separation.windows import MonitorInfo, WindowInfo, monitor_position


class FakeChannels:
    def __init__(self) -> None:
        self.values = [0.0, 0.0]

    def GetChannelCount(self) -> int:
        return 2

    def SetChannelVolume(self, channel: int, value: float, _context: object) -> None:
        self.values[channel] = value


class FakeSession:
    def __init__(self, identifier: str) -> None:
        self.InstanceIdentifier = identifier
        self.ProcessId = 123
        self.Process = object()
        self.channels = FakeChannels()

    def channelAudioVolume(self) -> FakeChannels:
        return self.channels


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


def test_restore_returns_touched_sessions_to_neutral_balance(monkeypatch) -> None:
    from screen_sound_separation.audio import AudioRouter, AudioUtilities

    session = FakeSession("test-session")
    monkeypatch.setattr(AudioUtilities, "GetAllSessions", lambda: [session])

    router = AudioRouter()
    router._touched.add("test-session")
    router.restore()

    assert session.channels.values == [1.0, 1.0]
    assert router._touched == set()


def test_startup_repair_centres_stale_channel_balance(monkeypatch) -> None:
    from screen_sound_separation.audio import AudioRouter, AudioUtilities

    session = FakeSession("stale-session")
    session.channels.values = [0.13, 0.06]
    monkeypatch.setattr(AudioUtilities, "GetAllSessions", lambda: [session])

    AudioRouter().repair_stale_balances()

    assert session.channels.values == [1.0, 1.0]


def test_position_override_can_be_set_and_returned_to_auto() -> None:
    from screen_sound_separation.audio import AudioRouter

    router = AudioRouter()
    router.set_position_override("Example.exe", -1)
    assert router._position_overrides == {"example.exe": -1}

    router.set_position_override("EXAMPLE.EXE", None)
    assert router._position_overrides == {}


def test_position_override_works_without_a_detected_window(monkeypatch) -> None:
    from screen_sound_separation import audio

    class FakeProcess:
        @staticmethod
        def name() -> str:
            return "Example.exe"

    session = FakeSession("manual-session")
    session.Process = FakeProcess()
    monkeypatch.setattr(audio.AudioUtilities, "GetAllSessions", lambda: [session])
    monkeypatch.setattr(audio, "visible_windows_by_pid", lambda: {})
    monkeypatch.setattr(audio, "monitor_layout", lambda: [])
    monkeypatch.setattr(audio.AudioRouter, "_window_for_session", lambda *_args: None)

    router = audio.AudioRouter()
    router.set_position_override("Example.exe", -1)
    routed = router.apply(0.75)

    assert session.channels.values == [1.0, 0.25]
    assert routed[0].position == -1
