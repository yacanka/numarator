"""Safe subprocess execution and foreground process supervision."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable, Sequence

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
    if process_group and os.name == "nt":
        from .windows_process import start as windows_start

        return windows_start([str(part) for part in command], cwd, env=environment(extra_env))
    return subprocess.Popen(
        [str(part) for part in command], cwd=cwd, env=environment(extra_env),
        start_new_session=process_group and os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if process_group and os.name == "nt" else 0,
    )


def supervise(
    processes: list[subprocess.Popen], *, process_groups: bool = False,
    ready: Callable[[], bool] | None = None, startup_timeout: float = 60.0,
) -> None:
    """Own child cleanup and, optionally, wait for bounded startup readiness."""
    try:
        deadline = time.monotonic() + startup_timeout
        while all(process.poll() is None for process in processes):
            if ready is not None:
                if time.monotonic() >= deadline:
                    raise LauncherError(f"services timed out becoming ready after {startup_timeout:g} seconds")
                if ready():
                    if time.monotonic() >= deadline:
                        raise LauncherError(f"services timed out becoming ready after {startup_timeout:g} seconds")
                    ready = None
            time.sleep(0.25)
        exited = next(process for process in processes if process.poll() is not None)
        raise LauncherError(f"server process exited with code {exited.returncode}")
    except KeyboardInterrupt:
        print("\nStopping services...")
    finally:
        terminate(processes, process_groups=process_groups)


def terminate(processes: Sequence[subprocess.Popen], *, process_groups: bool = False) -> None:
    try:
        _terminate(processes, process_groups=process_groups)
    finally:
        if os.name == "nt":
            from .windows_process import close_job

            for process in processes:
                close_job(process)


def _terminate(processes: Sequence[subprocess.Popen], *, process_groups: bool) -> None:
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
        except OSError:
            # A detached Windows console may reject CTRL_BREAK. Job ownership
            # still provides forced cleanup, including after a leader exits.
            if not (process_groups and os.name == "nt"):
                raise
    for process in processes:
        try:
            process.wait(timeout=15 if process_groups else 5)
        except subprocess.TimeoutExpired:
            if process_groups and os.name == "nt":
                from .windows_process import close_job

                if not close_job(process):
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False)
            elif not process_groups:
                process.kill()
        if process_groups and os.name != "nt":
            # A reloader may outlive its leader, so poll()/wait() alone cannot
            # establish that the complete process group has stopped.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.wait()
