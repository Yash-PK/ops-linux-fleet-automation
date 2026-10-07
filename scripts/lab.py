#!/usr/bin/env python3
"""Owned, local Lima VM lifecycle with pinned images and strict SSH trust.

Every mutation defaults to dry-run. This provider never targets the user's
ordinary Lima home, host SSH configuration or existing virtual machines.
"""

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import shlex
import socket
import stat
import subprocess
import sys
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB_ID = "ops-fleet-reference"
OWNER = "ops-linux-fleet-automation"
INSTANCES = {"ubuntu": "ops-fleet-ubuntu", "alma": "ops-fleet-alma"}
SSH = "/usr/bin/ssh"
SSH_KEYGEN = "/usr/bin/ssh-keygen"
MAX_IMAGE = 4 * 1024**3


class LabError(RuntimeError):
    """Fail closed when identity, platform, inputs or lifecycle do not match."""


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise LabError(f"refusing non-owned regular file: {path.name}")
    return path


def write_private(path, content, mode=0o600):
    if path.exists() or path.is_symlink():
        regular(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), mode)
        handle.write(content)


def json_read(path):
    regular(path)
    if path.stat().st_size > 1024 * 1024:
        raise LabError("metadata exceeds size limit")
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class Lab:
    def __init__(self, root=ROOT):
        self.root = Path(root).absolute()
        if self.root.is_symlink() or self.root.resolve() != self.root:
            raise LabError("repository root must be a canonical non-symlink path")
        self.runtime = self.root / ".runtime"
        self.home = self.runtime / "lima"
        self.state_path = self.runtime / "lab-state.json"
        self.tool = self.root / ".tools/lima/bin/limactl"
        self.lock_path = self.root / "provider.lock.json"

    def child(self, relative):
        path = self.runtime / relative
        if not path.is_relative_to(self.runtime):
            raise LabError("runtime path escaped repository")
        current = self.runtime
        for component in path.relative_to(self.runtime).parts:
            if component in {"..", "."}:
                raise LabError("unsafe runtime path component")
            if current.is_symlink():
                raise LabError("runtime path contains a symlink")
            if current.exists() and current.stat().st_uid != os.getuid():
                raise LabError("runtime directory not owned by current user")
            current /= component
        if current.is_symlink():
            raise LabError("runtime path is a symlink")
        return path

    def directory(self, relative):
        path = self.child(relative)
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not path.is_dir() or path.stat().st_uid != os.getuid():
            raise LabError("runtime directory ownership mismatch")
        path.chmod(0o700)
        return path

    def lock(self):
        data = json_read(self.lock_path)
        if data.get("schema_version") != 1 or data.get("tool", {}).get("name") != "lima":
            raise LabError("unsupported provider lock schema")
        version = data["tool"].get("version", "")
        if not re.fullmatch(r"2\.2\.[1-9][0-9]*", version):
            raise LabError("provider requires verified Lima 2.2.1 or later 2.2 patch")
        for distro in INSTANCES:
            image = data.get("images", {}).get(distro, {})
            location = urllib.parse.urlparse(image.get("url", ""))
            if location.scheme != "https" or location.hostname not in {
                "cloud-images.ubuntu.com",
                "repo.almalinux.org",
            }:
                raise LabError("image must use an approved official HTTPS origin")
            if (
                not re.fullmatch(r"[0-9a-f]{64}", image.get("sha256", ""))
                or image.get("arch") != "aarch64"
            ):
                raise LabError("image requires SHA-256 and native aarch64 architecture")
        return data

    def state(self, initialize=False):
        self.child("lab-state.json")
        if not self.state_path.exists():
            if not initialize:
                raise LabError("lab not initialized; create an explicitly named instance first")
            if self.home.exists() and any(self.home.iterdir()):
                raise LabError("unregistered Lima home is nonempty; refusing adoption")
            return {
                "schema_version": 1,
                "lab_id": LAB_ID,
                "managed_by": OWNER,
                "repository": str(self.root),
                "instances": {},
            }
        state = json_read(self.state_path)
        if (
            state.get("schema_version") != 1
            or state.get("lab_id") != LAB_ID
            or state.get("managed_by") != OWNER
            or state.get("repository") != str(self.root)
            or not isinstance(state.get("instances"), dict)
        ):
            raise LabError("lab state identity mismatch; refusing foreign resources")
        for distro, record in state["instances"].items():
            if (
                distro not in INSTANCES
                or not isinstance(record, dict)
                or record.get("name") != INSTANCES[distro]
            ):
                raise LabError("lab state contains an unrecognized instance")
        return state

    def save(self, state):
        write_private(self.state_path, json.dumps(state, indent=2, sort_keys=True) + "\n")

    @contextmanager
    def exclusive(self):
        if self.runtime.is_symlink():
            raise LabError("runtime root cannot be a symlink")
        self.runtime.mkdir(mode=0o700, exist_ok=True)
        if self.runtime.stat().st_uid != os.getuid():
            raise LabError("runtime root ownership mismatch")
        self.runtime.chmod(0o700)
        lock = self.child("provider-operation.lock")
        descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LabError("another provider operation is in progress") from exc
            yield

    def environment(self, distro=None):
        # The allowlist never forwards SSH_AUTH_SOCK, cloud credentials or proxies.
        result = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
            "LIMA_HOME": str(self.home),
            "LIMA_CACHE_HOME": str(self.runtime / "cache"),
            "LC_ALL": "C",
            "TMPDIR": str(self.runtime / "tmp"),
        }
        if distro:
            result["SSH"] = shlex.quote(str(self.child(f"transport/{INSTANCES[distro]}/ssh")))
        return result

    def run(self, arguments, *, distro=None, timeout=120, log="provider"):
        # Lima merges these files after reading the instance config. This lab
        # owns the full LIMA_HOME and permits no implicit global overrides.
        for name in ("default.yaml", "override.yaml"):
            implicit = self.child(f"lima/_config/{name}")
            if implicit.exists():
                raise LabError("Implicit Lima global configuration is forbidden in this lab")
        self.directory("logs")
        self.directory("tmp")
        path = self.child(f"logs/{log}.log")
        descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                result = subprocess.run(
                    [str(item) for item in arguments],
                    cwd=self.root,
                    env=self.environment(distro),
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise LabError(f"{log} timed out; inspect ignored runtime log") from exc
        if result.returncode:
            raise LabError(
                f"{log} failed with exit {result.returncode}; inspect ignored runtime log"
            )
        return path.read_text(encoding="utf-8")

    def require_platform(self):
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise LabError(
                "implemented provider requires macOS arm64 with Apple Virtualization.framework"
            )
        if int(platform.mac_ver()[0].split(".")[0]) < 13:
            raise LabError("VZ requires macOS 13 or newer")

    def require_tool(self):
        locked = self.lock()
        if not self.tool.is_file():
            raise LabError("project-local Lima absent; run make bootstrap")
        version = self.run([self.tool, "--version"], timeout=10, log="lima-version").strip()
        if version != f"limactl version {locked['tool']['version']}":
            raise LabError("local Lima version differs from provider lock")

    def image(self, distro):
        spec = self.lock()["images"][distro]
        folder = self.directory("images")
        destination = folder / f"{distro}-{spec['sha256']}.qcow2"
        self.child(destination.relative_to(self.runtime))
        if destination.exists():
            regular(destination)
            if digest(destination) != spec["sha256"]:
                raise LabError("cached image digest mismatch; refusing to replace it automatically")
            return destination
        temporary = destination.with_suffix(".part")
        if temporary.exists() or temporary.is_symlink():
            raise LabError(
                "partial download exists; review/remove only that lab-owned file before retry"
            )
        expected = hashlib.sha256()
        total = 0
        try:
            with (
                urllib.request.urlopen(spec["url"], timeout=60) as response,
                temporary.open("xb") as output,
            ):
                final = urllib.parse.urlparse(response.url)
                if (
                    final.scheme != "https"
                    or final.hostname != urllib.parse.urlparse(spec["url"]).hostname
                ):
                    raise LabError("image redirected outside its approved HTTPS origin")
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > MAX_IMAGE:
                        raise LabError("cloud image exceeded 4 GiB download limit")
                    expected.update(block)
                    output.write(block)
            if expected.hexdigest() != spec["sha256"]:
                raise LabError("downloaded cloud image digest mismatch")
            temporary.chmod(0o600)
            temporary.rename(destination)
            return destination
        except BaseException:
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()
            raise

    @staticmethod
    def free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return listener.getsockname()[1]

    def wrapper(self, distro):
        name = INSTANCES[distro]
        known = self.child(f"transport/{name}/known_hosts")
        options = [
            SSH,
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "NoHostAuthenticationForLocalhost=no",
            "-o",
            f"UserKnownHostsFile={known}",
            "-o",
            f"HostKeyAlias={name}",
            "-o",
            "HostKeyAlgorithms=ssh-ed25519",
            "-o",
            "UpdateHostKeys=no",
            "-o",
            "IdentityAgent=none",
            "-o",
            "ForwardAgent=no",
            "-o",
            "BatchMode=yes",
        ]
        return "#!/bin/sh\nset -eu\nexec " + shlex.join(options) + ' "$@"\n'

    def config(self, distro, image, port, private_key, public_key):
        name = INSTANCES[distro]
        marker = json.dumps({"lab_id": LAB_ID, "managed_by": OWNER}, sort_keys=True) + "\n"
        bootstrap = """#!/bin/sh
set -eu
if command -v restorecon >/dev/null 2>&1; then
    restorecon /etc/ssh/ssh_host_ed25519_key /etc/ssh/ssh_host_ed25519_key.pub
fi
/usr/sbin/sshd -t
if systemctl list-unit-files ssh.service --no-legend | grep -q '^ssh.service'; then
    systemctl reload-or-restart ssh.service
else
    systemctl reload-or-restart sshd.service
fi
"""
        return {
            "minimumLimaVersion": self.lock()["tool"]["version"],
            "vmType": "vz",
            "arch": "aarch64",
            "images": [
                {
                    "location": str(image),
                    "arch": "aarch64",
                    "digest": "sha256:" + self.lock()["images"][distro]["sha256"],
                }
            ],
            "cpus": 2,
            "memory": "2GiB",
            "disk": "24GiB",
            "plain": True,
            "mounts": [],
            "networks": [],
            "portForwards": [],
            "copyToHost": [],
            "containerd": {"system": False, "user": False},
            "upgradePackages": False,
            "ssh": {
                "localPort": port,
                "loadDotSSHPubKeys": False,
                "forwardAgent": False,
                "forwardX11": False,
                "forwardX11Trusted": False,
                "overVsock": False,
            },
            "user": {
                "name": "ops-control",
                "comment": "Disposable ops reference controller",
                "uid": 1001,
                "home": "/home/ops-control",
                "shell": "/bin/bash",
                "passwordlessSudo": True,
            },
            "propagateProxyEnv": False,
            "env": {
                key: ""
                for key in (
                    "http_proxy",
                    "https_proxy",
                    "ftp_proxy",
                    "no_proxy",
                    "HTTP_PROXY",
                    "HTTPS_PROXY",
                    "FTP_PROXY",
                    "NO_PROXY",
                )
            },
            "vmOpts": {
                "vz": {"rosetta": {"enabled": False, "binfmt": False}, "diskImageFormat": "raw"}
            },
            "provision": [
                {
                    "mode": "data",
                    "path": "/etc/ssh/ssh_host_ed25519_key",
                    "content": private_key,
                    "owner": "root:root",
                    "permissions": "0600",
                    "overwrite": True,
                },
                {
                    "mode": "data",
                    "path": "/etc/ssh/ssh_host_ed25519_key.pub",
                    "content": public_key,
                    "owner": "root:root",
                    "permissions": "0644",
                    "overwrite": True,
                },
                {
                    "mode": "data",
                    "path": "/etc/ops-fleet-lab.json",
                    "content": marker,
                    "owner": "root:root",
                    "permissions": "0644",
                    "overwrite": False,
                },
                {"mode": "system", "script": bootstrap},
            ],
            "message": f"{name}: lab reference VM; verify runtime inventory before connecting",
        }

    def verify_record(self, distro, record):
        name = INSTANCES[distro]
        if (
            record.get("name") != name
            or record.get("image_sha256") != self.lock()["images"][distro]["sha256"]
        ):
            raise LabError("recorded instance or image identity mismatch")
        for relative, key in (
            (f"configs/{name}.json", "config_sha256"),
            (f"transport/{name}/host_ed25519.pub", "public_key_sha256"),
            (f"transport/{name}/known_hosts", "known_hosts_sha256"),
            (f"transport/{name}/ssh", "wrapper_sha256"),
        ):
            path = regular(self.child(relative))
            if digest(path) != record.get(key):
                raise LabError(
                    "recorded provider configuration or SSH trust changed; refusing operation"
                )
        if type(record.get("port")) is not int or not 1024 <= record["port"] <= 65535:
            raise LabError("invalid recorded localhost SSH port")
        instance_path = self.child(f"lima/{name}")
        if len(str(instance_path / "ssh.sock").encode()) >= 104:
            raise LabError("Lima socket path too long for macOS; use a shorter checkout path")

    def record_instance(self, distro, state):
        name = INSTANCES[distro]
        path = self.child(f"lima/{name}")
        actual_config = regular(path / "lima.yaml")
        identity = {
            "lab_id": LAB_ID,
            "managed_by": OWNER,
            "instance": name,
            "repository": str(self.root),
        }
        write_private(path / ".ops-fleet-owner.json", json.dumps(identity, sort_keys=True) + "\n")
        state["instances"][distro]["lima_config_sha256"] = digest(actual_config)
        state["instances"][distro]["status"] = "created"
        self.save(state)

    def verify_instance(self, distro, record):
        self.verify_record(distro, record)
        name = INSTANCES[distro]
        folder = self.child(f"lima/{name}")
        identity = json_read(folder / ".ops-fleet-owner.json")
        if identity != {
            "lab_id": LAB_ID,
            "managed_by": OWNER,
            "instance": name,
            "repository": str(self.root),
        }:
            raise LabError("instance ownership marker mismatch")
        if digest(regular(folder / "lima.yaml")) != record.get("lima_config_sha256"):
            raise LabError("instance Lima configuration changed; refusing unmanaged edits")

    def create(self, distro):
        self.require_platform()
        self.require_tool()
        state = self.state(initialize=True)
        name = INSTANCES[distro]
        if distro in state["instances"]:
            self.verify_record(distro, state["instances"][distro])
            if (self.home / name / "lima.yaml").exists():
                self.verify_instance(distro, state["instances"][distro])
                print(f"Already created owned instance: {name}")
                return
            raise LabError("registered create incomplete; inspect runtime logs before recovery")
        if self.child(f"lima/{name}").exists():
            raise LabError("target Lima instance already exists without matching registry")
        image = self.image(distro)
        self.directory("lima")
        self.directory("configs")
        transport = self.directory(f"transport/{name}")
        if any(transport.iterdir()):
            raise LabError("unregistered transport directory is nonempty")
        key = transport / "host_ed25519"
        self.run(
            [SSH_KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", f"{name}-host", "-f", key],
            log=f"{name}-keygen",
        )
        private_key, public_key = (
            regular(key).read_text(),
            regular(key.with_suffix(".pub")).read_text(),
        )
        if not public_key.startswith("ssh-ed25519 "):
            raise LabError("unexpected generated host key type")
        write_private(
            transport / "known_hosts", name + " " + " ".join(public_key.split()[:2]) + "\n"
        )
        write_private(transport / "ssh", self.wrapper(distro), 0o700)
        port = self.free_port()
        config = self.config(distro, image, port, private_key, public_key)
        path = self.child(f"configs/{name}.json")
        write_private(path, json.dumps(config, indent=2) + "\n")
        state["instances"][distro] = {
            "name": name,
            "port": port,
            "status": "prepared",
            "config_sha256": digest(path),
            "image_sha256": self.lock()["images"][distro]["sha256"],
            "public_key_sha256": digest(key.with_suffix(".pub")),
            "known_hosts_sha256": digest(transport / "known_hosts"),
            "wrapper_sha256": digest(transport / "ssh"),
        }
        self.verify_record(distro, state["instances"][distro])
        self.save(state)
        self.run(
            [self.tool, "create", "--tty=false", f"--name={name}", path],
            distro=distro,
            timeout=300,
            log=f"{name}-create",
        )
        self.record_instance(distro, state)
        self.inventory()
        print(f"Created owned instance: {name}; no VM boot requested")

    def actual_instances(self):
        raw = self.run(
            [self.tool, "list", "--json", "--all-fields"], timeout=30, log="instance-list"
        )
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
        result = {}
        for record in records:
            name = record.get("name")
            if name not in INSTANCES.values() or Path(record.get("dir", "")) != self.home / name:
                raise LabError("foreign instance detected inside dedicated Lima home")
            result[name] = record
        return result

    def start(self, distro):
        self.create(distro)
        state = self.state()
        self.verify_instance(distro, state["instances"][distro])
        instances = self.actual_instances()
        name = INSTANCES[distro]
        for other, record in instances.items():
            if other != name and record.get("status") == "Running":
                raise LabError("another lab VM is running; stop it before this sequential profile")
        if instances.get(name, {}).get("status") != "Running":
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                try:
                    listener.bind(("127.0.0.1", state["instances"][distro]["port"]))
                except OSError as exc:
                    raise LabError(
                        "reserved localhost SSH port is already in use; no unrelated process changed"
                    ) from exc
        self.run(
            [self.tool, "start", "--tty=false", name],
            distro=distro,
            timeout=600,
            log=f"{name}-start",
        )
        # Authenticating this guest must already have used pinned host keys.
        marker = self.run(
            [
                self.tool,
                "shell",
                "--workdir=/home/ops-control",
                name,
                "cat",
                "/etc/ops-fleet-lab.json",
            ],
            distro=distro,
            timeout=30,
            log=f"{name}-identity",
        )
        if json.loads(marker) != {"lab_id": LAB_ID, "managed_by": OWNER}:
            raise LabError("guest lab marker mismatch")
        state["instances"][distro]["status"] = "running"
        self.save(state)
        self.inventory()
        print(f"Started and authenticated owned instance: {name}")

    def inventory(self):
        state = self.state()
        hosts = {}
        for distro, record in state["instances"].items():
            self.verify_record(distro, record)
            name = INSTANCES[distro]
            host = {
                "ansible_connection": "ssh",
                "ansible_host": "127.0.0.1",
                "ansible_port": record["port"],
                "ansible_user": "ops-control",
                "ansible_ssh_private_key_file": str(self.home / "_config/user"),
                "ansible_ssh_executable": str(self.child(f"transport/{name}/ssh")),
                "ansible_ssh_common_args": "-F "
                + shlex.quote(str(self.home / name / "ssh.config")),
                "ansible_ssh_transfer_method": "piped",
                "ansible_pipelining": True,
                "ansible_python_interpreter": "/usr/bin/python3",
                "ops_lab_owned": True,
                "ops_lab_id": LAB_ID,
            }
            hosts[name] = host
            single = {"all": {"children": {"fleet_lab": {"hosts": {name: host}}}}}
            write_private(
                self.child(f"inventory-{distro}.json"), json.dumps(single, indent=2) + "\n"
            )
        combined = {"all": {"children": {"fleet_lab": {"hosts": hosts}}}}
        write_private(self.child("inventory.json"), json.dumps(combined, indent=2) + "\n")
        return combined

    def stop(self, distro):
        self.require_platform()
        self.require_tool()
        state = self.state()
        if distro not in state["instances"]:
            raise LabError("instance is not in the owned registry")
        self.verify_instance(distro, state["instances"][distro])
        self.actual_instances()
        name = INSTANCES[distro]
        self.run([self.tool, "stop", name], distro=distro, timeout=120, log=f"{name}-stop")
        state["instances"][distro]["status"] = "stopped"
        self.save(state)
        print(f"Stopped owned instance: {name}")

    def destroy(self, distro):
        self.require_platform()
        self.require_tool()
        state = self.state()
        if distro not in state["instances"]:
            raise LabError("instance is not in the owned registry")
        self.verify_instance(distro, state["instances"][distro])
        instances = self.actual_instances()
        name = INSTANCES[distro]
        if name in instances and instances[name].get("status") == "Running":
            self.stop(distro)
        # Never use --force: unexpected running/busy states must fail visibly.
        self.run(
            [self.tool, "delete", "--tty=false", name],
            distro=distro,
            timeout=120,
            log=f"{name}-delete",
        )
        del state["instances"][distro]
        self.save(state)
        # Delete exactly the recorded regular transport/config files; no recursive delete.
        for relative in (
            f"configs/{name}.json",
            f"inventory-{distro}.json",
            f"transport/{name}/host_ed25519",
            f"transport/{name}/host_ed25519.pub",
            f"transport/{name}/known_hosts",
            f"transport/{name}/ssh",
        ):
            path = self.child(relative)
            if path.exists():
                regular(path).unlink()
        self.child(f"transport/{name}").rmdir()
        self.inventory()
        print(
            f"Deleted owned instance and its private host key: {name}; verified image cache retained"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("doctor", "create", "start", "inventory", "stop", "destroy")
    )
    parser.add_argument("--distro", choices=tuple(INSTANCES))
    parser.add_argument("--lab-id")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    try:
        lab = Lab()
        if args.action == "doctor":
            lab.require_platform()
            locked = lab.lock()
            print(
                json.dumps(
                    {
                        "provider": "Lima VZ",
                        "locked_version": locked["tool"]["version"],
                        "local_tool_present": lab.tool.is_file(),
                        "qemu_img_required": False,
                        "resources_per_vm": "2 CPU, 2 GiB RAM, 24 GiB sparse disk",
                        "status": "prerequisite inspection only",
                    }
                )
            )
            return 0
        if args.lab_id != LAB_ID:
            raise LabError(f"explicit --lab-id {LAB_ID} required")
        if args.action != "inventory" and args.distro is None:
            raise LabError("an explicit --distro is required")
        if args.action != "inventory" and not args.execute:
            print(f"DRY RUN: {args.action} {INSTANCES[args.distro]} in repository-owned Lima home")
            return 0
        if args.action == "destroy" and args.confirm != LAB_ID:
            raise LabError(f"destroy requires --confirm {LAB_ID}")
        with lab.exclusive():
            if args.action == "inventory":
                lab.inventory()
                print("Wrote ignored runtime inventory; credentials were not printed")
            else:
                getattr(lab, args.action)(args.distro)
        return 0
    except (LabError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
