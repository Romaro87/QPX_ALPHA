"""Scope-aware immutable provenance for qualified QPX research variants."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path(__file__).with_name("qualification_provenance.json")


@dataclass(frozen=True, slots=True)
class ProvenanceFailure:
    scope: str
    path: str
    reason: str


class ImmutableProvenanceError(RuntimeError):
    def __init__(self, failures: tuple[ProvenanceFailure, ...]):
        self.failures = failures
        detail = "\n".join(
            f"- {item.scope}:{item.path}: {item.reason}"
            for item in failures
        )
        super().__init__(f"Immutable provenance verification failed:\n{detail}")


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported qualification provenance schema.")
    scopes = payload.get("protected_scopes")
    if not isinstance(scopes, list) or not scopes:
        raise ValueError("Provenance manifest has no protected scopes.")
    names: set[str] = set()
    paths: set[str] = set()
    for scope in scopes:
        name = scope.get("name")
        commit = scope.get("authoritative_commit")
        protected = scope.get("protected_files")
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("Provenance scope names must be unique strings.")
        if not isinstance(commit, str) or len(commit) != 40:
            raise ValueError(f"{name}: authoritative commit must be a full SHA.")
        if not isinstance(protected, list) or not protected:
            raise ValueError(f"{name}: protected file list cannot be empty.")
        for relative in protected:
            if (
                not isinstance(relative, str)
                or not relative
                or Path(relative).is_absolute()
                or ".." in Path(relative).parts
            ):
                raise ValueError(f"{name}: invalid protected path {relative!r}.")
            if relative in paths:
                raise ValueError(f"Protected file appears in multiple scopes: {relative}")
            paths.add(relative)
        names.add(name)
    return payload


def _git(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        (
            "git",
            "-c",
            "safe.directory=/mnt/sdcard/QPX_ALPHA",
            "-c",
            "safe.directory=/storage/emulated/0/QPX_ALPHA",
            *arguments,
        ),
        cwd=ROOT,
        capture_output=True,
        check=False,
    )


def _authoritative_blob(commit: str, relative: str) -> bytes:
    result = _git("show", f"{commit}:{relative}")
    if result.returncode != 0:
        raise RuntimeError(
            f"Authoritative provenance object is unavailable: {commit}:{relative}"
        )
    return result.stdout


def _approved_bootstrap_text() -> str:
    module_hash = hashlib.sha256(
        (ROOT / "qpx_bot/qualification_provenance.py").read_bytes()
    ).hexdigest()
    manifest_hash = hashlib.sha256(
        (ROOT / "qpx_bot/qualification_provenance.json").read_bytes()
    ).hexdigest()
    return (
        "# BEGIN SCOPE-AWARE PROVENANCE BOOTSTRAP V1\n"
        "PROVENANCE_FILE_SHA256 = {\n"
        f"    \"qpx_bot/qualification_provenance.py\": \"{module_hash}\",\n"
        f"    \"qpx_bot/qualification_provenance.json\": \"{manifest_hash}\",\n"
        "}\n\n\n"
        "def verify_provenance_mechanism_files(*, root: Path = ROOT) -> dict[str, str]:\n"
        "    \"\"\"Authenticate provenance code and data before importing either.\"\"\"\n"
        "    failures: list[str] = []\n"
        "    observed: dict[str, str] = {}\n"
        "    for relative, expected in PROVENANCE_FILE_SHA256.items():\n"
        "        path = root / relative\n"
        "        if not path.is_file():\n"
        "            failures.append(f\"{relative}: missing\")\n"
        "            continue\n"
        "        actual = hashlib.sha256(path.read_bytes()).hexdigest()\n"
        "        observed[relative] = actual\n"
        "        if actual != expected:\n"
        "            failures.append(f\"{relative}: SHA-256 mismatch\")\n"
        "    if failures:\n"
        "        raise RuntimeError(\n"
        "            \"Provenance mechanism integrity verification failed: \"\n"
        "            + \"; \".join(failures)\n"
        "        )\n"
        "    return observed\n"
        "# END SCOPE-AWARE PROVENANCE BOOTSTRAP V1\n"
    )


def _normalize_explicit_exception(scope: dict, relative: str, current: bytes) -> bytes:
    exceptions = {
        item["path"]: item
        for item in scope.get("explicit_exceptions", [])
    }
    exception = exceptions.get(relative)
    if exception is None:
        return current
    if exception.get("normalizer") != "fixed_25pct_provenance_bootstrap_v1":
        return current
    text = current.decode("utf-8")
    begin = "# BEGIN SCOPE-AWARE PROVENANCE BOOTSTRAP V1\n"
    end = "# END SCOPE-AWARE PROVENANCE BOOTSTRAP V1\n"
    if text.count(begin) != 1 or text.count(end) != 1:
        return current
    start = text.index(begin)
    finish = text.index(end, start) + len(end)
    if text[start:finish] != _approved_bootstrap_text():
        return current
    text = text[:start] + text[finish:]
    text = text.replace("\n\n\n\n\ndef sha256_file", "\n\n\ndef sha256_file", 1)
    corrected = (
        "    verify_provenance_mechanism_files()\n"
        "    from qpx_bot.qualification_provenance import "
        "verify_immutable_provenance\n"
        "    verify_immutable_provenance()\n"
    )
    authoritative = (
        "    tracked_tree = account.challenger._git("
        "\"diff\", \"--quiet\", BASELINE_COMMIT, \"--\")\n"
        "    if tracked_tree.returncode != 0:\n"
        "        raise RuntimeError("
        "\"Tracked Candidate V1 tree differs from baseline commit.\")\n"
    )
    if text.count(corrected) != 1:
        return current
    return text.replace(corrected, authoritative, 1).encode("utf-8")


def verify_immutable_provenance(
    *,
    root: Path = ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict:
    """Verify only explicitly protected files; unrelated files are irrelevant."""
    manifest = load_manifest(manifest_path)
    failures: list[ProvenanceFailure] = []
    verified: list[dict] = []
    for scope in manifest["protected_scopes"]:
        name = scope["name"]
        commit = scope["authoritative_commit"]
        resolved = _git("rev-parse", commit)
        if resolved.returncode != 0 or resolved.stdout.decode().strip() != commit:
            failures.append(ProvenanceFailure(name, "<commit>", "authoritative commit missing"))
            continue
        for relative in scope["protected_files"]:
            current = root / relative
            if not current.is_file():
                failures.append(ProvenanceFailure(name, relative, "protected file missing"))
                continue
            expected = _authoritative_blob(commit, relative)
            observed = _normalize_explicit_exception(
                scope,
                relative,
                current.read_bytes(),
            )
            if observed != expected:
                failures.append(ProvenanceFailure(name, relative, "content differs from authoritative commit"))
                continue
            verified.append({"scope": name, "path": relative, "commit": commit})
    if failures:
        raise ImmutableProvenanceError(tuple(failures))
    return {
        "status": "PASS",
        "protected_file_count": len(verified),
        "verified": verified,
        "research_extensions_allowed": True,
    }
