#!/usr/bin/env python3
"""Inspect Git index without printing secret values. Not a full secret/history audit."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import PurePosixPath

PUBLIC_REPORTS = (
    "reports/baseline/",
    "reports/evaluation-v0_4/",
    "reports/evaluation-v0_5/",
    "reports/evaluation-quality/",
)
TOKEN = re.compile(
    rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|"
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)
ASSIGNMENT = re.compile(
    rb"(?mi)^[ \t]*(?:BINANCE_API_KEY|BINANCE_API_SECRET|TELEGRAM_BOT_TOKEN)"
    rb"[ \t]*=[ \t]*[^\s\r\n#]+"
)


def forbidden_path(path: str) -> bool:
    p = PurePosixPath(path.lower())
    name = p.name
    if name == ".env" or (name.startswith(".env.") and path != ".env.example"):
        return True
    if any(part in {"backups", "backup", "exports", "logs", ".ssh"} for part in p.parts):
        return True
    if name.endswith(
        (
            ".db",
            ".db-wal",
            ".db-shm",
            ".sqlite",
            ".sqlite3",
            ".sqlite-wal",
            ".sqlite-shm",
            ".sqlite3-wal",
            ".sqlite3-shm",
            ".log",
            ".pem",
            ".key",
            ".p12",
            ".pfx",
            ".zip",
            ".tar",
            ".gz",
        )
    ):
        return True
    if path.startswith("data/") and path != "data/.gitkeep":
        return True
    if path == "config/paper-server.yaml":
        return True
    return path.startswith("reports/") and not path.startswith(PUBLIC_REPORTS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    command = (
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
        if args.staged
        else ["git", "ls-files", "-z"]
    )
    paths = subprocess.check_output(command).decode().split("\0")
    failures = []
    for path in filter(None, paths):
        if forbidden_path(path):
            failures.append((path, "private/runtime file path"))
            continue
        data = subprocess.check_output(["git", "show", ":" + path])
        if TOKEN.search(data) or ASSIGNMENT.search(data):
            failures.append((path, "possible credential; value redacted"))
    for path, reason in failures:
        print(f"BLOCKED {path!r}: {reason}")
    if failures:
        print("Remove sensitive files from the index before commit. Rotate any exposed credential.")
        return 1
    print("Privacy check passed for Git index; history, ports and account settings not audited.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
