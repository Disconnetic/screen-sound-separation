"""Local bridge between the desktop UI and the browser extension."""

from __future__ import annotations

import json
import hashlib
import os
import queue
import shutil
import socket
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HOST_NAME = "com.thatoneguybanks.screen_sound_separation.browser"
DEV_EXTENSION_ID = "mbahplfohkgngffhkaokaaipbicpfcho"
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 43821
BROWSER_PROCESSES = {"chrome.exe"}
CHROME_WEB_STORE_URL: str | None = None


def _data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ScreenSoundSeparation"


def _remove_stale_native_hosts(data_dir: Path, current_host: Path) -> None:
    """Remove superseded packaged host binaries while keeping the active one.

    Packaged hosts use a content hash in their filename so upgrades can replace
    a helper that Chrome still has open. Once the new file exists, older hashes
    are no longer referenced and can be removed. A locked helper is harmless;
    leave it for a later launch instead of failing browser setup.
    """
    for candidate in data_dir.glob("native-host-*.exe"):
        if candidate == current_host:
            continue
        try:
            candidate.unlink()
        except OSError:
            pass


@dataclass(frozen=True)
class BrowserTab:
    """A browser tab currently managed by the extension."""

    tab_id: int
    title: str
    side: str
    pan: float


def install_native_host() -> Path:
    """Install and register Chrome's per-user native host.

    A packaged build contains a dedicated helper executable. During development,
    a quiet command wrapper starts this module with the project's console Python.
    """

    if os.name != "nt":
        raise OSError("Browser integration is currently available on Windows only.")

    import winreg

    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS"))
        bundled_host = bundle_root / "native-host" / "ScreenSoundSeparationNativeHost.exe"
        if not bundled_host.exists():
            raise FileNotFoundError(f"Bundled native host not found: {bundled_host}")
        digest = hashlib.sha256(bundled_host.read_bytes()).hexdigest()[:12]
        host_path = data_dir / f"native-host-{digest}.exe"
        if not host_path.exists():
            shutil.copy2(bundled_host, host_path)
        _remove_stale_native_hosts(data_dir, host_path)
        desktop_command = {
            "executable": str(Path(sys.executable)),
            "arguments": [],
            "working_directory": str(Path(sys.executable).parent),
        }
    else:
        project_root = Path(__file__).resolve().parents[1]
        host_path = data_dir / "native-host.cmd"
        python = Path(sys.executable)
        if python.name.casefold() == "pythonw.exe":
            python = python.with_name("python.exe")
        wrapper = (
            "@echo off\r\n"
            f'cd /d "{project_root}"\r\n'
            f'"{python}" -m screen_sound_separation.native_host\r\n'
        )
        if not host_path.exists() or host_path.read_text(encoding="utf-8") != wrapper:
            host_path.write_text(wrapper, encoding="utf-8", newline="")
        pythonw = python.with_name("pythonw.exe")
        desktop_command = {
            "executable": str(pythonw if pythonw.exists() else python),
            "arguments": ["-m", "screen_sound_separation.app"],
            "working_directory": str(project_root),
        }

    # The native helper uses this only after an explicit extension-button click.
    # Merely starting Chrome never launches the desktop app.
    launch_path = data_dir / "desktop-launch.json"
    launch_text = json.dumps(desktop_command, indent=2) + "\n"
    if not launch_path.exists() or launch_path.read_text(encoding="utf-8") != launch_text:
        launch_path.write_text(launch_text, encoding="utf-8")

    manifest_path = data_dir / "native-messaging-host.json"
    manifest = {
        "name": HOST_NAME,
        "description": "Screen Sound Separation browser bridge",
        "path": str(host_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{DEV_EXTENSION_ID}/"],
    }
    manifest_text = json.dumps(manifest, indent=2) + "\n"
    if not manifest_path.exists() or manifest_path.read_text(encoding="utf-8") != manifest_text:
        manifest_path.write_text(manifest_text, encoding="utf-8")

    key_path = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
    return manifest_path


def prepare_extension_files() -> Path:
    """Return a persistent folder Chrome can use for the bundled extension."""

    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[1] / "browser_extension"

    source = Path(getattr(sys, "_MEIPASS")) / "browser_extension"
    if not source.exists():
        raise FileNotFoundError(f"Bundled browser extension not found: {source}")
    destination = _data_dir() / "browser-extension"
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return destination


class BrowserBridge:
    """Exchange newline-delimited JSON with Chrome's native-host process."""

    def __init__(self, host: str = BRIDGE_HOST, port: int = BRIDGE_PORT) -> None:
        self.host = host
        self.port = port
        self._server: socket.socket | None = None
        self._clients: set[socket.socket] = set()
        self._clients_lock = threading.Lock()
        self._events: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        self._enabled = False
        self._separation = 0.75

    @property
    def connected(self) -> bool:
        with self._clients_lock:
            return bool(self._clients)

    def start(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        self.port = server.getsockname()[1]
        server.listen()
        server.settimeout(0.25)
        self._server = server
        threading.Thread(target=self._accept_loop, name="browser-bridge", daemon=True).start()

    def _accept_loop(self) -> None:
        while self._server is not None:
            try:
                client, _address = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._clients_lock:
                self._clients.add(client)
            self._events.put({"type": "connected"})
            self._send_to(client, self._state_message())
            threading.Thread(
                target=self._read_client,
                args=(client,),
                name="browser-client",
                daemon=True,
            ).start()

    def _read_client(self, client: socket.socket) -> None:
        try:
            with client.makefile("rb") as stream:
                while line := stream.readline():
                    message = json.loads(line.decode("utf-8"))
                    if isinstance(message, dict):
                        self._events.put(message)
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
        finally:
            with self._clients_lock:
                self._clients.discard(client)
                still_connected = bool(self._clients)
            try:
                client.close()
            except OSError:
                pass
            if not still_connected:
                self._events.put({"type": "disconnected"})

    def _state_message(self) -> dict[str, Any]:
        return {
            "type": "state",
            "enabled": self._enabled,
            "separation": self._separation,
        }

    @staticmethod
    def _send_to(client: socket.socket, message: dict[str, Any]) -> bool:
        try:
            payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
            client.sendall(payload)
            return True
        except OSError:
            return False

    def _broadcast(self, message: dict[str, Any]) -> None:
        with self._clients_lock:
            clients = list(self._clients)
        dead = [client for client in clients if not self._send_to(client, message)]
        if dead:
            with self._clients_lock:
                for client in dead:
                    self._clients.discard(client)

    def update(self, enabled: bool, separation: float) -> None:
        self._enabled = enabled
        self._separation = max(0.0, min(1.0, separation))
        self._broadcast(self._state_message())

    def release_all(self) -> None:
        self._broadcast({"type": "release_all"})

    def set_tab_position(self, tab_id: int, position: float | None) -> None:
        """Set a tab's manual side, or return it to display-based detection."""
        self._broadcast({"type": "tab_position", "tabId": tab_id, "position": position})

    def poll_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def close(self) -> None:
        self.release_all()
        server, self._server = self._server, None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()
