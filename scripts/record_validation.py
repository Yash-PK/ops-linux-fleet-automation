#!/usr/bin/env python3
"""Run documented gates and record actual revision, commands and exit codes."""

import argparse
import datetime
import json
import platform
import subprocess
import time
from pathlib import Path

from integration import code_digest

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["local"], default="local")
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if dirty:
        raise SystemExit("Commit changes first: evidence must identify clean tested source")
    fingerprint = code_digest()
    commands = [["make", "doctor"], ["make", "validate"], ["make", "demo"], ["make", "security"]]
    report = {
        "schema_version": 1,
        "revision": revision,
        "code_sha256": fingerprint,
        "clean_at_start": True,
        "environment": {
            "os": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "profile": args.profile,
        "commands": [],
    }
    for command in commands:
        start = time.monotonic()
        try:
            result = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=600,
            )
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout or b""
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", errors="replace")
            result = subprocess.CompletedProcess(
                command, 124, partial + "\nTIMEOUT after 600 seconds\n"
            )
        output = result.stdout.replace(str(ROOT), "$REPO").replace(str(Path.home()), "$HOME")
        report["commands"].append(
            {
                "argv": command,
                "exit_code": result.returncode,
                "duration_seconds": round(time.monotonic() - start, 3),
                "output": output,
            }
        )
        print(f"{' '.join(command)}: exit {result.returncode}", flush=True)
    report["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    final_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    report["source_unchanged"] = final_revision == revision and code_digest() == fingerprint
    report["passed"] = report["source_unchanged"] and all(
        item["exit_code"] == 0 for item in report["commands"]
    )
    folder = ROOT / "evidence"
    if folder.is_symlink():
        raise SystemExit("Refusing symlink evidence directory")
    folder.mkdir(exist_ok=True)
    destination = folder / f"{revision[:12]}-{args.profile}.json"
    if destination.is_symlink():
        raise SystemExit("Refusing symlink evidence file")
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(destination.relative_to(ROOT))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
