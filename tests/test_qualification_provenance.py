from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from qpx_bot.qualification_provenance import (
    ROOT,
    ImmutableProvenanceError,
    load_manifest,
    verify_immutable_provenance,
)


class QualificationProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.manifest = load_manifest()
        for scope in self.manifest["protected_scopes"]:
            for relative in scope["protected_files"]:
                destination = self.root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_failure(self, scope: str, relative: str) -> ImmutableProvenanceError:
        with self.assertRaises(ImmutableProvenanceError) as captured:
            verify_immutable_provenance(root=self.root)
        failure = captured.exception.failures[0]
        self.assertEqual(failure.scope, scope)
        self.assertEqual(failure.path, relative)
        self.assertIn(f"{scope}:{relative}", str(captured.exception))
        return captured.exception

    def test_current_repository_passes(self) -> None:
        result = verify_immutable_provenance()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["protected_file_count"], 18)

    def test_modified_candidate_v1_file_fails_with_scope_and_path(self) -> None:
        relative = "qpx_bot/causal_dividends.py"
        (self.root / relative).write_bytes((self.root / relative).read_bytes() + b"\n")
        self.assert_failure("candidate_v1", relative)

    def test_modified_fixed_25pct_file_fails_with_scope_and_path(self) -> None:
        relative = "qpx_bot/challenger_25pct_qualification.json"
        (self.root / relative).write_bytes((self.root / relative).read_bytes() + b"\n")
        self.assert_failure("fixed_25pct_challenger", relative)

    def test_unrelated_research_file_is_allowed(self) -> None:
        path = self.root / "research" / "future_accelerator.py"
        path.parent.mkdir(parents=True)
        path.write_text("RESEARCH_ONLY = True\n", encoding="utf-8")
        self.assertEqual(verify_immutable_provenance(root=self.root)["status"], "PASS")

    def test_removed_protected_file_fails(self) -> None:
        relative = "QPX_RUN_CHALLENGER_ACCOUNT_SIZED.py"
        (self.root / relative).unlink()
        error = self.assert_failure("fixed_25pct_challenger", relative)
        self.assertEqual(error.failures[0].reason, "protected file missing")

    def test_exception_is_explicit_and_limited_to_verifier(self) -> None:
        scope = next(
            item for item in self.manifest["protected_scopes"]
            if item["name"] == "fixed_25pct_challenger"
        )
        self.assertEqual(
            [item["path"] for item in scope["explicit_exceptions"]],
            ["QPX_RUN_CHALLENGER_25PCT_QUALIFICATION.py"],
        )
        self.assertNotIn(
            "QPX_RUN_CHALLENGER_ACCOUNT_SIZED.py",
            [item["path"] for item in scope["explicit_exceptions"]],
        )
        self.assertEqual(len(scope["explicit_exceptions"][0]["text_replacements"]), 2)

    def test_unrelated_verifier_change_is_not_covered_by_exception(self) -> None:
        relative = "QPX_RUN_CHALLENGER_25PCT_QUALIFICATION.py"
        source = self.root / relative
        source.write_bytes(source.read_bytes() + b"\n")
        self.assert_failure("fixed_25pct_challenger", relative)


if __name__ == "__main__":
    unittest.main(verbosity=2)
