"""Machine readings the supervisor paces itself by (no extra dependencies)."""

from __future__ import annotations

import ctypes
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from pathlib import Path
from typing import Any

# Set by the job queue around a handler: every subprocess the handler runs through ``run_cancellable``
# is told to it, so cancelling the job kills them (and what they started).
PROCESS_REGISTRAR: ContextVar[Callable[[subprocess.Popen[Any]], None] | None] = ContextVar(
    "process_registrar", default=None
)


def free_ram_gb() -> float | None:
    """Available physical memory in GB, or None when it can't be read."""
    if sys.platform == "win32":

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
            return None
        return status.ullAvailPhys / 1e9
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024 / 1e9
    return None


def kill_tree(pid: int) -> bool:
    """Kill a process and everything it started (yt-dlp starts ffmpeg; WhisperX starts workers). Returns
    whether the kill command ran. On Windows this is ``taskkill /T /F``; elsewhere the process was started
    in its own process group (``start_new_session``), and the group is killed."""
    if sys.platform == "win32":
        done = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False, timeout=15
        )
        return done.returncode in (0, 128)  # 128: it had already ended
    import os
    import signal

    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return True


def popen_flags() -> dict[str, Any]:
    """Popen keywords that make a child killable as a tree: its own process group where that matters."""
    return {} if sys.platform == "win32" else {"start_new_session": True}


def run_cancellable(
    cmd: Sequence[str],
    *,
    timeout: float,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    encoding: str = "utf-8",
) -> subprocess.CompletedProcess[str]:
    """``subprocess.run(capture_output=True, text=True, check=False)`` that a job can cancel: the process
    is registered with the running job (if any), and killed with its children on timeout."""
    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding=encoding,
        errors="replace",
        env=None if env is None else dict(env),
        cwd=cwd,
        **popen_flags(),
    )
    register = PROCESS_REGISTRAR.get()
    if register is not None:
        register(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc.pid)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(list(cmd), proc.returncode, out, err)
