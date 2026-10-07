#!/usr/bin/env python3
"""Read guest OS and installed core package versions without privilege escalation.

Standalone Python 3.9+ source: it may be sent to a guest as ``python3 -c SOURCE``.
Only successful, complete metadata is written to stdout. Failures exit nonzero;
package-manager diagnostics are deliberately not copied into public evidence.
"""

import json
import platform
import re
import shlex
import subprocess
import sys

PACKAGES = {
    "ubuntu": ("nginx", "chrony", "openssh-server", "nftables", "apparmor"),
    "almalinux": ("nginx", "chrony", "openssh-server", "firewalld", "selinux-policy"),
}
TIMEOUT_SECONDS = 10
MAX_OUTPUT_BYTES = 16_384


class MetadataError(Exception):
    """Required metadata is missing, invalid or unavailable."""


def os_release():
    try:
        with open("/etc/os-release", encoding="utf-8") as handle:
            content = handle.read(MAX_OUTPUT_BYTES + 1)
    except (OSError, UnicodeError) as error:
        raise MetadataError("Cannot read guest OS release metadata") from error
    if len(content) > MAX_OUTPUT_BYTES:
        raise MetadataError("Guest OS release metadata exceeds the size limit")
    selected = {}
    for line in content.splitlines():
        name, separator, value = line.partition("=")
        if not separator or name not in {"ID", "NAME", "VERSION_ID"}:
            continue
        try:
            words = shlex.split(value, comments=False, posix=True)
        except ValueError as error:
            raise MetadataError("Malformed guest OS release metadata") from error
        if name in selected or len(words) != 1 or not words[0]:
            raise MetadataError("Ambiguous or missing guest OS release field")
        if len(words[0]) > 128 or any(ord(char) < 32 or ord(char) == 127 for char in words[0]):
            raise MetadataError("Invalid guest OS release field")
        selected[name] = words[0]
    if set(selected) != {"ID", "NAME", "VERSION_ID"}:
        raise MetadataError("Required guest OS release fields are missing")
    if selected["ID"] not in PACKAGES:
        raise MetadataError("Guest distribution is unsupported by this metadata profile")
    return selected


def query(command):
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise MetadataError("Guest package query timed out after 10 seconds") from error
    except (OSError, UnicodeError) as error:
        raise MetadataError(
            "Required guest package query tool is unavailable or unreadable"
        ) from error
    if result.returncode != 0:
        raise MetadataError("Guest package query failed; required packages may be missing")
    # This is a post-capture size check; it is not a subprocess memory bound.
    if len(result.stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise MetadataError("Guest package query output exceeds the size limit")
    return result.stdout


def package_versions(distribution):
    expected = PACKAGES[distribution]
    if distribution == "ubuntu":
        manager = "dpkg-query"
        output = query(
            [
                "/usr/bin/dpkg-query",
                "--show",
                "--showformat=${Package}\\t${Version}\\t${db:Status-Status}\\n",
                "--",
                *expected,
            ]
        )
    else:
        manager = "rpm"
        output = query(
            [
                "/usr/bin/rpm",
                "--query",
                "--queryformat",
                "%{NAME}\\t%{EPOCH}\\t%{VERSION}\\t%{RELEASE}\\t%{ARCH}\\n",
                "--",
                *expected,
            ]
        )
    versions = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != (3 if distribution == "ubuntu" else 5):
            raise MetadataError("Malformed guest package inventory")
        name = fields[0]
        if name not in expected or name in versions:
            raise MetadataError("Unexpected or duplicate guest package record")
        if distribution == "ubuntu":
            version, status = fields[1:]
            if status != "installed":
                raise MetadataError("Required guest package is not fully installed")
        else:
            epoch, version, release, architecture = fields[1:]
            epoch = "0" if epoch == "(none)" else epoch
            if not epoch.isascii() or not epoch.isdecimal():
                raise MetadataError("Invalid RPM package epoch")
            if any(not field for field in (version, release, architecture)):
                raise MetadataError("Missing RPM version, release or architecture")
            version = f"{epoch}:{version}-{release}.{architecture}"
        if not re.fullmatch(r"[A-Za-z0-9.+:~_^\-]{1,256}", version):
            raise MetadataError("Invalid guest package version")
        versions[name] = version
    if set(versions) != set(expected):
        raise MetadataError("Required guest package records are missing")
    return manager, dict(sorted(versions.items()))


def collect():
    if platform.system() != "Linux":
        raise MetadataError("Guest metadata requires Linux")
    release = os_release()
    manager, versions = package_versions(release["ID"])
    return {
        "schema_version": 1,
        "os": release,
        "kernel_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "package_manager": manager,
        "package_versions": versions,
    }


def main():
    try:
        print(json.dumps(collect(), sort_keys=True))
    except MetadataError as error:
        print(f"Guest metadata unavailable: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
