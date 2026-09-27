"""Windows Core Audio session controller."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psutil
from pycaw.pycaw import AudioUtilities

from .routing import channel_gains
from .windows import WindowInfo, monitor_layout, monitor_position, visible_windows


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowOption:
    """A visible window that an audio session can follow."""

    handle: int
    title: str
    position: float


@dataclass(frozen=True)
class RoutedApp:
    session_id: str
    name: str
    pid: int
    title: str
    position: float
    left_gain: float
    right_gain: float
    selected_window: int | None
    window_options: tuple[WindowOption, ...]


class AudioRouter:
    """Apply and restore per-session stereo channel gains."""

    def __init__(self) -> None:
        self._original: dict[str, tuple[float, float]] = {}
        self._excluded: set[str] = set()
        self._window_overrides: dict[str, int] = {}

    @property
    def excluded(self) -> set[str]:
        return set(self._excluded)

    def set_excluded(self, process_names: set[str]) -> None:
        self._excluded = {name.casefold() for name in process_names}

    def set_window_override(self, session_id: str, window_handle: int) -> None:
        """Make one audio session follow a specific matching window."""
        self._window_overrides[session_id] = window_handle

    @staticmethod
    def _windows_for_session(
        process: psutil.Process, windows: list[WindowInfo]
    ) -> list[WindowInfo]:
        """Find all plausible UI windows for an audio process.

        Keeping every match is important for applications that own several
        titled windows with one process. The UI can then let the user choose the
        window that the shared audio session should follow.
        """
        direct = [window for window in windows if window.pid == process.pid]
        if direct:
            return direct

        # Chromium and similar apps put audio in a child process while the visible
        # window belongs to a parent with the same executable.
        try:
            process_name = process.name().casefold()
            for parent in process.parents():
                if parent.name().casefold() != process_name:
                    continue
                parent_windows = [window for window in windows if window.pid == parent.pid]
                if parent_windows:
                    return parent_windows
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        # Some app frameworks use sibling UI and audio processes. Match those by
        # executable name and favor the largest visible window.
        try:
            process_name = process.name().casefold()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []
        candidates: list[WindowInfo] = []
        for window in windows:
            try:
                if psutil.Process(window.pid).name().casefold() == process_name:
                    candidates.append(window)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return candidates

    def apply(self, separation: float) -> list[RoutedApp]:
        windows = visible_windows()
        monitors = monitor_layout()
        routed: list[RoutedApp] = []

        for session in AudioUtilities.GetAllSessions():
            process = session.Process
            if process is None or session.ProcessId == 0:
                continue
            try:
                name = process.name()
                candidates = self._windows_for_session(process, windows)
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

                option_by_handle = {window.handle: window for window in candidates}
                override = self._window_overrides.get(key)
                window = option_by_handle.get(override)
                if window is None:
                    window = max(candidates, key=lambda item: item.area, default=None)
                    if override is not None:
                        self._window_overrides.pop(key, None)

                options = tuple(
                    WindowOption(
                        candidate.handle,
                        candidate.title,
                        monitor_position(candidate, monitors),
                    )
                    for candidate in sorted(
                        candidates,
                        key=lambda item: (monitor_position(item, monitors), item.title.casefold()),
                    )
                )

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
                    RoutedApp(
                        key,
                        name,
                        session.ProcessId,
                        title,
                        position,
                        *gains,
                        window.handle if window is not None else None,
                        options,
                    )
                )
            except (OSError, RuntimeError):
                log.debug("Audio session disappeared while updating", exc_info=True)

        return sorted(routed, key=lambda app: (app.name.casefold(), app.pid))

    def restore(self) -> None:
        """Restore channel volumes captured before routing started."""
        if not self._original:
            return

        try:
            sessions = AudioUtilities.GetAllSessions()
        except (OSError, RuntimeError):
            # Keep the saved values so another shutdown fallback can retry if the
            # Windows audio service was only temporarily unavailable.
            log.warning("Could not enumerate audio sessions while restoring", exc_info=True)
            return

        for session in sessions:
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
