#!/usr/bin/env python3
"""Run a local process with one deadline, a hard output cap, and tree cleanup."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from typing import Mapping, Sequence


MAX_CHILD_SPEC_BYTES = 65_536
MAX_ARGUMENTS = 128
MAX_ARGUMENT_CHARS = 8_192


class OutputLimitExceeded(subprocess.SubprocessError):
    """The child crossed its declared combined stdout/stderr byte budget."""


@dataclass(frozen=True)
class BoundedProcessResult:
    returncode: int
    output: bytes


def _windows_job_child(argv: list[str]) -> int:
    """Place a Windows child in a kill-on-close job owned by this helper."""

    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return 125
    information = ExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x00002000
    configured = kernel32.SetInformationJobObject(
        job,
        9,
        ctypes.byref(information),
        ctypes.sizeof(information),
    )
    assigned = configured and kernel32.AssignProcessToJobObject(
        job, kernel32.GetCurrentProcess()
    )
    if not assigned:
        return 125
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            shell=False,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return 126
    return completed.returncode


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        try:
            process.kill()
        except OSError:
            pass
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            process.kill()
        except OSError:
            pass


def _validated_argv(argv: Sequence[str]) -> list[str]:
    values = list(argv)
    if (
        not values
        or len(values) > MAX_ARGUMENTS
        or any(
            not isinstance(value, str)
            or not value
            or "\0" in value
            or len(value) > MAX_ARGUMENT_CHARS
            for value in values
        )
    ):
        raise ValueError("process argv must contain bounded non-empty strings")
    return values


def run_bounded(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    output_limit: int,
    env: Mapping[str, str] | None = None,
) -> BoundedProcessResult:
    """Capture combined output in memory and kill the process tree at either bound."""

    values = _validated_argv(argv)
    if timeout_seconds <= 0 or output_limit < 1:
        raise ValueError("process timeout and output limit must be positive")
    launch_argv = values
    popen_options: dict[str, object] = {}
    if os.name == "nt":
        child_spec = json.dumps(values, separators=(",", ":"))
        if len(child_spec.encode("utf-8")) > MAX_CHILD_SPEC_BYTES:
            raise ValueError("Windows child process specification exceeds its cap")
        launch_argv = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--_windows-job-child",
            child_spec,
        ]
    else:
        popen_options["start_new_session"] = True

    process = subprocess.Popen(
        launch_argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
        env=dict(env) if env is not None else None,
        **popen_options,
    )
    assert process.stdout is not None
    captured = bytearray()
    overflow = threading.Event()
    reader_failed = threading.Event()

    def drain() -> None:
        try:
            while True:
                chunk = process.stdout.read(4_096)
                if not chunk:
                    return
                remaining = output_limit - len(captured)
                if remaining > 0:
                    captured.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()
                    _terminate_process_tree(process)
                    return
        except (OSError, ValueError):
            reader_failed.set()
            _terminate_process_tree(process)

    reader = threading.Thread(target=drain, name="bounded-process-output", daemon=True)
    reader.start()
    timed_out = False
    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process)
        return_code = process.wait(timeout=5)
    if os.name != "nt":
        _terminate_process_tree(process)
    reader.join(timeout=5)
    reader_stuck = reader.is_alive()
    try:
        process.stdout.close()
    except OSError:
        reader_failed.set()
    if reader_stuck:
        _terminate_process_tree(process)
        reader.join(timeout=1)
    if timed_out:
        raise subprocess.TimeoutExpired(values, timeout_seconds, output=bytes(captured))
    if overflow.is_set():
        raise OutputLimitExceeded(f"process output exceeded {output_limit} bytes")
    if reader_failed.is_set() or reader.is_alive():
        raise OSError("process output could not be drained safely")
    return BoundedProcessResult(returncode=return_code, output=bytes(captured))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--_windows-job-child", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._windows_job_child is None or os.name != "nt":
        return 2
    raw = args._windows_job_child.encode("utf-8")
    if len(raw) > MAX_CHILD_SPEC_BYTES:
        return 2
    try:
        argv = _validated_argv(json.loads(args._windows_job_child))
    except (json.JSONDecodeError, TypeError, ValueError):
        return 2
    return _windows_job_child(argv)


if __name__ == "__main__":
    sys.exit(main())
