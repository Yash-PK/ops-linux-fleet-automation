"""Execute the real Ansible input policy without contacting or changing guests."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / ".venv/bin/ansible-playbook"


class RoleInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PLAYBOOK.is_file():
            raise RuntimeError(
                "Required Ansible tool missing: run make bootstrap; no tests skipped"
            )

    def run_policy(
        self,
        extra=None,
        *,
        playbook="playbooks/check-input.yml",
        inventory=None,
        play_data=None,
    ):
        with tempfile.TemporaryDirectory(prefix="ops-ansible-input-") as folder:
            environment = dict(os.environ)
            environment["ANSIBLE_LOCAL_TEMP"] = folder
            environment["ANSIBLE_NOCOLOR"] = "1"
            environment["ANSIBLE_HOST_KEY_CHECKING"] = "True"
            environment["PATH"] = str(ROOT / ".venv/bin") + os.pathsep + os.defpath
            inventory_path = "localhost,"
            if inventory is not None:
                path = Path(folder) / "inventory.json"
                path.write_text(json.dumps(inventory))
                inventory_path = str(path)
            if play_data is not None:
                path = Path(folder) / "policy.json"
                path.write_text(json.dumps(play_data))
                playbook = str(path)
            command = [str(PLAYBOOK), "-i", inventory_path, playbook]
            if extra is not None:
                command.extend(["--extra-vars", json.dumps(extra)])
            return subprocess.run(
                command,
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )

    def test_valid_defaults_execute_actual_role_assertions_without_changes(self):
        result = self.run_policy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("changed=0", result.stdout)

    def test_valid_reversible_content_change_is_accepted(self):
        result = self.run_policy({"ops_baseline_web_content": "ops-fleet changed v2"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_invalid_fixtures_are_rejected_by_the_real_role(self):
        for fixture in sorted((ROOT / "tests/fixtures").glob("invalid-*.json")):
            with self.subTest(fixture=fixture.name):
                result = self.run_policy(json.loads(fixture.read_text()))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid baseline configuration", result.stdout)
                self.assertIn("changed=0", result.stdout)

    def test_trailing_newline_and_shell_markup_cannot_enter_configuration(self):
        for content in [
            "ops-fleet baseline\n",
            "$(touch /tmp/not-created)",
            "<script>test</script>",
        ]:
            with self.subTest(content=content):
                result = self.run_policy({"ops_baseline_web_content": content})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid baseline configuration", result.stdout)

    def test_site_play_rejects_empty_inventory_without_contact_or_mutation(self):
        result = self.run_policy(playbook="playbooks/site.yml")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Supply the explicit ignored lab inventory", result.stdout)
        self.assertIn("changed=0", result.stdout)

    @staticmethod
    def lab_inventory(overrides=None):
        variables = {
            "ansible_connection": "ssh",
            "ansible_host": "127.0.0.1",
            "ansible_port": 2222,
            "ops_lab_owned": True,
            "ops_lab_id": "ops-fleet-reference",
        }
        variables.update(overrides or {})
        return {"fleet_lab": {"hosts": {"ops-fleet-ubuntu": variables}}}

    def test_valid_transport_passes_controller_guard_without_contact(self):
        play = [
            {
                "name": "Exercise the shared controller inventory guard",
                "hosts": "localhost",
                "connection": "local",
                "gather_facts": False,
                "become": False,
                "tasks": [
                    {
                        "name": "Use the actual inventory guard",
                        "ansible.builtin.import_tasks": str(
                            ROOT / "playbooks/tasks/inventory_guard.yml"
                        ),
                    }
                ],
            }
        ]
        for port in [1024, 2222, 65535]:
            with self.subTest(port=port):
                result = self.run_policy(
                    inventory=self.lab_inventory({"ansible_port": port}),
                    play_data=play,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("changed=0", result.stdout)
                self.assertIn("unreachable=0", result.stdout)

    def test_unsafe_transports_rejected_by_both_guards_before_contact(self):
        direct_preflight = [
            {
                "name": "Exercise the role guard without the outer playbook",
                "hosts": "fleet_lab",
                "gather_facts": False,
                "become": False,
                "tasks": [
                    {
                        "name": "Use the actual role preflight",
                        "ansible.builtin.import_role": {
                            "name": "ops_baseline",
                            "tasks_from": "preflight",
                        },
                    }
                ],
            }
        ]
        unsafe = [
            {"ansible_host": "192.0.2.1"},
            {"ansible_host": "localhost"},
            {"ansible_host": None},
            {"ansible_port": "2222"},
            {"ansible_port": True},
            {"ansible_port": 22},
            {"ansible_port": 65536},
            {"ansible_port": 2222.0},
            {"ansible_connection": "local"},
            {"ops_lab_owned": "true"},
            {"ops_lab_id": "another-lab"},
        ]
        for overrides in unsafe:
            for direct in [False, True]:
                with self.subTest(overrides=overrides, direct_role=direct):
                    result = self.run_policy(
                        playbook="playbooks/site.yml",
                        inventory=self.lab_inventory(overrides),
                        play_data=direct_preflight if direct else None,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Target is not an explicitly inventoried owned", result.stdout)
                    self.assertIn("changed=0", result.stdout)
                    self.assertIn("unreachable=0", result.stdout)
                    self.assertNotIn("Inspect fixed guest ownership marker", result.stdout)


if __name__ == "__main__":
    unittest.main()
