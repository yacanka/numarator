"""One-time setup and fast foreground startup for the Windows shortcuts."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .dependencies import ensure_launcher_python, ensure_virtual_environment, install
from .model import LauncherError, Project, Scope
from .process import required_tool, run
from .production import external_file, prod, require_address, require_port as require_production_port
from .quickstart_state import Paths, checkout_lock, ensure_production_environment, fingerprint, read_json, save_json
from .readiness import Readiness
from .runtime import DJANGO_ENV, dev, django, require_runtime_ports


def require_node(root: Path) -> None:
    node = required_tool("node")
    required_tool("npm")
    result = run([node, "--version"], root, capture=True)
    match = re.fullmatch(r"v?(\d+)\.\d+\.\d+\s*", result.stdout)
    if not match or int(match.group(1)) < 20:
        raise LauncherError("Node.js 20+ with npm is required; install it and reopen the launcher")


def ask(label: str, default: str = "") -> str:
    prompt = f"{label}" + (f" [{default}]" if default else "") + ": "
    try:
        value = input(prompt).strip()
    except EOFError as error:
        raise LauncherError("First setup requires an interactive terminal; double-click the .bat file") from error
    return value or default


def port(value: object, label: str) -> int:
    try:
        number = int(str(value))
    except ValueError as error:
        raise LauncherError(f"{label} must be a number between 1 and 65535") from error
    if not 1 <= number <= 65535:
        raise LauncherError(f"{label} must be between 1 and 65535")
    return number


def development_config(saved: dict, configure: bool) -> dict:
    backend = saved.get("backend_port", 8000)
    frontend = saved.get("frontend_port", 5173)
    if configure:
        backend = ask("Local backend port", str(backend))
        frontend = ask("Local frontend port", str(frontend))
    values = {"backend_port": port(backend, "Backend port"), "frontend_port": port(frontend, "Frontend port")}
    if values["backend_port"] == values["frontend_port"]:
        raise LauncherError("Backend and frontend must use different ports")
    return values


def production_config(project: Project, saved: dict, configure: bool) -> dict:
    values = dict(saved)
    if configure or not saved:
        print("Production setup: use existing external PEM certificate and private key files.", flush=True)
        values = {
            "host": ask("Server IPv4 address", str(saved.get("host", ""))),
            "port": ask("HTTPS port", str(saved.get("port", 443))),
            "tls_cert_file": ask("TLS certificate absolute path", str(saved.get("tls_cert_file", ""))),
            "tls_key_file": ask("TLS private key absolute path", str(saved.get("tls_key_file", ""))),
        }
    host = values.get("host", "")
    if not isinstance(host, str):
        raise LauncherError("Server host must be an IPv4 address")
    values["port"] = port(values.get("port", 443), "HTTPS port")
    require_address(host, values["port"])
    for key, label in (("tls_cert_file", "TLS certificate"), ("tls_key_file", "TLS private key")):
        value = values.get(key, "")
        if not isinstance(value, str):
            raise LauncherError(f"{label} must be an absolute file path")
        path = Path(os.path.expandvars(value.strip().strip('"'))).expanduser()
        if not path.is_absolute():
            raise LauncherError(f"{label} must be an absolute file path")
        values[key] = str(external_file(project, path, label))
    if values["tls_cert_file"] == values["tls_key_file"]:
        raise LauncherError("TLS certificate and private key must be different files")
    return {key: values[key] for key in ("host", "port", "tls_cert_file", "tls_key_file")}


def load_configuration(project: Project, paths: Paths, configure: bool) -> dict:
    try:
        settings = read_json(paths.settings) or {"version": 1}
    except LauncherError as error:
        if not configure or paths.settings.is_symlink():
            raise LauncherError("Invalid launcher settings; run with --configure") from error
        settings = {"version": 1}
    if settings.get("version") != 1:
        raise LauncherError("Unsupported launcher settings version")
    saved = settings.get(project.environment, {})
    if not isinstance(saved, dict):
        raise LauncherError("Invalid launcher profile settings")
    values = (production_config(project, saved, configure) if project.environment == "production"
              else development_config(saved, configure))
    if saved != values:
        settings[project.environment] = values
        save_json(paths.settings, settings)
    return values


def production_arguments(paths: Paths, values: dict) -> dict:
    return {
        "host": values["host"], "port": values["port"], "env_file": paths.env_file,
        "certificate_file": Path(values["tls_cert_file"]),
        "private_key_file": Path(values["tls_key_file"]),
    }


def prepare_environment(project: Project, paths: Paths, values: dict, expected: dict) -> None:
    require_node(project.root)
    receipt = paths.receipt(project.environment)
    # Both profiles use the same venv/node_modules; an interrupted installer can
    # invalidate either profile, even if its own source fingerprint is unchanged.
    for environment in ("development", "production"):
        candidate = paths.receipt(environment)
        if candidate == receipt or candidate.exists():
            save_json(candidate, {"version": 1, "status": "preparing"})
    install(project, Scope(), "online", project.root / "offline")
    if project.environment == "production":
        prod(project, **production_arguments(paths, values), migrate=True,
             build_frontend=True, prepare_only=True, ensure_admin=True)
    else:
        django(project, ["check"])
        django(project, ["migrate", "--no-input"])
        run([project.python, "-m", "config.initial_admin"], project.backend, extra_env=DJANGO_ENV)
    save_json(receipt, {"version": 1, "status": "ready", "fingerprint": expected})
    print("[ok] preparation completed; subsequent starts skip installation", flush=True)


def preparation_receipt(paths: Paths, environment: str, prepare: bool) -> dict | None:
    path = paths.receipt(environment)
    try:
        return read_json(path)
    except LauncherError as error:
        if not prepare or path.is_symlink():
            raise LauncherError("Invalid preparation record; run with --prepare") from error
        return {"status": "invalid"}


def quickstart(project: Project, *, configure: bool = False, prepare: bool = False) -> None:
    ensure_launcher_python()
    paths = Paths.for_project(project)
    with checkout_lock(paths):
        values = load_configuration(project, paths, configure)
        production = project.environment == "production"
        new_environment = False
        if production:
            # The shortcut's saved env must not silently point to a different shell-selected DB/key.
            for name in ("SECRET_KEY", "NUMARATOR_DATA_DIR"):
                if name in os.environ:
                    raise LauncherError(f"Unset {name} before quickstart; production uses {paths.env_file}")
            require_production_port(values["host"], values["port"])
            new_environment = ensure_production_environment(project, paths)
        else:
            require_runtime_ports(Scope(), values["backend_port"], values["frontend_port"])
        expected = fingerprint(project)
        receipt = preparation_receipt(paths, project.environment, prepare)
        prepared = receipt == {"version": 1, "status": "ready", "fingerprint": expected}
        if not prepared and production and not prepare and (receipt is not None or not new_environment):
            raise LauncherError("Production requires explicit preparation; stop the service, back up existing data, "
                                "then run start-prod.bat --prepare")
        if prepare or not prepared:
            prepare_environment(project, paths, values, expected)
        ensure_virtual_environment(project, create=False)
        if production:
            url = f"https://{values['host']}:{values['port']}"
            ready = Readiness(url, url, Path(values["tls_cert_file"]))
            prod(project, **production_arguments(paths, values), migrate=False,
                 build_frontend=False, ready=ready)
        else:
            if prepared and not prepare:
                require_node(project.root)
            url = f"http://127.0.0.1:{values['frontend_port']}"
            ready = Readiness(url, f"http://127.0.0.1:{values['backend_port']}")
            dev(project, Scope(), migrate=False, no_backend_reload=False,
                backend_port=values["backend_port"], frontend_port=values["frontend_port"], ready=ready)
