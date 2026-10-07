"""Provider unit tests use synthetic files and mocked Lima; no VM integration claim."""

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "fleet_lab", Path(__file__).parents[1] / "scripts/lab.py"
)
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="of-unit-", dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.provider = lab.Lab(self.root)
        self.manifest = {
            "schema_version": 1,
            "tool": {"name": "lima", "version": "2.2.1", "platforms": {}},
            "images": {
                distro: {"url": url, "arch": "aarch64", "sha256": "a" * 64}
                for distro, url in (
                    ("ubuntu", "https://cloud-images.ubuntu.com/synthetic.img"),
                    ("alma", "https://repo.almalinux.org/synthetic.qcow2"),
                )
            },
        }
        self.write_lock()

    def write_lock(self):
        (self.root / "provider.lock.json").write_text(json.dumps(self.manifest))

    def prepared(self, distro="ubuntu"):
        name = lab.INSTANCES[distro]
        self.provider.runtime.mkdir(mode=0o700, exist_ok=True)
        for relative in ("configs", f"transport/{name}", f"lima/{name}"):
            self.provider.directory(relative)
        files = {
            f"configs/{name}.json": "{}\n",
            f"transport/{name}/host_ed25519": "synthetic non-key\n",
            f"transport/{name}/host_ed25519.pub": "ssh-ed25519 SYNTHETIC\n",
            f"transport/{name}/known_hosts": f"{name} ssh-ed25519 SYNTHETIC\n",
            f"transport/{name}/ssh": self.provider.wrapper(distro),
            f"lima/{name}/lima.yaml": "synthetic: true\n",
        }
        for path, text in files.items():
            lab.write_private(self.provider.child(path), text)
        state = {
            "schema_version": 1,
            "lab_id": lab.LAB_ID,
            "managed_by": lab.OWNER,
            "repository": str(self.root),
            "instances": {
                distro: {
                    "name": name,
                    "port": 60221,
                    "status": "created",
                    "image_sha256": "a" * 64,
                    "config_sha256": lab.digest(self.provider.child(f"configs/{name}.json")),
                    "public_key_sha256": lab.digest(
                        self.provider.child(f"transport/{name}/host_ed25519.pub")
                    ),
                    "known_hosts_sha256": lab.digest(
                        self.provider.child(f"transport/{name}/known_hosts")
                    ),
                    "wrapper_sha256": lab.digest(self.provider.child(f"transport/{name}/ssh")),
                }
            },
        }
        self.provider.save(state)
        self.provider.record_instance(distro, state)
        return state

    def test_lock_accepts_pinned_official_native_images(self):
        self.assertEqual(self.provider.lock()["tool"]["version"], "2.2.1")

    def test_lock_rejects_http_foreign_origin_arch_and_bad_digest(self):
        for key, value in (
            ("url", "http://cloud-images.ubuntu.com/image"),
            ("url", "https://example.com/image"),
            ("arch", "x86_64"),
            ("sha256", "invalid"),
        ):
            original = self.manifest["images"]["ubuntu"][key]
            self.manifest["images"]["ubuntu"][key] = value
            self.write_lock()
            with self.subTest(key=key, value=value), self.assertRaises(lab.LabError):
                self.provider.lock()
            self.manifest["images"]["ubuntu"][key] = original

    def test_old_lima_rejected(self):
        self.manifest["tool"]["version"] = "2.2.0"
        self.write_lock()
        with self.assertRaises(lab.LabError):
            self.provider.lock()

    def test_state_foreign_identity_rejected(self):
        state = self.prepared()
        for key, value in (
            ("lab_id", "foreign"),
            ("repository", "/foreign"),
            ("managed_by", "foreign"),
        ):
            altered = {**state, key: value}
            self.provider.save(altered)
            with self.subTest(key=key), self.assertRaises(lab.LabError):
                self.provider.state()

    def test_unknown_instance_record_rejected(self):
        state = self.prepared()
        state["instances"]["ubuntu"]["name"] = "user-production"
        self.provider.save(state)
        with self.assertRaises(lab.LabError):
            self.provider.state()

    def test_nonempty_unregistered_lima_home_is_not_adopted(self):
        path = self.provider.directory("lima/foreign-instance")
        (path / "lima.yaml").write_text("{}")
        with self.assertRaises(lab.LabError):
            self.provider.state(initialize=True)

    def test_implicit_global_lima_config_refused_before_subprocess(self):
        folder = self.provider.directory("lima/_config")
        for name in ("default.yaml", "override.yaml"):
            with self.subTest(name=name):
                target = folder / name
                target.write_text("mounts: []\n")
                with patch.object(lab.subprocess, "run") as process:
                    with self.assertRaisesRegex(lab.LabError, "Implicit Lima global"):
                        self.provider.run(["synthetic-never-executed"])
                process.assert_not_called()
                target.unlink()

    def test_symlinked_global_lima_config_refused_before_subprocess(self):
        folder = self.provider.directory("lima/_config")
        sentinel = self.root / "unrelated.yaml"
        sentinel.write_text("synthetic: preserve\n")
        for name in ("default.yaml", "override.yaml"):
            for link_target in (sentinel, self.root / "absent.yaml"):
                with self.subTest(name=name, link_target=link_target):
                    target = folder / name
                    target.symlink_to(link_target)
                    with patch.object(lab.subprocess, "run") as process:
                        with self.assertRaises(lab.LabError):
                            self.provider.run(["synthetic-never-executed"])
                    process.assert_not_called()
                    target.unlink()
        self.assertEqual(sentinel.read_text(), "synthetic: preserve\n")

    def test_runtime_symlink_refused(self):
        external = self.root / "external"
        external.mkdir()
        self.provider.runtime.symlink_to(external)
        with self.assertRaises(lab.LabError):
            self.provider.child("lab-state.json")

    def test_nested_symlink_refused(self):
        self.provider.runtime.mkdir()
        (self.provider.runtime / "transport").symlink_to(self.root)
        with self.assertRaises(lab.LabError):
            self.provider.child("transport/hostkey")

    def test_path_traversal_refused(self):
        with self.assertRaises(lab.LabError):
            self.provider.child("../unrelated")

    def test_private_write_rejects_symlinks(self):
        target = self.root / "target"
        target.write_text("unchanged")
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(lab.LabError):
            lab.write_private(link, "would overwrite")
        self.assertEqual(target.read_text(), "unchanged")

    def test_private_write_mode(self):
        target = self.root / "private"
        lab.write_private(target, "synthetic")
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_config_has_no_mounts_containers_forwarding_or_proxy_inheritance(self):
        config = self.provider.config(
            "ubuntu",
            self.root / "image",
            60221,
            "synthetic private fixture",
            "ssh-ed25519 SYNTHETIC",
        )
        self.assertTrue(config["plain"])
        self.assertEqual(config["mounts"], [])
        self.assertEqual(config["networks"], [])
        self.assertEqual(config["portForwards"], [])
        self.assertFalse(config["containerd"]["user"])
        self.assertFalse(config["containerd"]["system"])
        self.assertFalse(config["ssh"]["overVsock"])
        self.assertFalse(config["ssh"]["loadDotSSHPubKeys"])
        self.assertFalse(config["ssh"]["forwardAgent"])
        self.assertFalse(config["propagateProxyEnv"])
        self.assertTrue(all(value == "" for value in config["env"].values()))
        self.assertEqual(config["user"]["uid"], 1001)
        self.assertEqual(config["memory"], "2GiB")

    def test_hostkey_provision_replaces_initial_cloud_keys_without_logging_contents(self):
        config = self.provider.config(
            "alma", self.root / "image", 60221, "SYNTHETIC-PRIVATE", "ssh-ed25519 SYNTHETIC"
        )
        provisions = config["provision"]
        self.assertEqual(provisions[0]["mode"], "data")
        self.assertEqual(provisions[0]["permissions"], "0600")
        self.assertTrue(provisions[0]["overwrite"])
        self.assertNotIn("SYNTHETIC-PRIVATE", provisions[-1]["script"])
        self.assertNotIn("set -x", provisions[-1]["script"])
        self.assertIn("restorecon", provisions[-1]["script"])
        self.assertIn("sshd -t", provisions[-1]["script"])
        self.assertNotIn("setenforce", json.dumps(config))
        self.assertNotIn("SELINUX=disabled", json.dumps(config))

    def test_transport_is_strict_despite_later_provider_options(self):
        folder = self.provider.directory("transport/ops-fleet-ubuntu")
        wrapper = folder / "ssh"
        lab.write_private(wrapper, self.provider.wrapper("ubuntu"), 0o700)
        result = subprocess.run(
            [
                str(wrapper),
                "-G",
                "-F",
                "/dev/null",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "NoHostAuthenticationForLocalhost=yes",
                "127.0.0.1",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        options = dict(line.split(" ", 1) for line in result.stdout.splitlines() if " " in line)
        self.assertEqual(options["stricthostkeychecking"], "true")
        self.assertEqual(options["nohostauthenticationforlocalhost"], "no")
        self.assertEqual(options["userknownhostsfile"], str(folder / "known_hosts"))
        self.assertEqual(options["hostkeyalias"], "ops-fleet-ubuntu")
        self.assertEqual(options["identityagent"], "none")

    def test_subprocess_environment_does_not_forward_secrets(self):
        with patch.dict(
            os.environ,
            {
                "AWS_SECRET_ACCESS_KEY": "SYNTHETIC",
                "SSH_AUTH_SOCK": "/synthetic",
                "HTTPS_PROXY": "https://synthetic",
            },
        ):
            environment = self.provider.environment("ubuntu")
        for key in ("AWS_SECRET_ACCESS_KEY", "SSH_AUTH_SOCK", "HTTPS_PROXY"):
            self.assertNotIn(key, environment)
        self.assertEqual(environment["LIMA_HOME"], str(self.provider.home))

    def test_changed_trust_config_is_refused(self):
        state = self.prepared()
        (self.provider.runtime / "transport/ops-fleet-ubuntu/known_hosts").write_text("tampered")
        with self.assertRaises(lab.LabError):
            self.provider.verify_record("ubuntu", state["instances"]["ubuntu"])

    def test_invalid_port_refused(self):
        state = self.prepared()
        state["instances"]["ubuntu"]["port"] = 22
        with self.assertRaises(lab.LabError):
            self.provider.verify_record("ubuntu", state["instances"]["ubuntu"])

    def test_inventory_only_contains_owned_local_targets(self):
        self.prepared()
        inventory = self.provider.inventory()
        host = inventory["all"]["children"]["fleet_lab"]["hosts"]["ops-fleet-ubuntu"]
        self.assertEqual(host["ansible_host"], "127.0.0.1")
        self.assertEqual(host["ansible_connection"], "ssh")
        self.assertEqual(host["ops_lab_id"], lab.LAB_ID)
        self.assertTrue(host["ops_lab_owned"])
        self.assertEqual(host["ansible_ssh_transfer_method"], "piped")
        self.assertNotIn("StrictHostKeyChecking=no", json.dumps(inventory))
        self.assertEqual((self.provider.runtime / "inventory.json").stat().st_mode & 0o777, 0o600)

    def test_actual_instance_listing_rejects_foreign_names(self):
        with patch.object(
            self.provider,
            "run",
            return_value='{"name":"production","dir":"/foreign","status":"Running"}\n',
        ):
            with self.assertRaises(lab.LabError):
                self.provider.actual_instances()

    def test_actual_instance_listing_rejects_foreign_directory(self):
        with patch.object(
            self.provider,
            "run",
            return_value='{"name":"ops-fleet-ubuntu","dir":"/foreign","status":"Stopped"}\n',
        ):
            with self.assertRaises(lab.LabError):
                self.provider.actual_instances()

    def test_modified_lima_config_is_refused(self):
        state = self.prepared()
        (self.provider.home / "ops-fleet-ubuntu/lima.yaml").write_text("mounts: [unrelated]")
        with self.assertRaisesRegex(lab.LabError, "configuration changed"):
            self.provider.verify_instance("ubuntu", state["instances"]["ubuntu"])

    def test_missing_instance_marker_is_refused(self):
        state = self.prepared()
        (self.provider.home / "ops-fleet-ubuntu/.ops-fleet-owner.json").unlink()
        with self.assertRaises(OSError):
            self.provider.verify_instance("ubuntu", state["instances"]["ubuntu"])

    def test_cached_image_requires_matching_digest(self):
        folder = self.provider.directory("images")
        (folder / ("ubuntu-" + "a" * 64 + ".qcow2")).write_text("corrupt")
        with self.assertRaisesRegex(lab.LabError, "digest mismatch"):
            self.provider.image("ubuntu")

    def test_downloaded_image_hash_failure_cleans_partial(self):
        class Response(io.BytesIO):
            url = "https://cloud-images.ubuntu.com/synthetic.img"

        with patch("urllib.request.urlopen", return_value=Response(b"synthetic wrong digest")):
            with self.assertRaisesRegex(lab.LabError, "digest mismatch"):
                self.provider.image("ubuntu")
        self.assertEqual(list((self.provider.runtime / "images").iterdir()), [])

    def test_download_success_is_hashed_and_reused_without_network(self):
        content = b"synthetic unit-test image, not a bootable VM"
        self.manifest["images"]["ubuntu"]["sha256"] = hashlib.sha256(content).hexdigest()
        self.write_lock()

        class Response(io.BytesIO):
            url = "https://cloud-images.ubuntu.com/synthetic.img"

        with patch("urllib.request.urlopen", return_value=Response(content)) as network:
            first = self.provider.image("ubuntu")
            second = self.provider.image("ubuntu")
            self.assertEqual(first, second)
            self.assertEqual(first.read_bytes(), content)
            self.assertEqual(network.call_count, 1)

    def test_mocked_create_records_owned_resource_and_is_idempotent(self):
        self.provider.runtime.mkdir()
        image = self.provider.directory("images") / "synthetic.qcow2"
        image.write_bytes(b"synthetic")
        calls = []

        def fake_run(arguments, **kwargs):
            calls.append(arguments)
            if arguments[0] == lab.SSH_KEYGEN:
                private = Path(arguments[-1])
                private.write_text("synthetic non-key fixture")
                private.with_suffix(".pub").write_text("ssh-ed25519 SYNTHETIC unit\n")
            elif arguments[1] == "create":
                folder = self.provider.directory("lima/ops-fleet-ubuntu")
                (folder / "lima.yaml").write_text("synthetic: true\n")
            return ""

        with (
            patch.object(self.provider, "require_platform"),
            patch.object(self.provider, "require_tool"),
            patch.object(self.provider, "image", return_value=image),
            patch.object(self.provider, "free_port", return_value=60221),
            patch.object(self.provider, "run", side_effect=fake_run),
            patch("sys.stdout", io.StringIO()),
        ):
            self.provider.create("ubuntu")
            self.provider.create("ubuntu")
        self.assertEqual(len(calls), 2)
        state = self.provider.state()
        self.assertEqual(state["instances"]["ubuntu"]["status"], "created")
        self.provider.verify_instance("ubuntu", state["instances"]["ubuntu"])
        self.assertTrue((self.provider.runtime / "inventory-ubuntu.json").exists())

    def test_foreign_redirect_is_rejected(self):
        class Response(io.BytesIO):
            url = "https://example.com/image"

        with patch("urllib.request.urlopen", return_value=Response(b"synthetic")):
            with self.assertRaisesRegex(lab.LabError, "redirected"):
                self.provider.image("ubuntu")

    def test_create_and_destroy_default_to_dry_run(self):
        for action in ("create", "start", "stop", "destroy"):
            with (
                patch.object(lab, "Lab", return_value=self.provider),
                patch.object(self.provider, action) as mutate,
                patch("sys.stdout", io.StringIO()),
            ):
                self.assertEqual(
                    lab.main([action, "--distro", "ubuntu", "--lab-id", lab.LAB_ID]), 0
                )
                mutate.assert_not_called()
        self.assertFalse(self.provider.runtime.exists())

    def test_explicit_lab_identity_required(self):
        with (
            patch.object(lab, "Lab", return_value=self.provider),
            patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(lab.main(["start", "--distro", "ubuntu", "--execute"]), 2)
        self.assertFalse(self.provider.runtime.exists())

    def test_destroy_confirmation_required_before_mutation(self):
        with (
            patch.object(lab, "Lab", return_value=self.provider),
            patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(
                lab.main(["destroy", "--distro", "ubuntu", "--lab-id", lab.LAB_ID, "--execute"]), 2
            )
        self.assertFalse(self.provider.runtime.exists())

    def test_sequential_profile_refuses_second_running_vm(self):
        self.prepared()
        with (
            patch.object(self.provider, "create"),
            patch.object(
                self.provider,
                "actual_instances",
                return_value={"ops-fleet-alma": {"status": "Running"}},
            ),
        ):
            with self.assertRaisesRegex(lab.LabError, "another lab VM"):
                self.provider.start("ubuntu")

    def test_start_refuses_busy_localhost_port(self):
        self.prepared()
        with (
            patch.object(self.provider, "create"),
            patch.object(self.provider, "actual_instances", return_value={}),
            patch.object(lab.socket, "socket") as socket_factory,
        ):
            socket_factory.return_value.__enter__.return_value.bind.side_effect = OSError(
                "synthetic busy port"
            )
            with self.assertRaisesRegex(lab.LabError, "already in use"):
                self.provider.start("ubuntu")

    def test_mocked_delete_targets_one_registered_instance_and_cleans_only_its_keys(self):
        self.prepared()
        sentinel = self.root / "unrelated.txt"
        sentinel.write_text("preserve")
        self.provider.inventory()
        calls = []

        def fake_run(arguments, **kwargs):
            calls.append(arguments)
            return ""

        with (
            patch.object(self.provider, "require_platform"),
            patch.object(self.provider, "require_tool"),
            patch.object(
                self.provider,
                "actual_instances",
                return_value={"ops-fleet-ubuntu": {"status": "Stopped"}},
            ),
            patch.object(self.provider, "run", side_effect=fake_run),
            patch("sys.stdout", io.StringIO()),
        ):
            self.provider.destroy("ubuntu")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][-1], "ops-fleet-ubuntu")
        self.assertNotIn("--force", calls[0])
        self.assertFalse(
            (self.provider.runtime / "transport/ops-fleet-ubuntu/host_ed25519").exists()
        )
        self.assertEqual(sentinel.read_text(), "preserve")
        self.assertEqual(self.provider.state()["instances"], {})


if __name__ == "__main__":
    unittest.main()
