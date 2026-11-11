"""Local process ownership for the PowerShell workflow; no Azure SDK calls."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


class ProcessIdentity:
    """Hold an OS handle while checking and terminating, never kill a bare PID."""

    def __init__(self, pid: int):
        self.pid = pid
        self.handle = None
        if os.name == "nt":
            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
            self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self.api.OpenProcess.restype = wintypes.HANDLE
            self.api.CloseHandle.argtypes = [wintypes.HANDLE]
            self.api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            self.api.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
            ]
            self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            self.handle = self.api.OpenProcess(0x1000 | 0x100000 | 0x0001, False, pid)
            if not self.handle:
                if ctypes.get_last_error() == 87:
                    raise ProcessLookupError(pid)
                raise OSError("Cannot verify process identity; no process was stopped.")
            try:
                if not self.alive():
                    raise ProcessLookupError(pid)
                created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
                if not self.api.GetProcessTimes(
                    self.handle, ctypes.byref(created), ctypes.byref(exited),
                    ctypes.byref(kernel), ctypes.byref(user)
                ):
                    raise OSError("Cannot read process creation time.")
                self.start_time = str((created.dwHighDateTime << 32) | created.dwLowDateTime)
                path = ctypes.create_unicode_buffer(32768)
                size = wintypes.DWORD(len(path))
                if not self.api.QueryFullProcessImageNameW(self.handle, 0, path, ctypes.byref(size)):
                    raise OSError("Cannot read process executable.")
                self.executable = path.value
            except BaseException:
                self.close()
                raise
        elif sys.platform.startswith("linux") and hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
            self.handle = os.pidfd_open(pid)
            try:
                stat = Path(f"/proc/{pid}/stat").read_text()
                self.start_time = stat[stat.rfind(")") + 2:].split()[19]
                self.executable = str(Path(f"/proc/{pid}/exe").resolve(strict=True))
                if not self.alive():
                    raise ProcessLookupError(pid)
            except BaseException:
                self.close()
                raise
        else:
            raise RuntimeError("Managed Start/Stop requires Windows or Linux with pidfd support.")

    def alive(self):
        if os.name == "nt":
            return self.api.WaitForSingleObject(self.handle, 0) == 0x102
        return not select.select([self.handle], [], [], 0)[0]

    def terminate(self):
        if not self.alive():
            return
        if os.name == "nt":
            if not self.api.TerminateProcess(self.handle, 0):
                raise OSError("The owned process could not be stopped.")
            if self.api.WaitForSingleObject(self.handle, 5000) != 0:
                raise RuntimeError("The owned process did not exit within five seconds.")
        else:
            signal.pidfd_send_signal(self.handle, signal.SIGTERM)
            if not select.select([self.handle], [], [], 5)[0]:
                signal.pidfd_send_signal(self.handle, signal.SIGKILL)
                if not select.select([self.handle], [], [], 5)[0]:
                    raise RuntimeError("The owned process did not exit.")

    def close(self):
        if self.handle is not None:
            if os.name == "nt":
                self.api.CloseHandle(self.handle)
            else:
                os.close(self.handle)
            self.handle = None


def same_path(left, right):
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


@contextmanager
def control_lock(runtime):
    runtime.mkdir(exist_ok=True)
    lock = runtime / "control.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("Another Start/Stop is active. If it crashed, inspect .runtime/control.lock before removing that stale lock.") from exc
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def load_record(path, root):
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if not same_path(record["root"], root):
            raise RuntimeError("Process record root does not match this template; refusing to stop anything.")
        if record["version"] != 1 or type(record["pid"]) is not int or record["pid"] <= 0:
            raise ValueError("invalid process record")
        for key in ("start_time", "executable", "env_file", "port"):
            if key not in record:
                raise ValueError("incomplete process record")
        return record
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Invalid process identity record; inspect it manually. No process was stopped.") from exc


def verified_process(record):
    try:
        process = ProcessIdentity(record["pid"])
    except (ProcessLookupError, FileNotFoundError):
        return None
    if process.start_time != record["start_time"] or not same_path(process.executable, record["executable"]):
        process.close()
        raise RuntimeError("Process identity mismatch (PID may have been reused); refusing to stop anything.")
    return process


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def healthy(port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as response:
            payload = json.loads(response.read(8192))
        return payload.get("status") == "ok" and payload.get("application") == "foundry-voice-sales"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def start(root, env_file, executable, port, startup_timeout=20):
    if os.name != "nt" and not (
        sys.platform.startswith("linux") and hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal")
    ):
        raise RuntimeError("Managed Start/Stop requires Windows or Linux with pidfd support.")
    runtime = root / ".runtime"
    record_path = runtime / "process.json"
    with control_lock(runtime):
        if record_path.exists():
            record = load_record(record_path, root)
            process = verified_process(record)
            if process is not None:
                try:
                    if record["port"] != port or not same_path(record["env_file"], env_file):
                        raise RuntimeError("An instance owns another port/configuration. Stop it explicitly before starting again.")
                    if not healthy(port) or not process.alive():
                        raise RuntimeError("The owned instance is not healthy. Use Stop, inspect local logs, then retry.")
                    print(f"Already running: http://127.0.0.1:{port}/ (PID {record['pid']}).")
                    return
                finally:
                    process.close()
            record_path.unlink()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"Local port {port} is in use; refusing to reuse or stop an unrelated server.") from exc

        arguments = [
            str(executable), "-m", "sales_agent", "--env-file", str(env_file),
            "serve", "--allow-azure", "--port", str(port),
        ]
        options = {"cwd": str(root), "stdin": subprocess.DEVNULL}
        if os.name == "nt":
            options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        child = None
        identity = None
        try:
            with (runtime / "server.stdout.log").open("ab") as out, (runtime / "server.stderr.log").open("ab") as err:
                child = subprocess.Popen(arguments, stdout=out, stderr=err, **options)
            identity = ProcessIdentity(child.pid)
            record = {
                "version": 1, "pid": child.pid, "start_time": identity.start_time,
                "root": str(root), "executable": identity.executable,
                "env_file": str(env_file), "port": port,
            }
            staging = runtime / "process.json.new"
            staging.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            staging.replace(record_path)
            deadline = time.monotonic() + startup_timeout
            while time.monotonic() < deadline:
                if child.poll() is not None or not identity.alive():
                    raise RuntimeError("The local server exited during startup; inspect .runtime/server.stderr.log.")
                if healthy(port):
                    time.sleep(0.15)
                    if child.poll() is None and identity.alive():
                        print(f"Healthy local server: http://127.0.0.1:{port}/ (PID {child.pid}).")
                        print("This health check proves local startup only, not Azure, Fabric, or microphone access.")
                        return
                time.sleep(0.15)
            raise RuntimeError("Local health check timed out; inspect .runtime/server.stderr.log.")
        except BaseException:
            if identity is not None:
                identity.terminate()
            elif child is not None and child.poll() is None:
                # Popen retains the Windows child handle, not an unverified recycled PID.
                if os.name == "nt":
                    child.terminate()
                    child.wait(timeout=5)
            record_path.unlink(missing_ok=True)
            (runtime / "process.json.new").unlink(missing_ok=True)
            raise
        finally:
            if identity is not None:
                identity.close()


def stop(root):
    runtime = root / ".runtime"
    with control_lock(runtime):
        path = runtime / "process.json"
        if not path.exists():
            print("No managed local instance. No process was stopped.")
            return
        record = load_record(path, root)
        process = verified_process(record)
        if process is not None:
            try:
                process.terminate()
            finally:
                process.close()
            print(f"Stopped owned local instance (PID {record['pid']}). No cloud changes.")
        else:
            print("Owned process already exited; removed stale local ownership record.")
        path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-azure", action="store_true")
    args = parser.parse_args()
    try:
        root = args.root.resolve(strict=True)
        if args.action == "stop":
            stop(root)
        else:
            if not args.allow_azure:
                parser.error("start requires --allow-azure; use the PowerShell workflow for guided startup")
            if not args.env_file or not args.python or not 1024 <= args.port <= 65535:
                parser.error("start requires --env-file, --python, and a port in 1024..65535")
            executable = args.python.absolute()
            if not executable.is_file():
                raise FileNotFoundError("The local virtual-environment interpreter is missing.")
            # Preserve a venv symlink: resolving it before invocation bypasses pyvenv.cfg.
            start(root, args.env_file.resolve(strict=True), executable, args.port)
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
