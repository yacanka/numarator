"""Command-line surface for the Numarator launcher."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Numarator Django + Vue development and offline launcher."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    setup = commands.add_parser("setup", help="Install project dependencies.")
    add_scope(setup)
    setup.add_argument("--mode", choices=("online", "offline"), default="online")
    add_offline_dir(setup)

    project_check = commands.add_parser("check", help="Run project checks.")
    add_scope(project_check)
    project_test = commands.add_parser("test", help="Run project tests.")
    add_scope(project_test)

    development = commands.add_parser("dev", help="Run local development services.")
    add_scope(development)
    development.add_argument("--migrate", action="store_true")
    development.add_argument("--no-backend-reload", action="store_true")

    prepare = commands.add_parser(
        "prepare-offline", help="Download and verify offline dependencies."
    )
    add_scope(prepare)
    add_offline_dir(prepare)

    package = commands.add_parser(
        "package-offline", help="Create a source and dependency ZIP."
    )
    add_scope(package)
    add_offline_dir(package)
    package.add_argument("--output", default="numarator-offline.zip")
    return parser


def add_scope(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--skip-backend", action="store_true")
    parser.add_argument("--skip-frontend", action="store_true")


def add_offline_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--offline-dir", default="offline")
