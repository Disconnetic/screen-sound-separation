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


class AudioRouter:
    """Apply and restore per-session stereo channel gains."""

    def __init__(self) -> None:
        self._original: dict[str, tuple[float, float]] = {}
        self._excluded: set[str] = set()

    @property
    def excluded(self) -> set[str]:
        return set(self._excluded)

    def set_excluded(self, process_names: set[str]) -> None:
        self._excluded = {name.casefold() for name in process_names}

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

                key = session.InstanceIdentifier
                if key not in self._original:
                    self._original[key] = (
                        channels.GetChannelVolume(0),
                        channels.GetChannelVolume(1),
                    )
                original_left, original_right = self._original[key]

                if window is None or name.casefold() in self._excluded:
                    gains = (1.0, 1.0)
                    title = "No visible window" if window is None else window.title
                    position = 0.0
                else:
                    position = monitor_position(window, monitors)
                    gains = channel_gains(position, separation)
                    title = window.title

                channels.SetChannelVolume(0, original_left * gains[0], None)
                channels.SetChannelVolume(1, original_right * gains[1], None)
                routed.append(
                    RoutedApp(name, session.ProcessId, title, position, *gains)
                )
            except (OSError, RuntimeError):
                log.debug("Audio session disappeared while updating", exc_info=True)

        return sorted(routed, key=lambda app: (app.name.casefold(), app.pid))

    def restore(self) -> None:
        """Restore channel volumes captured before routing started."""
        for session in AudioUtilities.GetAllSessions():
            original = self._original.get(session.InstanceIdentifier)
            if original is None:
                continue
            try:
                channels = session.channelAudioVolume()
                if channels.GetChannelCount() >= 2:
                    channels.SetChannelVolume(0, original[0], None)
                    channels.SetChannelVolume(1, original[1], None)
            except (OSError, RuntimeError):
                log.debug("Audio session disappeared while restoring", exc_info=True)
        self._original.clear()
