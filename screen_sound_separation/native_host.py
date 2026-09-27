"""Chrome native-messaging host for the desktop browser bridge."""

from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
from typing import BinaryIO, Any

from .browser import BRIDGE_HOST, BRIDGE_PORT


MAX_MESSAGE_SIZE = 1024 * 1024


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


def run() -> int:
    stdin, stdout = _binary_stdio()
    output_lock = threading.Lock()
    try:
        connection = socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=2.0)
    except OSError:
        return 1

    def desktop_to_extension() -> None:
        try:
            with connection.makefile("rb") as stream:
                while line := stream.readline():
                    message = json.loads(line.decode("utf-8"))
                    if isinstance(message, dict):
                        with output_lock:
                            write_native_message(stdout, message)
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
        finally:
            # Closing the connection makes the main loop fail promptly when the
            # desktop app exits. This process exists only for this Chrome port,
            # so ending it is the reliable way to trigger the extension's
            # fail-safe disconnect handler while stdin is blocked.
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            os._exit(0)

    threading.Thread(target=desktop_to_extension, name="desktop-reader", daemon=True).start()
    try:
        while True:
            message = read_native_message(stdin)
            if message is None:
                break
            payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
            connection.sendall(payload)
    except (OSError, EOFError, ValueError, UnicodeError, json.JSONDecodeError):
        return 1
    finally:
        connection.close()
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
