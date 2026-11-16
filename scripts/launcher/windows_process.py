"""Own Windows process trees with a gated, kill-on-close Job Object.

Only the startup event is inherited. The launcher retains the job handle so
cleanup remains effective after the bootstrap or target process exits.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import weakref
from pathlib import Path
from typing import Sequence

from .model import LauncherError


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IOCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class WindowsAPI:
    """Small typed boundary around the documented Kernel32 job/event APIs."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows process jobs require Windows")
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle, boolean, dword = ctypes.c_void_p, ctypes.c_int32, ctypes.c_uint32
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, ctypes.c_wchar_p], handle),
            "SetInformationJobObject": ([handle, ctypes.c_int, ctypes.c_void_p, dword], boolean),
            "CreateEventW": ([ctypes.c_void_p, boolean, boolean, ctypes.c_wchar_p], handle),
            "OpenProcess": ([dword, boolean, dword], handle),
            "AssignProcessToJobObject": ([handle, handle], boolean),
            "SetEvent": ([handle], boolean),
            "CloseHandle": ([handle], boolean),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self._kernel, name)
            function.argtypes = arguments
            function.restype = result

    def create_job(self) -> int:
        handle = self._kernel.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close(handle)
            raise error
        return handle

    def create_gate(self) -> int:
        handle = self._kernel.CreateEventW(None, True, False, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def assign(self, job: int, pid: int) -> None:
        # Open the documented process handle instead of relying on Popen._handle.
        process = self._kernel.OpenProcess(0x0100 | 0x0001, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self._kernel.AssignProcessToJobObject(job, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.close(process)

    def release(self, gate: int) -> None:
        if not self._kernel.SetEvent(gate):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self, handle: int) -> None:
        if not self._kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


class _Job:
    def __init__(self, api: WindowsAPI, handle: int) -> None:
        self.handle = handle
        self._finalizer = weakref.finalize(self, api.close, handle)

    def close(self) -> None:
        self._finalizer()


def start(command: Sequence[str], cwd: Path, *, env: dict[str, str]) -> subprocess.Popen:
    """Release a bootstrap only after Windows has assigned it to our job.

    A denied job assignment fails closed; targets are never started outside the
    owned job. This can occur under an incompatible enclosing Windows job.
    """
    job = None
    child = None
    try:
        api = WindowsAPI()
        job = _Job(api, api.create_job())
        gate = api.create_gate()
        try:
            os.set_handle_inheritable(gate, True)
            startup = subprocess.STARTUPINFO(lpAttributeList={"handle_list": [gate]})
            helper = Path(__file__).with_name("windows_child.py")
            child = subprocess.Popen(
                [sys.executable, "-I", "-S", str(helper), str(gate), *command],
                cwd=cwd, env=env, startupinfo=startup, close_fds=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            api.assign(job.handle, child.pid)
            child._launcher_job = job
            api.release(gate)
            return child
        finally:
            api.close(gate)
    except BaseException as error:
        try:
            if child is not None:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=5)
        finally:
            if job is not None:
                job.close()
        if isinstance(error, OSError):
            raise LauncherError(
                "Windows process job setup failed; run from a terminal that permits nested Job Objects "
                "and verify permission to create and manage child processes"
            ) from error
        raise


def close_job(process: subprocess.Popen) -> bool:
    """Close the launcher's job even when its original process already exited."""
    job = getattr(process, "_launcher_job", None)
    if job is None:
        return False
    job.close()
    return True
