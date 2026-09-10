"""Owned interactive PTYs. Raw terminal data stays in bounded process memory."""

from __future__ import annotations

import codecs
import os
import signal
import socket
import subprocess
import sys
import threading
from collections import OrderedDict

from src.ticket_connectors import TicketError


class _WindowsJob:
    """Kernel-owned child tree; closing the API process also closes this handle."""

    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        for name, args, result in (
            ("CreateJobObjectW", [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            ("SetInformationJobObject", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            ("OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            ("AssignProcessToJobObject", [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
        ):
            fn = getattr(kernel, name)
            fn.argtypes, fn.restype = args, result
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        process = None
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            process = kernel.OpenProcess(0x0100 | 0x0001, False, pid)
            if not process or not kernel.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise
        finally:
            if process:
                kernel.CloseHandle(process)

    def close(self):
        if self.handle:
            if not self.kernel.CloseHandle(self.handle):
                import ctypes
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = None


class TerminalBuffer:
    def __init__(self, maximum=512 * 1024, chunk_size=64 * 1024):
        self.maximum = maximum
        self.chunk_size = chunk_size
        self.text = ""
        self.end = 0
        self.lock = threading.RLock()

    def append(self, text):
        with self.lock:
            self.end += len(text)
            self.text = (self.text + text)[-self.maximum:]

    def read(self, cursor):
        if type(cursor) is not int or cursor < 0:
            raise TicketError("Terminal cursor must be a nonnegative integer.")
        with self.lock:
            start = self.end - len(self.text)
            reset = cursor < start or cursor > self.end
            notice = "\r\n[Earlier terminal output is unavailable; showing retained output.]\r\n" if reset else ""
            offset = start if reset else cursor
            budget = max(1, self.chunk_size - len(notice.encode("utf-8")))
            text = self.text[offset - start:offset - start + budget]
            text = text.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
            return {"output": notice + text, "next_cursor": offset + len(text), "reset": reset}


class OwnedPty:
    """Launch exactly argv, never an interactive parent shell."""

    @staticmethod
    def available():
        if sys.platform == "win32":
            try:
                from winpty import PtyProcess, Backend
                return sys.getwindowsversion().build >= 17763 and PtyProcess is not None and hasattr(Backend, "ConPTY")
            except (ImportError, AttributeError):
                return False
        return os.name == "posix" and not getattr(sys, "frozen", False)

    def __init__(self, argv, cwd, env, columns=120, rows=30):
        self.lock = threading.RLock()
        self.closed = False
        self.job = None
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        if sys.platform == "win32":
            from winpty import PtyProcess, Backend
            self.process = PtyProcess.spawn(
                argv, cwd=cwd, env=env, dimensions=(rows, columns), backend=str(int(Backend.ConPTY)),
            )
            try:
                self.job = _WindowsJob(self.process.pid)
            except BaseException:
                self.process.close(force=True)
                raise
            self.process.fileobj.settimeout(.25)
            self.fd = None
        else:
            import fcntl
            import pty
            import struct
            import termios
            master, slave = pty.openpty()
            try:
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
                bootstrap = (
                    "import os,sys,fcntl,termios;"
                    "fcntl.ioctl(0,termios.TIOCSCTTY,0);"
                    "os.execvpe(sys.argv[1],sys.argv[1:],os.environ)"
                )
                self.process = subprocess.Popen(
                    [sys.executable, "-c", bootstrap, *argv], cwd=cwd, env=env, shell=False, stdin=slave, stdout=slave,
                    stderr=slave, start_new_session=True,
                )
                self.fd = master
            except BaseException:
                os.close(master)
                raise
            finally:
                os.close(slave)

    def read(self):
        if sys.platform == "win32":
            while True:
                try:
                    raw = self.process.fileobj.recv(16384)
                except socket.timeout:
                    if self.alive():
                        continue
                    raw = b""
                except OSError:
                    if not self.closed:
                        raise
                    raw = b""
                if raw == b"0011Ignore":
                    continue
                text = self.decoder.decode(raw, final=not raw)
                if text or not raw:
                    return text
        try:
            import select
            while not select.select([self.fd], [], [], .25)[0]:
                if not self.alive():
                    return self.decoder.decode(b"", final=True)
            raw = os.read(self.fd, 16384)
        except OSError as exc:
            if exc.errno != 5 and not self.closed:
                raise
            raw = b""
        return self.decoder.decode(raw, final=not raw)

    def alive(self):
        return self.process.isalive() if sys.platform == "win32" else self.process.poll() is None

    def write(self, data):
        with self.lock:
            if self.closed or not self.alive():
                raise TicketError("The deployment terminal is no longer accepting input.", 409)
            if sys.platform == "win32":
                self.process.write(data)
            else:
                raw = data.encode("utf-8")
                while raw:
                    raw = raw[os.write(self.fd, raw):]

    def resize(self, columns, rows):
        with self.lock:
            if self.closed or not self.alive():
                raise TicketError("The deployment terminal is closed.", 409)
            if sys.platform == "win32":
                self.process.setwinsize(rows, columns)
            else:
                import fcntl
                import struct
                import termios
                fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))

    def wait(self):
        if sys.platform == "win32":
            return self.process.wait()
        return self.process.wait()

    def close(self):
        with self.lock:
            if self.closed:
                return
            if sys.platform == "win32":
                self.job.close()
                self.process.close(force=True)
            else:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if self.fd >= 0:
                    os.close(self.fd)
                    self.fd = -1
                self.process.wait(timeout=5)
            self.closed = True


class TerminalSessions:
    def __init__(self, retained=8, maximum=512 * 1024):
        self.retained = retained
        self.maximum = maximum
        self.sessions = OrderedDict()
        self.lock = threading.RLock()

    def create(self, job_id):
        with self.lock:
            for key in list(self.sessions):
                if len(self.sessions) < self.retained:
                    break
                if self.sessions[key]["complete"]:
                    del self.sessions[key]
            if len(self.sessions) >= self.retained:
                raise TicketError("All interactive deployment terminal slots are in use.", 409)
            session = {"buffer": TerminalBuffer(self.maximum), "pty": None, "accepting": False, "complete": False}
            self.sessions[job_id] = session
            return session

    def get(self, job_id):
        with self.lock:
            return self.sessions.get(job_id)

    def shutdown(self):
        with self.lock:
            sessions = list(self.sessions.values())
        failures = []
        for session in sessions:
            session["accepting"] = False
            if session["pty"] is not None:
                try:
                    session["pty"].close()
                except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                    session["buffer"].append(f"\r\n[terminal cleanup] {type(exc).__name__}: owned child cleanup failed; verify before reconciliation.\r\n")
                    failures.append(type(exc).__name__)
        if failures:
            raise RuntimeError(f"Owned terminal cleanup failed for {len(failures)} session(s); inspect their local terminal notices.")
