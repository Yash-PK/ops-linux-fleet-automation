#!/usr/bin/env python3
"""Exercise one explicitly owned real VM, record evidence, and tear it down."""

import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from guest_metadata import PACKAGES
from lab import INSTANCES, LAB_ID, Lab, LabError

ROOT = Path(__file__).resolve().parents[1]
CODE_PATHS = (
    "scripts",
    "tests",
    "roles",
    "playbooks",
    "molecule",
    ".github",
    "ansible.cfg",
    "Makefile",
    "pyproject.toml",
    ".python-version",
    "requirements-dev.in",
    "requirements-dev.lock",
    "tools.lock.json",
    "provider.lock.json",
    "collections.lock.json",
)
REQUIRED_STEPS = (
    "ssh-reject-changed-key",
    "molecule",
    "reject-invalid",
    "verify-unchanged",
    "change",
    "verify-change",
    "restore",
    "verify-restored",
    "patch-reboot",
)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def code_digest(root=ROOT):
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *CODE_PATHS],
        cwd=root,
    ).split(b"\0")
    digest = hashlib.sha256()
    for name in sorted(set(names) - {b""}):
        path = root / os.fsdecode(name)
        if path.is_symlink() or not path.is_file():
            raise LabError("Code fingerprint requires regular project files")
        digest.update(name + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def verify_evidence(root=ROOT):
    expected = code_digest(root)
    for distro in INSTANCES:
        reports = []
        for path in (root / "evidence").glob(f"*-{distro}-vm.json"):
            value = json.loads(path.read_text())
            guest = value.get("guest_metadata", {})
            distribution = "ubuntu" if distro == "ubuntu" else "almalinux"
            if (
                value.get("schema_version") == 1
                and value.get("profile") == "real-vm"
                and value.get("distro") == distro
                and value.get("boot_authenticated") is True
                and value.get("lifecycle_passed") is True
                and guest.get("os", {}).get("ID") == distribution
                and guest.get("architecture") == "aarch64"
                and set(guest.get("package_versions", {})) == set(PACKAGES[distribution])
                and [step.get("name") for step in value.get("commands", [])] == list(REQUIRED_STEPS)
                and all(step.get("passed") is True for step in value.get("commands", []))
                and value.get("code_sha256") == expected
                and value.get("passed") is True
                and value.get("clean_at_start") is True
                and value.get("cleanup_passed") is True
            ):
                reports.append(path)
        if not reports:
            raise LabError(f"Required real {distro} VM evidence missing for this code fingerprint")
        print(f"Required {distro} VM evidence: {reports[-1].relative_to(root)}")


def environment(lab, distro):
    # Do not forward cloud credentials, SSH agents, user Ansible config or proxy secrets.
    result = {
        "PATH": str(ROOT / ".venv/bin") + ":/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(Path.home()),
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "ANSIBLE_CONFIG": str(ROOT / "ansible.cfg"),
        "ANSIBLE_HOME": str(lab.directory("ansible-home")),
        "ANSIBLE_LOCAL_TEMP": str(lab.directory("ansible-tmp")),
        "XDG_CACHE_HOME": str(lab.directory("controller-cache")),
        "ANSIBLE_NOCOLOR": "1",
        "NO_COLOR": "1",
        "ANSIBLE_HOST_KEY_CHECKING": "True",
        "ANSIBLE_INVENTORY": str(lab.child(f"inventory-{distro}.json")),
        "OPS_FLEET_INVENTORY": str(lab.child(f"inventory-{distro}.json")),
    }
    return result


def execute(report, lab, distro, name, command, *, timeout=900, reject=False, reject_hostkey=False):
    print(f"VM {distro}: {name}", flush=True)
    started = time.monotonic()
    path = lab.child(f"logs/integration-{distro}-{name}.log")
    lab.directory("logs")
    timed_out = False
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        try:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=environment(lab, distro),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            code = result.returncode
        except subprocess.TimeoutExpired:
            code, timed_out = 124, True
    output = path.read_text()
    # Publish only known recap/counter lines; raw facts, paths and logs remain ignored.
    recaps = re.findall(
        r"^(?:ops-fleet-(?:ubuntu|alma)|localhost)\s+:\s+ok=\d+[^\n]*$", output, re.MULTILINE
    )
    accepted = code == 0
    if reject:
        accepted = (
            code == 2
            and "Invalid baseline configuration" in output
            and bool(recaps)
            and all("changed=0" in line for line in recaps)
        )
    if reject_hostkey:
        accepted = code == 255 and "REMOTE HOST IDENTIFICATION HAS CHANGED" in output
    step = {
        "name": name,
        "argv": [str(v).replace(str(ROOT), "$REPO") for v in command],
        "exit_code": code,
        "expected": (
            "changed host key rejected"
            if reject_hostkey
            else "policy rejection with zero changes"
            if reject
            else "exit zero"
        ),
        "passed": accepted and not timed_out,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 3),
        "recaps": recaps,
        "runtime_log": str(path.relative_to(ROOT)),
    }
    report["commands"].append(step)
    if not step["passed"]:
        raise LabError(f"{name} failed (exit {code}); inspect ignored {path.relative_to(ROOT)}")


def run(distro, development=False):
    lab = Lab(ROOT)
    lab.require_platform()
    lab.require_tool()
    revision = (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
        or None
    )
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    clean = bool(revision) and not dirty
    if not clean and not development:
        raise LabError(
            "Commit source first; --development records unreleased ignored diagnostics only"
        )
    report = {
        "schema_version": 1,
        "profile": "real-vm",
        "distro": distro,
        "revision": revision,
        "code_sha256": code_digest(),
        "clean_at_start": clean,
        "started_at": now(),
        "environment": {
            "os": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
        },
        "provider": lab.lock(),
        "tool_versions": {
            name: importlib.metadata.version(name)
            for name in ("ansible-core", "ansible-lint", "molecule")
        },
        "commands": [],
        "cleanup_passed": False,
        "passed": False,
    }
    cleanup_owned = False
    try:
        # Exclusive provider operations each revalidate registry and ownership.
        with lab.exclusive():
            state = lab.state(initialize=True)
            if distro in state["instances"]:
                raise LabError(
                    "Integration requires a clean new instance; explicitly teardown existing lab first"
                )
            cleanup_owned = True
            lab.start(distro)
        report["boot_authenticated"] = True
        # A separate synthetic wrong trust file must reject the running VM. Do not
        # alter the enrolled key, VM host key or user's SSH trust/configuration.
        with tempfile.TemporaryDirectory(prefix="hostkey-negative-", dir=lab.runtime) as folder:
            key = Path(folder) / "wrong"
            subprocess.run(
                [
                    "/usr/bin/ssh-keygen",
                    "-q",
                    "-t",
                    "ed25519",
                    "-N",
                    "",
                    "-C",
                    "synthetic-negative-test",
                    "-f",
                    str(key),
                ],
                check=True,
                timeout=30,
                stdin=subprocess.DEVNULL,
            )
            known = Path(folder) / "known_hosts"
            known.write_text(INSTANCES[distro] + " " + key.with_suffix(".pub").read_text())
            known.chmod(0o600)
            execute(
                report,
                lab,
                distro,
                "ssh-reject-changed-key",
                [
                    "/usr/bin/ssh",
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    "NoHostAuthenticationForLocalhost=no",
                    "-o",
                    f"UserKnownHostsFile={known}",
                    "-o",
                    f"HostKeyAlias={INSTANCES[distro]}",
                    "-o",
                    "HostKeyAlgorithms=ssh-ed25519",
                    "-o",
                    "ControlMaster=no",
                    "-o",
                    "ControlPath=none",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "IdentityAgent=none",
                    "-F",
                    str(lab.home / INSTANCES[distro] / "ssh.config"),
                    f"lima-{INSTANCES[distro]}",
                    "true",
                ],
                timeout=30,
                reject_hostkey=True,
            )
        playbook = str(ROOT / ".venv/bin/ansible-playbook")
        inventory = str(lab.child(f"inventory-{distro}.json"))
        base = [playbook, "-i", inventory]
        execute(
            report,
            lab,
            distro,
            "molecule",
            [str(ROOT / ".venv/bin/molecule"), "test", "-s", "default"],
            timeout=1800,
        )
        execute(
            report,
            lab,
            distro,
            "reject-invalid",
            base + ["playbooks/site.yml", "-e", "@tests/fixtures/invalid-port.json"],
            reject=True,
        )
        execute(report, lab, distro, "verify-unchanged", base + ["playbooks/verify.yml"])
        change = json.dumps({"ops_baseline_web_content": "ops-fleet changed v2"})
        execute(report, lab, distro, "change", base + ["playbooks/site.yml", "-e", change])
        execute(report, lab, distro, "verify-change", base + ["playbooks/verify.yml", "-e", change])
        execute(report, lab, distro, "restore", base + ["playbooks/site.yml"])
        execute(report, lab, distro, "verify-restored", base + ["playbooks/verify.yml"])
        patch = json.dumps(
            {"ops_baseline_patch_confirm": LAB_ID, "ops_baseline_patch_reboot": True}
        )
        execute(
            report,
            lab,
            distro,
            "patch-reboot",
            base + ["playbooks/patch.yml", "-e", patch],
            timeout=1800,
        )
        report["guest_metadata"] = json.loads(
            lab.run(
                [
                    lab.tool,
                    "shell",
                    "--workdir=/home/ops-control",
                    INSTANCES[distro],
                    "/usr/bin/python3",
                    "-c",
                    (ROOT / "scripts/guest_metadata.py").read_text(),
                ],
                distro=distro,
                timeout=60,
                log=f"{distro}-metadata",
            )
        )
        report["lifecycle_passed"] = True
    except (LabError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["failure"] = str(error).replace(str(ROOT), "$REPO")
        print(f"FAILED: {report['failure']}", file=sys.stderr)
    finally:
        try:
            with lab.exclusive():
                state = lab.state(initialize=True)
                if cleanup_owned and distro in state["instances"]:
                    lab.destroy(distro)
                report["cleanup_passed"] = (
                    cleanup_owned and distro not in lab.state(initialize=True)["instances"]
                )
        except (LabError, OSError, subprocess.SubprocessError) as error:
            report["cleanup_failure"] = str(error).replace(str(ROOT), "$REPO")
            print("Cleanup blocked; follow explicit scoped recovery in runbook", file=sys.stderr)
        report["finished_at"] = now()
        report["passed"] = (
            report.get("lifecycle_passed", False)
            and report["cleanup_passed"]
            and code_digest() == report["code_sha256"]
        )
        destination = lab.child(f"integration-{distro}.json")
        destination.write_text(json.dumps(report, indent=2) + "\n")
        destination.chmod(0o600)
        if clean and not development:
            folder = ROOT / "evidence"
            if folder.is_symlink():
                raise LabError("Refusing symlink evidence directory")
            folder.mkdir(exist_ok=True)
            destination = folder / f"{revision[:12]}-{distro}-vm.json"
            if destination.is_symlink():
                raise LabError("Refusing symlink evidence file")
            destination.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Evidence: {destination.relative_to(ROOT)}; passed={report['passed']}", flush=True)
    return report["passed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distro", choices=INSTANCES)
    parser.add_argument("--lab-id")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--verify-evidence", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify_evidence:
            verify_evidence()
            return
        if args.lab_id != LAB_ID or not args.distro:
            raise LabError("An explicit --distro and matching --lab-id are required")
        if not args.execute:
            print(
                f"DRY RUN: create, provision, verify, change/restore, patch/reboot, delete {INSTANCES[args.distro]}"
            )
            return
        raise SystemExit(0 if run(args.distro, args.development) else 1)
    except LabError as error:
        raise SystemExit(f"BLOCKED: {error}") from error


if __name__ == "__main__":
    main()
