"""Secret-conscious offline ZIP packaging."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path

from .dependencies import require_files
from .model import LauncherError, Project, Scope
from .offline_manifest import (
    MANIFEST_NAME,
    is_ephemeral_npm_cache_path,
    verify_offline_manifest,
)

EXCLUDED_NAMES = {".env", ".env.local", ".dev-secret-key", ".DS_Store", "db.sqlite3"}
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "logs",
    "media",
    "staticfiles",
}
EXCLUDED_SUFFIXES = {
    ".7z",
    ".bak",
    ".db",
    ".dump",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".rar",
    ".sql",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".tgz",
    ".zip",
}


def package_offline(
    project: Project, scope: Scope, offline_dir: Path, output: Path
) -> None:
    scope.require_any()
    if output.resolve().is_relative_to(offline_dir.resolve()):
        raise LauncherError("offline ZIP output must be outside the offline dependency directory")
    verify_offline_manifest(project, scope, offline_dir)
    source_files = tracked_source_files(project)
    entries = [(path, path.relative_to(project.root)) for path in source_files]
    entries.extend(offline_dependency_entries(scope, offline_dir))
    write_zip(output, entries, allowed_roots=(project.root, offline_dir))
    print(f"[ok] offline package created: {output}")


def offline_dependency_entries(
    scope: Scope, offline_dir: Path
) -> list[tuple[Path, Path]]:
    manifest = offline_dir / MANIFEST_NAME
    if not manifest.is_file():
        raise LauncherError("offline dependency manifest is missing")
    dependencies = [(manifest, Path("offline") / MANIFEST_NAME)]
    if scope.backend:
        wheels = offline_dir / "wheels"
        require_files(wheels, "offline Python wheels")
        dependencies.extend(mapped_tree(wheels, Path("offline/wheels")))
    if scope.frontend:
        cache = offline_dir / "npm-cache"
        require_files(cache, "offline npm cache")
        dependencies.extend(
            mapped_tree(
                cache,
                Path("offline/npm-cache"),
                exclude=lambda path: is_ephemeral_npm_cache_path(path, offline_dir),
            )
        )
    return dependencies


def tracked_source_files(project: Project) -> list[Path]:
    completed = subprocess.run(
        ["git", "-C", str(project.root), "ls-files"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise LauncherError("Git repository metadata is required for safe packaging")
    files = [project.root / line for line in completed.stdout.splitlines() if line]
    launcher_files = [
        project.root / "launcher.py",
        project.root / "scripts/__init__.py",
        project.root / "scripts/test_launcher.py",
        project.root / "scripts/launcher/__init__.py",
        project.root / "scripts/launcher/cli.py",
        project.root / "scripts/launcher/dependencies.py",
        project.root / "scripts/launcher/model.py",
        project.root / "scripts/launcher/offline_manifest.py",
        project.root / "scripts/launcher/packaging.py",
        project.root / "scripts/launcher/parser.py",
        project.root / "scripts/launcher/process.py",
        project.root / "scripts/launcher/runtime.py",
    ]
    for path in launcher_files:
        if path.is_file():
            files.append(path)
    return sorted(set(path for path in files if packageable(path)))


def packageable(path: Path) -> bool:
    if not path.is_file():
        return False
    unsafe_env = path.name.startswith(".env") and not path.name.endswith(
        (".example", ".sample")
    )
    if unsafe_env or path.name in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return not set(path.parts).intersection(EXCLUDED_PARTS)


def mapped_tree(
    source: Path,
    destination: Path,
    *,
    exclude: Callable[[Path], bool] | None = None,
) -> list[tuple[Path, Path]]:
    return [
        (path, destination / path.relative_to(source))
        for path in source.rglob("*")
        if path.is_file() and not (exclude and exclude(path))
    ]


def write_zip(
    output: Path,
    entries: list[tuple[Path, Path]],
    *,
    allowed_roots: tuple[Path, ...],
) -> None:
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    roots = tuple(root.expanduser().resolve() for root in allowed_roots)
    unique: dict[str, Path] = {}
    for source, archive_path in entries:
        archive_name = safe_archive_name(archive_path)
        resolved_source = safe_source_file(source, roots)
        if resolved_source == output:
            continue
        if archive_name in unique and unique[archive_name] != resolved_source:
            raise LauncherError(f"duplicate archive path: {archive_name}")
        unique[archive_name] = resolved_source
    if not unique:
        raise LauncherError("no files were selected for packaging")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for archive_name, source in sorted(unique.items()):
            info = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            with source.open("rb") as input_file, archive.open(info, "w") as output_file:
                shutil.copyfileobj(input_file, output_file, length=1024 * 1024)


def safe_archive_name(path: Path) -> str:
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise LauncherError("archive entries must use safe relative paths")
    return path.as_posix()


def safe_source_file(path: Path, roots: tuple[Path, ...]) -> Path:
    lexical = path.expanduser().absolute()
    matching_root = next((root for root in roots if lexical.is_relative_to(root)), None)
    if matching_root is None:
        raise LauncherError("archive source is outside the allowed roots")
    current = matching_root
    for part in lexical.relative_to(matching_root).parts:
        current = current / part
        if current.is_symlink():
            raise LauncherError("symbolic links are not allowed in packages")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        raise LauncherError("archive source is unavailable") from error
    if not resolved.is_relative_to(matching_root) or not resolved.is_file():
        raise LauncherError("archive source escaped its allowed root")
    return resolved
