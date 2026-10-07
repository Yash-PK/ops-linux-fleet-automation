#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repo_root"
printf '%s\n' 'CONTROLLER POLICY: accepted input; only Ansible assertions, no guest/host configuration writes'
.venv/bin/ansible-playbook -i localhost, playbooks/check-input.yml --extra-vars @tests/fixtures/valid-input.json
printf '%s\n' 'CONTROLLER POLICY: rejected port, using the same validation tasks as VM provisioning'
result=0
.venv/bin/ansible-playbook -i localhost, playbooks/check-input.yml --extra-vars @tests/fixtures/invalid-port.json || result=$?
if [[ "$result" -eq 0 ]]; then
  printf '%s\n' 'ERROR: invalid input was accepted' >&2
  exit 1
fi
printf 'ASSERT invalid input rejected: exit=%s\n' "$result"
printf '%s\n' 'Real distro, systemd, idempotence and reboot evidence requires make integration LAB=ubuntu and LAB=alma.'
