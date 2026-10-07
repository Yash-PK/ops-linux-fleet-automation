"""Safety tests for the VM orchestrator; all provider operations are mocked."""

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
LAB_SPEC = importlib.util.spec_from_file_location("integration_test_lab", SCRIPTS / "lab.py")
lab_module = importlib.util.module_from_spec(LAB_SPEC)
LAB_SPEC.loader.exec_module(lab_module)
METADATA_SPEC = importlib.util.spec_from_file_location(
    "integration_test_metadata", SCRIPTS / "guest_metadata.py"
)
metadata_module = importlib.util.module_from_spec(METADATA_SPEC)
METADATA_SPEC.loader.exec_module(metadata_module)
SPEC = importlib.util.spec_from_file_location("fleet_integration", SCRIPTS / "integration.py")
integration = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {"lab": lab_module, "guest_metadata": metadata_module}):
    SPEC.loader.exec_module(integration)


def synthetic_metadata(distro):
    distribution = "ubuntu" if distro == "ubuntu" else "almalinux"
    return {
        "schema_version": 1,
        "synthetic": True,
        "os": {"ID": distribution, "NAME": "Synthetic unit fixture", "VERSION_ID": "1"},
        "architecture": "aarch64",
        "kernel_release": "synthetic-kernel",
        "python_version": "3.9.0",
        "package_manager": "dpkg-query" if distro == "ubuntu" else "rpm",
        "package_versions": {
            name: "synthetic-version" for name in metadata_module.PACKAGES[distribution]
        },
    }


class SyntheticProvider:
    """In-memory lifecycle with temporary output files, never real Lima calls."""

    def __init__(self, root):
        self.root = root
        self.runtime = root / ".runtime"
        self.runtime.mkdir()
        self.home = self.runtime / "lima"
        self.tool = root / ".tools/lima/bin/limactl"
        self.instances = {}
        self.started = []
        self.destroyed = []
        self.metadata_calls = []
        self.metadata = synthetic_metadata("ubuntu")

    def require_platform(self):
        return None

    def require_tool(self):
        return None

    def lock(self):
        return {"synthetic": True}

    def exclusive(self):
        return contextlib.nullcontext()

    def state(self, initialize=False):
        return {"instances": self.instances}

    def start(self, distro):
        self.started.append(distro)
        self.instances[distro] = {"synthetic": True}

    def destroy(self, distro):
        self.destroyed.append(distro)
        del self.instances[distro]

    def run(self, arguments, **kwargs):
        self.metadata_calls.append((arguments, kwargs))
        return json.dumps(self.metadata)

    def child(self, path):
        runtime = self.root / ".runtime"
        runtime.mkdir(exist_ok=True)
        return runtime / path

    def directory(self, path):
        target = self.child(path)
        target.mkdir(parents=True, exist_ok=True)
        return target


class OrchestratorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="fleet-orchestrator-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.provider = SyntheticProvider(self.root)
        source_directory = self.root / "scripts"
        source_directory.mkdir()
        self.metadata_source = "print('synthetic helper source; never executed by unit tests')\n"
        (source_directory / "guest_metadata.py").write_text(self.metadata_source)
        self.revision = "a" * 40

    @contextlib.contextmanager
    def run_boundary(self, *, dirty="", execute_effect=None):
        def passed(report, provider, distro, name, command, **kwargs):
            report["commands"].append({"name": name, "passed": True})

        def command(arguments, **kwargs):
            if arguments[:2] == ["git", "rev-parse"]:
                return SimpleNamespace(stdout=self.revision)
            self.assertEqual(arguments[0], "/usr/bin/ssh-keygen")
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            key = Path(arguments[-1])
            self.assertTrue(key.is_relative_to(self.provider.runtime))
            key.write_text("synthetic private placeholder; not a key")
            key.with_suffix(".pub").write_text("ssh-ed25519 SYNTHETIC unit fixture\n")
            return SimpleNamespace(returncode=0)

        with (
            patch.object(integration, "ROOT", self.root),
            patch.object(integration, "Lab", return_value=self.provider),
            patch.object(integration, "code_digest", return_value="c" * 64),
            patch.object(
                integration.importlib.metadata, "version", return_value="synthetic-version"
            ),
            patch.object(integration.subprocess, "run", side_effect=command),
            patch.object(integration.subprocess, "check_output", return_value=dirty),
            patch.object(integration, "execute", side_effect=execute_effect or passed) as execute,
            patch("sys.stdout", io.StringIO()),
            patch("sys.stderr", io.StringIO()),
        ):
            yield execute

    def report(self, distro="ubuntu"):
        return json.loads(self.provider.child(f"integration-{distro}.json").read_text())

    def test_no_execute_flag_is_a_dry_run_without_provider_construction(self):
        with (
            patch.object(integration, "Lab") as constructor,
            patch.object(integration, "run") as run,
            patch(
                "sys.argv", ["integration.py", "--distro", "ubuntu", "--lab-id", integration.LAB_ID]
            ),
            patch("sys.stdout", io.StringIO()) as output,
        ):
            integration.main()
        run.assert_not_called()
        constructor.assert_not_called()
        self.assertIn("DRY RUN", output.getvalue())

    def test_wrong_identity_blocks_execution(self):
        with (
            patch.object(integration, "run") as run,
            patch(
                "sys.argv",
                ["integration.py", "--distro", "ubuntu", "--lab-id", "foreign", "--execute"],
            ),
        ):
            with self.assertRaisesRegex(SystemExit, "matching --lab-id"):
                integration.main()
        run.assert_not_called()

    def test_preexisting_instance_is_neither_started_nor_deleted(self):
        original = {"synthetic": "preexisting"}
        self.provider.instances["ubuntu"] = original.copy()
        with self.run_boundary() as execute:
            self.assertFalse(integration.run("ubuntu"))
        self.assertEqual(self.provider.instances, {"ubuntu": original})
        self.assertEqual(self.provider.started, [])
        self.assertEqual(self.provider.destroyed, [])
        execute.assert_not_called()
        self.assertFalse(self.report()["cleanup_passed"])

    def test_failure_deletes_only_instance_created_by_this_run(self):
        self.provider.instances["alma"] = {"synthetic": "preserve"}
        with self.run_boundary(execute_effect=integration.LabError("synthetic failed gate")):
            self.assertFalse(integration.run("ubuntu"))
        self.assertEqual(self.provider.started, ["ubuntu"])
        self.assertEqual(self.provider.destroyed, ["ubuntu"])
        self.assertEqual(self.provider.instances, {"alma": {"synthetic": "preserve"}})
        self.assertTrue(self.report()["cleanup_passed"])
        self.assertFalse(self.report()["passed"])

    def test_partial_start_failure_still_attempts_scoped_cleanup(self):
        def partial_start(distro):
            self.provider.instances[distro] = {"synthetic": "partial"}
            raise integration.LabError("synthetic boot failed")

        with self.run_boundary(), patch.object(self.provider, "start", side_effect=partial_start):
            self.assertFalse(integration.run("ubuntu"))
        self.assertEqual(self.provider.destroyed, ["ubuntu"])
        self.assertEqual(self.provider.instances, {})
        self.assertTrue(self.report()["cleanup_passed"])

    def test_cleanup_failure_prevents_passing_evidence(self):
        with (
            self.run_boundary(),
            patch.object(
                self.provider,
                "destroy",
                side_effect=integration.LabError("synthetic cleanup blocked"),
            ),
        ):
            self.assertFalse(integration.run("ubuntu"))
        report = self.report()
        self.assertTrue(report["lifecycle_passed"])
        self.assertFalse(report["cleanup_passed"])
        self.assertFalse(report["passed"])
        self.assertIn("cleanup_failure", report)

    def test_metadata_failure_blocks_success_and_still_cleans_own_vm(self):
        with (
            self.run_boundary(),
            patch.object(
                self.provider, "run", side_effect=integration.LabError("synthetic metadata failed")
            ),
        ):
            self.assertFalse(integration.run("ubuntu"))
        self.assertEqual(self.provider.destroyed, ["ubuntu"])
        self.assertTrue(self.report()["cleanup_passed"])
        self.assertFalse(self.report()["passed"])
        self.assertNotIn("guest_metadata", self.report())

    def test_dirty_source_refused_before_vm_start(self):
        with self.run_boundary(dirty=" M scripts/lab.py\n") as execute:
            with self.assertRaisesRegex(integration.LabError, "Commit source first"):
                integration.run("ubuntu")
        self.assertEqual(self.provider.started, [])
        self.assertEqual(self.provider.destroyed, [])
        execute.assert_not_called()

    def test_development_run_never_writes_publishable_evidence(self):
        with self.run_boundary(dirty=" M scripts/lab.py\n"):
            self.assertTrue(integration.run("ubuntu", development=True))
        self.assertFalse((self.root / "evidence").exists())
        self.assertFalse(self.report()["clean_at_start"])
        self.assertTrue(self.report()["cleanup_passed"])

    def test_code_changed_during_run_prevents_passing_evidence(self):
        with (
            self.run_boundary(),
            patch.object(integration, "code_digest", side_effect=["c" * 64, "d" * 64]),
        ):
            self.assertFalse(integration.run("ubuntu"))
        self.assertEqual(self.provider.destroyed, ["ubuntu"])
        self.assertFalse(self.report()["passed"])

    def test_success_exercises_full_lifecycle_before_cleanup(self):
        with self.run_boundary() as execute:
            self.assertTrue(integration.run("ubuntu"))
        names = [call.args[3] for call in execute.call_args_list]
        self.assertEqual(
            names,
            [
                "ssh-reject-changed-key",
                "molecule",
                "reject-invalid",
                "verify-unchanged",
                "change",
                "verify-change",
                "restore",
                "verify-restored",
                "patch-reboot",
            ],
        )
        self.assertTrue(execute.call_args_list[0].kwargs["reject_hostkey"])
        self.assertTrue(execute.call_args_list[2].kwargs["reject"])
        negative_command = execute.call_args_list[0].args[4]
        for required in (
            "StrictHostKeyChecking=yes",
            "NoHostAuthenticationForLocalhost=no",
            "ControlMaster=no",
            "ControlPath=none",
            "HostKeyAlgorithms=ssh-ed25519",
        ):
            self.assertIn(required, negative_command)
        trust_option = next(
            item for item in negative_command if item.startswith("UserKnownHostsFile=")
        )
        temporary_trust = Path(trust_option.split("=", 1)[1])
        self.assertTrue(temporary_trust.is_relative_to(self.provider.runtime))
        self.assertFalse(temporary_trust.parent.exists())
        self.assertEqual(self.provider.destroyed, ["ubuntu"])
        report = self.report()
        self.assertTrue(report["passed"])
        self.assertEqual(report["revision"], self.revision)
        self.assertEqual(report["code_sha256"], "c" * 64)
        self.assertEqual(report["guest_metadata"], self.provider.metadata)
        self.assertEqual(
            self.provider.metadata_calls,
            [
                (
                    [
                        self.provider.tool,
                        "shell",
                        "--workdir=/home/ops-control",
                        "ops-fleet-ubuntu",
                        "/usr/bin/python3",
                        "-c",
                        self.metadata_source,
                    ],
                    {"distro": "ubuntu", "timeout": 60, "log": "ubuntu-metadata"},
                )
            ],
        )
        self.assertTrue((self.root / "evidence" / f"{self.revision[:12]}-ubuntu-vm.json").is_file())


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="fleet-evidence-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "evidence").mkdir()

    def write_report(self, filename_distro, **changes):
        report = {
            "schema_version": 1,
            "profile": "real-vm",
            "distro": filename_distro,
            "revision": "a" * 40,
            "code_sha256": "c" * 64,
            "passed": True,
            "clean_at_start": True,
            "cleanup_passed": True,
            "boot_authenticated": True,
            "lifecycle_passed": True,
            "guest_metadata": synthetic_metadata(filename_distro),
            "commands": [
                {"name": name, "passed": True}
                for name in (
                    "ssh-reject-changed-key",
                    "molecule",
                    "reject-invalid",
                    "verify-unchanged",
                    "change",
                    "verify-change",
                    "restore",
                    "verify-restored",
                    "patch-reboot",
                )
            ],
        }
        report.update(changes)
        (self.root / "evidence" / f"synthetic-{filename_distro}-vm.json").write_text(
            json.dumps(report)
        )

    def verify(self):
        with (
            patch.object(integration, "code_digest", return_value="c" * 64),
            patch("sys.stdout", io.StringIO()),
        ):
            integration.verify_evidence(self.root)

    def test_both_distro_reports_required(self):
        self.write_report("ubuntu")
        with self.assertRaisesRegex(integration.LabError, "alma"):
            self.verify()
        self.write_report("alma")
        self.verify()

    def test_stale_failed_dirty_or_unclean_report_cannot_release(self):
        self.write_report("ubuntu")
        for change in (
            {"code_sha256": "d" * 64},
            {"passed": False},
            {"clean_at_start": False},
            {"cleanup_passed": False},
            {"passed": "true"},
        ):
            with self.subTest(change=change):
                self.write_report("alma", **change)
                with self.assertRaisesRegex(integration.LabError, "alma"):
                    self.verify()

    def test_wrong_distribution_architecture_or_missing_packages_cannot_release(self):
        self.write_report("ubuntu")
        missing = synthetic_metadata("alma")
        del missing["package_versions"]["nginx"]
        for guest in (
            synthetic_metadata("ubuntu"),
            {**synthetic_metadata("alma"), "architecture": "x86_64"},
            missing,
            {},
        ):
            with self.subTest(guest=guest):
                self.write_report("alma", guest_metadata=guest)
                with self.assertRaisesRegex(integration.LabError, "alma"):
                    self.verify()

    def test_wrong_profile_distro_incomplete_lifecycle_or_steps_cannot_release(self):
        self.write_report("ubuntu")
        for change in (
            {"schema_version": 2},
            {"profile": "mock"},
            {"distro": "ubuntu"},
            {"boot_authenticated": False},
            {"lifecycle_passed": False},
            {"commands": []},
            {
                "commands": [
                    {"name": name, "passed": name != "molecule"}
                    for name in integration.REQUIRED_STEPS
                ]
            },
        ):
            with self.subTest(change=change):
                self.write_report("alma", **change)
                with self.assertRaisesRegex(integration.LabError, "alma"):
                    self.verify()

    def test_code_fingerprint_changes_with_content_and_rejects_links(self):
        folder = self.root / "scripts"
        folder.mkdir()
        source = folder / "example.py"
        source.write_text("print('first')\n")
        with patch.object(
            integration.subprocess, "check_output", return_value=b"scripts/example.py\0"
        ):
            before = integration.code_digest(self.root)
            source.write_text("print('second')\n")
            self.assertNotEqual(before, integration.code_digest(self.root))
            source.unlink()
            source.symlink_to(self.root / "unrelated")
            with self.assertRaisesRegex(integration.LabError, "regular project files"):
                integration.code_digest(self.root)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="fleet-exec-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.provider = SyntheticProvider(self.root)

    def execute(self, *, code=0, output="", timeout=False, reject=False, reject_hostkey=False):
        report = {"commands": []}

        def process(command, **kwargs):
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            kwargs["stdout"].write(output)
            kwargs["stdout"].flush()
            if timeout:
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            return SimpleNamespace(returncode=code)

        with (
            patch.object(integration, "ROOT", self.root),
            patch.object(integration.subprocess, "run", side_effect=process),
            patch("sys.stdout", io.StringIO()),
        ):
            try:
                integration.execute(
                    report,
                    self.provider,
                    "ubuntu",
                    "fixture",
                    ["synthetic-program"],
                    reject=reject,
                    reject_hostkey=reject_hostkey,
                )
            except integration.LabError:
                pass
        return report["commands"][0]

    def test_timeout_is_failed_not_success_or_skip(self):
        step = self.execute(timeout=True)
        self.assertFalse(step["passed"])
        self.assertTrue(step["timed_out"])
        self.assertEqual(step["exit_code"], 124)

    def test_host_key_gate_requires_identification_failure_not_network_failure(self):
        for code, output, expected in (
            (255, "REMOTE HOST IDENTIFICATION HAS CHANGED!", True),
            (255, "Connection refused", False),
            (255, "Permission denied (publickey).", False),
            (0, "REMOTE HOST IDENTIFICATION HAS CHANGED!", False),
        ):
            with self.subTest(code=code, output=output):
                step = self.execute(code=code, output=output, reject_hostkey=True)
                self.assertEqual(step["passed"], expected)

    def test_invalid_configuration_requires_named_failure_and_zero_changes(self):
        recap = "ops-fleet-ubuntu : ok=2 changed=0 unreachable=0 failed=1 skipped=0 rescued=0 ignored=0\n"
        for code, output, expected in (
            (2, "Invalid baseline configuration\n" + recap, True),
            (2, recap, False),
            (0, "Invalid baseline configuration\n" + recap, False),
            (
                2,
                "Invalid baseline configuration\n" + recap.replace("changed=0", "changed=1"),
                False,
            ),
        ):
            with self.subTest(code=code, output=output):
                self.assertEqual(
                    self.execute(code=code, output=output, reject=True)["passed"], expected
                )

    def test_published_step_retains_recaps_not_raw_output(self):
        output = (
            "SYNTHETIC_PRIVATE_MARKER\nops-fleet-ubuntu : ok=2 changed=0 unreachable=0 failed=0\n"
        )
        step = self.execute(output=output)
        self.assertTrue(step["passed"])
        self.assertNotIn("SYNTHETIC_PRIVATE_MARKER", json.dumps(step))
        self.assertEqual(len(step["recaps"]), 1)


if __name__ == "__main__":
    unittest.main()
