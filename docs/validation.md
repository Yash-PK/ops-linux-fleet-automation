# Validation report

Status: **integration-tested**, **v0.1.0 candidate**. Both required real-VM
profiles passed the bounded core. Controller validation and a clean-clone
quickstart passed. Final outgoing review, GitHub publication, hosted CI and a
versioned release remain pending; no release or remote success is claimed.

## Recorded source runs

| Profile | Tested revision | Result and evidence |
| --- | --- | --- |
| Controller gates | `c52155a5c15b04bdb2a85746b385da0243ecef93` | [Passed](../evidence/c52155a5c15b-local.json): doctor, production-profile ansible-lint, other required lint, 74 tests, documented input-policy demo and working/staged/full-history Gitleaks scans |
| Controller clean clone | `c52155a5c15b04bdb2a85746b385da0243ecef93` | [Passed](../evidence/c52155a5c15b-clean-clone.json): locked bootstrap, doctor, validation, demo and security; scratch checkout removed; no VM allocated by this profile |
| Ubuntu 24.04 ARM64 VM | `c52155a5c15b04bdb2a85746b385da0243ecef93` | [Passed](../evidence/c52155a5c15b-ubuntu-vm.json): all nine workflow steps, authenticated boot, lifecycle and scoped teardown |
| AlmaLinux 9.8 ARM64 VM | `e333e1c8c37b107fb6e99924c869555acca0ad68` | [Passed](../evidence/e333e1c8c37b-alma-vm.json): all nine workflow steps, authenticated boot, lifecycle and scoped teardown |
| Earlier Ubuntu failure | `8db4d22e1c567943ed80e2e8fe6ceebdc56d0fb7` | [Failed report retained](../evidence/8db4d22e1c56-ubuntu-vm.json): enabled firewall unit inactive after reboot; cleanup passed; corrected source was tested in the later passing Ubuntu run |
| GitHub publication / CI / release | None credited | Not created / not run / no release |

The two passing VM reports have the same implementation SHA-256:
`391a99a45747322a4358e199d1454d2b29f175e171592995cae890761137bb0d`.
The intervening `e333e1c8c37b107fb6e99924c869555acca0ad68` commit preserved observed
Ubuntu/controller evidence without changing implementation. It is the source
revision of the subsequent AlmaLinux run, not the earlier Ubuntu run. Later
documentation/evidence commits must retain these original execution identities.

The controller ran on macOS ARM64 (Darwin 25.6.0), Python 3.14.7, with
ansible-core 2.21.5, ansible-lint 26.9.0, Molecule 26.9.0 and Lima 2.2.1.
The pinned provider/images and tool versions are embedded in the VM records.
Each VM used Apple Virtualization.framework with 2 CPUs, 2 GiB RAM and a 24 GiB
sparse disk, one VM at a time. These are configured resource values, not measured
utilization or performance claims. Neither a container nor a cloud environment
was used.

## What both real VM profiles established

Each report records nine commands with expected exit semantics. Strict SSH
rejected an intentionally changed host key with exit 255, rather than accepting
it. Molecule completed syntax, initial converge, zero-change second converge and
verification against an explicitly owned real guest. Invalid configuration exited
2 with zero changed tasks; subsequent verification confirmed state remained valid.
The service content was changed, verified, restored and verified again. The explicit
patch/reboot play then passed shared state checks immediately after reboot,
**before repair**, as well as its remaining postchecks. All other workflow
commands exited 0. Expected negative cases are assertions, not hidden failures.

Ubuntu's second-converge recap was `changed=0`, and AlmaLinux's was also
`changed=0`. Effective SSH/sudo/nginx configuration, service state, worker identity,
nginx restrictions, response content and headers, denied POST, native firewall
policy, chrony and journald configuration were inspected. Ubuntu retained AppArmor;
AlmaLinux retained enforcing SELinux and its file labels. Firewall rule inspection
does not establish a denied external network path. Chrony tracking does not prove
synchronization to a trusted source. Serial single-guest runs do not demonstrate
multi-host rolling availability or production hardening certification.

Guest metadata was collected after the lifecycle; these observed versions are
not frozen package repository inputs:

| Observed metadata | Ubuntu profile | AlmaLinux profile |
| --- | --- | --- |
| OS / architecture | Ubuntu 24.04 / aarch64 | AlmaLinux 9.8 / aarch64 |
| Kernel | `6.8.0-146-generic` | `5.14.0-687.54.1.el9_8.aarch64` |
| Guest Python | `3.12.3` | `3.9.25` |
| chrony | `4.5-1ubuntu4.2` | `0:4.8-1.el9.aarch64` |
| nginx | `1.24.0-2ubuntu7.18` | `2:1.20.1-28.el9_8.6.alma.1.aarch64` |
| openssh-server | `1:9.6p1-3ubuntu13.19` | `0:9.9p1-12.el9_8.alma.1.aarch64` |
| Native firewall package | nftables `1.0.9-1ubuntu0.1` | firewalld `0:1.3.4-20.el9_8.noarch` |
| Security policy package | apparmor `4.0.1really4.0.1-0ubuntu0.24.04.8` | selinux-policy `0:38.1.75-2.el9_8.noarch` |

The safe controller demo uses the actual role's pure assertions with
`become: false`; its positive/negative results do not substitute for VM evidence.
Molecule's external inventory has no fake create/destroy driver. Provider tests
include mocked safety cases, which remain distinct from the live lifecycle above.

## Failures retained and corrections verified

The first development Ubuntu converge failed when chronyd's unchanged AppArmor
profile denied Ansible's temporary candidate path. Validation now stages a
root-only candidate beside the distribution's chrony configuration, validates it
under unchanged confinement, atomically copies only valid content, and always
removes the candidate. Temporary staging is excluded from desired-state change
counts; permanent installation still reports real changes. Subsequent real
Molecule runs passed zero-change idempotence. Ansible's local RPC socket also
needed permitted execution outside the restrictive command sandbox; the initial
restricted failure was not counted as a pass.

Revision `8db4d22e1c567943ed80e2e8fe6ceebdc56d0fb7` passed its
[controller checks](../evidence/8db4d22e1c56-local.json), host-key rejection,
Molecule, invalid input and content change/rollback, but failed the post-reboot
firewall assertion: `ops-baseline-firewall` was enabled and inactive. Verification
before repair exposed this persistence defect. Its failed report remains archived.

The unit now declares early-boot ordering explicitly, preserves shutdown ordering
and never flushes rules on stop. Installed-unit validation uses
`systemd-analyze --recursive-errors=yes verify` before activation. The earlier
ordering conflict is inferred from unit dependencies; a complete original boot
transaction trace was not captured. The fresh `c52155a5c15b` Ubuntu lifecycle,
including verification before repair, passed and provides evidence of the corrected
behavior. [ADR 0001](adr/0001.md) records the upstream basis for this choice.

## Cleanup and remaining publication gates

Both successful integration guests were deleted by the ownership-scoped provider,
and both reports record `cleanup_passed: true`. The clean-clone scratch checkout
was removed. Approximately 1.05 GiB of downloaded images remains cached; local
tools and ignored runtime metadata/credentials are retained. Raw logs, inventories
and keys are private runtime material, not public evidence. No cloud resources,
host configuration changes, global package changes or public application listeners
were created by these profiles.

1. Review the exact outgoing source/configuration, license, documentation claims,
   generated evidence and staged files. Repeat required security scans over the
   final working/staged files and complete outgoing history.
2. Confirm the two required VM reports match the current implementation fingerprint;
   source changes require appropriate fresh validation. Documentation-only updates
   do not change the original tested revisions. The README documents committing
   reviewed evidence between clean-source profile runs.
3. Complete the applicable final local publishing gate, create only the authorized
   new public repository and verify owner, visibility, default branch and remote SHA.
4. Inspect hosted CI for that exact revision. Hosted controller checks do not
   establish macOS VZ integration. Create v0.1.0 only after its release gates pass;
   it remains a candidate until publication and release verification are recorded.

Next task: finish the outgoing review and publish the gated repository, then
inspect its exact-revision CI before any release claim. No cloud apply, paid
services, container publishing or host configuration changes are authorized.
