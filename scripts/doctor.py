#!/usr/bin/env python3
"""Report non-sensitive relevant versions; missing required tools exit nonzero."""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.environ["PATH"] = str(ROOT / ".venv/bin") + os.pathsep + os.environ.get("PATH", "")
    os.environ["ANSIBLE_HOME"] = str(ROOT / ".runtime/ansible-home")
    print(f"OS={platform.system()} arch={platform.machine()} Python={platform.python_version()}")
    failed = not (3, 12) <= sys.version_info[:2] <= (3, 14)
    commands = [
        [str(ROOT / ".venv/bin/ansible-playbook"), "--version"],
        [str(ROOT / ".venv/bin/ansible-lint"), "--version"],
        [str(ROOT / ".venv/bin/molecule"), "--version"],
        ["git", "--version"],
        ["bash", "--version"],
        [str(ROOT / ".venv/bin/ruff"), "--version"],
        [str(ROOT / ".tools/bin/shellcheck"), "--version"],
        [str(ROOT / ".tools/bin/shfmt"), "--version"],
        [str(ROOT / ".tools/bin/actionlint"), "--version"],
        [str(ROOT / ".tools/bin/gitleaks"), "version"],
    ]
    for command in commands:
        if not shutil.which(command[0]):
            print(f"REQUIRED MISSING: {Path(command[0]).name}; run make bootstrap")
            failed = True
            continue
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        print(result.stdout.strip())
        failed |= result.returncode != 0
    if platform.system() != "Linux":
        print(
            "Real VM integration uses the separate scoped Lima provider; static checks are not VM evidence."
        )
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
