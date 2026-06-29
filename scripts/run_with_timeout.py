#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys


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

    try:
        completed = subprocess.run(command, timeout=args.timeout, check=False)
    except FileNotFoundError as exc:
        print(f"run_with_timeout: command not found: {exc.filename}", file=sys.stderr)
        return 127
    except subprocess.TimeoutExpired:
        print(
            f"run_with_timeout: command timed out after {args.timeout:g}s: {' '.join(command)}",
            file=sys.stderr,
        )
        return 124
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
