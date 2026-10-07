# Changelog

## Unreleased

- Added an explicitly owned Lima VZ provider and separate Ubuntu/AlmaLinux targets
  with repository-local state, image pins and strict seeded SSH trust.
- Added an Ansible baseline role with input/ownership preflight, accounts, SSH/sudo
  policy, packages, chrony, journald, native firewall profiles and hardened nginx.
- Added rolling converge, verification and explicitly gated patch/reboot playbooks.
- Added pure controller input-policy tests/demo and an external-inventory Molecule
  scenario for actual VM convergence, idempotence and verification.
- Documented boundaries, runbooks and pending validation.

These entries record source additions, not successful provisioning or release.
No versioned release is claimed.
