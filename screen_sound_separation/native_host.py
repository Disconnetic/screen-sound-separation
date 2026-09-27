"""Chrome native-messaging host for the desktop browser bridge."""

from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Any

from .browser import BRIDGE_HOST, BRIDGE_PORT


MAX_MESSAGE_SIZE = 1024 * 1024


def _log(message: str) -> None:
    """Write diagnostics to a file without corrupting Chrome's stdout protocol."""
    try:
        data_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ScreenSoundSeparation"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / "native-host.log"
        if log_path.exists() and log_path.stat().st_size > 200_000:
            log_path.write_text("", encoding="utf-8")
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(f"{timestamp} {message}\n")
    except OSError:
        pass


def read_native_message(stream: BinaryIO) -> dict[str, Any] | None:
    """Read one Chrome native-messaging frame from a binary stream."""

    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise EOFError("Incomplete native-messaging header")
    (size,) = struct.unpack("<I", header)
    if size > MAX_MESSAGE_SIZE:
        raise ValueError("Native message exceeds the 1 MiB host limit")
    payload = stream.read(size)
    if len(payload) != size:
        raise EOFError("Incomplete native-messaging payload")
    message = json.loads(payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("Native messages must be JSON objects")
    return message


def write_native_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    """Write one Chrome native-messaging frame to a binary stream."""

    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    stream.write(struct.pack("<I", len(payload)))
    stream.write(payload)
    stream.flush()


def _binary_stdio() -> tuple[BinaryIO, BinaryIO]:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    if os.name == "nt":
        import msvcrt

        msvcrt.setmode(stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(stdout.fileno(), os.O_BINARY)
    return stdin, stdout


def _launch_desktop() -> bool:
    """Launch the last registered desktop executable for a user-requested tab."""
    config_path = (
        Path(os.environ.get("LOCALAPPDATA", Path.home()))
        / "ScreenSoundSeparation"
        / "desktop-launch.json"
    )
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        executable = Path(config["executable"])
        arguments = [str(value) for value in config.get("arguments", [])]
        working_directory = Path(config.get("working_directory") or executable.parent)
        if not executable.is_file() or not working_directory.is_dir():
            raise FileNotFoundError("The registered desktop command is no longer available.")
        subprocess.Popen(
            [str(executable), *arguments],
            cwd=str(working_directory),
            close_fds=True,
        )
        _log(f"desktop launch requested: {executable}")
        return True
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _log(f"desktop launch failed: {exc!r}")
        return False


def _connect_to_desktop(launch_if_needed: bool) -> socket.socket | None:
    try:
        connection = socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=0.75)
        connection.settimeout(None)
        return connection
    except OSError as first_error:
        if not launch_if_needed or not _launch_desktop():
            _log(f"desktop connection failed: {first_error!r}")
            return None

    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        try:
            connection = socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=0.5)
            connection.settimeout(None)
            return connection
        except OSError:
            time.sleep(0.2)
    _log("desktop did not start before the connection deadline")
    return None


def run() -> int:
    _log("host starting")
    stdin, stdout = _binary_stdio()
    output_lock = threading.Lock()

    # Every connection begins with an extension hello. Background reconnects
    # never launch the GUI; a toolbar click explicitly opts into doing so.
    try:
        hello = read_native_message(stdin)
    except (EOFError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        _log(f"invalid extension hello: {exc!r}")
        return 1
    launch_if_needed = bool(hello and hello.get("launchIfNeeded"))
    connection = _connect_to_desktop(launch_if_needed)
    if connection is None:
        return 1
    _log("connected to desktop")

    def desktop_to_extension() -> None:
        try:
            with connection.makefile("rb") as stream:
                while line := stream.readline():
                    message = json.loads(line.decode("utf-8"))
                    if isinstance(message, dict):
                        with output_lock:
                            write_native_message(stdout, message)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            _log(f"desktop reader stopped: {exc!r}")
        finally:
            # Closing the connection makes the main loop fail promptly when the
            # desktop app exits. This process exists only for this Chrome port,
            # so ending it is the reliable way to trigger the extension's
            # fail-safe disconnect handler while stdin is blocked.
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            _log("desktop connection closed")
            os._exit(0)

    threading.Thread(target=desktop_to_extension, name="desktop-reader", daemon=True).start()
    try:
        while True:
            message = read_native_message(stdin)
            if message is None:
                break
            payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
            connection.sendall(payload)
    except (OSError, EOFError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        _log(f"Chrome reader stopped: {exc!r}")
        return 1
    finally:
        connection.close()
        _log("host stopped")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
