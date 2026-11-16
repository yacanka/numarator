"""Regression tests for synchronous native preparation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.launcher.model import LauncherError, Project
from scripts.launcher.production import prod


class ProductionPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = Project(root / "source", "production")
        self.options = {
            "host": "127.0.0.1", "port": 8443,
            "env_file": root / "production.env",
            "certificate_file": root / "server.crt",
            "private_key_file": root / "server.key", "migrate": False,
        }
        for name in ("env_file", "certificate_file", "private_key_file"):
            self.options[name].touch()
        for name in ("ensure_virtual_environment", "require_port", "run", "start", "supervise"):
            patch = mock.patch(f"scripts.launcher.production.{name}")
            setattr(self, name, patch.start())
            self.addCleanup(patch.stop)

    def test_preparation_runs_synchronously_without_binding_or_serving(self):
        prod(self.project, **{**self.options, "migrate": True},
             prepare_only=True, ensure_admin=True, build_frontend=True)

        command, cwd = self.run.call_args.args
        self.assertEqual(cwd, self.project.backend)
        self.assertEqual(command[:3], [self.project.python, "-m", "config.native_runtime"])
        for flag in ("--prepare-only", "--ensure-admin", "--migrate", "--build-frontend"):
            self.assertIn(flag, command)
        self.assertEqual(self.run.call_args.kwargs["extra_env"]["DJANGO_SETTINGS_MODULE"],
                         "config.settings.native")
        self.require_port.assert_not_called()
        self.start.assert_not_called()
        self.supervise.assert_not_called()

    def test_failed_preparation_is_propagated_without_starting_a_server(self):
        self.run.side_effect = LauncherError("preparation failed")
        with self.assertRaisesRegex(LauncherError, "preparation failed"):
            prod(self.project, **self.options, prepare_only=True)
        self.start.assert_not_called()
        self.supervise.assert_not_called()

    def test_preparation_cannot_be_combined_with_read_only_check(self):
        with self.assertRaises(LauncherError):
            prod(self.project, **self.options, prepare_only=True, check_only=True)
        self.run.assert_not_called()
        self.start.assert_not_called()

    def test_admin_bootstrap_requires_preparation_mode(self):
        with self.assertRaises(LauncherError):
            prod(self.project, **self.options, ensure_admin=True)
        self.run.assert_not_called()
        self.start.assert_not_called()

    def test_readiness_callback_is_forwarded_only_to_server_supervision(self):
        ready = mock.Mock(return_value=True)
        prod(self.project, **self.options, ready=ready)
        self.supervise.assert_called_once_with(
            [self.start.return_value], process_groups=True, ready=ready)
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
