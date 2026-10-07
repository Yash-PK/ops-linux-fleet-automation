#!/usr/bin/env python3
"""Credential-free new-repository publication; dry-run unless --execute is given."""

import argparse
import json
import re
import subprocess
from pathlib import Path

from integration import code_digest

ROOT = Path(__file__).resolve().parents[1]


def run(argv, **kwargs):
    return subprocess.run(argv, cwd=ROOT, text=True, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    metadata = json.loads((ROOT / ".portfolio.json").read_text())
    if args.owner != metadata["owner"] or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", args.owner):
        raise SystemExit("Owner differs from saved, user-authorized personal account")
    name = metadata["repository"]
    if ROOT.name != name or not name.startswith("ops-") or metadata["visibility"] != "public":
        raise SystemExit("Repository identity/visibility mismatch")
    target = f"{args.owner}/{name}"
    command = [
        "gh",
        "repo",
        "create",
        target,
        "--public",
        "--source",
        str(ROOT),
        "--remote",
        "origin",
        "--push",
    ]
    if not args.execute:
        print("Dry run; no network calls or changes. Review outgoing files and run:")
        print(" ".join(command))
        print(
            "With --execute this script first validates, scans, verifies identity and checks collision."
        )
        return
    if run(["git", "status", "--porcelain"], capture_output=True).stdout.strip():
        raise SystemExit("Commit/review all outgoing files first")
    if run(["git", "remote"], capture_output=True).stdout.strip():
        raise SystemExit("Remote already exists; this script only creates new repositories")
    initial_revision = run(["git", "rev-parse", "HEAD"], capture_output=True).stdout.strip()
    initial_code = code_digest()
    run(["make", "validate"])
    run(["make", "demo"])
    run(["make", "security"])
    run([str(ROOT / ".venv/bin/python"), "scripts/integration.py", "--verify-evidence"])
    run(["make", "clean-clone"])
    run(["make", "security"])
    run([str(ROOT / ".venv/bin/python"), "scripts/integration.py", "--verify-evidence"])
    if (
        run(["git", "rev-parse", "HEAD"], capture_output=True).stdout.strip() != initial_revision
        or code_digest() != initial_code
    ):
        raise SystemExit("Source changed during publishing gates; review and retry")
    if run(["git", "diff", "--name-only"], capture_output=True).stdout.strip():
        raise SystemExit("Tracked files changed during gates; commit reviewed evidence and retry")
    print(
        "Any new untracked clean-clone report is local evidence; only committed HEAD will be pushed."
    )
    run(["gh", "repo", "create", "--help"], stdout=subprocess.DEVNULL)
    account = json.loads(run(["gh", "api", "user"], capture_output=True).stdout)
    if account["login"] != args.owner or account["type"] != "User":
        raise SystemExit("Authenticated personal account does not match authorized owner")
    # Only a definitive authenticated 404 means the name is available.
    probe = subprocess.run(
        ["gh", "api", f"repos/{target}", "--include"], cwd=ROOT, capture_output=True, text=True
    )
    if probe.returncode == 0:
        raise SystemExit("Repository collision: refusing to reuse, overwrite or rename")
    if not re.search(r"^HTTP/\S+ 404", probe.stdout, flags=re.MULTILINE):
        raise SystemExit("Cannot establish repository absence; publishing blocked")
    run(command)
    details = json.loads(
        run(
            [
                "gh",
                "repo",
                "view",
                target,
                "--json",
                "nameWithOwner,url,visibility,defaultBranchRef",
            ],
            capture_output=True,
        ).stdout
    )
    if details["nameWithOwner"] != target or details["visibility"] != "PUBLIC":
        raise SystemExit("Remote verification failed; inspect without altering visibility")
    local = run(["git", "rev-parse", "HEAD"], capture_output=True).stdout.strip()
    branch = details["defaultBranchRef"]["name"]
    remote = run(
        ["gh", "api", f"repos/{target}/commits/{branch}", "--jq", ".sha"], capture_output=True
    ).stdout.strip()
    if local != remote:
        raise SystemExit("Remote commit differs from reviewed local HEAD")
    print(json.dumps(details, indent=2))
    print(f"Published revision {local}; CI is PENDING until verified for this SHA.")


if __name__ == "__main__":
    main()
