#!/usr/bin/env python3
"""Install, test, push, and initialize verified QPX backups."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap


def find_root() -> Path:
    for start in (
        Path(__file__).resolve().parent,
        Path.cwd().resolve(),
    ):
        for candidate in (start, *start.parents):
            if (
                (candidate / ".git").exists()
                and (candidate / "qpx_bot").exists()
                and (candidate / "tests").exists()
            ):
                return candidate

    raise RuntimeError(
        "QPX_ALPHA was not found. Save this installer inside "
        "/storage/emulated/0/QPX_ALPHA and run it again."
    )


ROOT = find_root()
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = (
    ROOT
    / "backups"
    / "qpx_verified_backup_recovery"
    / STAMP
)

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nResearch and paper-trading bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.12.0"\n',
    "qpx_bot/backup_config.json": '{\n  "schema_version": 1,\n  "archive_directory_name": "QPX_ALPHA_BACKUPS",\n  "retention_archives": 30,\n  "require_successful_session": true,\n  "notify_with_termux_api": true\n}\n',
    "qpx_bot/backup.py": '"""Verified QPX runtime backups, recovery drills, and guarded restore."""\n\nfrom __future__ import annotations\n\nimport argparse\nimport hashlib\nimport json\nimport os\nimport shutil\nimport subprocess\nimport tempfile\nimport time\nimport zipfile\nfrom contextlib import contextmanager\nfrom dataclasses import asdict, dataclass\nfrom datetime import datetime, timezone\nfrom pathlib import Path, PurePosixPath\nfrom typing import Any, Iterator, Mapping, Sequence\n\nfrom qpx_bot.paper_state import StateStore\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nPROJECT_ROOT = PACKAGE_DIR.parent\nDEFAULT_CONFIG_PATH = PACKAGE_DIR / "backup_config.json"\nDEFAULT_RUNTIME_DIR = PACKAGE_DIR / "backup_runtime"\nDEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "qpx_backup"\n\nBACKUP_MANIFEST = "QPX_BACKUP_MANIFEST.json"\n\nEXACT_FILES = (\n    "qpx_bot/swing_universe.json",\n    "qpx_bot/operations_config.json",\n    "qpx_bot/backup_config.json",\n    "qpx_bot/data_inputs/SWING.csv",\n    "qpx_bot/data_inputs/QDTE.csv",\n    "qpx_bot/data_inputs/QDTE_DIVIDENDS.csv",\n    "qpx_bot/data_inputs/VIX.csv",\n    "qpx_bot/data_inputs/DOWNLOAD_MANIFEST.json",\n    "reports/qpx_paper/paper_status.txt",\n    "reports/qpx_paper/paper_status.json",\n    "reports/qpx_operations/latest_health.txt",\n    "reports/qpx_operations/latest_health.json",\n    "reports/qpx_symbol_selection/symbol_selection_report.txt",\n    "reports/qpx_symbol_selection/symbol_selection_rankings.csv",\n    "reports/qpx_symbol_selection/symbol_selection_result.json",\n)\n\nRUNTIME_ROOTS = (\n    "qpx_bot/paper_runtime",\n    "qpx_bot/selection_runtime",\n    "qpx_bot/operations_runtime",\n)\n\nRESTORE_ROOTS = RUNTIME_ROOTS\n\nEXCLUDED_NAMES = {\n    "paper.lock",\n    "operations.lock",\n    "backup.lock",\n}\n\nEXCLUDED_SUFFIXES = (\n    ".tmp",\n    ".bak",\n)\n\n\n@dataclass(frozen=True, slots=True)\nclass BackupConfig:\n    schema_version: int\n    archive_directory_name: str\n    retention_archives: int\n    require_successful_session: bool\n    notify_with_termux_api: bool\n\n    def validate(self) -> None:\n        if self.schema_version != 1:\n            raise ValueError(\n                "Unsupported backup configuration version."\n            )\n\n        if not self.archive_directory_name.strip():\n            raise ValueError(\n                "Archive directory name cannot be empty."\n            )\n\n        candidate = Path(self.archive_directory_name)\n\n        if candidate.is_absolute() or ".." in candidate.parts:\n            raise ValueError(\n                "Archive directory must be a safe sibling name."\n            )\n\n        if self.retention_archives < 3:\n            raise ValueError(\n                "Backup retention must keep at least three archives."\n            )\n\n\n@dataclass(frozen=True, slots=True)\nclass BackupResult:\n    created: bool\n    archive_path: Path | None\n    identity: str | None\n    status: str\n    message: str\n    files: int\n    total_bytes: int\n\n\n@dataclass(frozen=True, slots=True)\nclass VerificationResult:\n    archive_path: Path\n    identity: str\n    files: int\n    total_bytes: int\n    paper_state_id: str\n    paper_revision: int\n    paper_last_processed_date: str | None\n    journal_records: int\n    git_commit: str | None\n\n\ndef _canonical_json(value: Any) -> bytes:\n    return json.dumps(\n        value,\n        sort_keys=True,\n        separators=(",", ":"),\n        ensure_ascii=False,\n    ).encode("utf-8")\n\n\ndef _sha256_bytes(value: bytes) -> str:\n    return hashlib.sha256(value).hexdigest()\n\n\ndef _sha256_file(path: Path) -> str:\n    digest = hashlib.sha256()\n\n    with path.open("rb") as file:\n        for chunk in iter(lambda: file.read(1024 * 1024), b""):\n            digest.update(chunk)\n\n    return digest.hexdigest()\n\n\ndef _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    temporary = path.with_suffix(path.suffix + ".tmp")\n\n    with temporary.open("w", encoding="utf-8") as file:\n        json.dump(payload, file, indent=2, sort_keys=True)\n        file.write("\\n")\n        file.flush()\n        os.fsync(file.fileno())\n\n    temporary.replace(path)\n\n\ndef _atomic_text(path: Path, content: str) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    temporary = path.with_suffix(path.suffix + ".tmp")\n\n    with temporary.open("w", encoding="utf-8") as file:\n        file.write(content)\n        file.flush()\n        os.fsync(file.fileno())\n\n    temporary.replace(path)\n\n\ndef load_backup_config(\n    filename: str | Path = DEFAULT_CONFIG_PATH,\n) -> BackupConfig:\n    path = Path(filename).expanduser().resolve()\n    payload = json.loads(path.read_text(encoding="utf-8"))\n\n    if not isinstance(payload, Mapping):\n        raise ValueError(\n            "Backup configuration must be a JSON object."\n        )\n\n    config = BackupConfig(\n        schema_version=int(payload["schema_version"]),\n        archive_directory_name=str(\n            payload["archive_directory_name"]\n        ),\n        retention_archives=int(\n            payload["retention_archives"]\n        ),\n        require_successful_session=bool(\n            payload["require_successful_session"]\n        ),\n        notify_with_termux_api=bool(\n            payload["notify_with_termux_api"]\n        ),\n    )\n    config.validate()\n    return config\n\n\ndef default_archive_directory(\n    project_root: str | Path,\n    config: BackupConfig,\n) -> Path:\n    root = Path(project_root).expanduser().resolve()\n    return root.parent / config.archive_directory_name\n\n\ndef _load_optional_json(path: Path) -> Mapping[str, Any]:\n    if not path.exists():\n        return {}\n\n    try:\n        payload = json.loads(path.read_text(encoding="utf-8"))\n    except (OSError, json.JSONDecodeError):\n        return {}\n\n    return payload if isinstance(payload, Mapping) else {}\n\n\ndef _safe_relative_path(value: str) -> str:\n    normalized = value.replace("\\\\", "/")\n    path = PurePosixPath(normalized)\n\n    if (\n        not normalized\n        or path.is_absolute()\n        or ".." in path.parts\n        or "." in path.parts\n    ):\n        raise RuntimeError(\n            f"Unsafe backup member path: {value!r}"\n        )\n\n    return str(path)\n\n\ndef _is_backup_candidate(path: Path) -> bool:\n    return (\n        path.is_file()\n        and path.name not in EXCLUDED_NAMES\n        and not path.name.startswith(".")\n        and not path.name.endswith(EXCLUDED_SUFFIXES)\n    )\n\n\ndef collect_source_files(\n    project_root: str | Path,\n) -> tuple[Path, ...]:\n    root = Path(project_root).expanduser().resolve()\n    collected: dict[str, Path] = {}\n\n    for relative in EXACT_FILES:\n        path = root / relative\n\n        if _is_backup_candidate(path):\n            collected[relative] = path\n\n    for relative_root in RUNTIME_ROOTS:\n        directory = root / relative_root\n\n        if not directory.exists():\n            continue\n\n        for path in directory.rglob("*"):\n            if not _is_backup_candidate(path):\n                continue\n\n            relative = path.relative_to(root).as_posix()\n            collected[relative] = path\n\n    return tuple(\n        collected[name]\n        for name in sorted(collected)\n    )\n\n\ndef _git_commit(project_root: Path) -> str | None:\n    try:\n        completed = subprocess.run(\n            ["git", "rev-parse", "HEAD"],\n            cwd=project_root,\n            text=True,\n            stdout=subprocess.PIPE,\n            stderr=subprocess.DEVNULL,\n            timeout=20,\n            check=True,\n        )\n    except (\n        OSError,\n        subprocess.SubprocessError,\n    ):\n        return None\n\n    value = completed.stdout.strip()\n    return value or None\n\n\ndef _paper_snapshot(\n    project_root: Path,\n) -> tuple[dict[str, Any], int]:\n    store = StateStore(\n        project_root / "qpx_bot" / "paper_runtime"\n    )\n\n    if not store.exists():\n        raise RuntimeError(\n            "Persistent paper state does not exist."\n        )\n\n    state = store.load()\n    _, _, records = store.verify_journal()\n    return (\n        {\n            "state_id": state.state_id,\n            "revision": state.revision,\n            "last_processed_date": (\n                state.last_processed_date.isoformat()\n                if state.last_processed_date\n                else None\n            ),\n            "swing_symbol": state.swing_symbol,\n            "income_symbol": state.income_symbol,\n        },\n        records,\n    )\n\n\ndef _operations_snapshot(\n    project_root: Path,\n) -> Mapping[str, Any]:\n    return _load_optional_json(\n        project_root\n        / "qpx_bot"\n        / "operations_runtime"\n        / "operations_state.json"\n    )\n\n\ndef _identity(\n    *,\n    paper: Mapping[str, Any],\n    journal_records: int,\n    successful_session: str | None,\n) -> str:\n    payload = {\n        "state_id": paper["state_id"],\n        "revision": paper["revision"],\n        "last_processed_date": paper["last_processed_date"],\n        "journal_records": journal_records,\n        "successful_session": successful_session,\n    }\n    return _sha256_bytes(_canonical_json(payload))[:20]\n\n\ndef _backup_filename(\n    *,\n    paper: Mapping[str, Any],\n    identity: str,\n    unique: bool,\n) -> str:\n    session = (\n        str(paper.get("last_processed_date"))\n        if paper.get("last_processed_date")\n        else "unprocessed"\n    )\n    revision = int(paper.get("revision", 0))\n    suffix = ""\n\n    if unique:\n        suffix = (\n            "_"\n            + datetime.now(\n                timezone.utc\n            ).strftime("%Y%m%dT%H%M%SZ")\n        )\n\n    return (\n        f"qpx_backup_{session}_r{revision}_"\n        f"{identity}{suffix}.zip"\n    )\n\n\ndef _compression() -> int:\n    try:\n        import zlib  # noqa: F401\n    except ImportError:\n        return zipfile.ZIP_STORED\n\n    return zipfile.ZIP_DEFLATED\n\n\n@contextmanager\ndef backup_lock(\n    runtime_directory: str | Path,\n    *,\n    stale_after_seconds: float = 21_600.0,\n) -> Iterator[None]:\n    directory = Path(\n        runtime_directory\n    ).expanduser().resolve()\n    directory.mkdir(parents=True, exist_ok=True)\n    lock_path = directory / "backup.lock"\n\n    for attempt in range(2):\n        try:\n            descriptor = os.open(\n                lock_path,\n                os.O_CREAT | os.O_EXCL | os.O_WRONLY,\n            )\n\n            with os.fdopen(\n                descriptor,\n                "w",\n                encoding="utf-8",\n            ) as file:\n                file.write(\n                    json.dumps(\n                        {\n                            "pid": os.getpid(),\n                            "created_at_utc": datetime.now(\n                                timezone.utc\n                            ).isoformat(),\n                        }\n                    )\n                )\n            break\n        except FileExistsError:\n            age = time.time() - lock_path.stat().st_mtime\n\n            if (\n                attempt == 0\n                and age > stale_after_seconds\n            ):\n                lock_path.unlink(missing_ok=True)\n                continue\n\n            raise RuntimeError(\n                "Another QPX backup or restore is active."\n            )\n    else:\n        raise RuntimeError(\n            "Unable to acquire the QPX backup lock."\n        )\n\n    try:\n        yield\n    finally:\n        lock_path.unlink(missing_ok=True)\n\n\ndef _notify(\n    *,\n    title: str,\n    content: str,\n    high_priority: bool,\n    enabled: bool,\n) -> None:\n    if not enabled:\n        return\n\n    command = shutil.which("termux-notification")\n\n    if command is None:\n        return\n\n    subprocess.run(\n        [\n            command,\n            "--id",\n            "qpx-backup-health",\n            "--title",\n            title,\n            "--content",\n            content[:500],\n            "--priority",\n            "high" if high_priority else "default",\n        ],\n        stdout=subprocess.DEVNULL,\n        stderr=subprocess.DEVNULL,\n        check=False,\n    )\n\n\ndef _write_status(\n    *,\n    report_directory: Path,\n    payload: Mapping[str, Any],\n) -> None:\n    report_directory.mkdir(parents=True, exist_ok=True)\n    _atomic_json(\n        report_directory / "latest_backup.json",\n        payload,\n    )\n    lines = [\n        "=" * 78,\n        "QPX BOT v1.12 — VERIFIED BACKUP STATUS",\n        "=" * 78,\n    ]\n\n    for key in (\n        "status",\n        "message",\n        "archive_path",\n        "identity",\n        "created_at_utc",\n        "files",\n        "total_bytes",\n        "verified",\n        "recovery_drill",\n    ):\n        lines.append(\n            f"{key.replace(\'_\', \' \').title():26}: "\n            f"{payload.get(key)}"\n        )\n\n    lines.extend(\n        [\n            "=" * 78,\n            (\n                "Backups contain simulated paper state only. "\n                "No brokerage credentials are stored."\n            ),\n        ]\n    )\n    _atomic_text(\n        report_directory / "latest_backup.txt",\n        "\\n".join(lines) + "\\n",\n    )\n\n\ndef _manifest_for_files(\n    *,\n    project_root: Path,\n    files: Sequence[Path],\n    paper: Mapping[str, Any],\n    operations: Mapping[str, Any],\n    journal_records: int,\n    identity: str,\n    reason: str,\n) -> dict[str, Any]:\n    entries = []\n\n    for path in files:\n        relative = path.relative_to(\n            project_root\n        ).as_posix()\n        relative = _safe_relative_path(relative)\n        entries.append(\n            {\n                "path": relative,\n                "size": path.stat().st_size,\n                "sha256": _sha256_file(path),\n            }\n        )\n\n    return {\n        "schema_version": 1,\n        "created_at_utc": datetime.now(\n            timezone.utc\n        ).isoformat(),\n        "identity": identity,\n        "reason": reason,\n        "project_name": project_root.name,\n        "git_commit": _git_commit(project_root),\n        "paper": dict(paper),\n        "journal_records": journal_records,\n        "operations": {\n            "last_successful_session": (\n                operations.get(\n                    "last_successful_session"\n                )\n            ),\n            "consecutive_failures": int(\n                operations.get(\n                    "consecutive_failures",\n                    0,\n                )\n            ),\n            "paused": bool(\n                operations.get("paused", False)\n            ),\n        },\n        "files": entries,\n    }\n\n\ndef _write_archive(\n    *,\n    temporary: Path,\n    project_root: Path,\n    files: Sequence[Path],\n    manifest: Mapping[str, Any],\n) -> None:\n    compression = _compression()\n\n    with zipfile.ZipFile(\n        temporary,\n        "w",\n        compression=compression,\n        allowZip64=True,\n    ) as archive:\n        for path in files:\n            relative = path.relative_to(\n                project_root\n            ).as_posix()\n            archive.write(\n                path,\n                arcname=_safe_relative_path(relative),\n            )\n\n        archive.writestr(\n            BACKUP_MANIFEST,\n            json.dumps(\n                manifest,\n                indent=2,\n                sort_keys=True,\n            )\n            + "\\n",\n        )\n\n    with temporary.open("rb") as file:\n        os.fsync(file.fileno())\n\n\ndef _write_sidecar(archive_path: Path) -> Path:\n    checksum = _sha256_file(archive_path)\n    sidecar = archive_path.with_suffix(\n        archive_path.suffix + ".sha256"\n    )\n    _atomic_text(\n        sidecar,\n        f"{checksum}  {archive_path.name}\\n",\n    )\n    return sidecar\n\n\ndef _read_sidecar(archive_path: Path) -> str | None:\n    sidecar = archive_path.with_suffix(\n        archive_path.suffix + ".sha256"\n    )\n\n    if not sidecar.exists():\n        return None\n\n    value = sidecar.read_text(\n        encoding="utf-8"\n    ).strip().split()\n\n    return value[0] if value else None\n\n\ndef verify_backup(\n    archive_path: str | Path,\n) -> VerificationResult:\n    path = Path(archive_path).expanduser().resolve()\n\n    if not path.exists():\n        raise FileNotFoundError(path)\n\n    expected_archive_hash = _read_sidecar(path)\n\n    if (\n        expected_archive_hash is not None\n        and _sha256_file(path) != expected_archive_hash\n    ):\n        raise RuntimeError(\n            "Backup archive checksum does not match its sidecar."\n        )\n\n    try:\n        archive = zipfile.ZipFile(path, "r")\n    except zipfile.BadZipFile as exc:\n        raise RuntimeError(\n            "Backup is not a valid ZIP archive."\n        ) from exc\n\n    with archive:\n        names = archive.namelist()\n\n        if len(names) != len(set(names)):\n            raise RuntimeError(\n                "Backup contains duplicate member names."\n            )\n\n        for name in names:\n            if name == BACKUP_MANIFEST:\n                continue\n\n            _safe_relative_path(name)\n\n        if BACKUP_MANIFEST not in names:\n            raise RuntimeError(\n                "Backup manifest is missing."\n            )\n\n        bad_member = archive.testzip()\n\n        if bad_member is not None:\n            raise RuntimeError(\n                f"Backup CRC failed for {bad_member}."\n            )\n\n        try:\n            manifest = json.loads(\n                archive.read(\n                    BACKUP_MANIFEST\n                ).decode("utf-8")\n            )\n        except (\n            UnicodeDecodeError,\n            json.JSONDecodeError,\n        ) as exc:\n            raise RuntimeError(\n                "Backup manifest is invalid."\n            ) from exc\n\n        if not isinstance(manifest, Mapping):\n            raise RuntimeError(\n                "Backup manifest root must be an object."\n            )\n\n        if int(manifest.get("schema_version", -1)) != 1:\n            raise RuntimeError(\n                "Unsupported backup manifest version."\n            )\n\n        entries = manifest.get("files")\n\n        if not isinstance(entries, list) or not entries:\n            raise RuntimeError(\n                "Backup manifest has no file entries."\n            )\n\n        expected_names = {BACKUP_MANIFEST}\n        total_bytes = 0\n\n        for entry in entries:\n            if not isinstance(entry, Mapping):\n                raise RuntimeError(\n                    "Backup manifest entry is invalid."\n                )\n\n            name = _safe_relative_path(\n                str(entry.get("path", ""))\n            )\n\n            if name in expected_names:\n                raise RuntimeError(\n                    f"Duplicate manifest path: {name}"\n                )\n\n            expected_names.add(name)\n\n            if name not in names:\n                raise RuntimeError(\n                    f"Backup member is missing: {name}"\n                )\n\n            content = archive.read(name)\n            expected_size = int(entry.get("size", -1))\n            expected_hash = str(entry.get("sha256", ""))\n\n            if len(content) != expected_size:\n                raise RuntimeError(\n                    f"Backup size mismatch: {name}"\n                )\n\n            if _sha256_bytes(content) != expected_hash:\n                raise RuntimeError(\n                    f"Backup content hash mismatch: {name}"\n                )\n\n            total_bytes += len(content)\n\n        if set(names) != expected_names:\n            unexpected = sorted(\n                set(names) - expected_names\n            )\n            raise RuntimeError(\n                "Backup contains unmanifested members: "\n                + ", ".join(unexpected)\n            )\n\n        paper = manifest.get("paper")\n\n        if not isinstance(paper, Mapping):\n            raise RuntimeError(\n                "Backup paper snapshot is missing."\n            )\n\n        return VerificationResult(\n            archive_path=path,\n            identity=str(manifest["identity"]),\n            files=len(entries),\n            total_bytes=total_bytes,\n            paper_state_id=str(paper["state_id"]),\n            paper_revision=int(paper["revision"]),\n            paper_last_processed_date=(\n                str(paper["last_processed_date"])\n                if paper.get("last_processed_date")\n                else None\n            ),\n            journal_records=int(\n                manifest["journal_records"]\n            ),\n            git_commit=(\n                str(manifest["git_commit"])\n                if manifest.get("git_commit")\n                else None\n            ),\n        )\n\n\ndef _extract_verified(\n    archive_path: Path,\n    destination: Path,\n) -> Mapping[str, Any]:\n    verify_backup(archive_path)\n\n    with zipfile.ZipFile(\n        archive_path,\n        "r",\n    ) as archive:\n        manifest = json.loads(\n            archive.read(\n                BACKUP_MANIFEST\n            ).decode("utf-8")\n        )\n\n        for entry in manifest["files"]:\n            relative = _safe_relative_path(\n                str(entry["path"])\n            )\n            target = destination / relative\n            target.parent.mkdir(\n                parents=True,\n                exist_ok=True,\n            )\n            content = archive.read(relative)\n            target.write_bytes(content)\n\n    return manifest\n\n\ndef recovery_drill(\n    archive_path: str | Path,\n) -> VerificationResult:\n    path = Path(archive_path).expanduser().resolve()\n    verification = verify_backup(path)\n\n    with tempfile.TemporaryDirectory(\n        prefix="qpx_recovery_drill_"\n    ) as temporary_directory:\n        staging = Path(temporary_directory)\n        manifest = _extract_verified(\n            path,\n            staging,\n        )\n        store = StateStore(\n            staging / "qpx_bot" / "paper_runtime"\n        )\n        state = store.load()\n        _, _, records = store.verify_journal()\n\n        if state.state_id != verification.paper_state_id:\n            raise RuntimeError(\n                "Recovery drill state ID does not match manifest."\n            )\n\n        if state.revision != verification.paper_revision:\n            raise RuntimeError(\n                "Recovery drill revision does not match manifest."\n            )\n\n        if records != verification.journal_records:\n            raise RuntimeError(\n                "Recovery drill journal count does not match."\n            )\n\n        for relative in (\n            "qpx_bot/swing_universe.json",\n            "qpx_bot/operations_config.json",\n            "qpx_bot/backup_config.json",\n        ):\n            candidate = staging / relative\n\n            if candidate.exists():\n                payload = json.loads(\n                    candidate.read_text(\n                        encoding="utf-8"\n                    )\n                )\n\n                if not isinstance(payload, Mapping):\n                    raise RuntimeError(\n                        f"Recovered JSON is invalid: {relative}"\n                    )\n\n        if (\n            manifest["identity"]\n            != verification.identity\n        ):\n            raise RuntimeError(\n                "Recovery drill identity mismatch."\n            )\n\n    return verification\n\n\ndef _rotate_archives(\n    archive_directory: Path,\n    retention: int,\n) -> None:\n    archives = sorted(\n        archive_directory.glob(\n            "qpx_backup_*.zip"\n        ),\n        key=lambda path: (\n            path.stat().st_mtime,\n            path.name,\n        ),\n        reverse=True,\n    )\n\n    for path in archives[retention:]:\n        path.unlink(missing_ok=True)\n        path.with_suffix(\n            path.suffix + ".sha256"\n        ).unlink(missing_ok=True)\n\n\ndef create_backup(\n    *,\n    project_root: str | Path = PROJECT_ROOT,\n    config: BackupConfig,\n    archive_directory: str | Path,\n    runtime_directory: str | Path = DEFAULT_RUNTIME_DIR,\n    report_directory: str | Path = DEFAULT_REPORT_DIR,\n    force: bool = False,\n    unique: bool = False,\n    reason: str = "scheduled",\n) -> BackupResult:\n    root = Path(project_root).expanduser().resolve()\n    archives = Path(\n        archive_directory\n    ).expanduser().resolve()\n    runtime = Path(\n        runtime_directory\n    ).expanduser().resolve()\n    reports = Path(\n        report_directory\n    ).expanduser().resolve()\n    archives.mkdir(parents=True, exist_ok=True)\n\n    with backup_lock(runtime):\n        paper, journal_records = _paper_snapshot(root)\n        operations = _operations_snapshot(root)\n        successful_session = (\n            str(\n                operations.get(\n                    "last_successful_session"\n                )\n            )\n            if operations.get(\n                "last_successful_session"\n            )\n            else None\n        )\n\n        if (\n            config.require_successful_session\n            and not force\n        ):\n            processed = paper.get(\n                "last_processed_date"\n            )\n\n            if (\n                successful_session is None\n                or processed != successful_session\n            ):\n                message = (\n                    "Backup skipped because no fully verified "\n                    "successful session is recorded."\n                )\n                result = BackupResult(\n                    created=False,\n                    archive_path=None,\n                    identity=None,\n                    status="SKIPPED",\n                    message=message,\n                    files=0,\n                    total_bytes=0,\n                )\n                _write_status(\n                    report_directory=reports,\n                    payload={\n                        **asdict(result),\n                        "archive_path": None,\n                        "created_at_utc": datetime.now(\n                            timezone.utc\n                        ).isoformat(),\n                        "verified": False,\n                        "recovery_drill": False,\n                    },\n                )\n                return result\n\n        identity = _identity(\n            paper=paper,\n            journal_records=journal_records,\n            successful_session=successful_session,\n        )\n        filename = _backup_filename(\n            paper=paper,\n            identity=identity,\n            unique=unique,\n        )\n        final_path = archives / filename\n\n        if final_path.exists() and not unique:\n            verification = verify_backup(final_path)\n            result = BackupResult(\n                created=False,\n                archive_path=final_path,\n                identity=verification.identity,\n                status="CURRENT",\n                message=(\n                    "Verified backup already exists for "\n                    "this exact paper-state revision."\n                ),\n                files=verification.files,\n                total_bytes=verification.total_bytes,\n            )\n            _write_status(\n                report_directory=reports,\n                payload={\n                    **asdict(result),\n                    "archive_path": str(final_path),\n                    "created_at_utc": datetime.now(\n                        timezone.utc\n                    ).isoformat(),\n                    "verified": True,\n                    "recovery_drill": False,\n                },\n            )\n            return result\n\n        files = collect_source_files(root)\n\n        if not files:\n            raise RuntimeError(\n                "No QPX runtime files were found for backup."\n            )\n\n        manifest = _manifest_for_files(\n            project_root=root,\n            files=files,\n            paper=paper,\n            operations=operations,\n            journal_records=journal_records,\n            identity=identity,\n            reason=reason,\n        )\n        temporary = archives / (\n            "." + filename + ".tmp"\n        )\n\n        try:\n            _write_archive(\n                temporary=temporary,\n                project_root=root,\n                files=files,\n                manifest=manifest,\n            )\n            temporary.replace(final_path)\n            _write_sidecar(final_path)\n            verification = verify_backup(final_path)\n        except Exception:\n            temporary.unlink(missing_ok=True)\n            final_path.unlink(missing_ok=True)\n            final_path.with_suffix(\n                final_path.suffix + ".sha256"\n            ).unlink(missing_ok=True)\n            raise\n\n        _rotate_archives(\n            archives,\n            config.retention_archives,\n        )\n        result = BackupResult(\n            created=True,\n            archive_path=final_path,\n            identity=verification.identity,\n            status="CREATED",\n            message=(\n                "Backup created and every manifest checksum "\n                "was verified."\n            ),\n            files=verification.files,\n            total_bytes=verification.total_bytes,\n        )\n        _write_status(\n            report_directory=reports,\n            payload={\n                **asdict(result),\n                "archive_path": str(final_path),\n                "created_at_utc": datetime.now(\n                    timezone.utc\n                ).isoformat(),\n                "verified": True,\n                "recovery_drill": False,\n            },\n        )\n        return result\n\n\ndef latest_backup(\n    archive_directory: str | Path,\n) -> Path:\n    directory = Path(\n        archive_directory\n    ).expanduser().resolve()\n    candidates = sorted(\n        directory.glob(\n            "qpx_backup_*.zip"\n        ),\n        key=lambda path: (\n            path.stat().st_mtime,\n            path.name,\n        ),\n        reverse=True,\n    )\n\n    if not candidates:\n        raise FileNotFoundError(\n            f"No QPX backups exist in {directory}"\n        )\n\n    return candidates[0]\n\n\ndef list_backups(\n    archive_directory: str | Path,\n) -> tuple[Path, ...]:\n    directory = Path(\n        archive_directory\n    ).expanduser().resolve()\n    return tuple(\n        sorted(\n            directory.glob(\n                "qpx_backup_*.zip"\n            ),\n            key=lambda path: (\n                path.stat().st_mtime,\n                path.name,\n            ),\n            reverse=True,\n        )\n    )\n\n\ndef _runtime_lock_present(project_root: Path) -> list[Path]:\n    locks = [\n        project_root\n        / "qpx_bot"\n        / "paper_runtime"\n        / "paper.lock",\n        project_root\n        / "qpx_bot"\n        / "operations_runtime"\n        / "operations.lock",\n    ]\n    return [\n        path\n        for path in locks\n        if path.exists()\n    ]\n\n\ndef restore_backup(\n    *,\n    archive_path: str | Path,\n    project_root: str | Path,\n    config: BackupConfig,\n    archive_directory: str | Path,\n    runtime_directory: str | Path,\n    report_directory: str | Path,\n    confirm_restore: bool,\n) -> VerificationResult:\n    if not confirm_restore:\n        raise RuntimeError(\n            "Restore requires --confirm-restore."\n        )\n\n    archive = Path(\n        archive_path\n    ).expanduser().resolve()\n    root = Path(\n        project_root\n    ).expanduser().resolve()\n    runtime = Path(\n        runtime_directory\n    ).expanduser().resolve()\n    reports = Path(\n        report_directory\n    ).expanduser().resolve()\n    verification = recovery_drill(archive)\n    locks = _runtime_lock_present(root)\n\n    if locks:\n        raise RuntimeError(\n            "Restore refused because runtime locks are active: "\n            + ", ".join(str(path) for path in locks)\n        )\n\n    with backup_lock(runtime):\n        create_backup(\n            project_root=root,\n            config=config,\n            archive_directory=archive_directory,\n            runtime_directory=runtime,\n            report_directory=reports,\n            force=True,\n            unique=True,\n            reason="pre_restore_safety_snapshot",\n        )\n\n        paper_runtime = (\n            root / "qpx_bot" / "paper_runtime"\n        )\n        paper_runtime.mkdir(\n            parents=True,\n            exist_ok=True,\n        )\n        kill_switch = paper_runtime / "KILL_SWITCH"\n        _atomic_text(\n            kill_switch,\n            (\n                "QPX recovery restore in progress. "\n                "Manual resume required.\\n"\n            ),\n        )\n\n        with tempfile.TemporaryDirectory(\n            prefix="qpx_restore_staging_",\n            dir=str(\n                Path(\n                    archive_directory\n                ).expanduser().resolve()\n            ),\n        ) as temporary_directory:\n            staging = Path(temporary_directory)\n            manifest = _extract_verified(\n                archive,\n                staging,\n            )\n\n            for relative_root in RESTORE_ROOTS:\n                live = root / relative_root\n                staged = staging / relative_root\n\n                if live.exists():\n                    shutil.rmtree(live)\n\n                if staged.exists():\n                    live.parent.mkdir(\n                        parents=True,\n                        exist_ok=True,\n                    )\n                    shutil.copytree(staged, live)\n\n            for entry in manifest["files"]:\n                relative = _safe_relative_path(\n                    str(entry["path"])\n                )\n\n                if any(\n                    relative == root_name\n                    or relative.startswith(\n                        root_name + "/"\n                    )\n                    for root_name in RESTORE_ROOTS\n                ):\n                    continue\n\n                staged_file = staging / relative\n                live_file = root / relative\n                live_file.parent.mkdir(\n                    parents=True,\n                    exist_ok=True,\n                )\n                temporary_live = live_file.with_suffix(\n                    live_file.suffix + ".restore.tmp"\n                )\n                shutil.copy2(\n                    staged_file,\n                    temporary_live,\n                )\n                temporary_live.replace(live_file)\n\n        paper_runtime.mkdir(\n            parents=True,\n            exist_ok=True,\n        )\n        _atomic_text(\n            paper_runtime / "KILL_SWITCH",\n            (\n                "Restored from verified backup. "\n                "Review health reports, then resume manually.\\n"\n            ),\n        )\n        live_store = StateStore(paper_runtime)\n        live_state = live_store.load()\n        _, _, live_records = live_store.verify_journal()\n\n        if (\n            live_state.state_id\n            != verification.paper_state_id\n            or live_state.revision\n            != verification.paper_revision\n            or live_records\n            != verification.journal_records\n        ):\n            raise RuntimeError(\n                "Post-restore state verification failed."\n            )\n\n        payload = {\n            "status": "RESTORED_AND_PAUSED",\n            "message": (\n                "Verified backup restored. Paper kill switch "\n                "remains active until manual resume."\n            ),\n            "archive_path": str(archive),\n            "identity": verification.identity,\n            "created_at_utc": datetime.now(\n                timezone.utc\n            ).isoformat(),\n            "files": verification.files,\n            "total_bytes": verification.total_bytes,\n            "verified": True,\n            "recovery_drill": True,\n        }\n        _write_status(\n            report_directory=reports,\n            payload=payload,\n        )\n        return verification\n\n\ndef _format_result(result: BackupResult) -> str:\n    return "\\n".join(\n        [\n            "=" * 78,\n            "QPX BOT v1.12 — VERIFIED BACKUP",\n            "=" * 78,\n            f"Status       : {result.status}",\n            f"Message      : {result.message}",\n            f"Archive      : {result.archive_path}",\n            f"Identity     : {result.identity}",\n            f"Files        : {result.files}",\n            f"Source bytes : {result.total_bytes:,}",\n            "=" * 78,\n        ]\n    )\n\n\ndef _parser() -> argparse.ArgumentParser:\n    parser = argparse.ArgumentParser(\n        description=(\n            "Create, verify, drill, list, or restore QPX "\n            "runtime backups."\n        )\n    )\n    parser.add_argument(\n        "--config",\n        default=str(DEFAULT_CONFIG_PATH),\n    )\n    parser.add_argument(\n        "--archive-dir",\n        default=None,\n    )\n    parser.add_argument(\n        "--runtime-dir",\n        default=str(DEFAULT_RUNTIME_DIR),\n    )\n    parser.add_argument(\n        "--report-dir",\n        default=str(DEFAULT_REPORT_DIR),\n    )\n    parser.add_argument(\n        "--create",\n        action="store_true",\n    )\n    parser.add_argument(\n        "--verify-latest",\n        action="store_true",\n    )\n    parser.add_argument(\n        "--drill-latest",\n        action="store_true",\n    )\n    parser.add_argument(\n        "--list",\n        action="store_true",\n    )\n    parser.add_argument(\n        "--restore-latest",\n        action="store_true",\n    )\n    parser.add_argument(\n        "--archive",\n        default=None,\n    )\n    parser.add_argument(\n        "--confirm-restore",\n        action="store_true",\n    )\n    parser.add_argument(\n        "--force",\n        action="store_true",\n    )\n    return parser\n\n\ndef main(argv: Sequence[str] | None = None) -> int:\n    args = _parser().parse_args(argv)\n    config = load_backup_config(args.config)\n    archive_directory = (\n        Path(args.archive_dir).expanduser().resolve()\n        if args.archive_dir\n        else default_archive_directory(\n            PROJECT_ROOT,\n            config,\n        )\n    )\n    actions = any(\n        (\n            args.create,\n            args.verify_latest,\n            args.drill_latest,\n            args.list,\n            args.restore_latest,\n            bool(args.archive),\n        )\n    )\n\n    if not actions:\n        args.create = True\n        args.drill_latest = True\n\n    if args.list:\n        backups = list_backups(\n            archive_directory\n        )\n        print("=" * 78)\n        print("QPX VERIFIED BACKUPS")\n        print("=" * 78)\n\n        for path in backups:\n            print(path)\n\n        if not backups:\n            print("No backups found.")\n\n    created_path: Path | None = None\n\n    if args.create:\n        try:\n            result = create_backup(\n                project_root=PROJECT_ROOT,\n                config=config,\n                archive_directory=archive_directory,\n                runtime_directory=args.runtime_dir,\n                report_directory=args.report_dir,\n                force=args.force,\n                reason=(\n                    "manual_force"\n                    if args.force\n                    else "scheduled"\n                ),\n            )\n            created_path = result.archive_path\n            print(_format_result(result))\n        except Exception as exc:\n            _notify(\n                title="QPX backup failed",\n                content=f"{type(exc).__name__}: {exc}",\n                high_priority=True,\n                enabled=config.notify_with_termux_api,\n            )\n            raise\n\n    selected_archive = (\n        Path(args.archive).expanduser().resolve()\n        if args.archive\n        else None\n    )\n\n    if args.verify_latest:\n        selected_archive = (\n            selected_archive\n            or created_path\n            or latest_backup(\n                archive_directory\n            )\n        )\n        result = verify_backup(selected_archive)\n        print(\n            "QPX BACKUP VERIFICATION: PASS\\n"\n            f"{result.archive_path}"\n        )\n\n    if args.drill_latest:\n        selected_archive = (\n            selected_archive\n            or created_path\n            or latest_backup(\n                archive_directory\n            )\n        )\n        result = recovery_drill(\n            selected_archive\n        )\n        payload = {\n            "status": "VERIFIED",\n            "message": (\n                "Backup verification and isolated recovery "\n                "drill passed."\n            ),\n            "archive_path": str(\n                result.archive_path\n            ),\n            "identity": result.identity,\n            "created_at_utc": datetime.now(\n                timezone.utc\n            ).isoformat(),\n            "files": result.files,\n            "total_bytes": result.total_bytes,\n            "verified": True,\n            "recovery_drill": True,\n        }\n        _write_status(\n            report_directory=Path(\n                args.report_dir\n            ).expanduser().resolve(),\n            payload=payload,\n        )\n        print(\n            "QPX RECOVERY DRILL: PASS\\n"\n            f"{result.archive_path}"\n        )\n\n    if args.restore_latest:\n        selected_archive = (\n            selected_archive\n            or latest_backup(\n                archive_directory\n            )\n        )\n        result = restore_backup(\n            archive_path=selected_archive,\n            project_root=PROJECT_ROOT,\n            config=config,\n            archive_directory=archive_directory,\n            runtime_directory=args.runtime_dir,\n            report_directory=args.report_dir,\n            confirm_restore=args.confirm_restore,\n        )\n        print(\n            "QPX VERIFIED RESTORE: COMPLETE\\n"\n            f"{result.archive_path}\\n"\n            "Paper trading remains paused. Review health, then "\n            "run QPX_RUN_DAILY_OPERATIONS.py --resume."\n        )\n\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "QPX_BACKUP_RUNTIME.py": '#!/usr/bin/env python3\n"""Create, verify, drill, list, or restore QPX runtime backups."""\n\nfrom qpx_bot.backup import main\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "tests/test_qpx_bot_backup_recovery.py": 'import json\nfrom datetime import date\nfrom pathlib import Path\nfrom tempfile import TemporaryDirectory\n\nfrom qpx_bot.backup import (\n    BackupConfig,\n    collect_source_files,\n    create_backup,\n    list_backups,\n    recovery_drill,\n    verify_backup,\n)\nfrom qpx_bot.paper_state import (\n    AuditEvent,\n    PaperState,\n    StateStore,\n)\n\n\ndef write_json(path: Path, payload) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    path.write_text(\n        json.dumps(payload, indent=2) + "\\n",\n        encoding="utf-8",\n    )\n\n\nwith TemporaryDirectory() as temporary_directory:\n    root = Path(temporary_directory) / "QPX_ALPHA"\n    archive_directory = (\n        Path(temporary_directory)\n        / "QPX_ALPHA_BACKUPS"\n    )\n    runtime_directory = (\n        root / "qpx_bot" / "backup_runtime"\n    )\n    report_directory = (\n        root / "reports" / "qpx_backup"\n    )\n    paper_directory = (\n        root / "qpx_bot" / "paper_runtime"\n    )\n    store = StateStore(paper_directory)\n    state = PaperState(\n        state_id="test-state",\n        swing_symbol="XLK",\n        income_symbol="QDTE",\n        start_date=date(2026, 8, 1),\n        starting_cash=10_000.0,\n        swing_cash=4_000.0,\n        tax_reserve_cash=0.0,\n        total_contributions=10_000.0,\n        realized_pnl=0.0,\n        income_shares=100.0,\n        income_cost=4_000.0,\n        dividends_received=0.0,\n        last_processed_date=date(2026, 8, 6),\n        revision=2,\n    )\n    store.save(state)\n    store.append_events(\n        [\n            AuditEvent(\n                event_id="initial-test-event",\n                event_type="INITIALIZED",\n                event_date=date(2026, 8, 1),\n                details={"mode": "test"},\n            )\n        ]\n    )\n\n    write_json(\n        root\n        / "qpx_bot"\n        / "operations_runtime"\n        / "operations_state.json",\n        {\n            "last_successful_session": "2026-08-06",\n            "consecutive_failures": 0,\n            "paused": False,\n            "last_status": "HEALTHY",\n        },\n    )\n    write_json(\n        root\n        / "qpx_bot"\n        / "selection_runtime"\n        / "selection_decision.json",\n        {\n            "decision_month": "2026-08",\n            "selected_symbol": "XLK",\n        },\n    )\n    write_json(\n        root / "qpx_bot" / "swing_universe.json",\n        {"schema_version": 1, "candidates": ["XLK", "SPY"]},\n    )\n    write_json(\n        root / "qpx_bot" / "operations_config.json",\n        {"schema_version": 1},\n    )\n    write_json(\n        root / "qpx_bot" / "backup_config.json",\n        {"schema_version": 1},\n    )\n\n    data_directory = root / "qpx_bot" / "data_inputs"\n    data_directory.mkdir(parents=True, exist_ok=True)\n\n    for name in (\n        "SWING.csv",\n        "QDTE.csv",\n        "QDTE_DIVIDENDS.csv",\n        "VIX.csv",\n    ):\n        (data_directory / name).write_text(\n            "Date,Value\\n2026-08-06,1\\n",\n            encoding="utf-8",\n        )\n\n    write_json(\n        data_directory / "DOWNLOAD_MANIFEST.json",\n        {"session": "2026-08-06"},\n    )\n\n    config = BackupConfig(\n        schema_version=1,\n        archive_directory_name="QPX_ALPHA_BACKUPS",\n        retention_archives=3,\n        require_successful_session=True,\n        notify_with_termux_api=False,\n    )\n    config.validate()\n\n    files = collect_source_files(root)\n    assert any(\n        path.name == "paper_state.json"\n        for path in files\n    )\n    assert not any(\n        path.name.endswith(".lock")\n        for path in files\n    )\n\n    result = create_backup(\n        project_root=root,\n        config=config,\n        archive_directory=archive_directory,\n        runtime_directory=runtime_directory,\n        report_directory=report_directory,\n    )\n    assert result.created\n    assert result.archive_path is not None\n    assert result.archive_path.exists()\n    assert result.archive_path.with_suffix(\n        ".zip.sha256"\n    ).exists()\n\n    verification = verify_backup(\n        result.archive_path\n    )\n    assert verification.paper_state_id == "test-state"\n    assert verification.paper_revision == 2\n    assert verification.journal_records == 1\n    assert verification.files >= 10\n\n    drill = recovery_drill(\n        result.archive_path\n    )\n    assert drill.identity == verification.identity\n\n    duplicate = create_backup(\n        project_root=root,\n        config=config,\n        archive_directory=archive_directory,\n        runtime_directory=runtime_directory,\n        report_directory=report_directory,\n    )\n    assert not duplicate.created\n    assert duplicate.status == "CURRENT"\n    assert duplicate.archive_path == result.archive_path\n    assert len(list_backups(archive_directory)) == 1\n\n    corrupted = archive_directory / "corrupted.zip"\n    corrupted.write_bytes(\n        result.archive_path.read_bytes()[:100]\n    )\n\n    try:\n        verify_backup(corrupted)\n    except RuntimeError:\n        pass\n    else:\n        raise AssertionError(\n            "Truncated backup was not rejected."\n        )\n\nprint("QPX Bot Verified Backup and Recovery PASS")\n',
    "qpx_bot/BACKUP_RECOVERY_README.txt": "QPX VERIFIED BACKUP AND DISASTER RECOVERY\n=========================================\n\nAutomatic behavior:\n\n- QPX_TERMUX_DAILY.sh runs a backup after a successful automated\n  operations command.\n- A backup is skipped until operations records a fully successful\n  market session matching the paper account's processed session.\n- The same paper revision is never backed up repeatedly.\n- Every archive is verified against an external SHA-256 checksum,\n  an internal manifest, per-file SHA-256 hashes, ZIP CRC checks,\n  the paper-state checksum, and the audit-journal hash chain.\n- An isolated recovery drill extracts the archive into a temporary\n  directory and loads the recovered paper state without touching the\n  live account.\n- The newest 30 archives are retained by default.\n\nBackup location:\n\n/storage/emulated/0/QPX_ALPHA_BACKUPS\n\nImportant commands:\n\nCreate and drill:\npython QPX_BACKUP_RUNTIME.py --create --drill-latest\n\nVerify newest:\npython QPX_BACKUP_RUNTIME.py --verify-latest\n\nList:\npython QPX_BACKUP_RUNTIME.py --list\n\nRun an isolated recovery drill:\npython QPX_BACKUP_RUNTIME.py --drill-latest\n\nRestore newest verified backup:\npython QPX_BACKUP_RUNTIME.py --restore-latest --confirm-restore\n\nRestore safety:\n\n- Restore is refused while paper or operations locks are active.\n- A pre-restore safety backup is created first.\n- The requested archive must pass a full isolated recovery drill.\n- The paper kill switch is active during and after restoration.\n- After reviewing reports/qpx_backup/latest_backup.txt and\n  reports/qpx_operations/latest_health.txt, resume with:\n\npython QPX_RUN_DAILY_OPERATIONS.py --resume\n\nBackups include simulated runtime state, current market inputs, and\nlatest reports. They do not contain brokerage credentials because QPX\nhas no brokerage connection.\n",
}

PATCHES = {
    "QPX_TERMUX_DAILY.sh": [
        (
            'cd "${ROOT}" || exit 1\n"${PYTHON_BIN}" QPX_RUN_DAILY_OPERATIONS.py >>"${LOG_FILE}" 2>&1\nstatus=$?\n\nif [ "${wake_locked}" -eq 1 ] \\\n',
            'cd "${ROOT}" || exit 1\n"${PYTHON_BIN}" QPX_RUN_DAILY_OPERATIONS.py >>"${LOG_FILE}" 2>&1\nstatus=$?\n\nif [ "${status}" -eq 0 ]; then\n    "${PYTHON_BIN}" QPX_BACKUP_RUNTIME.py \\\n        --create \\\n        --drill-latest >>"${LOG_FILE}" 2>&1\n    backup_status=$?\n\n    if [ "${backup_status}" -ne 0 ]; then\n        status="${backup_status}"\n    fi\nfi\n\nif [ "${wake_locked}" -eq 1 ] \\\n',
        )
    ],
}

GITIGNORE_APPEND = '# QPX verified backup runtime and reports\nqpx_bot/backup_runtime/\nreports/qpx_backup/\n'
TARGETS = [*FILES, *PATCHES, ".gitignore"]
originals: dict[str, bytes | None] = {}


def run(command: list[str]) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def is_tracked(relative: str) -> bool:
    return subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def ensure_targets_are_safe() -> None:
    changed: list[str] = []

    for relative in TARGETS:
        path = ROOT / relative
        worktree = subprocess.run(
            ["git", "diff", "--quiet", "--", relative],
            cwd=ROOT,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", relative],
            cwd=ROOT,
        )

        if worktree.returncode != 0 or staged.returncode != 0:
            changed.append(relative)
            continue

        if (
            relative in FILES
            and path.exists()
            and not is_tracked(relative)
        ):
            changed.append(relative)

    if changed:
        raise RuntimeError(
            "These target files contain local changes and were "
            "not overwritten:\n" + "\n".join(changed)
        )


def validate_patch_markers() -> None:
    failures: list[str] = []

    for relative, replacements in PATCHES.items():
        path = ROOT / relative

        if not path.exists():
            failures.append(
                f"{relative}: file not found"
            )
            continue

        content = path.read_text(encoding="utf-8")

        for old, new in replacements:
            if old in content:
                content = content.replace(old, new, 1)
            elif new in content:
                continue
            else:
                failures.append(
                    f"{relative}: expected marker not found\n{old}"
                )
                break

    if failures:
        raise RuntimeError(
            "Patch preflight failed before any file changed:\n\n"
            + "\n\n".join(failures)
        )


def preserve(relative: str) -> None:
    if relative in originals:
        return

    path = ROOT / relative
    originals[relative] = (
        path.read_bytes()
        if path.exists()
        else None
    )

    if path.exists():
        backup_path = BACKUP / relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_path)


def install_files() -> None:
    for relative, content in FILES.items():
        preserve(relative)
        path = ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            textwrap.dedent(content).strip() + "\n",
            encoding="utf-8",
        )

        if path.suffix == ".sh":
            path.chmod(0o700)

        print(f"Installed: {relative}")


def patch_files() -> None:
    for relative, replacements in PATCHES.items():
        preserve(relative)
        path = ROOT / relative
        content = path.read_text(encoding="utf-8")

        for old, new in replacements:
            if old in content:
                content = content.replace(old, new, 1)
            elif new in content:
                continue
            else:
                raise RuntimeError(
                    f"Expected patch marker not found in "
                    f"{relative}:\n{old}"
                )

        path.write_text(content, encoding="utf-8")

        if path.suffix == ".sh":
            path.chmod(0o700)

        print(f"Updated: {relative}")


def patch_gitignore() -> None:
    relative = ".gitignore"
    preserve(relative)
    path = ROOT / relative
    content = path.read_text(encoding="utf-8")
    addition = textwrap.dedent(
        GITIGNORE_APPEND
    ).strip()

    if addition not in content:
        path.write_text(
            content.rstrip()
            + "\n\n"
            + addition
            + "\n",
            encoding="utf-8",
        )
        print("Updated: .gitignore")


def restore() -> None:
    print("Restoring previous target files...")

    for relative, original in originals.items():
        path = ROOT / relative

        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)


def commit_and_push() -> None:
    paths = list(TARGETS)

    try:
        paths.append(
            str(Path(__file__).resolve().relative_to(ROOT))
        )
    except ValueError:
        pass

    run(["git", "add", "--", *paths])

    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
    )

    if staged.returncode == 0:
        print("Verified backup recovery is already committed.")
        return

    run([
        "git",
        "commit",
        "-m",
        "Implement QPX Bot verified backup and recovery",
    ])

    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError(
            "Cannot push from detached Git state."
        )

    run(["git", "push", "origin", branch])


def main() -> int:
    print("=" * 78)
    print("QPX BOT — VERIFIED BACKUP AND RECOVERY INSTALLER")
    print("=" * 78)
    print(f"Project: {ROOT}")

    ensure_targets_are_safe()
    validate_patch_markers()
    install_files()
    patch_files()
    patch_gitignore()

    try:
        run([
            sys.executable,
            "-m",
            "tests.test_qpx_bot_backup_recovery",
        ])
        run([
            sys.executable,
            "tests/run_all_tests.py",
        ])
    except Exception:
        restore()
        raise

    commit_and_push()

    print()
    print("Creating and drilling the first verified backup...")
    print()

    try:
        run([
            sys.executable,
            "QPX_BACKUP_RUNTIME.py",
            "--create",
            "--force",
            "--drill-latest",
        ])
    except Exception:
        print()
        print("=" * 78)
        print("QPX BACKUP RECOVERY CODE: INSTALLED AND PUSHED")
        print("INITIAL BACKUP/DRILL: NEEDS RETRY")
        print("=" * 78)
        print(
            "Re-run:\n"
            "python QPX_BACKUP_RUNTIME.py "
            "--create --force --drill-latest"
        )
        return 2

    print()
    print("=" * 78)
    print("QPX VERIFIED BACKUP AND RECOVERY: COMPLETE")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
