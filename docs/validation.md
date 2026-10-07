# Validation report

Status: **implemented-unverified** pending the full revision-linked release gate.
Development runs have exercised the Ubuntu VM and controller checks. Both-distro
lifecycle/reboot evidence, clean-clone validation and publication remain pending.

## Current evidence boundary

| Profile | Current result | What it establishes |
| --- | --- | --- |
| YAML parsing and Python test-source lint | Basic syntax checks performed during development | YAML parseability and Python source lint only; not Ansible schema/runtime validity |
| Locked tool bootstrap | Passed during development | 37 hash-locked Python packages, verified developer tools, ansible.posix and Lima installed locally |
| Production-profile ansible-lint and syntax | Passed during development | Zero lint failures/warnings; Molecule syntax passed |
| Actual controller input-policy tests | Passed during development | Real Ansible positive/negative assertions; no guest writes |
| Provider, integration safety, metadata and destination tests | Passed during development | 74 tests total including 7 actual Ansible policy tests; mocks remain separate from VM proof |
| Ubuntu 24.04 ARM64 VM | Development boot, strict SSH and Molecule converge/idempotence/verify passed | Actual VZ VM; final clean-revision lifecycle report pending |
| AlmaLinux 9 ARM64 VM | Not run | Unverified |
| Second converge, content change/rollback, patch/reboot | Not run | Unverified |
| Clean clone and outgoing security gate | Not completed | Publication gate pending |
| GitHub publication / CI / release | Not created / not run / none | No remote or release success claim |

The implemented provider targets macOS ARM64 Apple Virtualization.framework via
repository-local Lima, with pinned official ARM64 images, one running VM, 2 CPUs,
2 GiB RAM and a 24 GiB sparse disk per target. These configuration values are not
measurements of actual utilization. The Ubuntu development boot succeeded on this
host; final reports must retain the exact tested revision and image.

The first Ubuntu converge failed when chronyd's AppArmor profile denied Ansible's
temporary candidate path. Validation now stages a root-only candidate beside the
distribution's chrony configuration, checks it under unchanged confinement, copies
only valid content atomically, and always removes the candidate. The next Molecule
run passed, including zero-change idempotence. Temporary staging is excluded from
desired-state change counts; the permanent installation reports real changes.
Ansible's local RPC socket needed permitted execution outside the restrictive
command sandbox; the initial restricted attempt failed and was not counted as pass.

The safe controller demo runs the actual role's pure input assertions with
`become: false` and no guest/host configuration writes. Invalid fixture cases must
exit nonzero and leave changed-task count zero. This does not substitute for Linux
VM evidence. Molecule uses explicit real per-distro inventory and runs syntax,
converge, idempotence and verification. No create/destroy stub is counted as a pass.

## Required gates before publication

1. Finish locked bootstrap and record actual controller/provider versions. Run
   `make doctor`, `make validate`, `make demo` and `make security` successfully.
2. Run `make integration LAB=ubuntu`, then `make integration LAB=alma` sequentially.
   Each claimed distro must demonstrate first converge, zero-change second
   converge, effective security/service assertions, invalid input rejection,
   reversible content change/rollback and the required guest reboot behavior.
3. Verify teardown and any retained cache/state. Capture only reviewed/redacted
   evidence; private runtime files and raw inventory are not publication artifacts.
4. Validate the documented controller quickstart from a clean temporary clone.
   Record exactly which VM profile, if any, that clone additionally exercised.
5. Review exact outgoing files, license, source/configuration, documentation claims,
   staged content and full outgoing history. Only after required gates pass may
   the authorized new public repository be created and verified.
6. Inspect hosted CI for the exact remote revision. Its controller checks do not
   establish macOS VZ integration. A release additionally requires all documented
   project acceptance and release evidence, not just a CI configuration file.

## Evidence format and continuation

For each real run record the tested source revision, UTC timestamps, host/guest
OS and architecture, tool versions, image pins, exact commands/exit codes,
changed-task counts, assertions, failure details and cleanup state. Preserve
original tested revisions when later documentation/evidence commits are added.
Do not turn a skipped optional check into a pass or count a missing required gate
as completed. Record dependency, provider, networking or privilege blockers exactly.

Next task: commit the reviewed source, collect complete Ubuntu and AlmaLinux
lifecycle evidence sequentially from fresh VMs, and address any failures. Reconcile
this report with actual source and runtime inventory before
continuing. The project has no permission to alter the host, provision cloud
resources, subscribe to paid services or publish container packages.
