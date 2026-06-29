#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time


def _process_diagnostics(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-o", "pid,ppid,stat,etime,command", "-ax"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return f"process diagnostics unavailable: {exc}"
    lines = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 4)
        if line.lstrip().startswith("PID"):
            lines.append(line)
        elif len(parts) >= 2 and (parts[0] == str(pid) or parts[1] == str(pid)):
            lines.append(line)
    return "\n".join(lines) if lines else f"no ps entries found for pid={pid}"


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except Exception:
            process.kill()
        process.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a command with a portable timeout.")
    parser.add_argument("--timeout", type=float, default=120.0, help="Timeout in seconds.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command and arguments to run.")
    args = parser.parse_args(argv)

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("missing command")

    start = time.monotonic()
    try:
        process = subprocess.Popen(command, start_new_session=True)
    except FileNotFoundError as exc:
        print(f"run_with_timeout: command not found: {exc.filename}", file=sys.stderr)
        return 127
    try:
        return int(process.wait(timeout=args.timeout))
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        print(
            f"run_with_timeout: command timed out after {args.timeout:g}s "
            f"(elapsed={elapsed:.1f}s, pid={process.pid}): {' '.join(command)}",
            file=sys.stderr,
        )
        print("run_with_timeout: child process diagnostics:", file=sys.stderr)
        print(_process_diagnostics(process.pid), file=sys.stderr)
        _terminate_process_group(process)
        return 124


if __name__ == "__main__":
    raise SystemExit(main())
