"""Isolated Windows bootstrap; execute directly with Python -I -S."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys


def main() -> int:
    if os.name != "nt" or len(sys.argv) < 3:
        return 125
    gate = int(sys.argv[1])
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int32
    # Keep the bootstrap waiting while CTRL_BREAK is delivered to the target.
    signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    try:
        released = kernel.WaitForSingleObject(gate, 30000) == 0
    finally:
        kernel.CloseHandle(gate)
    if not released:
        print("Windows startup gate was not released; no service was started.", file=sys.stderr)
        return 125
    return subprocess.call(sys.argv[2:], close_fds=True)


if __name__ == "__main__":
    raise SystemExit(main())
