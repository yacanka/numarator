"""Numarator checks, tests, and local development runtime."""

from __future__ import annotations

import json
import socket

from .dependencies import ensure_virtual_environment
from .model import LauncherError, Project, Scope
from .process import required_tool, run, start, supervise

DJANGO_ENV = {"DJANGO_SETTINGS_MODULE": "config.settings.development"}


def check(project: Project, scope: Scope) -> None:
    scope.require_any()
    if scope.backend:
        ensure_virtual_environment(project, create=False)
        django(project, ["check"])
        django(project, ["makemigrations", "--check", "--dry-run"])
        django(project, ["migrate", "--plan"])
    if scope.frontend:
        run_npm_script(project, "build")
    print("[ok] checks completed")


def test(project: Project, scope: Scope) -> None:
    scope.require_any()
    if scope.backend:
        ensure_virtual_environment(project, create=False)
        django(project, ["test"])
        run(
            [project.python, "-m", "unittest", "scripts.test_launcher"],
            project.root,
        )
    if scope.frontend:
        run_npm_script(project, "test")
    print("[ok] tests completed")


def dev(
    project: Project, scope: Scope, *, migrate: bool, no_backend_reload: bool,
    backend_port: int = 8000, frontend_port: int = 5173,
) -> None:
    scope.require_any()
    require_runtime_ports(scope, backend_port, frontend_port)
    processes = []
    if scope.backend:
        ensure_virtual_environment(project, create=False)
        if migrate:
            django(project, ["migrate", "--no-input"])
        command = [project.python, "manage.py", "runserver", f"127.0.0.1:{backend_port}"]
        if no_backend_reload:
            command.append("--noreload")
        processes.append(start(command, project.backend, extra_env={
            **DJANGO_ENV, "DEV_FRONTEND_PORT": str(frontend_port),
        }))
    if scope.frontend:
        require_npm_script(project, "dev")
        processes.append(
            start(
                [
                    required_tool("npm"),
                    "run",
                    "dev",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(frontend_port),
                    "--strictPort",
                ],
                project.frontend,
                extra_env={
                    "NUMARATOR_DEV_BACKEND_URL": f"http://127.0.0.1:{backend_port}",
                    "VITE_CSRF_COOKIE_NAME": "dn_csrftoken",
                },
            )
        )
    print_urls(scope, backend_port, frontend_port)
    supervise(processes)


def django(project: Project, arguments: list[str]) -> None:
    run(
        [project.python, "manage.py", *arguments],
        project.backend,
        extra_env=DJANGO_ENV,
    )


def package_scripts(project: Project) -> dict[str, str]:
    try:
        manifest = json.loads(project.package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LauncherError(f"invalid frontend/package.json: {error}") from error
    scripts = manifest.get("scripts", {})
    return {key: value for key, value in scripts.items() if isinstance(value, str)}


def require_npm_script(project: Project, name: str) -> None:
    if name not in package_scripts(project):
        raise LauncherError(f"frontend npm script is missing: {name}")


def run_npm_script(project: Project, name: str) -> None:
    require_npm_script(project, name)
    run([required_tool("npm"), "run", name], project.frontend)


def require_runtime_ports(scope: Scope, backend_port: int = 8000, frontend_port: int = 5173) -> None:
    if scope.backend and scope.frontend and backend_port == frontend_port:
        raise LauncherError("backend and frontend must use different ports")
    if scope.backend:
        require_port(backend_port)
    if scope.frontend:
        require_port(frontend_port)


def require_port(port: int) -> None:
    if not 1 <= port <= 65535:
        raise LauncherError(f"invalid port: {port}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            raise LauncherError(f"port is unavailable: 127.0.0.1:{port}") from error


def print_urls(scope: Scope, backend_port: int = 8000, frontend_port: int = 5173) -> None:
    if scope.backend:
        print(f"Backend:  http://127.0.0.1:{backend_port}")
    if scope.frontend:
        print(f"Frontend: http://127.0.0.1:{frontend_port}")
    print("Press Ctrl+C to stop.")
