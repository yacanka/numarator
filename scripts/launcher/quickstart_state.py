"""External, secret-free launcher state and exclusive checkout ownership."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .model import LauncherError, Project, Scope
from .offline_manifest import file_sha256, lock_metadata, target_metadata
from .production import external_file


@dataclass(frozen=True)
class Paths:
    home: Path
    checkout: Path

    @classmethod
    def for_project(cls, project: Project) -> "Paths":
        value = os.environ.get("LOCALAPPDATA", "")
        if not value or not Path(value).is_absolute():
            raise LauncherError("Windows LOCALAPPDATA must be an absolute directory")
        home = (Path(value) / "Numarator").resolve()
        if home.is_relative_to(project.root):
            raise LauncherError("LOCALAPPDATA must be outside the repository")
        identity = os.path.normcase(str(project.root))
        checkout_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return cls(home, home / "launcher" / checkout_id)

    @property
    def settings(self) -> Path:
        return self.checkout / "settings.json"

    @property
    def env_file(self) -> Path:
        return self.home / "production.env"

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    def receipt(self, environment: str) -> Path:
        return self.checkout / f"{environment}.prepared.json"


def directory(path: Path) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise LauncherError("Launcher state directories cannot be symbolic links")
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict | None:
    if path.is_symlink():
        raise LauncherError("Launcher state files cannot be symbolic links")
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LauncherError(f"Invalid launcher state file: {path}") from error
    if not isinstance(value, dict):
        raise LauncherError(f"Invalid launcher state file: {path}")
    return value


def save_json(path: Path, value: dict) -> None:
    directory(path.parent)
    if path.is_symlink():
        raise LauncherError("Launcher state files cannot be symbolic links")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".launcher-", delete=False) as output:
            temporary = Path(output.name)
            json.dump(value, output, indent=2, sort_keys=True)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def ensure_production_environment(project: Project, paths: Paths) -> bool:
    """Create a signing key once; an absent env never authorizes replacing data."""
    if paths.env_file.is_symlink() or paths.data_dir.is_symlink():
        raise LauncherError("Production environment and data cannot be symbolic links")
    if paths.env_file.exists():
        external_file(project, paths.env_file, "production environment")
        return False
    if paths.data_dir.exists() and any(paths.data_dir.iterdir()):
        raise LauncherError("Existing production data found; restore the original production.env first")
    directory(paths.home)
    directory(paths.data_dir)
    contents = (
        f"SECRET_KEY={secrets.token_urlsafe(64)}\n"
        f"NUMARATOR_DATA_DIR={paths.data_dir}\n"
        "TIME_ZONE=Europe/Istanbul\nAPP_LOG_LEVEL=INFO\n"
    )
    # O_EXCL prevents a concurrent checkout from replacing an existing signing key.
    try:
        descriptor = os.open(paths.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        external_file(project, paths.env_file, "production environment")
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(contents)
    return True


def fingerprint(project: Project) -> dict:
    inputs = lock_metadata(project, Scope())
    sources = [project.package_json]
    if project.environment == "production":
        sources.extend(project.frontend / name for name in ("index.html", "vite.config.ts", "tsconfig.json"))
        source_dir = project.frontend / "src"
        if source_dir.is_symlink():
            raise LauncherError("Frontend sources cannot be symbolic links")
        if source_dir.exists():
            sources.extend(source_dir.rglob("*"))
    for path in sorted(sources):
        if path.is_symlink():
            raise LauncherError("Launcher inputs cannot be symbolic links")
        if path.is_file():
            inputs[path.relative_to(project.root).as_posix()] = file_sha256(path)
    return {"environment": project.environment, "target": target_metadata(), "inputs": inputs}


@contextmanager
def checkout_lock(paths: Paths):
    """Hold through runtime: setup must not replace files used by a running profile."""
    directory(paths.checkout)
    lock_file = paths.checkout / "launcher.lock"
    if lock_file.is_symlink():
        raise LauncherError("Launcher lock cannot be a symbolic link")
    with lock_file.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise LauncherError("Numarator quickstart is already running for this checkout; stop it first") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
