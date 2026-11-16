"""Runtime supervision and startup readiness regressions."""

from __future__ import annotations

import importlib.util
import io
import os
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from scripts.launcher import process, runtime
from scripts.launcher.model import LauncherError, Scope
from scripts.launcher.readiness import Readiness
from scripts.test_launcher import create_project


class ChildProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        return self.returncode


class SupervisionTests(unittest.TestCase):
    def test_readiness_deadline_stops_live_children(self):
        child = ChildProcess()
        elapsed = 0.0

        def advance(seconds):
            nonlocal elapsed
            elapsed += seconds

        with mock.patch.object(process.time, "monotonic", side_effect=lambda: elapsed), \
                mock.patch.object(process.time, "sleep", side_effect=advance):
            with self.assertRaisesRegex(LauncherError, "timed out"):
                process.supervise([child], ready=lambda: False, startup_timeout=0.5)

        self.assertTrue(child.terminated)
        self.assertEqual(elapsed, 0.5)

    @unittest.skipIf(os.name == "nt", "POSIX process-group integration")
    def test_group_cleanup_stops_descendants_after_their_parent_exits(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "child.pid"
            child_code = (
                "import os, signal, time; from pathlib import Path; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(60)"
            )
            parent_code = f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {child_code!r}])"
            parent = process.start([sys.executable, "-c", parent_code], Path(temporary), process_group=True)
            try:
                parent.wait(timeout=5)
                deadline = time.monotonic() + 5
                while not marker.is_file() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.is_file(), "descendant did not initialize")
                child_pid = int(marker.read_text())
                process.terminate([parent], process_groups=True)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    status = subprocess.run(
                        ["ps", "-p", str(child_pid), "-o", "stat="], capture_output=True, text=True,
                    ).stdout.strip()
                    if not status or status.startswith("Z"):
                        break
                    time.sleep(0.01)
                self.assertTrue(not status or status.startswith("Z"), "descendant survived group cleanup")
            finally:
                try:
                    os.killpg(parent.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                parent.wait(timeout=5)

    def test_successful_readiness_is_not_polled_again(self):
        child = ChildProcess()
        readiness_calls = 0
        sleeps = 0

        def ready():
            nonlocal readiness_calls
            readiness_calls += 1
            return True

        def advance(_seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 3:
                child.returncode = 9

        with mock.patch.object(process.time, "sleep", side_effect=advance):
            with self.assertRaisesRegex(LauncherError, "exited with code 9"):
                process.supervise([child], ready=ready)

        self.assertEqual(readiness_calls, 1)

    def test_readiness_exception_cleans_up_children(self):
        child = ChildProcess()

        def ready():
            raise LauncherError("invalid readiness configuration")

        with self.assertRaisesRegex(LauncherError, "invalid readiness configuration"):
            process.supervise([child], ready=ready)

        self.assertTrue(child.terminated)

    def test_readiness_after_deadline_is_still_a_startup_failure(self):
        child = ChildProcess()
        elapsed = 0.0

        def ready():
            nonlocal elapsed
            elapsed = 2.0
            return True

        with mock.patch.object(process.time, "monotonic", side_effect=lambda: elapsed), \
                mock.patch.object(process.time, "sleep", side_effect=KeyboardInterrupt):
            with self.assertRaisesRegex(LauncherError, "timed out"):
                process.supervise([child], ready=ready, startup_timeout=1.0)
        self.assertTrue(child.terminated)

    def test_keyboard_interrupt_cleans_up_children(self):
        child = ChildProcess()
        with mock.patch.object(process.time, "sleep", side_effect=KeyboardInterrupt), \
                redirect_stdout(io.StringIO()):
            process.supervise([child])
        self.assertTrue(child.terminated)


class DevelopmentCleanupTests(unittest.TestCase):
    def run_development(self, start):
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))
            with mock.patch.object(runtime, "require_runtime_ports"), \
                    mock.patch.object(runtime, "ensure_virtual_environment"), \
                    mock.patch.object(runtime, "required_tool", return_value="npm"), \
                    mock.patch.object(runtime, "start", side_effect=start), \
                    redirect_stdout(io.StringIO()):
                runtime.dev(project, Scope(), migrate=False, no_backend_reload=False)

    def test_frontend_launch_failure_stops_backend(self):
        child = ChildProcess()
        failure = OSError("frontend failed to launch")
        with mock.patch.object(runtime, "terminate") as terminate:
            with self.assertRaisesRegex(OSError, "frontend failed to launch"):
                self.run_development(mock.Mock(side_effect=[child, failure]))
        terminate.assert_called_once_with([child], process_groups=True)

    def test_interrupted_frontend_launch_stops_backend(self):
        child = ChildProcess()
        with mock.patch.object(runtime, "terminate") as terminate:
            with self.assertRaises(KeyboardInterrupt):
                self.run_development(mock.Mock(side_effect=[child, KeyboardInterrupt]))
        terminate.assert_called_once_with([child], process_groups=True)

    def test_supervisor_owns_cleanup_after_both_children_start(self):
        children = [ChildProcess(), ChildProcess()]
        with mock.patch.object(runtime, "supervise", side_effect=LauncherError("server exited")) as supervise, \
                mock.patch.object(runtime, "terminate") as terminate:
            with self.assertRaisesRegex(LauncherError, "server exited"):
                self.run_development(mock.Mock(side_effect=children))
        supervise.assert_called_once_with(children, process_groups=True)
        terminate.assert_not_called()


@contextmanager
def readiness_server(responses, *, tls=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            status, body, headers = responses.get(self.path, (404, b"", {}))
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(*tls)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    scheme = "https" if tls is not None else "http"
    try:
        yield f"{scheme}://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class ReadinessTests(unittest.TestCase):
    def responses(self, csrf=b'{"success": true}'):
        return {"/": (200, b"<html>ready</html>", {}),
                "/api/v1/auth/csrf/": (200, csrf, {"Content-Type": "application/json"})}

    def test_http_probes_both_endpoints_without_environment_proxy_and_opens_once(self):
        with readiness_server(self.responses()) as (url, requests), \
                mock.patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "no_proxy": ""}), \
                mock.patch("scripts.launcher.readiness.webbrowser.open") as browser, \
                redirect_stdout(io.StringIO()) as output:
            readiness = Readiness(url, url)
            self.assertTrue(readiness())
            self.assertTrue(readiness())
        self.assertEqual(requests, ["/", "/api/v1/auth/csrf/"])
        browser.assert_called_once_with(url)
        self.assertIn("ready", output.getvalue().lower())

    def test_csrf_must_return_a_json_success_boolean(self):
        for body in (b'{"success": false}', b'{"success": "true"}', b'{"success": 1}',
                     b'[]', b'not JSON'):
            with self.subTest(body=body), readiness_server(self.responses(body)) as (url, _), \
                    mock.patch("scripts.launcher.readiness.webbrowser.open") as browser, \
                    redirect_stdout(io.StringIO()) as output:
                self.assertFalse(Readiness(url, url)())
                browser.assert_not_called()
                self.assertEqual(output.getvalue(), "")

    def test_http_failure_does_not_open_browser(self):
        responses = self.responses()
        responses["/api/v1/auth/csrf/"] = (503, b'{"success": true}', {})
        with readiness_server(responses) as (url, _), \
                mock.patch("scripts.launcher.readiness.webbrowser.open") as browser:
            self.assertFalse(Readiness(url, url)())
        browser.assert_not_called()

    def test_external_redirect_is_not_followed(self):
        with readiness_server(self.responses()) as (external, external_requests):
            responses = self.responses()
            responses["/"] = (302, b"", {"Location": external + "/"})
            with readiness_server(responses) as (url, _), \
                    mock.patch("scripts.launcher.readiness.webbrowser.open") as browser:
                self.assertFalse(Readiness(url, url)())
        self.assertEqual(external_requests, [])
        browser.assert_not_called()

    def test_invalid_certificate_configuration_is_actionable(self):
        with tempfile.TemporaryDirectory() as temporary:
            certificate = Path(temporary) / "invalid.pem"
            certificate.write_text("invalid certificate", encoding="utf-8")
            with self.assertRaisesRegex(LauncherError, "certificate"):
                Readiness("https://127.0.0.1", "https://127.0.0.1", certificate)

    @unittest.skipUnless(importlib.util.find_spec("cryptography") and importlib.util.find_spec("django"),
                         "TLS fixtures require backend virtual environment dependencies")
    def test_https_uses_supplied_certificate_and_rejects_hostname_mismatch(self):
        from scripts.test_native import tls_files

        with tempfile.TemporaryDirectory() as temporary:
            certificate, key = tls_files(Path(temporary))
            with readiness_server(self.responses(), tls=(certificate, key)) as (url, _), \
                    mock.patch("scripts.launcher.readiness.webbrowser.open") as browser, \
                    redirect_stdout(io.StringIO()):
                self.assertFalse(Readiness(url, url)())
                self.assertFalse(Readiness(url.replace("127.0.0.1", "localhost"), url, certificate)())
                self.assertTrue(Readiness(url, url, certificate)())
            browser.assert_called_once_with(url)


if __name__ == "__main__":
    unittest.main()
