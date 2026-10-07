# Changelog

## Unreleased — v0.1.0 candidate

- Added an explicitly owned Lima VZ provider and separate Ubuntu/AlmaLinux targets
  with repository-local state, image pins and strict seeded SSH trust.
- Added an Ansible baseline role with input/ownership preflight, accounts, SSH/sudo
  policy, packages, chrony, journald, native firewall profiles and hardened nginx.
- Added rolling converge, verification and explicitly gated patch/reboot playbooks.
- Added actual Ansible input-policy tests/demo and external-inventory Molecule
  convergence, idempotence and verification; the controller gate passed 74 tests.
- Validated both real Ubuntu 24.04 and AlmaLinux 9.8 ARM64 profiles, including
  expected rejection, reversible content changes, patch/reboot checks before
  repair and scoped deletion. Recorded source revisions and package versions in
  the [validation report](docs/validation.md).
- Corrected chrony candidate validation to work under unchanged Ubuntu AppArmor
  confinement, and corrected the owned firewall unit's early-boot ordering after
  a recorded post-reboot failure. Preserved the failed report and fresh passing run.
- Passed the documented controller quickstart from a clean clone and removed its
  scratch directory. Documented reviewed evidence commits between guest profiles.

The bounded core is integration-tested. Publication, hosted CI and release are
pending; this candidate entry does not claim an existing v0.1.0 release.
