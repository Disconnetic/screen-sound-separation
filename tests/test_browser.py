import io
import json
import socket
import subprocess
import sys
import time

from screen_sound_separation.browser import BrowserBridge, _remove_stale_native_hosts
from screen_sound_separation.native_host import read_native_message, write_native_message


def wait_for(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Condition was not reached before the timeout")


def test_native_message_round_trip() -> None:
    stream = io.BytesIO()
    message = {"type": "state", "enabled": True, "separation": 0.75}
    write_native_message(stream, message)
    stream.seek(0)
    assert read_native_message(stream) == message


def test_native_message_rejects_incomplete_payload() -> None:
    stream = io.BytesIO(b"\x05\x00\x00\x00{}")
    try:
        read_native_message(stream)
    except EOFError:
        pass
    else:
        raise AssertionError("Incomplete messages must be rejected")


def test_stale_packaged_native_hosts_are_removed(tmp_path) -> None:
    current = tmp_path / "native-host-current.exe"
    stale = tmp_path / "native-host-stale.exe"
    unrelated = tmp_path / "native-host.cmd"
    current.write_bytes(b"current")
    stale.write_bytes(b"stale")
    unrelated.write_text("development helper", encoding="utf-8")

    _remove_stale_native_hosts(tmp_path, current)

    assert current.exists()
    assert not stale.exists()
    assert unrelated.exists()


def test_browser_bridge_sends_state_and_receives_status() -> None:
    bridge = BrowserBridge(port=0)
    bridge.update(True, 0.6)
    bridge.start()
    client = socket.create_connection((bridge.host, bridge.port), timeout=1.0)
    reader = client.makefile("rb")
    try:
        state = json.loads(reader.readline())
        assert state == {"type": "state", "enabled": True, "separation": 0.6}

        status = {"type": "tab_status", "tabId": 7, "captured": True}
        client.sendall(json.dumps(status).encode("utf-8") + b"\n")

        received = []

        def found_status() -> bool:
            received.extend(bridge.poll_events())
            return status in received

        wait_for(found_status)
        assert {"type": "connected"} in received
    finally:
        reader.close()
        client.close()
        bridge.close()


def test_native_host_forwards_messages_end_to_end() -> None:
    bridge = BrowserBridge(port=0)
    bridge.update(True, 0.4)
    bridge.start()
    # The native-host subprocess imports its port constant afresh, so pass the
    # test port through a tiny module invocation rather than touching Chrome.
    code = (
        "import screen_sound_separation.native_host as h;"
        f"h.BRIDGE_PORT={bridge.port};"
        "raise SystemExit(h.run())"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        # A pre-0.3 extension sends no hello. It must still connect when the
        # desktop app is already running so updating files never breaks audio.
        assert read_native_message(process.stdout) == {
            "type": "state",
            "enabled": True,
            "separation": 0.4,
        }
        status = {"type": "tab_status", "tabId": 12, "captured": True}
        write_native_message(process.stdin, status)

        received = []

        def found_status() -> bool:
            received.extend(bridge.poll_events())
            return status in received

        wait_for(found_status)
    finally:
        bridge.close()
        process.wait(timeout=2)
