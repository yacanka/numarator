"""Guarded Windows job ownership and native process-tree regressions."""

from __future__ import annotations

import ctypes
import io
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts.launcher import process, windows_child, windows_process
from scripts.launcher.model import LauncherError


class FakeChild:
    pid = 123

    def __init__(self):
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = 1

    def wait(self, timeout=None):
        return self.returncode


class FakeWindowsAPI:
    def __init__(self):
        self.actions = []
        self.open_handles = set()
        self.failure = None

    def create_job(self):
        self.actions.append("create-job")
        self.open_handles.add(10)
        return 10

    def create_gate(self):
        self.actions.append("create-gate")
        self.open_handles.add(20)
        return 20

    def assign(self, job, pid):
        self.actions.append(("assign", job, pid))
        if self.failure == "assign":
            raise OSError("assignment denied")

    def release(self, gate):
        self.actions.append(("release", gate))
        if self.failure == "release":
            raise OSError("event release failed")

    def close(self, handle):
        self.actions.append(("close", handle))
        self.open_handles.remove(handle)


class WindowsOwnershipTests(unittest.TestCase):
    def launch(self, api, child):
        def spawn(command, **kwargs):
            api.actions.append("spawn-helper")
            self.assertEqual(command[:3], [sys.executable, "-I", "-S"])
            self.assertEqual(command[-2:], ["20", "target.exe"])
            self.assertEqual(kwargs["startupinfo"].lpAttributeList, {"handle_list": [20]})
            self.assertTrue(kwargs["close_fds"])
            return child

        with mock.patch.object(windows_process, "WindowsAPI", return_value=api), \
                mock.patch.object(windows_process.os, "set_handle_inheritable", create=True), \
                mock.patch.object(windows_process.subprocess, "STARTUPINFO", SimpleNamespace, create=True), \
                mock.patch.object(windows_process.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, create=True), \
                mock.patch.object(windows_process.subprocess, "Popen", side_effect=spawn):
            return windows_process.start(["target.exe"], Path.cwd(), env={})

    def test_target_release_follows_assignment_and_only_job_stays_owned(self):
        api, child = FakeWindowsAPI(), FakeChild()
        self.assertIs(self.launch(api, child), child)
        self.assertEqual(api.actions, ["create-job", "create-gate", "spawn-helper",
                                      ("assign", 10, 123), ("release", 20), ("close", 20)])
        self.assertEqual(api.open_handles, {10})
        child.returncode = 0
        self.assertTrue(windows_process.close_job(child))
        self.assertEqual(api.open_handles, set())
        windows_process.close_job(child)
        self.assertEqual(api.actions.count(("close", 10)), 1)

    def test_assignment_failure_never_releases_target_and_closes_handles(self):
        api, child = FakeWindowsAPI(), FakeChild()
        api.failure = "assign"
        with self.assertRaisesRegex(LauncherError, "Windows.*job"):
            self.launch(api, child)
        self.assertTrue(child.killed)
        self.assertNotIn(("release", 20), api.actions)
        self.assertEqual(api.open_handles, set())

    def test_release_failure_kills_guarded_helper_and_closes_handles(self):
        api, child = FakeWindowsAPI(), FakeChild()
        api.failure = "release"
        with self.assertRaisesRegex(LauncherError, "Windows.*job"):
            self.launch(api, child)
        self.assertTrue(child.killed)
        self.assertEqual(api.open_handles, set())

    def test_windows_cleanup_closes_job_after_group_leader_has_exited(self):
        api, child = FakeWindowsAPI(), FakeChild()
        self.launch(api, child)
        child.returncode = 0
        with mock.patch.object(process.os, "name", "nt"):
            process.terminate([child], process_groups=True)
        self.assertEqual(api.open_handles, set())


class WindowsBootstrapTests(unittest.TestCase):
    def run_helper(self, wait_result):
        kernel = SimpleNamespace(
            WaitForSingleObject=mock.Mock(return_value=wait_result),
            CloseHandle=mock.Mock(return_value=1),
        )

        def target(command, **kwargs):
            self.assertEqual(command, ["target.exe", "--argument"])
            self.assertTrue(kwargs["close_fds"])
            kernel.CloseHandle.assert_called_once_with(20)
            return 7

        with mock.patch.object(windows_child.os, "name", "nt"), \
                mock.patch.object(windows_child.sys, "argv", ["bootstrap", "20", "target.exe", "--argument"]), \
                mock.patch.object(windows_child.ctypes, "WinDLL", return_value=kernel, create=True), \
                mock.patch.object(windows_child.signal, "SIGBREAK", 21, create=True), \
                mock.patch.object(windows_child.signal, "signal"), \
                mock.patch.object(windows_child.subprocess, "call", side_effect=target) as call, \
                mock.patch.object(windows_child.sys, "stderr", io.StringIO()):
            result = windows_child.main()
        kernel.WaitForSingleObject.assert_called_once_with(20, 30000)
        kernel.CloseHandle.assert_called_once_with(20)
        return result, call.call_count

    def test_helper_closes_gate_before_starting_target_and_preserves_exit_status(self):
        self.assertEqual(self.run_helper(0), (7, 1))

    def test_expired_or_failed_gate_never_starts_target(self):
        for result in (0x102, 0xFFFFFFFF):
            with self.subTest(result=result):
                self.assertEqual(self.run_helper(result), (125, 0))


@unittest.skipUnless(os.name == "nt", "requires real Windows Job Object APIs")
class NativeWindowsOwnershipTests(unittest.TestCase):
    def wait_for_file(self, path):
        deadline = time.monotonic() + 10
        while not path.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(path.is_file(), "child did not initialize")

    def test_descendant_ignoring_ctrl_break_dies_after_parent_exits_first(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            marker = directory / "descendant.pid"
            child_code = (
                "import os, signal, time; from pathlib import Path; "
                "signal.signal(signal.SIGBREAK, signal.SIG_IGN); "
                f"Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)"
            )
            parent_code = f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {child_code!r}])"
            with redirect_stdout(io.StringIO()):
                parent = process.start([sys.executable, "-c", parent_code], directory, process_group=True)
            descendant = None
            try:
                self.wait_for_file(marker)
                descendant = kernel.OpenProcess(0x00100000 | 0x0001, False, int(marker.read_text()))
                self.assertTrue(descendant, "could not observe descendant")
                self.assertEqual(parent.wait(timeout=10), 0)
                self.assertEqual(kernel.WaitForSingleObject(descendant, 0), 0x102)
                process.terminate([parent], process_groups=True)
                self.assertEqual(kernel.WaitForSingleObject(descendant, 5000), 0,
                                 "descendant survived launcher cleanup")
            finally:
                windows_process.close_job(parent)
                if descendant:
                    kernel.TerminateProcess(descendant, 1)
                    kernel.CloseHandle(descendant)
                parent.wait(timeout=10)

    def test_helper_cannot_run_target_before_job_assignment(self):
        original = windows_process.WindowsAPI.assign
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            marker = directory / "target-started"

            def delayed_assignment(api, job, pid):
                time.sleep(0.2)
                self.assertFalse(marker.exists(), "target ran before job assignment")
                original(api, job, pid)

            code = f"from pathlib import Path; Path({str(marker)!r}).touch()"
            with mock.patch.object(windows_process.WindowsAPI, "assign", autospec=True,
                                   side_effect=delayed_assignment), redirect_stdout(io.StringIO()):
                parent = process.start([sys.executable, "-c", code], directory, process_group=True)
            try:
                self.assertEqual(parent.wait(timeout=10), 0)
                self.assertTrue(marker.is_file())
            finally:
                windows_process.close_job(parent)
                parent.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
