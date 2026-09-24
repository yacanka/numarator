"""Regression tests for the Numarator-specific launcher."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from scripts.launcher.dependencies import (
    install_frontend,
    populate_npm_cache,
    verify_npm_cache,
)
from scripts.launcher.model import LauncherError, Project, Scope
from scripts.launcher.offline_manifest import (
    artifact_metadata,
    lock_metadata,
    verify_offline_manifest,
    write_offline_manifest,
)
from scripts.launcher.packaging import (
    offline_dependency_entries,
    tracked_source_files,
    write_zip,
)
from scripts.launcher.parser import build_parser
from scripts.launcher.runtime import dev, require_runtime_ports
from scripts.launcher.production import prod, require_address, external_file


def create_project(root: Path) -> Project:
    backend = root / "backend"
    requirements = backend / "requirements"
    frontend = root / "frontend"
    requirements.mkdir(parents=True)
    frontend.mkdir()
    (backend / "manage.py").write_text("# test\n", encoding="utf-8")
    (requirements / "development.txt").write_text("-r base.txt\n", encoding="utf-8")
    (requirements / "native.txt").write_text("-r base.txt\nuvicorn==0.53.0\n", encoding="utf-8")
    (requirements / "base.txt").write_text("Django==4.2.10\n", encoding="utf-8")
    (frontend / "package.json").write_text(
        json.dumps({"scripts": {"dev": "vite"}, "dependencies": {"vue": "3"}}),
        encoding="utf-8",
    )
    (frontend / "package-lock.json").write_text("{}\n", encoding="utf-8")
    return Project.load(root)


class ProjectTests(unittest.TestCase):
    def test_project_uses_numarator_layout_and_backend_virtual_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))

        self.assertEqual(project.backend.name, "backend")
        self.assertEqual(project.requirements.name, "development.txt")
        self.assertEqual(project.venv, project.backend / ".venv")


class DependencyTests(unittest.TestCase):
    @mock.patch("scripts.launcher.dependencies.run")
    @mock.patch("scripts.launcher.dependencies.required_tool", return_value="npm")
    def test_online_frontend_setup_does_not_force_offline_cache(
        self, _tool: mock.Mock, run_mock: mock.Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))
            install_frontend(project, "online", project.root / "offline")

        command, cwd = run_mock.call_args.args
        self.assertEqual(command, ["npm", "ci", "--no-audit", "--no-fund"])
        self.assertEqual(cwd, project.frontend)

    @mock.patch("scripts.launcher.dependencies.run")
    @mock.patch("scripts.launcher.dependencies.required_tool", return_value="npm")
    def test_offline_frontend_setup_uses_only_prepared_cache(
        self, _tool: mock.Mock, run_mock: mock.Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))
            cache = project.root / "offline/npm-cache"
            cache.mkdir(parents=True)
            (cache / "entry").write_text("cached", encoding="utf-8")
            install_frontend(project, "offline", project.root / "offline")

        command = run_mock.call_args.args[0]
        self.assertIn("--offline", command)
        self.assertIn(cache, command)

    @mock.patch("scripts.launcher.dependencies.run")
    @mock.patch("scripts.launcher.dependencies.required_tool", return_value="npm")
    def test_cache_population_and_verification_use_clean_trees(
        self, _tool: mock.Mock, run_mock: mock.Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))
            cache = project.root / "offline/npm-cache"
            populate_npm_cache(project, cache)
            verify_npm_cache(project, cache)

        populate_command, populate_cwd = run_mock.call_args_list[0].args
        verify_command, verify_cwd = run_mock.call_args_list[1].args
        self.assertNotEqual(populate_cwd, project.frontend)
        self.assertNotEqual(verify_cwd, project.frontend)
        self.assertIn("--prefer-online", populate_command)
        self.assertIn("--offline", verify_command)
        self.assertIn("--ignore-scripts", populate_command)


class ManifestTests(unittest.TestCase):
    def test_ephemeral_npm_logs_do_not_invalidate_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            offline_dir = Path(temporary)
            cache = offline_dir / "npm-cache"
            logs = cache / "_logs"
            logs.mkdir(parents=True)
            (logs / "debug.log").write_text("temporary path", encoding="utf-8")
            (cache / "entry").write_text("cached", encoding="utf-8")

            artifacts = artifact_metadata(offline_dir, Scope(backend=False))

        self.assertEqual([item["path"] for item in artifacts], ["npm-cache/entry"])

    def test_backend_lock_includes_transitive_requirement_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))
            locks = lock_metadata(project, Scope(frontend=False))

        self.assertIn("backend/requirements/development.txt", locks)
        self.assertIn("backend/requirements/base.txt", locks)

    @mock.patch("scripts.launcher.offline_manifest.git_commit", return_value="abc123")
    @mock.patch("scripts.launcher.offline_manifest.toolchain_metadata", return_value={})
    def test_manifest_rejects_scope_changes(
        self, _toolchain: mock.Mock, _commit: mock.Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))
            cache = project.root / "offline/npm-cache"
            cache.mkdir(parents=True)
            (cache / "entry").write_text("cached", encoding="utf-8")
            write_offline_manifest(project, Scope(backend=False), project.root / "offline")

            with self.assertRaises(LauncherError):
                verify_offline_manifest(project, Scope(), project.root / "offline")


class PackagingTests(unittest.TestCase):
    @mock.patch("scripts.launcher.packaging.subprocess.run")
    def test_source_packaging_excludes_local_signing_key_even_if_tracked(
        self, run_mock: mock.Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))
            key_file = project.backend / ".dev-secret-key"
            key_file.touch()
            run_mock.return_value = mock.Mock(
                returncode=0,
                stdout="backend/manage.py\nbackend/.dev-secret-key\n",
            )
            files = tracked_source_files(project)

        self.assertIn(project.manage_py, files)
        self.assertNotIn(key_file, files)

    @mock.patch("scripts.launcher.packaging.subprocess.run")
    def test_source_packaging_keeps_both_application_sides(
        self, run_mock: mock.Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))
            run_mock.return_value = mock.Mock(
                returncode=0,
                stdout="backend/manage.py\nfrontend/package.json\n",
            )
            files = tracked_source_files(project)

        self.assertIn(project.manage_py, files)
        self.assertIn(project.package_json, files)

    def test_offline_entries_include_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            offline_dir = Path(temporary)
            cache = offline_dir / "npm-cache"
            cache.mkdir()
            (cache / "entry").write_text("cached", encoding="utf-8")
            (offline_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
            entries = offline_dependency_entries(Scope(backend=False), offline_dir)

        archive_paths = [archive_path.as_posix() for _, archive_path in entries]
        self.assertIn("offline/manifest.json", archive_paths)
        self.assertIn("offline/npm-cache/entry", archive_paths)

    def test_zip_rejects_archive_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "safe.txt"
            source.write_text("safe", encoding="utf-8")
            with self.assertRaises(LauncherError):
                write_zip(
                    root / "bundle.zip",
                    [(source, Path("../escape.txt"))],
                    allowed_roots=(root,),
                )


class ParserTests(unittest.TestCase):
    def test_development_ports_are_explicit_and_keep_legacy_defaults(self) -> None:
        defaults = build_parser().parse_args(["dev"])
        self.assertEqual((defaults.backend_port, defaults.frontend_port), (8000, 5173))
        custom = build_parser().parse_args(["dev", "--backend-port", "8100", "--frontend-port", "5174"])
        self.assertEqual((custom.backend_port, custom.frontend_port), (8100, 5174))

    def test_setup_is_online_by_default_and_uses_skip_flags(self) -> None:
        parser = build_parser()
        setup = parser.parse_args(["setup", "--skip-backend"])

        self.assertEqual(setup.mode, "online")
        self.assertTrue(setup.skip_backend)

    def test_foreign_ignore_backend_flag_is_not_silently_accepted(self) -> None:
        parser = build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["setup", "--ignore-backend"])


class DevelopmentTests(unittest.TestCase):
    @mock.patch("scripts.launcher.runtime.require_port")
    def test_only_selected_ports_are_checked(self, port: mock.Mock) -> None:
        require_runtime_ports(Scope(frontend=False), 8100, 5174)
        port.assert_called_once_with(8100)
        with self.assertRaises(LauncherError):
            require_runtime_ports(Scope(), 8100, 8100)

    def test_invalid_ports_fail_before_socket_binding(self) -> None:
        for port in (0, -1, 65536):
            with self.subTest(port=port), self.assertRaises(LauncherError):
                require_runtime_ports(Scope(frontend=False), port, 5174)

    @mock.patch("scripts.launcher.runtime.supervise")
    @mock.patch("scripts.launcher.runtime.start")
    @mock.patch("scripts.launcher.runtime.required_tool", return_value="npm")
    @mock.patch("scripts.launcher.runtime.ensure_virtual_environment")
    @mock.patch("scripts.launcher.runtime.require_runtime_ports")
    def test_ports_reach_django_vite_and_proxy(self, _ports, _venv, _tool, start, supervise):
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))
            dev(project, Scope(), migrate=False, no_backend_reload=True,
                backend_port=8100, frontend_port=5174)
        backend, frontend = start.call_args_list
        self.assertIn("127.0.0.1:8100", backend.args[0])
        self.assertIn("--noreload", backend.args[0])
        self.assertEqual(backend.kwargs["extra_env"]["DEV_FRONTEND_PORT"], "5174")
        self.assertIn("5174", frontend.args[0])
        self.assertEqual(frontend.kwargs["extra_env"]["NUMARATOR_DEV_BACKEND_URL"], "http://127.0.0.1:8100")
        supervise.assert_called_once()


class ProductionTests(unittest.TestCase):
    def test_production_dependencies_and_offline_locks_are_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            development = create_project(Path(temporary))
            production = Project.load(development.root, "production")
            self.assertEqual(production.requirements.name, "native.txt")
            self.assertNotEqual(lock_metadata(development, Scope()), lock_metadata(production, Scope()))

    @mock.patch("scripts.launcher.offline_manifest.git_commit", return_value="abc123")
    @mock.patch("scripts.launcher.offline_manifest.toolchain_metadata", return_value={})
    def test_frontend_only_offline_bundle_cannot_cross_environments(self, toolchain, commit):
        with tempfile.TemporaryDirectory() as temporary:
            development = create_project(Path(temporary))
            production = Project.load(development.root, "production")
            offline = development.root / "offline"
            cache = offline / "npm-cache"
            cache.mkdir(parents=True)
            (cache / "entry").write_text("cached")
            scope = Scope(backend=False)
            write_offline_manifest(development, scope, offline)
            with self.assertRaises(LauncherError):
                verify_offline_manifest(production, scope, offline)

    def test_production_setup_parser_preserves_online_default(self):
        args = build_parser().parse_args(["setup", "--environment", "production"])
        self.assertEqual(args.environment, "production")
        self.assertEqual(args.mode, "online")

    def test_invalid_bind_addresses_are_rejected(self):
        for host, port in [("0.0.0.0", 443), ("224.0.0.1", 443), ("localhost", 443),
                           ("::1", 443), ("127.0.0.1", 0), ("127.0.0.1", 65536)]:
            with self.subTest(host=host, port=port), self.assertRaises(LauncherError):
                require_address(host, port)
        require_address("127.0.0.1", 8443)

    def test_external_config_rejects_repository_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))
            with self.assertRaises(LauncherError):
                external_file(project, project.manage_py, "env")
            link = project.root / "link"
            link.symlink_to(project.manage_py)
            with self.assertRaises(LauncherError):
                external_file(project, link, "env")

    @mock.patch("scripts.launcher.production.supervise")
    @mock.patch("scripts.launcher.production.start")
    @mock.patch("scripts.launcher.production.require_port")
    @mock.patch("scripts.launcher.production.ensure_virtual_environment")
    def test_production_uses_native_child_and_only_explicit_migration(self, venv, port, start, supervise):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create_project(root / "source")
            files = [root / name for name in ("production.env", "server.crt", "server.key")]
            for path in files:
                path.touch()
            prod(project, host="127.0.0.1", port=8443, env_file=files[0],
                 certificate_file=files[1], private_key_file=files[2], migrate=False)
            command = start.call_args.args[0]
            self.assertIn("config.native_runtime", command)
            self.assertNotIn("--migrate", command)
            self.assertNotIn("runserver", command)
            self.assertEqual(start.call_args.kwargs["extra_env"]["DJANGO_SETTINGS_MODULE"], "config.settings.native")
            supervise.assert_called_once_with([start.return_value], process_groups=True)

    @mock.patch("scripts.launcher.production.start")
    def test_check_cannot_apply_changes(self, start):
        with tempfile.TemporaryDirectory() as temporary:
            project = create_project(Path(temporary))
            with self.assertRaises(LauncherError):
                prod(project, host="127.0.0.1", port=8443, env_file=Path("unused"),
                     certificate_file=Path("unused"), private_key_file=Path("unused"),
                     migrate=True, check_only=True)
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
