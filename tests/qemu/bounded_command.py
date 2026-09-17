#!/usr/bin/env python3
"""Run one command with a deadline and a private, bounded combined log."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import time
from typing import Any, BinaryIO, Iterator


MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 3600
TERM_SECONDS = 5
SIGNAL_TRAMPOLINE = (
    "import os,signal,sys;"
    "signal.pthread_sigmask(signal.SIG_UNBLOCK,"
    "{signal.SIGHUP,signal.SIGINT,signal.SIGTERM});"
    "os.execvp(sys.argv[1],sys.argv[1:])"
)


class RunnerError(ValueError):
    pass


class _SignalReceived(BaseException):
    def __init__(self, number: int) -> None:
        super().__init__(number)
        self.number = number


def _open_private_output(path: Path) -> BinaryIO:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    details = os.fstat(fd)
    if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600:
        os.close(fd)
        raise RunnerError("bounded output is not a private regular file")
    return os.fdopen(fd, "wb", buffering=0)


def _process_group_exists(group_id: int) -> bool:
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_process_group(process: subprocess.Popen[bytes]) -> bool:
    existed = _process_group_exists(process.pid)
    if not existed:
        process.poll()
        return False
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.poll()
        return existed
    deadline = time.monotonic() + TERM_SECONDS
    while _process_group_exists(process.pid) and time.monotonic() < deadline:
        process.poll()
        time.sleep(0.05)
    if _process_group_exists(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.wait(timeout=TERM_SECONDS)
    return existed


@contextmanager
def _defer_termination_signals() -> Iterator[None]:
    blocked = frozenset((signal.SIGHUP, signal.SIGINT, signal.SIGTERM))
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def run_bounded(command: list[str], output_path: Path,
                timeout_seconds: int) -> tuple[int, bool, bool]:
    if not command or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise RunnerError("invalid bounded command")
    process: subprocess.Popen[bytes] | None = None
    overflow = False
    timed_out = False
    interrupted = 0
    lingering_group = False
    old_handlers: dict[int, Any] = {}

    def handle_signal(number: int, _frame: object) -> None:
        for installed in old_handlers:
            signal.signal(installed, signal.SIG_IGN)
        raise _SignalReceived(number)

    with _open_private_output(output_path) as output:
        try:
            for number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
                old_handlers[number] = signal.signal(number, handle_signal)
            with _defer_termination_signals():
                process = subprocess.Popen(
                    [sys.executable, "-B", "-c", SIGNAL_TRAMPOLINE, *command],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            assert process.stdout is not None
            retained = 0
            deadline = time.monotonic() + timeout_seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                readable, _writable, _errors = select.select(
                    [process.stdout], [], [], min(0.25, remaining))
                if not readable:
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                available = max(0, MAX_OUTPUT_BYTES - retained)
                if available:
                    written = chunk[:available]
                    output.write(written)
                    retained += len(written)
                if len(chunk) > available:
                    overflow = True
                    break
            if overflow:
                _stop_process_group(process)
            if timed_out:
                _stop_process_group(process)
            elif not overflow:
                try:
                    process.wait(timeout=max(0.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
                    _stop_process_group(process)
            output.flush()
            os.fsync(output.fileno())
        except _SignalReceived as received:
            interrupted = received.number
            if process is not None:
                _stop_process_group(process)
        finally:
            with _defer_termination_signals():
                if process is not None:
                    remaining_group = _stop_process_group(process)
                    if not timed_out and not interrupted and not overflow:
                        lingering_group = remaining_group
                    if process.stdout is not None:
                        process.stdout.close()
                for number, handler in old_handlers.items():
                    signal.signal(number, handler)

    if interrupted:
        return 128 + interrupted, overflow, timed_out
    if timed_out:
        return 124, overflow, True
    if lingering_group:
        return 126, overflow, False
    assert process is not None and process.returncode is not None
    status = process.returncode if process.returncode >= 0 else 128 - process.returncode
    return min(status, 255), overflow, False


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    if argv is None:
        argv = sys.argv
    if len(argv) < 4:
        print("error: bounded command requires OUTPUT TIMEOUT COMMAND", file=sys.stderr)
        return 126
    try:
        timeout_seconds = int(argv[2])
        status, overflow, timed_out = run_bounded(
            argv[3:], Path(argv[1]), timeout_seconds)
    except (OSError, RunnerError, subprocess.SubprocessError, ValueError):
        print("error: bounded command failed", file=sys.stderr)
        return 126
    if overflow:
        print("error: bounded command output exceeded 2097152 bytes", file=sys.stderr)
        return 125
    if status == 124 and not timed_out:
        print("error: command used the reserved timeout status", file=sys.stderr)
        return 126
    return status


if __name__ == "__main__":
    sys.exit(main())
