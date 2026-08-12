from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import QPX_RUN_CHALLENGER_25PCT_QUALIFICATION as qualification
from qpx_bot.qualification_provenance import (
    ImmutableProvenanceError,
    load_manifest,
    verify_immutable_provenance,
)


class ProvenanceBootstrapIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for relative in qualification.PROVENANCE_FILE_SHA256:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(qualification.ROOT / relative, destination)
        for scope in load_manifest()["protected_scopes"]:
            for relative in scope["protected_files"]:
                destination = self.root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    shutil.copyfile(qualification.ROOT / relative, destination)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_runner_mutation_fails(self, old: str, new: str) -> None:
        path = self.root / "QPX_RUN_CHALLENGER_25PCT_QUALIFICATION.py"
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count(old), 1)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        with self.assertRaises(ImmutableProvenanceError) as captured:
            verify_immutable_provenance(root=self.root)
        self.assertTrue(
            any(
                failure.path == "QPX_RUN_CHALLENGER_25PCT_QUALIFICATION.py"
                for failure in captured.exception.failures
            )
        )

    def test_current_provenance_files_match_sealed_hashes(self) -> None:
        observed = qualification.verify_provenance_mechanism_files()
        self.assertEqual(observed, qualification.PROVENANCE_FILE_SHA256)

    def test_modified_provenance_module_fails_before_import(self) -> None:
        relative = "qpx_bot/qualification_provenance.py"
        path = self.root / relative
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, relative):
            qualification.verify_provenance_mechanism_files(root=self.root)

    def test_modified_provenance_manifest_fails_before_import(self) -> None:
        relative = "qpx_bot/qualification_provenance.json"
        path = self.root / relative
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(RuntimeError, relative):
            qualification.verify_provenance_mechanism_files(root=self.root)

    def test_missing_provenance_file_fails_before_import(self) -> None:
        relative = "qpx_bot/qualification_provenance.py"
        (self.root / relative).unlink()
        with self.assertRaisesRegex(RuntimeError, relative):
            qualification.verify_provenance_mechanism_files(root=self.root)


    def test_unchanged_bootstrap_passes_immutable_provenance(self) -> None:
        self.assertEqual(verify_immutable_provenance()["status"], "PASS")

    def test_changing_expected_sha_fails_provenance(self) -> None:
        self.assert_runner_mutation_fails(
            qualification.PROVENANCE_FILE_SHA256["qpx_bot/qualification_provenance.py"],
            "0" * 64,
        )

    def test_changing_bootstrap_logic_fails_provenance(self) -> None:
        self.assert_runner_mutation_fails(
            "        if actual != expected:\n",
            "        if actual == expected:\n",
        )

    def test_adding_executable_line_inside_bootstrap_fails(self) -> None:
        marker = "# END SCOPE-AWARE PROVENANCE BOOTSTRAP V1\n"
        self.assert_runner_mutation_fails(
            marker,
            "raise RuntimeError(\"unauthorized\")\n" + marker,
        )

    def test_changing_bootstrap_marker_fails_provenance(self) -> None:
        self.assert_runner_mutation_fails(
            "# BEGIN SCOPE-AWARE PROVENANCE BOOTSTRAP V1\n",
            "# BEGIN ALTERED PROVENANCE BOOTSTRAP V1\n",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
