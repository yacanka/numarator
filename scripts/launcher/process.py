"""Safe subprocess execution and foreground process supervision."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Sequence

from .model import LauncherError

Command = Sequence[str | Path]


def environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    values = os.environ.copy()
    values.setdefault("PYTHONUTF8", "1")
    values.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    if extra:
        values.update({key: str(value) for key, value in extra.items()})
    return values


def required_tool(name: str) -> str:
    candidates = (f"{name}.cmd", f"{name}.exe", name) if os.name == "nt" else (name,)
    for candidate in candidates:
        executable = shutil.which(candidate)
        if executable:
            return executable
    raise LauncherError(f"required tool is not available on PATH: {name}")


def display(command: Command) -> str:
    return shlex.join(str(part) for part in command)


def run(
    command: Command,
    cwd: Path,
    *,
    extra_env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    print(f"[run] {display(command)}\n      cwd: {cwd}", flush=True)
    completed = subprocess.run(
        [str(part) for part in command],
        cwd=cwd,
        env=environment(extra_env),
        check=False,
        capture_output=capture,
        text=True,
    )
    if completed.returncode:
        detail = completed.stderr.strip() if capture else ""
        suffix = f"\n{detail}" if detail else ""
        raise LauncherError(
            f"command failed ({completed.returncode}): {display(command)}{suffix}"
        )
    return completed


def start(
    command: Command, cwd: Path, *, extra_env: dict[str, str] | None = None,
    process_group: bool = False,
) -> subprocess.Popen:
    print(f"[start] {display(command)}\n        cwd: {cwd}", flush=True)
    return subprocess.Popen(
        [str(part) for part in command], cwd=cwd, env=environment(extra_env),
        start_new_session=process_group and os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if process_group and os.name == "nt" else 0,
    )


def supervise(processes: list[subprocess.Popen], *, process_groups: bool = False) -> None:
    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.25)
        exited = next(process for process in processes if process.poll() is not None)
        raise LauncherError(f"server process exited with code {exited.returncode}")
    except KeyboardInterrupt:
        print("\nStopping services...")
    finally:
        terminate(processes, process_groups=process_groups)


def terminate(processes: Sequence[subprocess.Popen], *, process_groups: bool = False) -> None:
    for process in processes:
        try:
            if process_groups and os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            elif process.poll() is None:
                if process_groups:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    process.terminate()
        except ProcessLookupError:
            pass
    for process in processes:
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=15 if process_groups else 5)
        except subprocess.TimeoutExpired:
            if process_groups and os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            elif process_groups:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False)
            else:
                process.kill()
            process.wait()
