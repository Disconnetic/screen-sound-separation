import io
import os
import subprocess
import threading
import time

from screen_sound_separation import failsafe


def test_guardian_restores_active_lease_on_pipe_close() -> None:
    restores: list[str] = []

    result = failsafe.run_guardian(
        io.BytesIO(failsafe.ACTIVE),
        lambda: restores.append("restored"),
    )

    assert result == 0
    assert restores == ["restored"]


def test_guardian_restores_immediately_when_lease_goes_idle() -> None:
    restores: list[str] = []

    failsafe.run_guardian(
        io.BytesIO(failsafe.ACTIVE + failsafe.IDLE),
        lambda: restores.append("restored"),
    )

    assert restores == ["restored"]


def test_guardian_restore_command_is_safe_while_idle() -> None:
    restores: list[str] = []

    failsafe.run_guardian(
        io.BytesIO(failsafe.RESTORE + failsafe.EXIT),
        lambda: restores.append("restored"),
    )

    assert restores == ["restored"]


def test_guardian_restores_when_active_lease_times_out() -> None:
    restores: list[str] = []
    read_fd, write_fd = os.pipe()
    read_stream = os.fdopen(read_fd, "rb", buffering=0)
    write_stream = os.fdopen(write_fd, "wb", buffering=0)

    def send_commands() -> None:
        write_stream.write(failsafe.ACTIVE)
        time.sleep(0.03)
        write_stream.write(failsafe.EXIT)
        write_stream.close()

    writer = threading.Thread(target=send_commands)
    writer.start()

    try:
        failsafe.run_guardian(
            read_stream,
            lambda: restores.append("restored"),
            timeout=0.005,
        )
    finally:
        read_stream.close()
        writer.join(timeout=1)

    assert restores == ["restored"]


def test_lease_refuses_to_pulse_without_live_guardian() -> None:
    lease = failsafe.AudioFailsafeLease()
    lease._process = subprocess.Popen(
        ["cmd", "/c", "exit", "0"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    lease._process.wait(timeout=2)

    assert lease.pulse() is False
