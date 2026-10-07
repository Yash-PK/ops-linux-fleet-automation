# Fleet automation continuation

This is the only active engineering project. Read docs/acceptance.md and the
sibling portfolio hub's status before work. Preserve original user authorization:
new public ops- repositories under Yash-PK after local gates; no cloud, billing,
host configuration changes, container packages or unrelated resource changes.

Architecture: reusable Ansible roles operate only on explicitly inventoried,
disposable Lima VMs. Controller code owns a repository-local LIMA_HOME and verifies
lab identity before starting/stopping/deleting instances. No host mounts or public
listeners; use guest commands through the lab transport. Never target localhost
with become or bypass SELinux/AppArmor, SSH verification, firewalls or lint checks.

Define and pin maintained versions/images from official sources. Keep distribution
behavior explicit. Tests must cover real systemd, second-converge idempotence,
invalid input rejection, reachability, a reversible change and reboot behavior.
Mocks/static checks do not replace VM integration. Record exact tested revisions,
environments, versions, commands, exit codes and redacted assertions.

Use make help/doctor/bootstrap/lint/test/validate/demo/integration/security/clean
when implemented. Unsupported targets must fail clearly. Scoped teardown defaults
to dry-run and requires the explicit lab ID plus matching confirmation to execute.
Keep private keys, guest inventories, host facts and runtime logs under ignored
.runtime. Do not publish raw secrets or sensitive inventory. Existing Git identity
must be used. No force pushes or repository collision reuse. Save continuation
state and actual publication/CI/evidence in docs/validation.md and the hub.
