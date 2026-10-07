# Contributing

Read [AGENTS.md](AGENTS.md), [acceptance](docs/acceptance.md),
[validation status](docs/validation.md) and the [runbooks](docs/runbooks.md).
The provider and Ansible role must preserve the explicit disposable-lab boundary.

Use the locked local tools and the documented task interface:

```sh
make PYTHON=python3.14 bootstrap
make doctor
make validate
make demo
make security
```

A missing required tool or failed check is not a skip/pass. New role inputs need
positive and negative tests against the actual Ansible assertions. Avoid a second
Python implementation of the same policy. Controller tests must neither provision
localhost nor invoke host sudo. A restricted execution environment may require
permission to create Ansible's local RPC socket or run the VM provider; that does
not authorize host configuration changes.

Role behavior needs real target evidence. Run one supported VM profile at a time,
observe a second converge with zero changes, inspect security/service assertions,
and record a reversible change, rollback and reboot as required by acceptance.
Do not claim container, mock or syntax tests establish systemd/reboot behavior.
No additional distro/provider is covered until it has its own compatible inputs
and integration evidence.

Use fixed argument vectors, explicit resource identities and bounded timeouts in
controller code. Keep instance state, SSH keys, host inventory and raw logs out of
Git. Never weaken an ownership, host-key, firewall or security check to make a
profile work. Destructive operations need an explicit lab identifier, a dry run
and matching confirmation. Preserve third-party attribution and existing Git
author identity; do not manufacture commit activity.

Before dependencies change, consult official support information, release notes
and advisories; update pins/hashes through review and rerun relevant gates.
Distro package channels are environmental dependencies rather than frozen package
snapshots. Document that reproducibility boundary.

Before publication, review all outgoing files, claims, license and diff; scan
staged content and full outgoing history; validate a clean clone. Record exact
source revision, environment, tools, commands, exit codes, redacted assertions,
cleanup and remaining gaps. Treat publication, hosted CI, VM integration and a
versioned release as separate states. Follow the [security policy](SECURITY.md)
for sensitive reports.
