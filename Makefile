PYTHON ?= $(if $(wildcard .venv/bin/python),$(CURDIR)/.venv/bin/python,python3)
SHELL := /bin/bash
export PATH := $(CURDIR)/.venv/bin:$(PATH)
export ANSIBLE_HOME := $(CURDIR)/.runtime/ansible-home
export XDG_CACHE_HOME := $(CURDIR)/.runtime/controller-cache
LAB ?= ubuntu
.PHONY: help bootstrap doctor lint test validate demo integration security clean clean-clone gate publish teardown
help:
	@printf '%s\n' 'bootstrap    Install hash-locked controller tools and local VM provider' 'doctor       Verify controller versions; no VM creation' 'lint         Python, Bash, Actions, Ansible and repository checks' 'test         Provider safety and actual Ansible input-policy tests' 'validate     Required static/controller gates' 'demo         Execute accepted/rejected input policy locally; no host writes' 'integration  Real disposable VM lifecycle for LAB=ubuntu or LAB=alma' 'security     Scan working/staged/full history with Gitleaks' 'clean-clone  Fresh checkout bootstrap and controller gates' 'clean        Report retained VM data; no implicit VM removal' 'teardown     Dry-run scoped VM deletion; see README for confirmation' 'publish      Credential-free dry run'
bootstrap:
	$(PYTHON) scripts/bootstrap.py
	$(PYTHON) scripts/bootstrap_fleet.py
doctor:
	$(PYTHON) scripts/doctor.py
lint:
	.venv/bin/ruff check scripts tests
	.venv/bin/ruff format --check scripts tests
	.tools/bin/shellcheck scripts/demo.sh
	.tools/bin/shfmt -d -i 2 scripts/demo.sh
	PATH="$(CURDIR)/.tools/bin:$$PATH" .tools/bin/actionlint
	.venv/bin/ansible-lint --offline --profile production
	$(PYTHON) scripts/quality.py
test:
	$(PYTHON) -m unittest discover -s tests -v
validate: lint test
demo:
	bash scripts/demo.sh
integration:
	$(PYTHON) scripts/integration.py --distro $(LAB) --lab-id ops-fleet-reference --execute
security:
	$(PYTHON) scripts/security.py
clean-clone:
	$(PYTHON) scripts/clean_clone.py
gate: doctor validate demo security clean-clone
publish:
	$(PYTHON) scripts/publish.py --owner Yash-PK
teardown:
	$(PYTHON) scripts/lab.py destroy --distro $(LAB) --lab-id ops-fleet-reference
clean:
	@printf '%s\n' 'No automatic VM or credential removal. Use the explicit scoped teardown documented in README.' 'Temporary unit-test directories clean themselves; .runtime, .venv and .tools are retained.'
