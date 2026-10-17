"""Independent audio-routing lease and crash recovery guardian."""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import BinaryIO


log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_MS = 250
LEASE_TIMEOUT_SECONDS = 1.5

ACTIVE = b"ACTIVE\n"
IDLE = b"IDLE\n"
RESTORE = b"RESTORE\n"
EXIT = b"EXIT\n"


def _restore_audio() -> None:
    from .audio import set_neutral_balance

    set_neutral_balance()


def run_guardian(
    stream: BinaryIO,
    restore_audio: Callable[[], None] = _restore_audio,
    *,
    timeout: float = LEASE_TIMEOUT_SECONDS,
) -> int:
    """Restore neutral balance whenever the desktop's active lease disappears."""
    commands: queue.Queue[bytes | None] = queue.Queue()

    def read_commands() -> None:
        try:
            while line := stream.readline():
                commands.put(line.strip().upper())
        finally:
            commands.put(None)

    threading.Thread(target=read_commands, name="failsafe-input", daemon=True).start()
    active = False
    deadline = 0.0

    while True:
        wait = max(0.0, deadline - time.monotonic()) if active else None
        try:
            command = commands.get(timeout=wait)
        except queue.Empty:
            restore_audio()
            active = False
            continue

        if command is None:
            if active:
                restore_audio()
            return 0
        if command == ACTIVE.strip():
            active = True
            deadline = time.monotonic() + timeout
        elif command == IDLE.strip():
            if active:
                restore_audio()
            active = False
        elif command == RESTORE.strip():
            restore_audio()
            active = False
        elif command == EXIT.strip():
            if active:
                restore_audio()
            return 0


def run() -> int:
    stream = sys.stdin.buffer
    if os.name == "nt":
        import msvcrt

        msvcrt.setmode(stream.fileno(), os.O_BINARY)
    return run_guardian(stream)


class AudioFailsafeLease:
    """Keep routing leased to a separate process with a short heartbeat."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def available(self) -> bool:
        return self._process is not None and self._process.poll() is None and self._process.stdin is not None

    def start(self) -> bool:
        if self.available:
            return True
        command = (
            [sys.executable, "--audio-failsafe"]
            if getattr(sys, "frozen", False)
            else [sys.executable, "-m", "screen_sound_separation.failsafe"]
        )
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            return self.available
        except OSError:
            log.exception("Could not start the audio safety guardian")
            self._process = None
            return False

    def _send(self, command: bytes) -> bool:
        if not self.available or self._process is None or self._process.stdin is None:
            return False
        try:
            self._process.stdin.write(command)
            self._process.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            log.exception("Lost the audio safety guardian")
            return False

    def pulse(self) -> bool:
        return self._send(ACTIVE)

    def idle(self) -> bool:
        return self._send(IDLE)

    def restore(self) -> bool:
        return self._send(RESTORE)

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.poll() is None and process.stdin is not None:
                process.stdin.write(EXIT)
                process.stdin.flush()
                process.stdin.close()
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
            log.debug("Safety guardian had to be terminated", exc_info=True)
        except (BrokenPipeError, OSError, ValueError):
            log.debug("Safety guardian did not exit cleanly", exc_info=True)


if __name__ == "__main__":
    raise SystemExit(run())
