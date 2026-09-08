"""Project paths and shared launcher errors."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class LauncherError(RuntimeError):
    """Expected launcher failure with a user-actionable message."""


@dataclass(frozen=True)
class Project:
    """Validated Numarator repository paths."""

    root: Path

    @classmethod
    def load(cls, root: Path) -> "Project":
        project = cls(root.expanduser().resolve())
        expected = (
            project.manage_py,
            project.package_json,
            project.package_lock,
            project.requirements,
        )
        missing = next((path for path in expected if not path.is_file()), None)
        if missing:
            raise LauncherError(f"Numarator project file is missing: {missing}")
        return project

    @property
    def backend(self) -> Path:
        return self.root / "docnumber"

    @property
    def frontend(self) -> Path:
        return self.root / "frontend"

    @property
    def manage_py(self) -> Path:
        return self.backend / "manage.py"

    @property
    def package_json(self) -> Path:
        return self.frontend / "package.json"

    @property
    def package_lock(self) -> Path:
        return self.frontend / "package-lock.json"

    @property
    def requirements(self) -> Path:
        return self.backend / "requirements" / "development.txt"

    @property
    def venv(self) -> Path:
        # Keep compatibility with start-dev.bat and start-dev.sh.
        return self.backend / ".venv"

    @property
    def python(self) -> Path:
        directory = "Scripts" if os.name == "nt" else "bin"
        executable = "python.exe" if os.name == "nt" else "python"
        return self.venv / directory / executable


@dataclass(frozen=True)
class Scope:
    """Select the backend and frontend sides of a workflow."""

    backend: bool = True
    frontend: bool = True

    def require_any(self) -> None:
        if not self.backend and not self.frontend:
            raise LauncherError("both backend and frontend were skipped")
