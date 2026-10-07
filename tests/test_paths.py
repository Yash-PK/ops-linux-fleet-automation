"""Tool installation destinations must remain within a canonical repository."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "fleet_paths", Path(__file__).resolve().parents[1] / "scripts/paths.py"
)
paths = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paths)


class DestinationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="fleet-destination-")
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name).resolve()
        self.root = self.parent / "repo"
        self.root.mkdir()
        self.sentinel = self.parent / "preserve.txt"
        self.sentinel.write_text("synthetic unrelated data")

    def test_uncreated_contained_destination_is_accepted_without_creation(self):
        destination = self.root / ".tools/lima/bin/limactl"
        self.assertEqual(paths.bounded(self.root, destination), destination)
        self.assertFalse(destination.parent.exists())

    def test_preexisting_parent_symlink_cannot_escape(self):
        (self.root / ".tools").symlink_to(self.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            paths.bounded(self.root, self.root / ".tools/preserve.txt")
        self.assertEqual(self.sentinel.read_text(), "synthetic unrelated data")

    def test_destination_file_symlink_refused(self):
        destination = self.root / "tool"
        destination.symlink_to(self.sentinel)
        with self.assertRaisesRegex(ValueError, "symlink"):
            paths.bounded(self.root, destination)
        self.assertEqual(self.sentinel.read_text(), "synthetic unrelated data")

    def test_dangling_symlink_refused(self):
        destination = self.root / "tool"
        destination.symlink_to(self.parent / "missing")
        with self.assertRaisesRegex(ValueError, "symlink"):
            paths.bounded(self.root, destination)

    def test_traversal_and_absolute_external_path_refused(self):
        for destination in (
            self.root / "../preserve.txt",
            self.sentinel,
            self.parent / "repo-lookalike/tool",
        ):
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                paths.bounded(self.root, destination)
        self.assertEqual(self.sentinel.read_text(), "synthetic unrelated data")

    def test_symlinked_repository_root_refused(self):
        alias = self.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "canonical"):
            paths.bounded(alias, alias / "tool")


if __name__ == "__main__":
    unittest.main()
