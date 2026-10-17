"""Windows Core Audio session controller."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psutil
from pycaw.pycaw import AudioUtilities

from .routing import channel_gains
from .windows import WindowInfo, monitor_layout, monitor_position, visible_windows_by_pid


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutedApp:
    name: str
    pid: int
    title: str
    position: float
    left_gain: float
    right_gain: float


def set_neutral_balance(session_ids: set[str] | None = None) -> bool:
    """Set active stereo sessions back to neutral channel balance.

    ``None`` deliberately means every active session. The independent safety
    guardian uses that mode after a lost routing lease because it may not know
    which session the desktop process was changing when it stopped.
    """
    try:
        sessions = AudioUtilities.GetAllSessions()
    except (OSError, RuntimeError):
        log.warning("Could not enumerate audio sessions while restoring", exc_info=True)
        return False

    for session in sessions:
        if session.Process is None or session.ProcessId == 0:
            continue
        if session_ids is not None and session.InstanceIdentifier not in session_ids:
            continue
        try:
            channels = session.channelAudioVolume()
            if channels.GetChannelCount() >= 2:
                channels.SetChannelVolume(0, 1.0, None)
                channels.SetChannelVolume(1, 1.0, None)
        except (OSError, RuntimeError):
            log.debug("Audio session disappeared while restoring", exc_info=True)
    return True


class AudioRouter:
    """Apply and restore per-session stereo channel gains."""

    def __init__(self) -> None:
        self._touched: set[str] = set()
        self._excluded: set[str] = set()
        self._position_overrides: dict[str, float] = {}

    @property
    def excluded(self) -> set[str]:
        return set(self._excluded)

    def set_excluded(self, process_names: set[str]) -> None:
        self._excluded = {name.casefold() for name in process_names}

    def set_position_override(self, process_name: str, position: float | None) -> None:
        """Override one executable's detected position, or return it to Auto."""
        key = process_name.casefold()
        if position is None:
            self._position_overrides.pop(key, None)
        else:
            self._position_overrides[key] = max(-1.0, min(1.0, position))

    @staticmethod
    def _window_for_session(
        process: psutil.Process, windows: dict[int, WindowInfo]
    ) -> WindowInfo | None:
        """Find a UI window for an audio process, including browser child processes."""
        direct = windows.get(process.pid)
        if direct is not None:
            return direct

        # Chromium and similar apps put audio in a child process while the visible
        # window belongs to a parent with the same executable.
        try:
            process_name = process.name().casefold()
            for parent in process.parents():
                window = windows.get(parent.pid)
                if window is not None and parent.name().casefold() == process_name:
                    return window
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        # Some app frameworks use sibling UI and audio processes. Match those by
        # executable name and favor the largest visible window.
        try:
            process_name = process.name().casefold()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
        candidates: list[WindowInfo] = []
        for pid, window in windows.items():
            try:
                if psutil.Process(pid).name().casefold() == process_name:
                    candidates.append(window)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return max(candidates, key=lambda item: item.area, default=None)

    def apply(self, separation: float) -> list[RoutedApp]:
        windows = visible_windows_by_pid()
        monitors = monitor_layout()
        routed: list[RoutedApp] = []

        for session in AudioUtilities.GetAllSessions():
            process = session.Process
            if process is None or session.ProcessId == 0:
                continue
            try:
                name = process.name()
                window = self._window_for_session(process, windows)
                channels = session.channelAudioVolume()
                if channels.GetChannelCount() < 2:
                    continue

                override = self._position_overrides.get(name.casefold())
                if name.casefold() in self._excluded:
                    gains = (1.0, 1.0)
                    title = "No visible window" if window is None else window.title
                    position = 0.0
                elif override is not None:
                    position = override
                    gains = channel_gains(position, separation)
                    title = "No visible window" if window is None else window.title
                elif window is None:
                    gains = (1.0, 1.0)
                    title = "No visible window"
                    position = 0.0
                else:
                    position = monitor_position(window, monitors)
                    gains = channel_gains(position, separation)
                    title = window.title

                # Channel volumes are balance multipliers, separate from the
                # session's normal master volume. Set them absolutely so a crash
                # and restart can never compound an already-reduced channel.
                channels.SetChannelVolume(0, gains[0], None)
                channels.SetChannelVolume(1, gains[1], None)
                self._touched.add(session.InstanceIdentifier)
                routed.append(
                    RoutedApp(name, session.ProcessId, title, position, *gains)
                )
            except (OSError, RuntimeError):
                log.debug("Audio session disappeared while updating", exc_info=True)

        return sorted(routed, key=lambda app: (app.name.casefold(), app.pid))

    def restore(self) -> None:
        """Return every session changed by this router to neutral balance."""
        if not self._touched:
            return

        if set_neutral_balance(self._touched):
            self._touched.clear()

    def repair_stale_balances(self) -> None:
        """Centre active sessions in case a previous run was force-terminated."""
        set_neutral_balance()
