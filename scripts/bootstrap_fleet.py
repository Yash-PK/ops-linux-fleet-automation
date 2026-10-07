#!/usr/bin/env python3
"""Install locked Ansible collections and the optional macOS VM provider locally."""

import hashlib
import io
import json
import platform
import subprocess
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

from paths import bounded

ROOT = Path(__file__).resolve().parents[1]


def download(asset, limit=100_000_000):
    if not asset["url"].startswith("https://"):
        raise SystemExit("Refusing non-TLS dependency URL")
    with urllib.request.urlopen(asset["url"], timeout=90) as response:
        data = response.read(limit + 1)
    if len(data) > limit or hashlib.sha256(data).hexdigest() != asset["sha256"]:
        raise SystemExit("Dependency size or SHA256 mismatch")
    return data


def main():
    lock = json.loads((ROOT / "collections.lock.json").read_text())
    bounded(ROOT, ROOT / ".ansible/collections")
    for item in lock["collections"]:
        namespace, name = item["name"].split(".")
        installed = bounded(
            ROOT,
            (
                ROOT
                / ".ansible/collections/ansible_collections"
                / namespace
                / name
                / "MANIFEST.json"
            ),
        )
        if (
            installed.exists()
            and json.loads(installed.read_text())["collection_info"]["version"] == item["version"]
        ):
            print(f"Collection {item['name']} {item['version']}: installed")
            continue
        data = download(item, 20_000_000)
        cache = bounded(ROOT, ROOT / ".tools/downloads")
        cache.mkdir(parents=True, exist_ok=True)
        archive = bounded(ROOT, cache / f"{namespace}-{name}-{item['version']}.tar.gz")
        archive.write_bytes(data)
        subprocess.run(
            [
                str(ROOT / ".venv/bin/ansible-galaxy"),
                "collection",
                "install",
                str(archive),
                "--collections-path",
                str(ROOT / ".ansible/collections"),
                "--offline",
                "--no-deps",
            ],
            cwd=ROOT,
            check=True,
            timeout=120,
        )
    provider = json.loads((ROOT / "provider.lock.json").read_text())
    key = f"{platform.system()}-{platform.machine()}"
    if key not in provider["tool"]["platforms"]:
        print(f"VM provider UNAVAILABLE on {key}; static controller checks remain supported")
        return
    asset = provider["tool"]["platforms"][key]
    destination = bounded(ROOT, ROOT / ".tools/lima")
    binary = bounded(ROOT, destination / "bin/limactl")
    receipt = bounded(ROOT, destination / ".verified-artifact")
    if binary.exists() and receipt.exists():
        if receipt.read_text().split() == [
            asset["sha256"],
            hashlib.sha256(binary.read_bytes()).hexdigest(),
        ]:
            print(f"Lima {provider['tool']['version']}: verified local install")
            return
    data = download(asset)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for entry in archive:
            name = PurePosixPath(entry.name)
            if name.is_absolute() or ".." in name.parts:
                raise SystemExit("Unsafe provider archive member")
            # Do not follow or recreate archive symlinks/hardlinks. limactl and its
            # shared templates/assets are regular files; the lima alias is unused.
            if not entry.isfile():
                continue
            if entry.size > 100_000_000:
                raise SystemExit("Oversized provider member")
            path = bounded(ROOT, destination / name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(entry).read())
            path.chmod(0o755 if entry.mode & 0o111 else 0o644)
    if not binary.is_file():
        raise SystemExit("Provider executable missing from verified archive")
    receipt.write_text(
        asset["sha256"] + " " + hashlib.sha256(binary.read_bytes()).hexdigest() + "\n"
    )
    subprocess.run([str(binary), "--version"], check=True, timeout=10)
    print("Collections and provider installed only inside this repository.")


if __name__ == "__main__":
    main()
