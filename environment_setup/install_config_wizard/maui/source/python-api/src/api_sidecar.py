"""Windows entry point for the MAUI-owned FastAPI sidecar."""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import threading
from pathlib import Path

import uvicorn

from src.api import app


def parse_args():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--parent-pid", type=int)
    return parser.parse_args()


def _parent_kernel():
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def watch_parent(parent_pid):
    if parent_pid is None:
        return
    if type(parent_pid) is not int or not 0 < parent_pid <= 0xFFFFFFFF or parent_pid == os.getpid():
        raise SystemExit("A distinct, valid owning parent process is required.")
    if os.name != "nt":
        return
    kernel = _parent_kernel()
    synchronize = 0x00100000
    handle = kernel.OpenProcess(synchronize, False, parent_pid)
    if not handle:
        raise SystemExit("The owning parent process is unavailable.")
    if kernel.WaitForSingleObject(handle, 0) != 0x00000102:
        kernel.CloseHandle(handle)
        raise SystemExit("The owning parent process is unavailable.")

    def wait_for_exit():
        try:
            kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        finally:
            kernel.CloseHandle(handle)
        taskkill = Path(
            os.environ.get("SystemRoot", r"C:\Windows")
        ) / "System32" / "taskkill.exe"
        try:
            subprocess.Popen(
                [str(taskkill), "/PID", str(os.getpid()), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError:
            pass
        os._exit(0)

    threading.Thread(target=wait_for_exit, daemon=True).start()


def main():
    if sys.argv[1:2] == ["--catalog-worker"]:
        from src.catalog_worker import main as worker_main
        arguments = sys.argv[2:]
        if arguments in (["--help"], ["-h"]):
            return worker_main(arguments)
        owner_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
        owner_parser.add_argument("--parent-pid", type=int, required=True)
        owner, arguments = owner_parser.parse_known_args(arguments)
        watch_parent(owner.parent_pid)
        return worker_main(arguments)
    args = parse_args()
    if args.host != "127.0.0.1":
        raise SystemExit("The bundled API accepts loopback only.")
    if not 1024 <= args.port <= 65535:
        raise SystemExit("The API port must be between 1024 and 65535.")
    if not os.environ.get("AIFACTORY_API_KEY"):
        raise SystemExit("AIFACTORY_API_KEY is required.")
    watch_parent(args.parent_pid)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    raise SystemExit(main())
