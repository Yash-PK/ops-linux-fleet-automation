#!/usr/bin/env python3
"""Repository checks with explicit failures; only inspect project-owned files."""

import ast
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {".git", ".venv", ".tools", "__pycache__", ".ruff_cache", ".runtime"}
REQUIRED = [
    "README.md",
    "AGENTS.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "LICENSE",
    "Makefile",
    ".gitignore",
    ".editorconfig",
    ".portfolio.json",
]


def files():
    # git ls-files includes new files before the initial commit, not ignored tools.
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
    )
    return sorted({ROOT / p.decode() for p in output.split(b"\0") if p})


def main():
    errors = []
    for name in REQUIRED:
        if not (ROOT / name).is_file():
            errors.append(f"required file missing: {name}")
    for path in files():
        if path.is_symlink():
            errors.append(f"symlink requires review: {path.relative_to(ROOT)}")
            continue
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in IGNORED for part in relative.parts):
            errors.append(f"ignored build output tracked: {relative}")
        if path.suffix == ".py":
            ast.parse(path.read_text(), filename=str(relative))
        if path.suffix == ".json":
            json.loads(path.read_text())
        if path.suffix == ".md":
            content = path.read_text()
            for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
                link = link.split("#", 1)[0].strip("<>")
                if not link or re.match(r"[a-z]+:", link):
                    continue
                if not (path.parent / link).exists():
                    errors.append(f"broken relative link in {relative}: {link}")
        if path.suffix in {".yml", ".yaml"} and ".github/workflows" in str(relative):
            for line in path.read_text().splitlines():
                match = re.search(r"uses:\s+([^\s]+)", line)
                if match and not re.fullmatch(r"[^@]+@[0-9a-f]{40}", match[1]):
                    errors.append(f"unpinned action in {relative}: {match[1]}")
    if errors:
        raise SystemExit("\n".join(errors))
    print("Repository structure, Python/JSON syntax, local document links and action pins: PASS")


if __name__ == "__main__":
    main()
