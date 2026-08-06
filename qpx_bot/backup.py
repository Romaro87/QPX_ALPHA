"""Verified QPX runtime backups, recovery drills, and guarded restore."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence

from qpx_bot.paper_state import StateStore


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "backup_config.json"
DEFAULT_RUNTIME_DIR = PACKAGE_DIR / "backup_runtime"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "qpx_backup"

BACKUP_MANIFEST = "QPX_BACKUP_MANIFEST.json"

EXACT_FILES = (
    "qpx_bot/swing_universe.json",
    "qpx_bot/operations_config.json",
    "qpx_bot/backup_config.json",
    "qpx_bot/session_execution_config.json",
    "qpx_bot/qualification_config.json",
    "qpx_bot/data_inputs/SWING.csv",
    "qpx_bot/data_inputs/QDTE.csv",
    "qpx_bot/data_inputs/QDTE_DIVIDENDS.csv",
    "qpx_bot/data_inputs/VIX.csv",
    "qpx_bot/data_inputs/DOWNLOAD_MANIFEST.json",
    "reports/qpx_paper/paper_status.txt",
    "reports/qpx_paper/paper_status.json",
    "reports/qpx_operations/latest_health.txt",
    "reports/qpx_operations/latest_health.json",
    "reports/qpx_session_execution/latest_session_execution.txt",
    "reports/qpx_session_execution/latest_session_execution.json",
    "reports/qpx_qualification/latest_qualification.txt",
    "reports/qpx_qualification/latest_qualification.json",
    "reports/qpx_qualification/session_ledger.csv",
    "reports/qpx_symbol_selection/symbol_selection_report.txt",
    "reports/qpx_symbol_selection/symbol_selection_rankings.csv",
    "reports/qpx_symbol_selection/symbol_selection_result.json",
)

RUNTIME_ROOTS = (
    "qpx_bot/paper_runtime",
    "qpx_bot/selection_runtime",
    "qpx_bot/operations_runtime",
    "qpx_bot/qualification_runtime",
)

RESTORE_ROOTS = RUNTIME_ROOTS

EXCLUDED_NAMES = {
    "paper.lock",
    "operations.lock",
    "backup.lock",
    "qualification.lock",
}

EXCLUDED_SUFFIXES = (
    ".tmp",
    ".bak",
)


@dataclass(frozen=True, slots=True)
class BackupConfig:
    schema_version: int
    archive_directory_name: str
    retention_archives: int
    require_successful_session: bool
    notify_with_termux_api: bool

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported backup configuration version."
            )

        if not self.archive_directory_name.strip():
            raise ValueError(
                "Archive directory name cannot be empty."
            )

        candidate = Path(self.archive_directory_name)

        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(
                "Archive directory must be a safe sibling name."
            )

        if self.retention_archives < 3:
            raise ValueError(
                "Backup retention must keep at least three archives."
            )


@dataclass(frozen=True, slots=True)
class BackupResult:
    created: bool
    archive_path: Path | None
    identity: str | None
    status: str
    message: str
    files: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class VerificationResult:
    archive_path: Path
    identity: str
    files: int
    total_bytes: int
    paper_state_id: str
    paper_revision: int
    paper_last_processed_date: str | None
    journal_records: int
    git_commit: str | None


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=True)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())

    temporary.replace(path)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        file.write(content)
        file.flush()
        os.fsync(file.fileno())

    temporary.replace(path)


def load_backup_config(
    filename: str | Path = DEFAULT_CONFIG_PATH,
) -> BackupConfig:
    path = Path(filename).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, Mapping):
        raise ValueError(
            "Backup configuration must be a JSON object."
        )

    config = BackupConfig(
        schema_version=int(payload["schema_version"]),
        archive_directory_name=str(
            payload["archive_directory_name"]
        ),
        retention_archives=int(
            payload["retention_archives"]
        ),
        require_successful_session=bool(
            payload["require_successful_session"]
        ),
        notify_with_termux_api=bool(
            payload["notify_with_termux_api"]
        ),
    )
    config.validate()
    return config


def default_archive_directory(
    project_root: str | Path,
    config: BackupConfig,
) -> Path:
    root = Path(project_root).expanduser().resolve()
    return root.parent / config.archive_directory_name


def _load_optional_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, Mapping) else {}


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)

    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
    ):
        raise RuntimeError(
            f"Unsafe backup member path: {value!r}"
        )

    return str(path)


def _is_backup_candidate(path: Path) -> bool:
    return (
        path.is_file()
        and path.name not in EXCLUDED_NAMES
        and not path.name.startswith(".")
        and not path.name.endswith(EXCLUDED_SUFFIXES)
    )


def collect_source_files(
    project_root: str | Path,
) -> tuple[Path, ...]:
    root = Path(project_root).expanduser().resolve()
    collected: dict[str, Path] = {}

    for relative in EXACT_FILES:
        path = root / relative

        if _is_backup_candidate(path):
            collected[relative] = path

    for relative_root in RUNTIME_ROOTS:
        directory = root / relative_root

        if not directory.exists():
            continue

        for path in directory.rglob("*"):
            if not _is_backup_candidate(path):
                continue

            relative = path.relative_to(root).as_posix()
            collected[relative] = path

    return tuple(
        collected[name]
        for name in sorted(collected)
    )


def _git_commit(project_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=True,
        )
    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return None

    value = completed.stdout.strip()
    return value or None


def _paper_snapshot(
    project_root: Path,
) -> tuple[dict[str, Any], int]:
    store = StateStore(
        project_root / "qpx_bot" / "paper_runtime"
    )

    if not store.exists():
        raise RuntimeError(
            "Persistent paper state does not exist."
        )

    state = store.load()
    _, _, records = store.verify_journal()
    return (
        {
            "state_id": state.state_id,
            "revision": state.revision,
            "last_processed_date": (
                state.last_processed_date.isoformat()
                if state.last_processed_date
                else None
            ),
            "swing_symbol": state.swing_symbol,
            "income_symbol": state.income_symbol,
        },
        records,
    )


def _operations_snapshot(
    project_root: Path,
) -> Mapping[str, Any]:
    return _load_optional_json(
        project_root
        / "qpx_bot"
        / "operations_runtime"
        / "operations_state.json"
    )


def _identity(
    *,
    paper: Mapping[str, Any],
    journal_records: int,
    successful_session: str | None,
) -> str:
    payload = {
        "state_id": paper["state_id"],
        "revision": paper["revision"],
        "last_processed_date": paper["last_processed_date"],
        "journal_records": journal_records,
        "successful_session": successful_session,
    }
    return _sha256_bytes(_canonical_json(payload))[:20]


def _backup_filename(
    *,
    paper: Mapping[str, Any],
    identity: str,
    unique: bool,
) -> str:
    session = (
        str(paper.get("last_processed_date"))
        if paper.get("last_processed_date")
        else "unprocessed"
    )
    revision = int(paper.get("revision", 0))
    suffix = ""

    if unique:
        suffix = (
            "_"
            + datetime.now(
                timezone.utc
            ).strftime("%Y%m%dT%H%M%SZ")
        )

    return (
        f"qpx_backup_{session}_r{revision}_"
        f"{identity}{suffix}.zip"
    )


def _compression() -> int:
    try:
        import zlib  # noqa: F401
    except ImportError:
        return zipfile.ZIP_STORED

    return zipfile.ZIP_DEFLATED


@contextmanager
def backup_lock(
    runtime_directory: str | Path,
    *,
    stale_after_seconds: float = 21_600.0,
) -> Iterator[None]:
    directory = Path(
        runtime_directory
    ).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / "backup.lock"

    for attempt in range(2):
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )

            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
            ) as file:
                file.write(
                    json.dumps(
                        {
                            "pid": os.getpid(),
                            "created_at_utc": datetime.now(
                                timezone.utc
                            ).isoformat(),
                        }
                    )
                )
            break
        except FileExistsError:
            age = time.time() - lock_path.stat().st_mtime

            if (
                attempt == 0
                and age > stale_after_seconds
            ):
                lock_path.unlink(missing_ok=True)
                continue

            raise RuntimeError(
                "Another QPX backup or restore is active."
            )
    else:
        raise RuntimeError(
            "Unable to acquire the QPX backup lock."
        )

    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _notify(
    *,
    title: str,
    content: str,
    high_priority: bool,
    enabled: bool,
) -> None:
    if not enabled:
        return

    command = shutil.which("termux-notification")

    if command is None:
        return

    subprocess.run(
        [
            command,
            "--id",
            "qpx-backup-health",
            "--title",
            title,
            "--content",
            content[:500],
            "--priority",
            "high" if high_priority else "default",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _write_status(
    *,
    report_directory: Path,
    payload: Mapping[str, Any],
) -> None:
    report_directory.mkdir(parents=True, exist_ok=True)
    _atomic_json(
        report_directory / "latest_backup.json",
        payload,
    )
    lines = [
        "=" * 78,
        "QPX BOT v1.12 — VERIFIED BACKUP STATUS",
        "=" * 78,
    ]

    for key in (
        "status",
        "message",
        "archive_path",
        "identity",
        "created_at_utc",
        "files",
        "total_bytes",
        "verified",
        "recovery_drill",
    ):
        lines.append(
            f"{key.replace('_', ' ').title():26}: "
            f"{payload.get(key)}"
        )

    lines.extend(
        [
            "=" * 78,
            (
                "Backups contain simulated paper state only. "
                "No brokerage credentials are stored."
            ),
        ]
    )
    _atomic_text(
        report_directory / "latest_backup.txt",
        "\n".join(lines) + "\n",
    )


def _manifest_for_files(
    *,
    project_root: Path,
    files: Sequence[Path],
    paper: Mapping[str, Any],
    operations: Mapping[str, Any],
    journal_records: int,
    identity: str,
    reason: str,
) -> dict[str, Any]:
    entries = []

    for path in files:
        relative = path.relative_to(
            project_root
        ).as_posix()
        relative = _safe_relative_path(relative)
        entries.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )

    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "identity": identity,
        "reason": reason,
        "project_name": project_root.name,
        "git_commit": _git_commit(project_root),
        "paper": dict(paper),
        "journal_records": journal_records,
        "operations": {
            "last_successful_session": (
                operations.get(
                    "last_successful_session"
                )
            ),
            "consecutive_failures": int(
                operations.get(
                    "consecutive_failures",
                    0,
                )
            ),
            "paused": bool(
                operations.get("paused", False)
            ),
        },
        "files": entries,
    }


def _write_archive(
    *,
    temporary: Path,
    project_root: Path,
    files: Sequence[Path],
    manifest: Mapping[str, Any],
) -> None:
    compression = _compression()

    with zipfile.ZipFile(
        temporary,
        "w",
        compression=compression,
        allowZip64=True,
    ) as archive:
        for path in files:
            relative = path.relative_to(
                project_root
            ).as_posix()
            archive.write(
                path,
                arcname=_safe_relative_path(relative),
            )

        archive.writestr(
            BACKUP_MANIFEST,
            json.dumps(
                manifest,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )

    with temporary.open("rb") as file:
        os.fsync(file.fileno())


def _write_sidecar(archive_path: Path) -> Path:
    checksum = _sha256_file(archive_path)
    sidecar = archive_path.with_suffix(
        archive_path.suffix + ".sha256"
    )
    _atomic_text(
        sidecar,
        f"{checksum}  {archive_path.name}\n",
    )
    return sidecar


def _read_sidecar(archive_path: Path) -> str | None:
    sidecar = archive_path.with_suffix(
        archive_path.suffix + ".sha256"
    )

    if not sidecar.exists():
        return None

    value = sidecar.read_text(
        encoding="utf-8"
    ).strip().split()

    return value[0] if value else None


def verify_backup(
    archive_path: str | Path,
) -> VerificationResult:
    path = Path(archive_path).expanduser().resolve()

    if not path.exists():
        raise FileNotFoundError(path)

    expected_archive_hash = _read_sidecar(path)

    if (
        expected_archive_hash is not None
        and _sha256_file(path) != expected_archive_hash
    ):
        raise RuntimeError(
            "Backup archive checksum does not match its sidecar."
        )

    try:
        archive = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as exc:
        raise RuntimeError(
            "Backup is not a valid ZIP archive."
        ) from exc

    with archive:
        names = archive.namelist()

        if len(names) != len(set(names)):
            raise RuntimeError(
                "Backup contains duplicate member names."
            )

        for name in names:
            if name == BACKUP_MANIFEST:
                continue

            _safe_relative_path(name)

        if BACKUP_MANIFEST not in names:
            raise RuntimeError(
                "Backup manifest is missing."
            )

        bad_member = archive.testzip()

        if bad_member is not None:
            raise RuntimeError(
                f"Backup CRC failed for {bad_member}."
            )

        try:
            manifest = json.loads(
                archive.read(
                    BACKUP_MANIFEST
                ).decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError(
                "Backup manifest is invalid."
            ) from exc

        if not isinstance(manifest, Mapping):
            raise RuntimeError(
                "Backup manifest root must be an object."
            )

        if int(manifest.get("schema_version", -1)) != 1:
            raise RuntimeError(
                "Unsupported backup manifest version."
            )

        entries = manifest.get("files")

        if not isinstance(entries, list) or not entries:
            raise RuntimeError(
                "Backup manifest has no file entries."
            )

        expected_names = {BACKUP_MANIFEST}
        total_bytes = 0

        for entry in entries:
            if not isinstance(entry, Mapping):
                raise RuntimeError(
                    "Backup manifest entry is invalid."
                )

            name = _safe_relative_path(
                str(entry.get("path", ""))
            )

            if name in expected_names:
                raise RuntimeError(
                    f"Duplicate manifest path: {name}"
                )

            expected_names.add(name)

            if name not in names:
                raise RuntimeError(
                    f"Backup member is missing: {name}"
                )

            content = archive.read(name)
            expected_size = int(entry.get("size", -1))
            expected_hash = str(entry.get("sha256", ""))

            if len(content) != expected_size:
                raise RuntimeError(
                    f"Backup size mismatch: {name}"
                )

            if _sha256_bytes(content) != expected_hash:
                raise RuntimeError(
                    f"Backup content hash mismatch: {name}"
                )

            total_bytes += len(content)

        if set(names) != expected_names:
            unexpected = sorted(
                set(names) - expected_names
            )
            raise RuntimeError(
                "Backup contains unmanifested members: "
                + ", ".join(unexpected)
            )

        paper = manifest.get("paper")

        if not isinstance(paper, Mapping):
            raise RuntimeError(
                "Backup paper snapshot is missing."
            )

        return VerificationResult(
            archive_path=path,
            identity=str(manifest["identity"]),
            files=len(entries),
            total_bytes=total_bytes,
            paper_state_id=str(paper["state_id"]),
            paper_revision=int(paper["revision"]),
            paper_last_processed_date=(
                str(paper["last_processed_date"])
                if paper.get("last_processed_date")
                else None
            ),
            journal_records=int(
                manifest["journal_records"]
            ),
            git_commit=(
                str(manifest["git_commit"])
                if manifest.get("git_commit")
                else None
            ),
        )


def _extract_verified(
    archive_path: Path,
    destination: Path,
) -> Mapping[str, Any]:
    verify_backup(archive_path)

    with zipfile.ZipFile(
        archive_path,
        "r",
    ) as archive:
        manifest = json.loads(
            archive.read(
                BACKUP_MANIFEST
            ).decode("utf-8")
        )

        for entry in manifest["files"]:
            relative = _safe_relative_path(
                str(entry["path"])
            )
            target = destination / relative
            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            content = archive.read(relative)
            target.write_bytes(content)

    return manifest


def recovery_drill(
    archive_path: str | Path,
) -> VerificationResult:
    path = Path(archive_path).expanduser().resolve()
    verification = verify_backup(path)

    with tempfile.TemporaryDirectory(
        prefix="qpx_recovery_drill_"
    ) as temporary_directory:
        staging = Path(temporary_directory)
        manifest = _extract_verified(
            path,
            staging,
        )
        store = StateStore(
            staging / "qpx_bot" / "paper_runtime"
        )
        state = store.load()
        _, _, records = store.verify_journal()

        if state.state_id != verification.paper_state_id:
            raise RuntimeError(
                "Recovery drill state ID does not match manifest."
            )

        if state.revision != verification.paper_revision:
            raise RuntimeError(
                "Recovery drill revision does not match manifest."
            )

        if records != verification.journal_records:
            raise RuntimeError(
                "Recovery drill journal count does not match."
            )

        for relative in (
            "qpx_bot/swing_universe.json",
            "qpx_bot/operations_config.json",
            "qpx_bot/backup_config.json",
        ):
            candidate = staging / relative

            if candidate.exists():
                payload = json.loads(
                    candidate.read_text(
                        encoding="utf-8"
                    )
                )

                if not isinstance(payload, Mapping):
                    raise RuntimeError(
                        f"Recovered JSON is invalid: {relative}"
                    )

        if (
            manifest["identity"]
            != verification.identity
        ):
            raise RuntimeError(
                "Recovery drill identity mismatch."
            )

    return verification


def _rotate_archives(
    archive_directory: Path,
    retention: int,
) -> None:
    archives = sorted(
        archive_directory.glob(
            "qpx_backup_*.zip"
        ),
        key=lambda path: (
            path.stat().st_mtime,
            path.name,
        ),
        reverse=True,
    )

    for path in archives[retention:]:
        path.unlink(missing_ok=True)
        path.with_suffix(
            path.suffix + ".sha256"
        ).unlink(missing_ok=True)


def create_backup(
    *,
    project_root: str | Path = PROJECT_ROOT,
    config: BackupConfig,
    archive_directory: str | Path,
    runtime_directory: str | Path = DEFAULT_RUNTIME_DIR,
    report_directory: str | Path = DEFAULT_REPORT_DIR,
    force: bool = False,
    unique: bool = False,
    reason: str = "scheduled",
    _lock_held: bool = False,
) -> BackupResult:
    root = Path(project_root).expanduser().resolve()
    archives = Path(
        archive_directory
    ).expanduser().resolve()
    runtime = Path(
        runtime_directory
    ).expanduser().resolve()
    reports = Path(
        report_directory
    ).expanduser().resolve()
    archives.mkdir(parents=True, exist_ok=True)
    lock_context = (
        nullcontext()
        if _lock_held
        else backup_lock(runtime)
    )

    with lock_context:
        paper, journal_records = _paper_snapshot(root)
        operations = _operations_snapshot(root)
        successful_session = (
            str(
                operations.get(
                    "last_successful_session"
                )
            )
            if operations.get(
                "last_successful_session"
            )
            else None
        )

        if (
            config.require_successful_session
            and not force
        ):
            processed = paper.get(
                "last_processed_date"
            )

            if (
                successful_session is None
                or processed != successful_session
            ):
                message = (
                    "Backup skipped because no fully verified "
                    "successful session is recorded."
                )
                result = BackupResult(
                    created=False,
                    archive_path=None,
                    identity=None,
                    status="SKIPPED",
                    message=message,
                    files=0,
                    total_bytes=0,
                )
                _write_status(
                    report_directory=reports,
                    payload={
                        **asdict(result),
                        "archive_path": None,
                        "created_at_utc": datetime.now(
                            timezone.utc
                        ).isoformat(),
                        "verified": False,
                        "recovery_drill": False,
                    },
                )
                return result

        identity = _identity(
            paper=paper,
            journal_records=journal_records,
            successful_session=successful_session,
        )
        filename = _backup_filename(
            paper=paper,
            identity=identity,
            unique=unique,
        )
        final_path = archives / filename

        if final_path.exists() and not unique:
            verification = verify_backup(final_path)
            result = BackupResult(
                created=False,
                archive_path=final_path,
                identity=verification.identity,
                status="CURRENT",
                message=(
                    "Verified backup already exists for "
                    "this exact paper-state revision."
                ),
                files=verification.files,
                total_bytes=verification.total_bytes,
            )
            _write_status(
                report_directory=reports,
                payload={
                    **asdict(result),
                    "archive_path": str(final_path),
                    "created_at_utc": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "verified": True,
                    "recovery_drill": False,
                },
            )
            return result

        files = collect_source_files(root)

        if not files:
            raise RuntimeError(
                "No QPX runtime files were found for backup."
            )

        manifest = _manifest_for_files(
            project_root=root,
            files=files,
            paper=paper,
            operations=operations,
            journal_records=journal_records,
            identity=identity,
            reason=reason,
        )
        temporary = archives / (
            "." + filename + ".tmp"
        )

        try:
            _write_archive(
                temporary=temporary,
                project_root=root,
                files=files,
                manifest=manifest,
            )
            temporary.replace(final_path)
            _write_sidecar(final_path)
            verification = verify_backup(final_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            final_path.unlink(missing_ok=True)
            final_path.with_suffix(
                final_path.suffix + ".sha256"
            ).unlink(missing_ok=True)
            raise

        _rotate_archives(
            archives,
            config.retention_archives,
        )
        result = BackupResult(
            created=True,
            archive_path=final_path,
            identity=verification.identity,
            status="CREATED",
            message=(
                "Backup created and every manifest checksum "
                "was verified."
            ),
            files=verification.files,
            total_bytes=verification.total_bytes,
        )
        _write_status(
            report_directory=reports,
            payload={
                **asdict(result),
                "archive_path": str(final_path),
                "created_at_utc": datetime.now(
                    timezone.utc
                ).isoformat(),
                "verified": True,
                "recovery_drill": False,
            },
        )
        return result


def latest_backup(
    archive_directory: str | Path,
) -> Path:
    directory = Path(
        archive_directory
    ).expanduser().resolve()
    candidates = sorted(
        directory.glob(
            "qpx_backup_*.zip"
        ),
        key=lambda path: (
            path.stat().st_mtime,
            path.name,
        ),
        reverse=True,
    )

    if not candidates:
        raise FileNotFoundError(
            f"No QPX backups exist in {directory}"
        )

    return candidates[0]


def list_backups(
    archive_directory: str | Path,
) -> tuple[Path, ...]:
    directory = Path(
        archive_directory
    ).expanduser().resolve()
    return tuple(
        sorted(
            directory.glob(
                "qpx_backup_*.zip"
            ),
            key=lambda path: (
                path.stat().st_mtime,
                path.name,
            ),
            reverse=True,
        )
    )


def _runtime_lock_present(project_root: Path) -> list[Path]:
    locks = [
        project_root
        / "qpx_bot"
        / "paper_runtime"
        / "paper.lock",
        project_root
        / "qpx_bot"
        / "operations_runtime"
        / "operations.lock",
        project_root
        / "qpx_bot"
        / "qualification_runtime"
        / "qualification.lock",
    ]
    return [
        path
        for path in locks
        if path.exists()
    ]


def restore_backup(
    *,
    archive_path: str | Path,
    project_root: str | Path,
    config: BackupConfig,
    archive_directory: str | Path,
    runtime_directory: str | Path,
    report_directory: str | Path,
    confirm_restore: bool,
) -> VerificationResult:
    if not confirm_restore:
        raise RuntimeError(
            "Restore requires --confirm-restore."
        )

    archive = Path(
        archive_path
    ).expanduser().resolve()
    root = Path(
        project_root
    ).expanduser().resolve()
    runtime = Path(
        runtime_directory
    ).expanduser().resolve()
    reports = Path(
        report_directory
    ).expanduser().resolve()
    verification = recovery_drill(archive)
    locks = _runtime_lock_present(root)

    if locks:
        raise RuntimeError(
            "Restore refused because runtime locks are active: "
            + ", ".join(str(path) for path in locks)
        )

    with backup_lock(runtime):
        create_backup(
            project_root=root,
            config=config,
            archive_directory=archive_directory,
            runtime_directory=runtime,
            report_directory=reports,
            force=True,
            unique=True,
            reason="pre_restore_safety_snapshot",
            _lock_held=True,
        )

        paper_runtime = (
            root / "qpx_bot" / "paper_runtime"
        )
        paper_runtime.mkdir(
            parents=True,
            exist_ok=True,
        )
        restore_store = StateStore(
            paper_runtime
        )
        restore_store.activate_kill_switch(
            (
                "QPX recovery restore in progress. "
                "Manual resume required."
            ),
            owner="restore_guard",
        )

        with tempfile.TemporaryDirectory(
            prefix="qpx_restore_staging_",
            dir=str(
                Path(
                    archive_directory
                ).expanduser().resolve()
            ),
        ) as temporary_directory:
            staging = Path(temporary_directory)
            manifest = _extract_verified(
                archive,
                staging,
            )

            for relative_root in RESTORE_ROOTS:
                live = root / relative_root
                staged = staging / relative_root

                if live.exists():
                    shutil.rmtree(live)

                if staged.exists():
                    live.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )
                    shutil.copytree(staged, live)

            for entry in manifest["files"]:
                relative = _safe_relative_path(
                    str(entry["path"])
                )

                if any(
                    relative == root_name
                    or relative.startswith(
                        root_name + "/"
                    )
                    for root_name in RESTORE_ROOTS
                ):
                    continue

                staged_file = staging / relative
                live_file = root / relative
                live_file.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                temporary_live = live_file.with_suffix(
                    live_file.suffix + ".restore.tmp"
                )
                shutil.copy2(
                    staged_file,
                    temporary_live,
                )
                temporary_live.replace(live_file)

        paper_runtime.mkdir(
            parents=True,
            exist_ok=True,
        )
        live_store = StateStore(
            paper_runtime
        )
        live_store.activate_kill_switch(
            (
                "Restored from verified backup. "
                "Review health reports, then resume manually."
            ),
            owner="restore_guard",
        )
        live_state = live_store.load()
        _, _, live_records = live_store.verify_journal()

        if (
            live_state.state_id
            != verification.paper_state_id
            or live_state.revision
            != verification.paper_revision
            or live_records
            != verification.journal_records
        ):
            raise RuntimeError(
                "Post-restore state verification failed."
            )

        payload = {
            "status": "RESTORED_AND_PAUSED",
            "message": (
                "Verified backup restored. Paper kill switch "
                "remains active until manual resume."
            ),
            "archive_path": str(archive),
            "identity": verification.identity,
            "created_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "files": verification.files,
            "total_bytes": verification.total_bytes,
            "verified": True,
            "recovery_drill": True,
        }
        _write_status(
            report_directory=reports,
            payload=payload,
        )
        return verification


def _format_result(result: BackupResult) -> str:
    return "\n".join(
        [
            "=" * 78,
            "QPX BOT v1.12 — VERIFIED BACKUP",
            "=" * 78,
            f"Status       : {result.status}",
            f"Message      : {result.message}",
            f"Archive      : {result.archive_path}",
            f"Identity     : {result.identity}",
            f"Files        : {result.files}",
            f"Source bytes : {result.total_bytes:,}",
            "=" * 78,
        ]
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create, verify, drill, list, or restore QPX "
            "runtime backups."
        )
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
    )
    parser.add_argument(
        "--archive-dir",
        default=None,
    )
    parser.add_argument(
        "--runtime-dir",
        default=str(DEFAULT_RUNTIME_DIR),
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
    )
    parser.add_argument(
        "--create",
        action="store_true",
    )
    parser.add_argument(
        "--verify-latest",
        action="store_true",
    )
    parser.add_argument(
        "--drill-latest",
        action="store_true",
    )
    parser.add_argument(
        "--list",
        action="store_true",
    )
    parser.add_argument(
        "--restore-latest",
        action="store_true",
    )
    parser.add_argument(
        "--archive",
        default=None,
    )
    parser.add_argument(
        "--confirm-restore",
        action="store_true",
    )
    parser.add_argument(
        "--force",
        action="store_true",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_backup_config(args.config)
    archive_directory = (
        Path(args.archive_dir).expanduser().resolve()
        if args.archive_dir
        else default_archive_directory(
            PROJECT_ROOT,
            config,
        )
    )
    actions = any(
        (
            args.create,
            args.verify_latest,
            args.drill_latest,
            args.list,
            args.restore_latest,
            bool(args.archive),
        )
    )

    if not actions:
        args.create = True
        args.drill_latest = True

    if args.list:
        backups = list_backups(
            archive_directory
        )
        print("=" * 78)
        print("QPX VERIFIED BACKUPS")
        print("=" * 78)

        for path in backups:
            print(path)

        if not backups:
            print("No backups found.")

    created_path: Path | None = None

    if args.create:
        try:
            result = create_backup(
                project_root=PROJECT_ROOT,
                config=config,
                archive_directory=archive_directory,
                runtime_directory=args.runtime_dir,
                report_directory=args.report_dir,
                force=args.force,
                reason=(
                    "manual_force"
                    if args.force
                    else "scheduled"
                ),
            )
            created_path = result.archive_path
            print(_format_result(result))
        except Exception as exc:
            _notify(
                title="QPX backup failed",
                content=f"{type(exc).__name__}: {exc}",
                high_priority=True,
                enabled=config.notify_with_termux_api,
            )
            raise

    selected_archive = (
        Path(args.archive).expanduser().resolve()
        if args.archive
        else None
    )

    if args.verify_latest:
        selected_archive = (
            selected_archive
            or created_path
            or latest_backup(
                archive_directory
            )
        )
        result = verify_backup(selected_archive)
        print(
            "QPX BACKUP VERIFICATION: PASS\n"
            f"{result.archive_path}"
        )

    if args.drill_latest:
        selected_archive = (
            selected_archive
            or created_path
            or latest_backup(
                archive_directory
            )
        )
        result = recovery_drill(
            selected_archive
        )
        payload = {
            "status": "VERIFIED",
            "message": (
                "Backup verification and isolated recovery "
                "drill passed."
            ),
            "archive_path": str(
                result.archive_path
            ),
            "identity": result.identity,
            "created_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "files": result.files,
            "total_bytes": result.total_bytes,
            "verified": True,
            "recovery_drill": True,
        }
        _write_status(
            report_directory=Path(
                args.report_dir
            ).expanduser().resolve(),
            payload=payload,
        )
        print(
            "QPX RECOVERY DRILL: PASS\n"
            f"{result.archive_path}"
        )

    if args.restore_latest:
        selected_archive = (
            selected_archive
            or latest_backup(
                archive_directory
            )
        )
        result = restore_backup(
            archive_path=selected_archive,
            project_root=PROJECT_ROOT,
            config=config,
            archive_directory=archive_directory,
            runtime_directory=args.runtime_dir,
            report_directory=args.report_dir,
            confirm_restore=args.confirm_restore,
        )
        print(
            "QPX VERIFIED RESTORE: COMPLETE\n"
            f"{result.archive_path}\n"
            "Paper trading remains paused. Review health, then "
            "run QPX_RUN_DAILY_OPERATIONS.py "
            "--resume-restored-paper "
            "--confirm-resume-restored-paper."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
