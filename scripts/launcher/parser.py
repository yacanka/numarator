"""Command-line surface for the Numarator launcher."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Numarator development, HTTPS production and offline launcher."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    setup = commands.add_parser("setup", help="Install project dependencies.")
    add_scope(setup)
    add_environment(setup)
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
    development.add_argument("--backend-port", type=int, default=8000)
    development.add_argument("--frontend-port", type=int, default=5173)

    production = commands.add_parser("prod", help="Run the native HTTPS production service.")
    production.add_argument("--env-file", required=True, help="Environment file outside the repository.")
    production.add_argument("--host", required=True, help="Server IPv4 address included in certificate SAN.")
    production.add_argument("--port", type=int, default=443)
    production.add_argument("--tls-cert-file", required=True)
    production.add_argument("--tls-key-file", required=True)
    production.add_argument("--build-frontend", action="store_true")
    production.add_argument("--migrate", action="store_true")
    production.add_argument("--check", action="store_true", help="Validate deployment without starting the server.")

    prepare = commands.add_parser(
        "prepare-offline", help="Download and verify offline dependencies."
    )
    add_scope(prepare)
    add_environment(prepare)
    add_offline_dir(prepare)

    package = commands.add_parser(
        "package-offline", help="Create a source and dependency ZIP."
    )
    add_scope(package)
    add_environment(package)
    add_offline_dir(package)
    package.add_argument("--output", default="numarator-offline.zip")
    return parser


def add_scope(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--skip-backend", action="store_true")
    parser.add_argument("--skip-frontend", action="store_true")


def add_offline_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--offline-dir", default="offline")


def add_environment(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--environment", choices=("development", "production"), default="development")
