# Bounded core acceptance — before implementation

The core manages an explicitly owned pair of disposable VMs: maintained Ubuntu
24.04 ARM64 and one verified AlmaLinux 9 ARM64 cloud image. Exact images, digests,
controller tooling and support evidence will be locked before provisioning.
Other Debian/Rocky distributions and providers are unverified alternatives.

1. Reusable Ansible roles configure lab accounts and groups, validated SSH/sudo
   drop-ins, packages, chrony, journald policy, native firewall and hardened nginx.
   No host changes; no firewall or SELinux/AppArmor disablement.
2. Preflight rejects non-inventoried/non-Linux/unsupported targets and invalid
   configuration before mutation. Distro package/service/security differences
   are explicit. Runtime access keys and inventories remain ignored.
3. Cloud-init defines guest bootstrap requirements; controller and VM lifecycle
   are reproducible from a standalone checkout with pinned inputs and no sibling
   dependency. One 2-vCPU/2-GiB VM runs at a time by default.
4. Lint and meaningful tests include ansible-lint, Molecule scenarios and actual
   integration assertions. Initial converge succeeds on both claimed distros;
   second converge reports zero changed tasks; service returns identifiable content.
5. A validated content change and rollback both work; rolling play serializes
   hosts; an explicit patch profile and guest reboot exercise have postchecks.
6. Invalid configuration fails before writes. SELinux/AppArmor mode and rules,
   SSH/sudo/nginx configuration, chrony and service enablement are inspected.
7. Teardown is restricted to recorded lab resources, defaults to dry-run and
   requires explicit lab ID/confirmation; no blanket prune or arbitrary devices.
8. Documentation, ADR/runbooks, pinned least-privilege CI, Make interface,
   provenance, clean-clone checks, staged/history secret scans and revision-linked
   evidence pass before publication. Release needs required VM tests, not mocks.

Out of core: production SSH trust/PKI, fleet discovery, external identity,
unattended production upgrades, real customer hosts, cloud apply, paid services,
additional distros, privileged containers and production availability claims.
