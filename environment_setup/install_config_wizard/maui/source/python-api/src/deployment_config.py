"""Current-Windows-user encryption for immutable derived deployment configuration."""

import ctypes
import sys
from ctypes import wintypes


def protect(data):
    if sys.platform != "win32":
        raise ValueError("Derived deployment configuration requires Windows current-user DPAPI; export JSON explicitly on this platform.")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                                      ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptProtectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.c_void_p))
    result = Blob()
    if not crypt.CryptProtectData(ctypes.byref(source), "AI Factory reviewed deployment", None, None, None, 1, ctypes.byref(result)):
        raise ValueError("Current-user DPAPI protection is unavailable; no plaintext artifact was written.")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)
        ctypes.memset(buffer, 0, len(buffer))
