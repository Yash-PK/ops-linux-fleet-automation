# Operational runbooks

All commands below assume this repository's root and locked local tools. Runtime
files may contain private keys, inventory and logs; do not publish them. Select a
single explicit distro inventory rather than relying on all registered hosts.
These are executable procedures, not evidence that they have already succeeded.
Consult [validation](validation.md) for actual outcomes.

## Reject invalid input without allocating a VM

```sh
make demo
.venv/bin/ansible-playbook -i localhost, playbooks/check-input.yml \
  --extra-vars @tests/fixtures/invalid-content.json
```

The demo requires valid input to pass and its invalid-port case to fail. The
second command is an additional expected nonzero rejection. The shared role
assertions run locally without facts, privilege escalation or target writes.
A failed assertion is the intended safety behavior; do not change the validator
to accept an unsafe value. Controller temporary files are distinct from host
configuration changes.

## Create and converge one owned Ubuntu guest

```sh
.venv/bin/python scripts/lab.py doctor
.venv/bin/python scripts/lab.py start --distro ubuntu --lab-id ops-fleet-reference
.venv/bin/python scripts/lab.py start --distro ubuntu --lab-id ops-fleet-reference --execute
ANSIBLE_INVENTORY="$PWD/.runtime/inventory-ubuntu.json" \
  .venv/bin/ansible-playbook playbooks/site.yml
ANSIBLE_INVENTORY="$PWD/.runtime/inventory-ubuntu.json" \
  .venv/bin/ansible-playbook playbooks/verify.yml
```

The first start command is a dry run. The explicit execution downloads/verifies a
pinned image if needed, creates only the named lab guest and starts it. A second
site converge must report zero changed tasks before idempotence is credited.
Molecule's actual sequence is:

```sh
PATH="$PWD/.venv/bin:$PATH" \
OPS_FLEET_INVENTORY="$PWD/.runtime/inventory-ubuntu.json" \
ANSIBLE_HOME="$PWD/.runtime/ansible-home" \
XDG_CACHE_HOME="$PWD/.runtime/controller-cache" \
  .venv/bin/molecule test -s default
```

The scenario uses the real guest, including its SSH trust and Ansible assertions.
It has no fake provisioning driver. Stop Ubuntu before starting AlmaLinux; use
`--distro alma` and `inventory-alma.json` for the second target.

## Demonstrate a bounded content change and rollback

Run this only after the baseline and its verification have passed on the selected
guest. Changing the response is a guest-only, reversible configuration exercise.

```sh
ANSIBLE_INVENTORY="$PWD/.runtime/inventory-ubuntu.json" \
  .venv/bin/ansible-playbook playbooks/site.yml \
  --extra-vars '{"ops_baseline_web_content":"ops-fleet changed v2"}'
ANSIBLE_INVENTORY="$PWD/.runtime/inventory-ubuntu.json" \
  .venv/bin/ansible-playbook playbooks/verify.yml \
  --extra-vars '{"ops_baseline_web_content":"ops-fleet changed v2"}'
ANSIBLE_INVENTORY="$PWD/.runtime/inventory-ubuntu.json" \
  .venv/bin/ansible-playbook playbooks/site.yml
ANSIBLE_INVENTORY="$PWD/.runtime/inventory-ubuntu.json" \
  .venv/bin/ansible-playbook playbooks/verify.yml
```

The last two commands restore and verify the default `ops-fleet baseline v1`
response. This demonstrates content rollback, not package downgrade or system
snapshot restoration. Record before/change/restored assertions from the actual
run, not screenshots of expected content.

## Explicit package maintenance and reboot

This optional profile changes guest packages and reboots the selected lab VM.
Review the selected inventory and record a passing baseline first. Both explicit
confirmation variables are required; the boolean uses JSON to avoid string
coercion. Do not run it against a production inventory.

```sh
ANSIBLE_INVENTORY="$PWD/.runtime/inventory-ubuntu.json" \
  .venv/bin/ansible-playbook playbooks/patch.yml \
  --extra-vars '{"ops_baseline_patch_confirm":"ops-fleet-reference","ops_baseline_patch_reboot":true}'
```

The play validates lab ownership, applies distro-specific updates, reboots using
the supported Ansible module, verifies boot identity/service readiness and
reasserts baseline configuration. Serial execution and failure stopping limit the
active scope. Package repositories can change, so record actual versions and
results. A failed update/reboot is not success because a reconnect was attempted.

## Triage a failed preflight or SSH connection

For an ownership, marker, hostname, inventory or configuration-hash mismatch,
stop that operation and inspect only the named lab's private metadata/logs.
Do not adopt a foreign instance, edit identity records to force a match, remove
known-hosts checking, or replace a changed key blindly. Regenerate trust only
through a reviewed teardown/recreation of the correctly inventoried lab guest.

A stopped peer in a combined inventory is not a role failure. Select the exact
per-distro inventory and ensure the provider reports the intended VM running.
The localhost SSH endpoint is the VM transport, not permission to provision the
controller. The role requires an SSH connection and guest ownership evidence.

For AppArmor/SELinux preflight failures, establish the expected image/security
state. Disabled or unavailable security controls block the claimed profile.
Do not turn them off to continue. Read ignored per-instance logs locally and
publish only redacted assertions.

## Triage service/configuration failure

The role validates generated configuration before a handler reload/restart. Use
the verification play first; it checks complete SSH/nginx/sudo syntax, service
state, response behavior, sandbox properties and firewall/security observations.
The distribution difference matters: Ubuntu uses `ssh`/`chrony`; AlmaLinux uses
`sshd`/`chronyd`. Consult the relevant task and variable files before changing
service names or paths.

If HTTP responds but a firewall assertion fails, do not infer a passed network
policy from localhost reachability. If chrony runs but has no synchronized source,
record that separately from service reachability. If nginx fails under SELinux or
systemd restrictions, investigate the exact denial and file labels; keep the
kernel security controls enabled.

A lost SSH path can require recreating the disposable guest after reviewing the
last successful identity/state record. Teardown must still satisfy the same
ownership and confirmation checks. No generic recovery command is allowed to
operate on arbitrary VM names or host devices.

## Stop and scoped teardown

Stop without deleting the guest disk:

```sh
.venv/bin/python scripts/lab.py stop --distro ubuntu --lab-id ops-fleet-reference
.venv/bin/python scripts/lab.py stop --distro ubuntu --lab-id ops-fleet-reference --execute
```

Delete only the owned guest after reviewing the dry run:

```sh
make teardown LAB=ubuntu
.venv/bin/python scripts/lab.py destroy --distro ubuntu \
  --lab-id ops-fleet-reference --execute --confirm ops-fleet-reference
```

The same explicit procedure applies to AlmaLinux. The provider validates recorded
ownership/configuration/trust, stops a running target, deletes it without blanket
force/prune, and removes its known per-instance files. Verified image caches and
shared runtime metadata may remain. `make clean` intentionally reports retained
resources rather than silently deleting them. Never remove `.runtime` while a VM
is running or while its inventory is needed to perform verified teardown.

## Evidence and publishing recovery

Record source revision, platform/architecture, lockfile versions, exact commands,
exit codes, changed-task counts, verification assertions and cleanup state.
Keep controller tests, VM integrations and hosted CI distinct. A failed command,
missing tool or unsupported environment stays failed/blocked/unverified.

Before a new public repository is created, complete the documented local gates,
clean-clone validation, outgoing review and staged/history scans. The script
`python3 scripts/publish.py --owner Yash-PK` is a credential-free dry run. Its
`--execute` path is only for the authorized new repository after all required
project gates, including VM acceptance, have actually passed. Do not reuse an
unrelated remote or force-push. Authentication recovery happens locally through
GitHub CLI; never paste tokens into chat or a public issue. No release is currently
asserted by this document.
