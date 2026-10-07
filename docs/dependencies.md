# Dependencies, provenance, and support boundaries

Reviewed **2026-10-07**. This lab's controller is CPython **3.14.7** on macOS
ARM64. The VM profiles target **Ubuntu Server 24.04 ARM64** and **AlmaLinux 9.8
ARM64** using Apple Virtualization.framework through Lima. A declared support
range or available binary is not integration evidence: see the validation report
for which commands and VM scenarios actually ran. Other distributions,
architectures, hypervisors, and Python versions remain unverified profiles.

## Python dependency graph

| Direct dependency | Pin | Purpose |
| --- | --- | --- |
| ansible-core | 2.21.5 | Playbooks, built-in modules, SSH transport |
| ansible-lint | 26.9.0 | Ansible style, syntax, and safety checks |
| Molecule | 26.9.0 | Role scenario validation and lifecycle assertions |
| Ruff | 0.16.10 | Controller Python lint and formatting |

These versions were verified against official PyPI metadata and upstream release
notes before installation. The full dependency graph has **37 exact package
versions**. [requirements-dev.lock](../requirements-dev.lock) contains **619
non-yanked wheel hashes**, covering the available platform-specific wheels for
those versions. Source distributions are excluded from bootstrap.

[dependency-audit.json](dependency-audit.json) records each package's name,
version, Python requirement, dependency markers, project URLs, metadata URL and
digest, wheel hashes, and PyPI-reported vulnerability data. It also records the
resolver version, platform, and SHA-256 of the original resolution report.
The report came from pip 26.2.1 on CPython 3.14.7, Darwin ARM64. Every exact
version returned an empty PyPI vulnerability list during this review. This is
a point-in-time feed result, not a claim of vulnerability-free software.

Bootstrap installs only inside the project virtual environment using
`--only-binary=:all: --require-hashes`. Downloaded wheel bytes must match a
recorded hash before installation. Package metadata was retrieved using TLS;
upstream build provenance was not independently attested by this audit.
The macOS resolver result does not by itself prove Linux marker equivalence or
Linux runtime behavior. Linux CI must install the same lock and run the gates;
any extra unpinned dependency must fail installation rather than be accepted.

The [Ansible support matrix](https://docs.ansible.com/projects/ansible-core/devel/reference_appendices/release_and_maintenance.html)
explicitly supports controller Python 3.12–3.14 and target Python 3.9–3.14 in
core 2.21, with scheduled end of life in November 2027. This accommodates the
local controller, Ubuntu 24.04's Python 3.12, and AlmaLinux 9's Python 3.9.

Relevant upstream changes reviewed:

- [Core 2.21.5](https://github.com/ansible/ansible/blob/v2.21.5/changelogs/CHANGELOG-v2.21.rst)
  fixes persistent-connection directory permissions. The same supported series
  includes the earlier CVE-2026-11332 role-dependency command-injection fix.
- [ansible-lint 26.9.0](https://github.com/ansible/ansible-lint/releases/tag/v26.9.0)
  raises its Black minimum for CVE-2026-32274 and raises cryptography's minimum.
  This lock resolves Black 26.10.0 and cryptography 50.0.2.
- [Molecule 26.9.0](https://github.com/ansible/molecule/releases/tag/v26.9.0)
  includes scenario state fixes and allows the Lima driver name. Merely accepting
  that name does not prove a separately installed provider plugin works; this
  project's own VM lifecycle and its tests are the evidence.
- [Ruff's version policy](https://docs.astral.sh/ruff/versioning/) permits lint
  and formatting changes in minor releases, so upgrades must rerun the gates.

Installation documentation consulted:
[Ansible Lint](https://docs.ansible.com/projects/lint/installing/),
[Molecule](https://docs.ansible.com/projects/molecule/installation/), and
[Molecule configuration](https://docs.ansible.com/projects/molecule/configuration/).

## Ansible collection

The roles use built-in modules plus **ansible.posix 2.2.2** for firewalld.
[collections.lock.json](../collections.lock.json) pins the official Galaxy
artifact URL and SHA-256. Its [version metadata](https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/collections/index/ansible/posix/versions/2.2.2/)
declares Ansible >=2.16.0 and no collection dependencies, compatible with the
chosen core. Only this required collection is installed. Ubuntu's nftables
configuration does not require another collection.

The official published-advisory APIs for
[core](https://api.github.com/repos/ansible/ansible/security-advisories),
[lint](https://api.github.com/repos/ansible/ansible-lint/security-advisories),
[Molecule](https://api.github.com/repos/ansible/molecule/security-advisories), and
[ansible.posix](https://api.github.com/repos/ansible-collections/ansible.posix/security-advisories)
returned empty lists. Release notes and the PyPI version audit were also checked
because an empty repository advisory list does not establish security.

## Provider and images

[provider.lock.json](../provider.lock.json) pins **Lima 2.2.1**, released
2026-10-03, from its [official release](https://github.com/lima-vm/lima/releases/tag/v2.2.1).
The Darwin ARM64 archive was independently downloaded into memory and hashed
against GitHub's published release-asset digest. All 215 member paths were
inspected. It contains `bin/limactl`, the Linux aarch64 guest agent, templates,
and upstream license notices. The project-local installation under `.tools/lima`
preserves the required directory structure and licenses; no global Lima upgrade
is required.

2.2.1 includes fixes for external qcow2 data-file references, stale PID-file
trust, rsync option parsing, log control characters, and invalid guest IP events.
Published advisories reviewed:

- [GHSA-2j9v-p4xj-cjw2](https://github.com/lima-vm/lima/security/advisories/GHSA-2j9v-p4xj-cjw2)
  affects QEMU <=2.1.2, fixed in 2.1.3; VZ is not affected.
- [GHSA-f7qw-jj9c-rpq9](https://github.com/lima-vm/lima/security/advisories/GHSA-f7qw-jj9c-rpq9)
  affects Lima <0.16.0, fixed in 0.16.0.

| Guest | Dated image | Download size | Official checksum manifest |
| --- | --- | --- | --- |
| Ubuntu Server 24.04 | 2026-09-26, aarch64 | 620224512 bytes | [SHA256SUMS](https://cloud-images.ubuntu.com/releases/noble/release-20260926/SHA256SUMS) |
| AlmaLinux 9.8 GenericCloud | 2026-10-05, aarch64 | 483262464 bytes | [CHECKSUM](https://repo.almalinux.org/almalinux/9.8/cloud/aarch64/images/CHECKSUM) |

Image URLs and hashes are recorded in the provider lock. Official server HEAD
requests returned HTTP 200 for both images during selection. The provider must
verify the full downloaded bytes before VM creation. Reading a checksum manifest
or finding a supported image family in Lima's templates is not a boot test.
Detached distro manifest signatures were not verified during this source review;
the initial trust is the official HTTPS source plus the reviewed hash pin.
There are no unpinned `latest` fallbacks. A missing retired image must fail and
be replaced by a reviewed pin with fresh integration evidence.

[Ubuntu's lifecycle](https://ubuntu.com/about/release-cycle) and
[AlmaLinux release notes](https://wiki.almalinux.org/release-notes/) were consulted;
9.8 was the current stable AlmaLinux 9 minor release on the review date. Guest
apt/dnf repositories are live package sources. Pinned base images and controller
dependencies do not make later guest package transactions byte-for-byte
reproducible; validation must capture actual installed versions.

## Provider trust and resource limits

The configured initial profile uses two virtual CPUs, 2 GiB guest RAM, and a
16 GiB virtual disk per VM. Run guests sequentially on resource-constrained
hosts. Image downloads total roughly 1.1 GB before unpacked virtual disks,
controller dependencies, and package caches. Virtual disks may be sparse, so
their apparent size differs from allocated host storage. No nested
virtualization, container daemon, physical disk access, cloud service, or
billable resource is needed.

The provider owns a new `LIMA_HOME` under ignored `.runtime`, with no host
filesystem mounts, imported host public keys, agent forwarding, proxy-variable
propagation, or automatic application-port forwarding. Images are downloaded
into project-owned storage before being passed to Lima. This avoids depending
on Lima's separate, shared macOS download cache. Keep Unix socket paths short:
Lima documents a 104-character macOS limit.

Lima's own default SSH options disable host-key verification. This project
must override those defaults for **provider-internal SSH as well as Ansible**:
the provider supplies a per-VM SSH wrapper whose first command-line options
enforce strict checking, a fixed host alias, the project known_hosts file, and
the expected Ed25519 host key. Guest host keys are generated locally under
ignored runtime storage and installed by the VM's bootstrap configuration;
known_hosts is derived from that locally generated public key. A changed-key
rejection test is required integration evidence. Neither an unauthenticated
ssh-keyscan nor trust-on-first-use is labeled authenticated enrollment.

Do not rely on SSH-over-vsock for these guest versions: upstream documents a
systemd >=256 requirement, which the selected Ubuntu 24.04 and AlmaLinux 9
profiles do not generally meet. Localhost TCP SSH with pinned host keys is the
intended transport. Neither SSH configuration nor known_hosts in the user's
home directory is modified.

Configuration and implementation sources consulted:
[Lima default template](https://raw.githubusercontent.com/lima-vm/lima/v2.2.0/templates/default.yaml),
[SSH utility](https://raw.githubusercontent.com/lima-vm/lima/v2.2.0/pkg/sshutil/sshutil.go),
[environment settings](https://raw.githubusercontent.com/lima-vm/lima/v2.2.0/website/content/en/docs/config/environment-variables.md),
and [data directories](https://lima-vm.io/docs/dev/internals/).
The configuration review used the installed 2.2.0 reference plus 2.2.1 release
changes; the locked 2.2.1 binary must still pass local validation and integration.

## Other development tools and update procedure

The [tool lock](../tools.lock.json) pins ShellCheck 0.11.0, shfmt 3.14.1,
actionlint 1.7.12, and Gitleaks 8.30.1. Their official release assets and digests
were verified on **2026-10-06** for the first portfolio milestone. Reuse of those
exact pins is intentional; this is not a claim of a fresh October 7 advisory
audit for every embedded Go dependency. Gitleaks' upstream policy supports only
its latest release. Their upstream licenses remain separate from this
repository's MIT license for original work.

For an update, review official support tables, release notes and advisories;
resolve the complete Python graph; regenerate all wheel hashes and the audit;
update only required collection/provider/image pins; then run local gates, CI,
and both VM profiles. Retain failed evidence and mark missing executions
unverified. Never loosen a hash or skip a failing check to complete an upgrade.
