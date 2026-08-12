from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import QPX_RUN_CHALLENGER_25PCT_QUALIFICATION as qualification


class ProvenanceBootstrapIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for relative in qualification.PROVENANCE_FILE_SHA256:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(qualification.ROOT / relative, destination)

    def tearDown(self) -> None:
        self.temporary.cleanup()

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
