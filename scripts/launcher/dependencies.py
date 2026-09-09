"""Backend/frontend installation and offline-cache preparation."""

from __future__ import annotations

import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .model import LauncherError, Project, Scope
from .offline_manifest import (
    ensure_wheels_only,
    verify_offline_manifest,
    write_offline_manifest,
)
from .process import required_tool, run

MINIMUM_PYTHON = (3, 11)


def ensure_launcher_python() -> None:
    if sys.version_info[:2] < MINIMUM_PYTHON:
        raise LauncherError("Python 3.11 or newer is required")


def ensure_virtual_environment(project: Project, *, create: bool) -> None:
    ensure_launcher_python()
    if project.python.is_file():
        check_virtual_environment_version(project)
        return
    if not create:
        raise LauncherError("backend/.venv is missing; run `python launcher.py setup`")
    if project.venv.exists():
        raise LauncherError(f"incomplete virtual environment: {project.venv}")
    run([sys.executable, "-m", "venv", project.venv], project.root)
    check_virtual_environment_version(project)


def check_virtual_environment_version(project: Project) -> None:
    script = "import sys; print('.'.join(map(str, sys.version_info[:3])))"
    completed = run([project.python, "-c", script], project.root, capture=True)
    version = tuple(int(part) for part in completed.stdout.strip().split("."))
    if version[:2] < MINIMUM_PYTHON:
        rendered = ".".join(str(part) for part in version)
        raise LauncherError(
            f"backend/.venv uses unsupported Python {rendered}; recreate it with Python 3.11+"
        )


def install(project: Project, scope: Scope, mode: str, offline_dir: Path) -> None:
    scope.require_any()
    if mode == "offline":
        verify_offline_manifest(project, scope, offline_dir)
    if scope.backend:
        install_backend(project, mode, offline_dir)
    if scope.frontend:
        install_frontend(project, mode, offline_dir)
    print("[ok] selected dependencies installed")


def install_backend(project: Project, mode: str, offline_dir: Path) -> None:
    ensure_virtual_environment(project, create=True)
    command: list[str | Path] = [project.python, "-m", "pip", "install"]
    if mode == "offline":
        wheels = offline_dir / "wheels"
        require_files(wheels, "offline Python wheels")
        command += ["--no-index", "--find-links", wheels]
    command += ["-r", project.requirements]
    run(command, project.root)
    run([project.python, "-m", "pip", "check"], project.root)


def install_frontend(project: Project, mode: str, offline_dir: Path) -> None:
    command: list[str | Path] = [
        required_tool("npm"),
        "ci",
        "--no-audit",
        "--no-fund",
    ]
    if mode == "offline":
        cache = offline_dir / "npm-cache"
        require_files(cache, "offline npm cache")
        command += ["--offline", "--cache", cache]
    try:
        run(command, project.frontend)
    except LauncherError as error:
        if mode == "offline":
            raise LauncherError(
                f"{error}\noffline npm cache is incomplete for this platform; "
                "run `python launcher.py prepare-offline` on a matching online machine"
            ) from error
        raise


def prepare_offline(project: Project, scope: Scope, offline_dir: Path) -> None:
    scope.require_any()
    if scope.backend:
        wheels = offline_dir / "wheels"
        wheels.mkdir(parents=True, exist_ok=True)
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "-r",
                project.requirements,
                "--wheel-dir",
                wheels,
            ],
            project.root,
        )
        ensure_wheels_only(wheels)
    if scope.frontend:
        cache = offline_dir / "npm-cache"
        cache.mkdir(parents=True, exist_ok=True)
        populate_npm_cache(project, cache)
        verify_npm_cache(project, cache)
    write_offline_manifest(project, scope, offline_dir)
    print(f"[ok] offline dependencies prepared and verified at {offline_dir}")


def populate_npm_cache(project: Project, cache: Path) -> None:
    """Populate the cache from a clean tree without touching workspace node_modules."""
    with npm_staging_tree(project) as staging:
        run(
            [
                required_tool("npm"),
                "ci",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                "--cache",
                cache,
                "--prefer-online",
            ],
            staging,
        )


def verify_npm_cache(project: Project, cache: Path) -> None:
    """Prove that a second clean install succeeds with network access disabled."""
    with npm_staging_tree(project) as staging:
        run(
            [
                required_tool("npm"),
                "ci",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                "--offline",
                "--cache",
                cache,
            ],
            staging,
        )


@contextmanager
def npm_staging_tree(project: Project) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="numarator-npm-") as temporary:
        staging = Path(temporary)
        for name in ("package.json", "package-lock.json", ".npmrc"):
            source = project.frontend / name
            if source.is_file():
                shutil.copy2(source, staging / name)
        yield staging


def require_files(path: Path, label: str) -> None:
    if not path.is_dir() or not any(item.is_file() for item in path.rglob("*")):
        raise LauncherError(f"{label} not found at {path}; run prepare-offline first")
