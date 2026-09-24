"""Native HTTPS lifecycle, separate from the Docker production profile."""

from __future__ import annotations

import ipaddress
import socket
from pathlib import Path

from .dependencies import ensure_virtual_environment
from .model import LauncherError, Project
from .process import run, start, supervise


def external_file(project: Project, path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise LauncherError(f"{label} must be an existing regular file")
    resolved = path.resolve()
    if resolved.is_relative_to(project.root):
        raise LauncherError(f"{label} must be outside the repository")
    return resolved


def require_address(host: str, port: int) -> None:
    try:
        address = ipaddress.IPv4Address(host)
    except ValueError as error:
        raise LauncherError("prod --host must be an explicit IPv4 address") from error
    if address.is_unspecified or address.is_multicast or address.is_reserved:
        raise LauncherError("prod --host must be a unicast IPv4 address")
    if not 1 <= port <= 65535:
        raise LauncherError("prod --port must be between 1 and 65535")


def require_port(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError as error:
            raise LauncherError(f"production address is unavailable: {host}:{port}") from error


def prod(
    project: Project, *, host: str, port: int, env_file: Path,
    certificate_file: Path, private_key_file: Path, migrate: bool,
    build_frontend: bool = False, check_only: bool = False,
) -> None:
    if check_only and (migrate or build_frontend):
        raise LauncherError("--check cannot be combined with --migrate or --build-frontend")
    require_address(host, port)
    env_file = external_file(project, env_file, "production environment")
    certificate_file = external_file(project, certificate_file, "TLS certificate")
    private_key_file = external_file(project, private_key_file, "TLS private key")
    if certificate_file == private_key_file:
        raise LauncherError("TLS certificate and private key must be different files")
    ensure_virtual_environment(project, create=False)
    extra_env = {
        "DJANGO_SETTINGS_MODULE": "config.settings.native",
        "NUMARATOR_ENV_FILE": str(env_file),
        "NUMARATOR_HOST": host,
        "NUMARATOR_PORT": str(port),
    }
    command = [
        project.python, "-m", "config.native_runtime",
        "--tls-cert-file", certificate_file, "--tls-key-file", private_key_file,
    ]
    if check_only:
        run([*command, "--check"], project.backend, extra_env=extra_env)
        return
    require_port(host, port)
    if migrate:
        command.append("--migrate")
    if build_frontend:
        command.append("--build-frontend")
    process = start(command, project.backend, extra_env=extra_env, process_group=True)
    print("Production startup checks are running; Ctrl+C stops the service.", flush=True)
    supervise([process], process_groups=True)
