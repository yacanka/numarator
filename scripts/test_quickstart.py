"""Quickstart configuration and lifecycle regressions, without installing packages."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.launcher.model import LauncherError, Project
from scripts.test_launcher import create_project
from scripts.launcher.quickstart_state import (
    Paths, checkout_lock, ensure_production_environment, fingerprint, read_json, save_json,
)
from scripts.launcher.quickstart import quickstart, require_node
from scripts.launcher.cli import dispatch
from scripts.launcher.packaging import tracked_source_files
from scripts.launcher.parser import build_parser


class ProjectFixture:
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = create_project(self.root / "source")
        patcher = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.paths = Paths.for_project(self.project)


class StateTests(ProjectFixture, unittest.TestCase):
    def test_production_env_is_external_private_and_never_rotated(self):
        self.assertTrue(ensure_production_environment(self.project, self.paths))
        original = self.paths.env_file.read_bytes()
        settings = dict(line.split("=", 1) for line in original.decode().splitlines())
        self.assertGreaterEqual(len(settings["SECRET_KEY"]), 50)
        self.assertEqual(settings["NUMARATOR_DATA_DIR"], str(self.paths.data_dir))
        self.assertFalse(self.paths.env_file.is_relative_to(self.project.root))
        if os.name != "nt":
            self.assertEqual(self.paths.env_file.stat().st_mode & 0o777, 0o600)
        self.assertFalse(ensure_production_environment(self.project, self.paths))
        self.assertEqual(self.paths.env_file.read_bytes(), original)

    def test_missing_env_with_existing_data_never_generates_replacement_secret(self):
        self.paths.data_dir.mkdir(parents=True)
        (self.paths.data_dir / "numarator.sqlite3").write_bytes(b"existing database")
        with self.assertRaisesRegex(LauncherError, "production.env"):
            ensure_production_environment(self.project, self.paths)
        self.assertFalse(self.paths.env_file.exists())

    def test_external_env_symlink_is_rejected_without_touching_target(self):
        self.paths.home.mkdir(parents=True)
        target = self.root / "existing.env"
        target.write_text("unchanged", encoding="utf-8")
        self.paths.env_file.symlink_to(target)
        with self.assertRaises(LauncherError):
            ensure_production_environment(self.project, self.paths)
        self.assertEqual(target.read_text(), "unchanged")

    def test_settings_store_no_environment_contents(self):
        ensure_production_environment(self.project, self.paths)
        save_json(self.paths.settings, {"version": 1, "production": {"env_file": str(self.paths.env_file)}})
        self.assertEqual(read_json(self.paths.settings)["version"], 1)
        self.assertNotIn("SECRET_KEY", self.paths.settings.read_text())

    def test_checkout_lock_rejects_second_launch_and_releases(self):
        with checkout_lock(self.paths):
            with self.assertRaises(LauncherError):
                with checkout_lock(self.paths):
                    self.fail("second launcher acquired the same checkout")
        with checkout_lock(self.paths):
            pass

    def test_fingerprint_tracks_transitive_requirements_and_production_source(self):
        production = Project.load(self.project.root, "production")
        source = production.frontend / "src" / "App.vue"
        source.parent.mkdir()
        source.write_text("before", encoding="utf-8")
        original = fingerprint(production)
        source.write_text("after", encoding="utf-8")
        self.assertNotEqual(fingerprint(production), original)
        original = fingerprint(self.project)
        (self.project.backend / "requirements/base.txt").write_text("Django==5.2.19\n", encoding="utf-8")
        self.assertNotEqual(fingerprint(self.project), original)

    def test_localappdata_inside_checkout_is_rejected(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.project.root / "state")}):
            with self.assertRaises(LauncherError):
                Paths.for_project(self.project)


class LifecycleTests(ProjectFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.effects = {}
        for name in ("install", "django", "run", "dev", "prod", "require_node", "require_runtime_ports",
                     "require_production_port", "Readiness"):
            patcher = mock.patch(f"scripts.launcher.quickstart.{name}")
            self.effects[name] = patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch("scripts.launcher.quickstart.ensure_virtual_environment")
        patcher.start()
        self.addCleanup(patcher.stop)

    def production(self):
        cert, key = self.root / "server.crt", self.root / "server.key"
        cert.touch()
        key.touch()
        save_json(self.paths.settings, {
            "version": 1,
            "production": {"host": "127.0.0.1", "port": 8443,
                           "tls_cert_file": str(cert), "tls_key_file": str(key)},
        })
        return Project.load(self.project.root, "production")

    def test_local_first_run_prepares_and_repeat_start_skips_install(self):
        quickstart(self.project)
        self.effects["install"].assert_called_once()
        self.assertTrue(self.paths.receipt("development").is_file())
        self.effects["install"].reset_mock()
        self.effects["django"].reset_mock()
        quickstart(self.project)
        self.effects["install"].assert_not_called()
        self.assertFalse(any(call.args[1][0] == "migrate" for call in self.effects["django"].call_args_list))
        self.assertEqual(self.effects["dev"].call_count, 2)

    def test_fresh_production_prepares_once_then_starts_without_mutating_flags(self):
        project = self.production()
        quickstart(project)
        calls = self.effects["prod"].call_args_list
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].kwargs["prepare_only"])
        self.assertTrue(calls[0].kwargs["migrate"])
        self.assertTrue(calls[0].kwargs["ensure_admin"])
        self.assertFalse(calls[1].kwargs["migrate"])
        self.assertFalse(calls[1].kwargs["build_frontend"])
        self.effects["prod"].reset_mock()
        self.effects["install"].reset_mock()
        self.effects["require_node"].reset_mock()
        quickstart(project)
        self.effects["install"].assert_not_called()
        self.effects["require_node"].assert_not_called()
        self.effects["prod"].assert_called_once()
        self.assertFalse(self.effects["prod"].call_args.kwargs["migrate"])

    def test_existing_env_without_receipt_requires_explicit_preparation(self):
        project = self.production()
        ensure_production_environment(project, self.paths)
        with self.assertRaisesRegex(LauncherError, "--prepare"):
            quickstart(project)
        self.effects["install"].assert_not_called()
        self.effects["prod"].assert_not_called()
        quickstart(project, prepare=True)
        self.assertTrue(self.paths.receipt("production").is_file())

    def test_failed_preparation_never_leaves_successful_receipt(self):
        project = self.production()
        self.effects["prod"].side_effect = LauncherError("build failed")
        with self.assertRaisesRegex(LauncherError, "build failed"):
            quickstart(project)
        receipt = read_json(self.paths.receipt("production"))
        self.assertNotEqual(receipt.get("status"), "ready")
        self.effects["prod"].side_effect = None
        with self.assertRaisesRegex(LauncherError, "--prepare"):
            quickstart(project)

    def test_failed_refresh_invalidates_previous_successful_receipt(self):
        quickstart(self.project)
        self.effects["install"].side_effect = LauncherError("offline")
        with self.assertRaises(LauncherError):
            quickstart(self.project, prepare=True)
        self.assertNotEqual(read_json(self.paths.receipt("development")).get("status"), "ready")

    def test_changed_production_sources_require_explicit_refresh(self):
        project = self.production()
        quickstart(project)
        (project.frontend / "index.html").write_text("changed release", encoding="utf-8")
        self.effects["prod"].reset_mock()
        with self.assertRaisesRegex(LauncherError, "--prepare"):
            quickstart(project)
        self.effects["prod"].assert_not_called()

    def test_reconfiguration_preserves_env_and_does_not_repeat_preparation(self):
        project = self.production()
        quickstart(project)
        original = self.paths.env_file.read_bytes()
        self.effects["install"].reset_mock()
        with mock.patch("builtins.input", side_effect=["", "9443", "", ""]):
            quickstart(project, configure=True)
        self.assertEqual(read_json(self.paths.settings)["production"]["port"], 9443)
        self.assertEqual(self.paths.env_file.read_bytes(), original)
        self.effects["install"].assert_not_called()

    def test_port_conflict_prevents_first_install(self):
        self.effects["require_runtime_ports"].side_effect = LauncherError("port is unavailable")
        with self.assertRaises(LauncherError):
            quickstart(self.project)
        self.effects["install"].assert_not_called()

    def test_inherited_production_data_override_is_rejected(self):
        project = self.production()
        with mock.patch.dict(os.environ, {"NUMARATOR_DATA_DIR": str(self.root / "other-data")}):
            with self.assertRaisesRegex(LauncherError, "NUMARATOR_DATA_DIR"):
                quickstart(project)
        self.effects["install"].assert_not_called()
        self.assertFalse(self.paths.env_file.exists())

    def test_explicit_preparation_repairs_corrupt_receipt(self):
        project = self.production()
        ensure_production_environment(project, self.paths)
        self.paths.receipt("production").write_text("{interrupted write", encoding="utf-8")
        with self.assertRaisesRegex(LauncherError, "--prepare"):
            quickstart(project)
        quickstart(project, prepare=True)
        self.assertEqual(read_json(self.paths.receipt("production"))["status"], "ready")

    def test_failed_local_preparation_invalidates_shared_production_dependencies(self):
        project = self.production()
        quickstart(project)
        self.effects["install"].side_effect = LauncherError("install interrupted")
        with self.assertRaises(LauncherError):
            quickstart(self.project, prepare=True)
        self.effects["prod"].reset_mock()
        with self.assertRaisesRegex(LauncherError, "--prepare"):
            quickstart(project)
        self.effects["prod"].assert_not_called()

    def test_explicit_reconfiguration_repairs_invalid_settings_without_rotating_env(self):
        project = self.production()
        quickstart(project)
        original = self.paths.env_file.read_bytes()
        self.paths.settings.write_text("invalid JSON", encoding="utf-8")
        with mock.patch("builtins.input", side_effect=["127.0.0.1", "8443",
                                                       str(self.root / "server.crt"), str(self.root / "server.key")]):
            quickstart(project, configure=True)
        self.assertEqual(self.paths.env_file.read_bytes(), original)
        self.assertEqual(read_json(self.paths.settings)["production"]["port"], 8443)


class InterfaceTests(unittest.TestCase):
    def test_quickstart_parser_and_dispatch_preserve_selected_profile_and_switches(self):
        args = build_parser().parse_args(["quickstart", "--environment", "production", "--configure", "--prepare"])
        project = Project(Path("source"), "production")
        with mock.patch("scripts.launcher.cli.quickstart") as start:
            dispatch(project, args)
        start.assert_called_once_with(project, configure=True, prepare=True)
        default = build_parser().parse_args(["quickstart"])
        self.assertEqual(default.environment, "development")
        self.assertFalse(default.prepare)

    def test_offline_package_includes_untracked_quickstart_runtime_and_shortcuts(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))
            names = ["start-local.bat", "start-prod.bat", "scripts/launcher/quickstart.py",
                     "scripts/launcher/quickstart_state.py", "scripts/launcher/readiness.py",
                     "scripts/launcher/windows_process.py", "scripts/launcher/windows_child.py",
                     "backend/config/initial_admin.py", "docs/windows-quickstart.md"]
            for name in names:
                path = project.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with mock.patch("scripts.launcher.packaging.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "backend/manage.py\nfrontend/package.json\n"
                packaged = {path.relative_to(project.root).as_posix() for path in tracked_source_files(project)}
        self.assertTrue(set(names).issubset(packaged))


class ToolTests(unittest.TestCase):
    @mock.patch("scripts.launcher.quickstart.required_tool", return_value="node")
    @mock.patch("scripts.launcher.quickstart.run")
    def test_node_version_floor_is_enforced(self, run, tool):
        run.return_value.stdout = "v18.20.0\n"
        with self.assertRaisesRegex(LauncherError, "20"):
            require_node(Path.cwd())
        run.return_value.stdout = "v22.21.0\n"
        require_node(Path.cwd())


if __name__ == "__main__":
    unittest.main()
