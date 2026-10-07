# Security policy and lab boundary

This repository is lab/reference engineering work. No production support,
compliance attestation or vulnerability-free guarantee is offered. Until a
validated release exists, only the development line is in scope for reports.

The role may change accounts, SSH policy, sudo, packages, logging, time services,
firewalling and nginx **inside explicitly inventoried disposable VMs**. It must
never target localhost for provisioning. The localhost input demo runs only pure
assertions with `become: false`. No host configuration, cloud resources, paid
services, package registry publication or unrelated VM changes are authorized.

The provider uses a repository-owned Lima home, fixed instance names, checked
ownership records and exact image hashes. It generates guest host keys before
boot, provisions those keys through local guest initialization, and seeds a local
known-hosts file. SSH uses strict checking and refuses agent forwarding. This
trusts the local hypervisor/controller and official image inputs; it does not
provide enterprise PKI or defend against a compromised host administrator.
Host mounts, default user SSH-key loading and application port forwarding are
excluded from the lab configuration.

All keys, VM configurations containing private data, inventories, state and raw
logs remain in ignored `.runtime` with restricted permissions. Never commit them,
`.env` files, kubeconfigs, cloud credentials, Terraform state/plans, customer data
or backups. Do not attach raw runtime logs to public issues without review.
Gitleaks scans working files, staged contents and outgoing history, but pattern
scanning is not a guarantee that every secret has been detected.

Preflight requires the exact lab ID, allowed SSH inventory target, a regular
root-owned guest marker, supported Linux/systemd facts and the platform security
mode. Invalid role values fail before mutation. SSH/sudo/nginx/chrony/firewall
configuration has relevant validation; effective behavior still needs real VM
assertions. Do not disable SELinux, AppArmor, firewalling, TLS checks or SSH trust
to obtain a green run. A trust or ownership mismatch is a recovery investigation,
not permission to adopt or overwrite an unknown resource.

The observer account has a locked password and no installed login key. Its sudo
rule permits one exact no-pager nginx-status command. The provider's separate
management account retains guest-only administrative access for Ansible. This is
not a production account lifecycle or centralized identity implementation.

CI must use read-only repository permissions and pinned third-party actions, with
no secrets or privileged self-hosted runners for untrusted changes. A hosted
controller check must not claim it executed the macOS VZ VM profile.

For a sensitive finding, use GitHub private vulnerability reporting if it is
available for the verified repository. If unavailable, request a private contact
route without disclosing exploit details or credentials publicly. Include affected
revision, safe synthetic reproduction, scope and impact. No response deadline is
promised. If a real secret is exposed, stop publication and arrange authorized
revocation/remediation; deleting one working-tree file does not erase Git history.
