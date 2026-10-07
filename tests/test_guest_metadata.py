"""Metadata parsing tests use synthetic guest data, never the host package database."""

import ast
import importlib.util
import io
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import mock_open, patch

SOURCE = Path(__file__).resolve().parents[1] / "scripts/guest_metadata.py"
SPEC = importlib.util.spec_from_file_location("fleet_guest_metadata", SOURCE)
metadata = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metadata)


class GuestMetadataTests(unittest.TestCase):
    def test_python39_syntax_and_nonlinux_rejection(self):
        ast.parse(SOURCE.read_text(), feature_version=(3, 9))
        with (
            patch.object(metadata.platform, "system", return_value="Darwin"),
            patch.object(metadata, "os_release") as release,
        ):
            with self.assertRaisesRegex(metadata.MetadataError, "requires Linux"):
                metadata.collect()
        release.assert_not_called()

    def test_release_only_selects_three_fields_and_does_not_execute_values(self):
        content = 'ID=ubuntu\nNAME="Ubuntu"\nVERSION_ID="24.04"\nIGNORED="private fixture"\n'
        with patch("builtins.open", mock_open(read_data=content)):
            self.assertEqual(
                metadata.os_release(), {"ID": "ubuntu", "NAME": "Ubuntu", "VERSION_ID": "24.04"}
            )
        for content in (
            'ID=ubuntu\nNAME="broken\nVERSION_ID=24.04\n',
            "ID=ubuntu\nNAME=Ubuntu\n",
            "ID=foreign\nNAME=Foreign\nVERSION_ID=1\n",
        ):
            with (
                self.subTest(content=content),
                patch("builtins.open", mock_open(read_data=content)),
            ):
                with self.assertRaises(metadata.MetadataError):
                    metadata.os_release()

    def test_dpkg_requires_every_package_fully_installed(self):
        output = "".join(
            f"{name}\t1:2.3-4ubuntu1\tinstalled\n" for name in metadata.PACKAGES["ubuntu"]
        )
        with patch.object(metadata, "query", return_value=output):
            manager, versions = metadata.package_versions("ubuntu")
        self.assertEqual(manager, "dpkg-query")
        self.assertEqual(set(versions), set(metadata.PACKAGES["ubuntu"]))
        for bad in (
            output.replace("installed", "config-files", 1),
            output.splitlines()[0],
            output + output.splitlines()[0] + "\n",
        ):
            with self.subTest(output=bad), patch.object(metadata, "query", return_value=bad):
                with self.assertRaises(metadata.MetadataError):
                    metadata.package_versions("ubuntu")

    def test_rpm_records_epoch_release_and_architecture(self):
        output = "".join(
            f"{name}\t(none)\t2.3\t4.el9\taarch64\n" for name in metadata.PACKAGES["almalinux"]
        )
        with patch.object(metadata, "query", return_value=output):
            manager, versions = metadata.package_versions("almalinux")
        self.assertEqual(manager, "rpm")
        self.assertEqual(versions["nginx"], "0:2.3-4.el9.aarch64")
        with patch.object(metadata, "query", return_value=output.replace("(none)", "invalid", 1)):
            with self.assertRaisesRegex(metadata.MetadataError, "epoch"):
                metadata.package_versions("almalinux")

    def test_query_timeout_missing_tool_and_missing_package_are_failures(self):
        for error in (subprocess.TimeoutExpired(["synthetic"], 10), FileNotFoundError("synthetic")):
            with (
                self.subTest(error=error),
                patch.object(metadata.subprocess, "run", side_effect=error),
            ):
                with self.assertRaises(metadata.MetadataError):
                    metadata.query(["synthetic"])
        with patch.object(
            metadata.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="partial")
        ) as process:
            with self.assertRaises(metadata.MetadataError):
                metadata.query(["synthetic"])
        self.assertEqual(process.call_args.kwargs["timeout"], 10)
        self.assertEqual(process.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(process.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_failed_metadata_emits_no_success_json(self):
        with (
            patch.object(
                metadata, "collect", side_effect=metadata.MetadataError("synthetic failure")
            ),
            patch("sys.stdout", io.StringIO()) as stdout,
            patch("sys.stderr", io.StringIO()) as stderr,
        ):
            self.assertEqual(metadata.main(), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("synthetic failure", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
