"""Top-level command dispatch for the Numarator launcher."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .dependencies import install, prepare_offline
from .model import LauncherError, Project, Scope
from .packaging import package_offline
from .parser import build_parser
from .runtime import check, dev, test


def main(arguments: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(arguments)
        project = Project.load(Path(__file__).resolve().parents[2])
        print_context(project, args.command)
        dispatch(project, args)
        return 0
    except (LauncherError, OSError, ValueError) as error:
        print(f"[error] {error}", file=sys.stderr)
        return 1


def dispatch(project: Project, args: argparse.Namespace) -> None:
    scope = scope_from(args)
    if args.command == "setup":
        install(project, scope, args.mode, project_path(project, args.offline_dir))
    elif args.command == "check":
        check(project, scope)
    elif args.command == "test":
        test(project, scope)
    elif args.command == "dev":
        dev(
            project,
            scope,
            migrate=args.migrate,
            no_backend_reload=args.no_backend_reload,
        )
    elif args.command == "prepare-offline":
        prepare_offline(project, scope, project_path(project, args.offline_dir))
    elif args.command == "package-offline":
        package_offline(
            project,
            scope,
            project_path(project, args.offline_dir),
            project_path(project, args.output),
        )


def scope_from(args: argparse.Namespace) -> Scope:
    return Scope(
        backend=not getattr(args, "skip_backend", False),
        frontend=not getattr(args, "skip_frontend", False),
    )


def project_path(project: Project, value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else project.root / path).resolve()


def print_context(project: Project, command: str) -> None:
    print(f"Project:  {project.root}")
    print(f"Backend:  {project.backend}")
    print(f"Frontend: {project.frontend}")
    print(f"Command:  {command}", flush=True)
