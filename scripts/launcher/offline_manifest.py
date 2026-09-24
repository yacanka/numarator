"""Checksummed, platform-bound metadata for offline dependencies."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path

from .model import LauncherError, Project, Scope
from .process import required_tool

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
EPHEMERAL_NPM_CACHE_NAMES = {"_logs", "_update-notifier-last-checked"}


def write_offline_manifest(project: Project, scope: Scope, offline_dir: Path) -> Path:
    offline_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = offline_dir / MANIFEST_NAME
    manifest = {
        "format_version": MANIFEST_VERSION,
        "commit": git_commit(project.root),
        "scope": {"backend": scope.backend, "frontend": scope.frontend},
        "environment": project.environment,
        "target": target_metadata(),
        "toolchain": toolchain_metadata(scope),
        "locks": lock_metadata(project, scope),
        "artifacts": artifact_metadata(offline_dir, scope),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def verify_offline_manifest(project: Project, scope: Scope, offline_dir: Path) -> dict:
    path = offline_dir / MANIFEST_NAME
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LauncherError("offline dependency manifest is missing or invalid") from error

    expected_scope = {"backend": scope.backend, "frontend": scope.frontend}
    if manifest.get("format_version") != MANIFEST_VERSION:
        raise LauncherError("offline dependency manifest version is unsupported")
    if manifest.get("scope") != expected_scope:
        raise LauncherError(
            "offline dependencies were prepared for a different backend/frontend scope"
        )
    # Old bundles predate native production and are development-only.
    if manifest.get("environment", "development") != project.environment:
        raise LauncherError("offline dependencies were prepared for a different environment")
    if manifest.get("target") != target_metadata():
        raise LauncherError(
            "offline dependencies target a different OS, architecture, or Python version"
        )
    if manifest.get("locks") != lock_metadata(project, scope):
        raise LauncherError("offline dependencies do not match the current lock files")
    if manifest.get("artifacts") != artifact_metadata(offline_dir, scope):
        raise LauncherError("offline dependency checksum verification failed")
    return manifest


def target_metadata() -> dict[str, str]:
    return {
        "implementation": sys.implementation.name,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "system": platform.system().lower(),
        "machine": platform.machine().lower(),
    }


def toolchain_metadata(scope: Scope) -> dict[str, str]:
    metadata = {
        "python": platform.python_version(),
        "pip": importlib.metadata.version("pip"),
    }
    if scope.frontend:
        metadata["node"] = command_version("node")
        metadata["npm"] = command_version("npm")
    return metadata


def lock_metadata(project: Project, scope: Scope) -> dict[str, str]:
    locks: dict[str, str] = {}
    if scope.backend:
        for path in requirement_files(project.requirements, project.root):
            locks[path.relative_to(project.root).as_posix()] = file_sha256(path)
    if scope.frontend:
        locks[project.package_lock.relative_to(project.root).as_posix()] = file_sha256(
            project.package_lock
        )
    return locks


def requirement_files(entrypoint: Path, root: Path) -> list[Path]:
    """Return the transitive local requirement files used by the entrypoint."""
    pending = [entrypoint.resolve()]
    found: set[Path] = set()
    root = root.resolve()
    while pending:
        path = pending.pop()
        if path in found:
            continue
        if not path.is_file() or not path.is_relative_to(root):
            raise LauncherError(f"requirements include is unavailable or unsafe: {path}")
        found.add(path)
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("-r "):
                pending.append((path.parent / stripped[3:].strip()).resolve())
            elif stripped.startswith("--requirement "):
                pending.append((path.parent / stripped[14:].strip()).resolve())
    return sorted(found)


def artifact_metadata(offline_dir: Path, scope: Scope) -> list[dict[str, int | str]]:
    artifacts = []
    roots = []
    if scope.backend:
        roots.append(offline_dir / "wheels")
    if scope.frontend:
        roots.append(offline_dir / "npm-cache")
    paths = (path for root in roots if root.is_dir() for path in root.rglob("*"))
    for path in sorted(paths):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        if is_ephemeral_npm_cache_path(path, offline_dir):
            continue
        if path.is_symlink():
            raise LauncherError("offline dependencies cannot contain symbolic links")
        artifacts.append(
            {
                "path": path.relative_to(offline_dir).as_posix(),
                "sha256": file_sha256(path),
                "size": path.stat().st_size,
            }
        )
    return artifacts


def is_ephemeral_npm_cache_path(path: Path, offline_dir: Path) -> bool:
    """Ignore npm diagnostics that are regenerated by every setup invocation."""
    try:
        relative = path.relative_to(offline_dir / "npm-cache")
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] in EPHEMERAL_NPM_CACHE_NAMES


def ensure_wheels_only(wheels: Path) -> None:
    invalid = [path.name for path in wheels.iterdir() if path.is_file() and path.suffix != ".whl"]
    if invalid:
        raise LauncherError(
            f"offline Python dependencies contain a non-wheel artifact: {invalid[0]}"
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise LauncherError("Git commit metadata is required for offline preparation")
    return completed.stdout.strip()


def command_version(command: str) -> str:
    executable = required_tool(command)
    completed = subprocess.run(
        [executable, "--version"], check=False, capture_output=True, text=True
    )
    if completed.returncode:
        raise LauncherError(f"{command} version could not be determined")
    return completed.stdout.strip()
