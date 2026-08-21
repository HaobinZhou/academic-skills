#!/usr/bin/env python3
"""Maintain deterministic current-state governance for durable projects."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows retains atomic single writes.
    fcntl = None  # type: ignore[assignment]


SCHEMA_MARKER = "<!-- oppen-project-steward:v3 -->"
STEWARD_NAMESPACE = ".oppen-project-steward"
REGISTRY_NAME = "registry.md"
MANAGED_STATE_NAME = ".managed-state.json"
MANAGED_STATE_SCHEMA_VERSION = 1
ROLE_START = "<!-- oppen-project-steward:roles:start -->"
ROLE_END = "<!-- oppen-project-steward:roles:end -->"
CANONICAL_START = "<!-- oppen-project-steward:canonical:start -->"
CANONICAL_END = "<!-- oppen-project-steward:canonical:end -->"
DELIVERABLE_START = "<!-- oppen-project-steward:deliverables:start -->"
DELIVERABLE_END = "<!-- oppen-project-steward:deliverables:end -->"
CONTRACT_AUDIT_START = "<!-- oppen-project-steward:contract-audits:start -->"
CONTRACT_AUDIT_END = "<!-- oppen-project-steward:contract-audits:end -->"
ATTENTION_INDEX_MARKER = "<!-- oppen-project-steward:attention-index -->"
MEMORY_INDEX_MARKER = "<!-- oppen-project-steward:memory-index -->"
ATTENTION_HIGH_WATER = re.compile(
    r"<!-- oppen-project-steward:attention-high-water:(\d{4}) -->"
)
MEMORY_HIGH_WATER = re.compile(
    r"<!-- oppen-project-steward:memory-high-water:(\d{4}) -->"
)
ATTENTION_ID = re.compile(r"^A-(\d{4})$")
MEMORY_ID = re.compile(r"^M-(\d{4})$")

ROLE_ALIASES = {
    "Source": ("src", "app"),
    "Data": ("Data", "data"),
    "Deliverables": (
        "Deliverables",
        "deliverables",
        "Output",
        "output",
        "Outputs",
        "outputs",
    ),
}
ROLE_DESCRIPTIONS = {
    "Source": "Code and implementation",
    "Data": "Raw and derived machine-readable data",
    "Deliverables": "Current outputs retained for direct human use",
}
ALLOWED_STATUSES = {"draft", "partially-frozen", "frozen"}
HUMAN_DELIVERABLE_SUFFIXES = {
    ".csv",
    ".tsv",
    ".xlsx",
    ".ods",
    ".md",
    ".html",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".tif",
    ".tiff",
    ".docx",
    ".pptx",
    ".txt",
}
FORBIDDEN_DELIVERABLE_SUFFIXES = {
    ".log",
    ".tmp",
    ".cache",
    ".pickle",
    ".pkl",
    ".rds",
    ".rdata",
    ".sqlite",
    ".db",
    ".parquet",
    ".feather",
    ".npy",
    ".npz",
}
FORBIDDEN_DELIVERABLE_TOKEN = re.compile(
    r"(?:^|[_\-.])(?:audit|trace|acceptance|manifest|session|cache|qa|qc|"
    r"diagnostic|debug|intermediate|draft|staging|tmp|temp|old|backup|legacy|"
    r"invalidated|run[_\-.]?\d+)(?:[_\-.]|$)",
    re.IGNORECASE,
)
PARALLEL_COPY_TOKEN = re.compile(
    r"(?:^|[_\-.])(?:old|new|updated|final|backup|copy|legacy|superseded|obsolete)"
    r"(?:[_\-.](?:\d{8}|\d{4}-\d{2}-\d{2}|v?\d+))?$|"
    r"(?:副本|备份|旧版|新版|最终版)",
    re.IGNORECASE,
)
VERSION_SUFFIX = re.compile(
    r"(?:[_\-.](?:v\d+|\d{8}|\d{4}-\d{2}-\d{2}))$", re.IGNORECASE
)
RECOVERABLE_AUDIT_RESIDUE = re.compile(
    r"^(?:\.steward-(?:promote|previous|rollback|recover-remove)-.+|"
    r"(?:staging|failed|incomplete|abandoned|candidate|partial)"
    r"(?:[._-].*)?)$",
    re.IGNORECASE,
)
KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
PLACEHOLDER_PATTERN = re.compile(r"\bTODO\b|请填写", re.IGNORECASE)
MEMORY_STATUSES = {"active", "superseded", "invalidated"}
ATTENTION_PAYLOAD_FIELDS = (
    "title",
    "blocking",
    "observation",
    "evidence",
    "why_it_matters",
    "why_no_action_was_taken",
    "human_decision_needed",
)
ATTENTION_SECTIONS = (
    "Observation",
    "Evidence",
    "Why It Matters",
    "Why No Action Was Taken",
    "Human Decision Needed",
)
ATTENTION_METADATA_FIELDS = ("id", "title", "blocking")
CONTRACT_AUDIT_PAYLOAD_FIELDS = (
    "purpose_and_risk",
    "contract",
    "edge_cases_and_verification",
    "known_limits",
)
MEMORY_PAYLOAD_FIELDS = (
    "title",
    "related_topics",
    "supersedes",
    "invalidates",
    "before",
    "trigger",
    "decision",
    "why",
    "rejected_or_prior_approach",
    "consequence",
)
MEMORY_SECTIONS = (
    "Before",
    "Trigger",
    "Decision",
    "Why",
    "Rejected or Prior Approach",
    "Consequence",
)
MEMORY_METADATA_FIELDS = (
    "id",
    "status",
    "title",
    "related_topics",
    "supersedes",
    "invalidates",
    "superseded_by",
    "invalidated_by",
)
ADOPTION_PAYLOAD_FIELDS = (
    "role_mappings",
    "initial_canonical_registrations",
    "initial_deliverable_registrations",
)
ADOPTION_CANONICAL_FIELDS = (
    "topic",
    "path",
    "section",
    "status",
    "verification",
)
ADOPTION_DELIVERABLE_FIELDS = (
    "id",
    "path",
    "kind",
    "audience",
    "producer",
)
IGNORED_PROJECT_DIRS = {
    ".git",
    ".agents",
    ".codex",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    "__pycache__",
}


class ProjectError(RuntimeError):
    """Raised when deterministic project governance cannot proceed safely."""


class RecoverableBlocker(ProjectError):
    """Raised when a deterministic operational precondition blocks mutation."""

    def __init__(
        self, code: str, message: str, paths: tuple[str, ...], recovery: str
    ) -> None:
        self.code = code
        self.paths = paths
        self.recovery = recovery
        super().__init__(message)

    def __str__(self) -> str:
        paths = ", ".join(self.paths) if self.paths else "(none)"
        return (
            f"BLOCKED_RECOVERABLE: {self.code}: {super().__str__()}\n"
            f"affected paths: {paths}\n"
            f"safe recovery action: {self.recovery}"
        )


@dataclass(frozen=True)
class CanonicalEntry:
    topic: str
    path: str
    section: str
    verification: str
    status: str = "frozen"


@dataclass(frozen=True)
class DeliverableEntry:
    deliverable_id: str
    path: str
    kind: str
    audience: str
    producer: str


@dataclass(frozen=True)
class ContractAuditEntry:
    topic: str
    audit: str
    source: str
    risk_reason: str


@dataclass(frozen=True)
class AttentionEntry:
    attention_id: str
    title: str
    blocking: bool
    path: Path


@dataclass(frozen=True)
class MemoryEntry:
    memory_id: str
    status: str
    title: str
    related_topics: tuple[str, ...]
    supersedes: tuple[str, ...]
    invalidates: tuple[str, ...]
    superseded_by: tuple[str, ...]
    invalidated_by: tuple[str, ...]
    path: Path


@dataclass(frozen=True)
class RuntimeBlocker:
    code: str
    message: str
    paths: tuple[str, ...]
    recovery: str


@dataclass(frozen=True)
class ManagedOperationWriteSet:
    root: Path
    operation: str
    exact_paths: tuple[Path, ...]
    tree_paths: tuple[Path, ...] = ()


@dataclass(frozen=True)
class ManagedTransactionPlan:
    operation: str
    write_set: ManagedOperationWriteSet
    materialized_paths: tuple[Path, ...]
    estimated_staged_regular_file_bytes: int


@dataclass(frozen=True)
class ManagedStateBaseline:
    generation: int
    files: dict[str, str]


class CandidateOverlay:
    """Resolve candidate reads without constructing a candidate project tree."""

    def __init__(
        self,
        root: Path,
        write_set: ManagedOperationWriteSet,
        staged: dict[Path, Path],
        deletes: tuple[Path, ...],
    ) -> None:
        self.root = root.resolve()
        self.write_set = write_set
        self._staged = dict(staged)
        self._deletes = frozenset(deletes)

    def logical_path(self, path: Path) -> Path:
        candidate = path if path.is_absolute() else self.root / path
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ProjectError(
                f"Candidate overlay path escapes the project: {resolved}"
            ) from exc
        return resolved

    def resolve(self, path: Path) -> Path | None:
        logical = self.logical_path(path)
        if logical in self._deletes:
            return None
        return self._staged.get(logical, logical)

    def exists(self, path: Path) -> bool:
        resolved = self.resolve(path)
        return resolved is not None and resolved.exists()

    def is_file(self, path: Path) -> bool:
        resolved = self.resolve(path)
        return resolved is not None and resolved.is_file()

    def is_dir(self, path: Path) -> bool:
        resolved = self.resolve(path)
        return resolved is not None and resolved.is_dir()

    def read_text(
        self, path: Path, *, encoding: str = "utf-8", errors: str = "strict"
    ) -> str:
        resolved = self.resolve(path)
        if resolved is None:
            raise ProjectError(f"Candidate overlay path is deleted: {path}")
        return resolved.read_text(encoding=encoding, errors=errors)


@dataclass
class ValidationReport:
    errors: list[str]
    warnings: list[str]
    blockers: list[RuntimeBlocker]
    damaging_errors: list[str]
    project_state: str | None = None

    @property
    def status(self) -> str:
        if self.project_state is not None:
            return self.project_state
        if self.damaging_errors:
            return "DAMAGED"
        if self.blockers:
            return "BLOCKED_RECOVERABLE"
        return "MANAGED_READY"

    @property
    def ok(self) -> bool:
        return self.status == "MANAGED_READY"


def managed_write_set(
    root: Path,
    operation: str,
    *,
    exact: tuple[Path, ...] = (),
    trees: tuple[Path, ...] = (),
) -> ManagedOperationWriteSet:
    root = root.resolve()

    def normalize(path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ProjectError(
                f"Managed write-set path escapes the project: {resolved}"
            ) from exc
        return resolved

    return ManagedOperationWriteSet(
        root,
        operation,
        tuple(sorted({normalize(path) for path in exact})),
        tuple(sorted({normalize(path) for path in trees})),
    )


def write_set_contains(write_set: ManagedOperationWriteSet, path: Path) -> bool:
    resolved = path.resolve()
    return resolved in write_set.exact_paths or any(
        resolved == tree or tree in resolved.parents for tree in write_set.tree_paths
    )


def build_transaction_plan(
    root: Path,
    write_set: ManagedOperationWriteSet,
    materialized_paths: tuple[Path, ...],
    estimated_staged_regular_file_bytes: int,
) -> ManagedTransactionPlan:
    root = root.resolve()
    if write_set.root != root:
        raise RecoverableBlocker(
            "BLOCKED_UNSAFE_TRANSACTION_PLAN",
            "Managed transaction write set belongs to a different project",
            (str(write_set.root), str(root)),
            "report the helper safety defect; do not retry the mutation",
        )
    normalized: set[Path] = set()
    for path in materialized_paths:
        candidate = path if path.is_absolute() else root / path
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RecoverableBlocker(
                "BLOCKED_UNSAFE_TRANSACTION_PLAN",
                f"{write_set.operation} planned materialization outside the project",
                (str(resolved),),
                "report the helper safety defect; do not retry the mutation",
            ) from exc
        normalized.add(resolved)
    unsafe = tuple(
        sorted(path for path in normalized if not write_set_contains(write_set, path))
    )
    if unsafe:
        raise RecoverableBlocker(
            "BLOCKED_UNSAFE_TRANSACTION_PLAN",
            f"{write_set.operation} planned materialization outside its managed write set",
            tuple(path.relative_to(root).as_posix() for path in unsafe),
            "report the helper safety defect; do not retry the mutation",
        )
    if estimated_staged_regular_file_bytes < 0:
        raise ProjectError("Estimated transaction bytes cannot be negative")
    return ManagedTransactionPlan(
        write_set.operation,
        write_set,
        tuple(sorted(normalized)),
        estimated_staged_regular_file_bytes,
    )


def git_dirty_paths(root: Path) -> tuple[Path, ...]:
    root = root.resolve()
    if not root.is_dir():
        return ()
    try:
        probe = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        return ()
    if probe.returncode != 0:
        return ()
    repository_root = Path(
        probe.stdout.decode("utf-8", errors="surrogateescape").strip()
    ).resolve()
    try:
        project_prefix = root.relative_to(repository_root)
    except ValueError as exc:
        raise ProjectError("Git repository root does not contain the project") from exc
    status = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            ".",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if status.returncode != 0:
        detail = status.stderr.decode("utf-8", errors="replace").strip()
        raise ProjectError(f"Cannot inspect Git dirty paths: {detail or 'git failed'}")
    records = status.stdout.split(b"\0")
    dirty: set[Path] = set()

    def add_status_path(raw_path: bytes) -> None:
        path = Path(raw_path.decode("utf-8", errors="surrogateescape"))
        if project_prefix.parts:
            try:
                path = path.relative_to(project_prefix)
            except ValueError:
                return
        dirty.add(path)

    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            raise ProjectError("Cannot parse Git porcelain status safely")
        status_code = record[:2].decode("ascii", errors="replace")
        raw_path = record[3:]
        add_status_path(raw_path)
        if "R" in status_code or "C" in status_code:
            if index >= len(records) or not records[index]:
                raise ProjectError("Cannot parse Git rename status safely")
            add_status_path(records[index])
            index += 1
    return tuple(sorted(dirty))


def assert_managed_write_set_clean(
    root: Path,
    write_set: ManagedOperationWriteSet,
    *,
    dirty_paths: tuple[Path, ...] | None = None,
    allowed_managed_drift: tuple[str, ...] = (),
) -> None:
    root = root.resolve()
    namespace = (root / STEWARD_NAMESPACE).resolve()
    managed_paths = tuple(
        path
        for path in (*write_set.exact_paths, *write_set.tree_paths)
        if path == namespace or namespace in path.parents
    )
    if namespace.exists() and managed_paths:
        assert_managed_state_integrity(root, allowed_managed_drift)

    exact = {
        path.relative_to(root)
        for path in write_set.exact_paths
        if path != namespace and namespace not in path.parents
    }
    trees = {
        path.relative_to(root)
        for path in write_set.tree_paths
        if path != namespace and namespace not in path.parents
    }
    if not exact and not trees:
        return
    dirty = git_dirty_paths(root) if dirty_paths is None else dirty_paths
    conflicts = sorted(
        {
            path
            for path in dirty
            if path in exact
            or any(path == tree or tree in path.parents for tree in trees)
        }
    )
    if conflicts:
        rendered = tuple(path.as_posix() for path in conflicts)
        raise RecoverableBlocker(
            "MANAGED_WRITESET_CONFLICT",
            f"{write_set.operation} would overwrite dirty user-owned paths",
            rendered,
            "commit, restore, or manually reconcile only the affected user paths, then rerun "
            f"{write_set.operation}",
        )


def validate_key(value: str, label: str) -> str:
    cleaned = value.strip()
    if not KEY_PATTERN.fullmatch(cleaned):
        raise ProjectError(
            f"{label} must use lowercase letters, digits, '.', '_' or '-' and be 1-80 "
            f"characters: {value!r}"
        )
    return cleaned


def validate_table_value(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ProjectError(f"{label} cannot be empty")
    if "|" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ProjectError(f"{label} cannot contain table delimiters or newlines")
    return cleaned


def resolve_project_path(
    root: Path, raw_path: str, label: str, *, must_exist: bool = True
) -> tuple[Path, str]:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ProjectError(f"{label} must stay inside the project: {raw_path}") from exc
    if must_exist and not candidate.exists():
        raise ProjectError(f"{label} does not exist: {relative.as_posix()}")
    return candidate, relative.as_posix()


def detect_roles(root: Path, *, create_missing: bool) -> dict[str, Path]:
    if create_missing:
        raise ProjectError("Optional project roles are never created automatically")
    existing = (
        {path.name: path for path in root.iterdir() if path.is_dir()}
        if root.is_dir()
        else {}
    )
    roles: dict[str, Path] = {}
    for role, aliases in ROLE_ALIASES.items():
        matches = [existing[name] for name in aliases if name in existing]
        if len(matches) > 1:
            names = ", ".join(path.name for path in matches)
            raise ProjectError(f"Ambiguous {role} directories: {names}")
        if matches:
            try:
                matches[0].resolve().relative_to(root)
            except ValueError as exc:
                raise ProjectError(
                    f"{role} directory resolves outside the project: {matches[0]}"
                ) from exc
            roles[role] = matches[0]
    return roles


def markdown_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    if not rows:
        return "_None registered._"

    def clean(value: str) -> str:
        return value.replace("|", "&#124;").replace("\n", " ")

    lines = [
        "| " + " | ".join(clean(value) for value in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(clean(value) if value else "-" for value in row) + " |"
        for row in rows
    )
    return "\n".join(lines)


def parse_markdown_table(body: str, width: int, label: str) -> list[tuple[str, ...]]:
    lines = [line.strip() for line in body.splitlines() if line.strip().startswith("|")]
    if not lines:
        return []
    if len(lines) < 2:
        raise ProjectError(f"Malformed {label} table")
    rows: list[tuple[str, ...]] = []
    for line in lines[2:]:
        values = tuple(value.strip() for value in line.strip("|").split("|"))
        if len(values) != width:
            raise ProjectError(f"Malformed {label} row: {line}")
        rows.append(tuple("" if value == "-" else value.strip("`") for value in values))
    return rows


def extract_block(text: str, start: str, end: str, label: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise ProjectError(
            f"Steward registry must contain exactly one managed {label} block; refusing to "
            "append or guess a migration"
        )
    start_index = text.index(start) + len(start)
    end_index = text.index(end)
    if end_index < start_index:
        raise ProjectError(f"Managed {label} block markers are out of order")
    return text[start_index:end_index].strip()


def replace_block(text: str, start: str, end: str, body: str, label: str) -> str:
    extract_block(text, start, end, label)
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    return pattern.sub(lambda _: f"{start}\n{body}\n{end}", text, count=1)


def atomic_write(path: Path, text: str) -> None:
    staging_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.steward-staging-",
            delete=False,
        ) as staging:
            staging.write(text)
            staging.flush()
            os.fsync(staging.fileno())
            staging_path = Path(staging.name)
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        staging_path.chmod(mode)
        staging_path.replace(path)
    finally:
        if staging_path is not None:
            staging_path.unlink(missing_ok=True)


def managed_file_transaction(
    root: Path,
    write_set: ManagedOperationWriteSet,
    writes: dict[Path, str],
    deletes: tuple[Path, ...] = (),
    *,
    validate_candidate: Callable[[CandidateOverlay], None] | None = None,
    update_managed_baseline: bool = True,
    allowed_managed_drift: tuple[str, ...] = (),
) -> ManagedTransactionPlan:
    root = root.resolve()
    normalized_writes: dict[Path, str] = {}
    for path, text in writes.items():
        candidate = path if path.is_absolute() else root / path
        normalized = candidate.resolve()
        if normalized in normalized_writes:
            raise ProjectError(
                f"Managed transaction repeats a write target: {normalized}"
            )
        normalized_writes[normalized] = text
    normalized_deletes = tuple(
        sorted(
            {
                (path if path.is_absolute() else root / path).resolve()
                for path in deletes
            }
        )
    )
    overlap = set(normalized_writes) & set(normalized_deletes)
    if overlap:
        raise ProjectError(
            "Managed transaction cannot write and delete the same path: "
            + ", ".join(str(path) for path in sorted(overlap))
        )
    baseline_path = root / STEWARD_NAMESPACE / MANAGED_STATE_NAME
    if update_managed_baseline:
        baseline_content = prepare_managed_state_update(
            root,
            normalized_writes,
            normalized_deletes,
            allowed_managed_drift=allowed_managed_drift,
        )
        if baseline_content is not None:
            normalized_writes[baseline_path] = baseline_content
    transaction_write_set = write_set
    if baseline_path in normalized_writes and not write_set_contains(
        write_set, baseline_path
    ):
        transaction_write_set = ManagedOperationWriteSet(
            write_set.root,
            write_set.operation,
            tuple(sorted({*write_set.exact_paths, baseline_path})),
            write_set.tree_paths,
        )
    affected = sorted(set(normalized_writes) | set(normalized_deletes))
    estimated_bytes = sum(
        len(text.encode("utf-8")) for text in normalized_writes.values()
    ) + sum(path.stat().st_size for path in affected if path.is_file())
    plan = build_transaction_plan(
        root,
        transaction_write_set,
        tuple(affected),
        estimated_bytes,
    )
    if not affected:
        return plan
    for path in affected:
        if path.exists() and not path.is_file():
            raise ProjectError(f"Managed transaction target must be a file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)

    staged: dict[Path, Path] = {}
    with tempfile.TemporaryDirectory(prefix="oppen-steward-transaction-") as backup_dir:
        backup_root = Path(backup_dir)
        backups: dict[Path, Path | None] = {}
        for index, path in enumerate(affected):
            if path.exists():
                backup = backup_root / f"{index:04d}.backup"
                shutil.copy2(path, backup)
                backups[path] = backup
            else:
                backups[path] = None
        promoted: set[Path] = set()
        try:
            for path, text in normalized_writes.items():
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=path.parent,
                    prefix=f".{path.name}.steward-transaction-",
                    delete=False,
                ) as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                    staged_path = Path(handle.name)
                mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
                staged_path.chmod(mode)
                staged[path] = staged_path
            overlay = CandidateOverlay(
                root, transaction_write_set, staged, normalized_deletes
            )
            for path, text in normalized_writes.items():
                if overlay.read_text(path) != text:
                    raise ProjectError(
                        f"Candidate overlay read-back failed for {path.relative_to(root)}"
                    )
            if validate_candidate is not None:
                validate_candidate(overlay)
            for path in sorted(
                path for path in normalized_writes if path != baseline_path
            ):
                staged[path].replace(path)
                staged.pop(path)
                promoted.add(path)
            for path in normalized_deletes:
                path.unlink(missing_ok=False)
                promoted.add(path)
            if baseline_path in normalized_writes:
                staged[baseline_path].replace(baseline_path)
                staged.pop(baseline_path)
                promoted.add(baseline_path)
                assert_managed_state_integrity(root)
        except Exception:
            for path in sorted(promoted):
                backup = backups[path]
                if backup is None:
                    path.unlink(missing_ok=True)
                    continue
                with tempfile.NamedTemporaryFile(
                    dir=path.parent,
                    prefix=f".{path.name}.steward-restore-",
                    delete=False,
                ) as handle:
                    restore_path = Path(handle.name)
                shutil.copy2(backup, restore_path)
                restore_path.replace(path)
            raise
        finally:
            for staged_path in staged.values():
                staged_path.unlink(missing_ok=True)
    return plan


@contextmanager
def project_write_lock(root: Path):
    if fcntl is None:
        yield
        return
    lock_root = Path(tempfile.gettempdir()) / "oppen-project-steward-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_key = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()
    with (lock_root / f"{lock_key}.lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def managed_state_path(root: Path) -> Path:
    return root / STEWARD_NAMESPACE / MANAGED_STATE_NAME


def is_managed_control_relative(relative: PurePosixPath) -> bool:
    if relative == PurePosixPath(REGISTRY_NAME):
        return True
    if relative.parts and relative.parts[0] in {"Memory", "Attention"}:
        return len(relative.parts) > 1
    return relative.parts[:2] == ("Audit", "Contracts") and len(relative.parts) > 2


def managed_control_relative(root: Path, path: Path) -> str | None:
    namespace = (root / STEWARD_NAMESPACE).resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(namespace)
    except ValueError:
        return None
    pure = PurePosixPath(relative.as_posix())
    if pure.name == ".DS_Store" or not is_managed_control_relative(pure):
        return None
    return pure.as_posix()


def managed_control_snapshot(namespace: Path) -> dict[str, str]:
    files: list[Path] = []
    registry = namespace / REGISTRY_NAME
    if registry.exists():
        files.append(registry)
    for scope in (
        namespace / "Memory",
        namespace / "Attention",
        namespace / "Audit" / "Contracts",
    ):
        if scope.exists():
            files.extend(path for path in scope.rglob("*") if path.name != ".DS_Store")
    snapshot: dict[str, str] = {}
    for path in sorted(set(files)):
        relative = path.relative_to(namespace).as_posix()
        if path.is_symlink():
            raise ProjectError(
                f"Managed control plane cannot contain symbolic links: {relative}"
            )
        if path.is_dir():
            continue
        if not path.is_file():
            raise ProjectError(
                f"Managed control plane contains an unsupported entry: {relative}"
            )
        pure = PurePosixPath(relative)
        if not is_managed_control_relative(pure):
            continue
        snapshot[relative] = file_sha256(path)
    return dict(sorted(snapshot.items()))


def render_managed_state(generation: int, files: dict[str, str]) -> str:
    payload = {
        "schema_version": MANAGED_STATE_SCHEMA_VERSION,
        "generation": generation,
        "files": [
            {"path": path, "sha256": digest} for path, digest in sorted(files.items())
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def render_managed_state_for_namespace(namespace: Path, generation: int) -> str:
    return render_managed_state(generation, managed_control_snapshot(namespace))


def _reject_managed_state_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectError(f"Managed baseline contains a duplicate key: {key}")
        result[key] = value
    return result


def load_managed_state(root: Path) -> ManagedStateBaseline:
    root = root.resolve()
    baseline_path = managed_state_path(root)
    if not baseline_path.exists():
        raise RecoverableBlocker(
            "MANAGED_BASELINE_MISSING",
            "Steward managed-state baseline is missing",
            (baseline_path.relative_to(root).as_posix(),),
            f"run managed-state --check {root}, then managed-state --bootstrap {root}",
        )
    if not baseline_path.is_file() or baseline_path.is_symlink():
        raise ProjectError("Managed baseline must be a real regular file")
    try:
        payload = json.loads(
            baseline_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_managed_state_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise ProjectError(f"Managed baseline is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "generation",
        "files",
    }:
        raise ProjectError("Managed baseline has an invalid fixed schema")
    if payload["schema_version"] != MANAGED_STATE_SCHEMA_VERSION:
        raise ProjectError("Managed baseline has an unsupported schema version")
    generation = payload["generation"]
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 1
    ):
        raise ProjectError("Managed baseline generation must be a positive integer")
    raw_files = payload["files"]
    if not isinstance(raw_files, list):
        raise ProjectError("Managed baseline files must be an array")
    files: dict[str, str] = {}
    hash_pattern = re.compile(r"^[0-9a-f]{64}$")
    namespace = root / STEWARD_NAMESPACE
    for item in raw_files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ProjectError("Managed baseline file entry has an invalid schema")
        raw_path = item["path"]
        digest = item["sha256"]
        if not isinstance(raw_path, str) or not isinstance(digest, str):
            raise ProjectError("Managed baseline path and hash must be strings")
        relative = PurePosixPath(raw_path)
        if (
            not raw_path
            or relative.is_absolute()
            or relative.as_posix() != raw_path
            or any(part in {"", ".", ".."} for part in relative.parts)
            or not is_managed_control_relative(relative)
        ):
            raise ProjectError(f"Managed baseline contains an invalid path: {raw_path}")
        resolved = (namespace / Path(*relative.parts)).resolve()
        try:
            resolved.relative_to(namespace.resolve())
        except ValueError as exc:
            raise ProjectError(
                f"Managed baseline path escapes the namespace: {raw_path}"
            ) from exc
        if raw_path in files:
            raise ProjectError(f"Managed baseline repeats a path: {raw_path}")
        if not hash_pattern.fullmatch(digest):
            raise ProjectError(f"Managed baseline has an invalid SHA-256: {raw_path}")
        files[raw_path] = digest
    if list(files) != sorted(files):
        raise ProjectError("Managed baseline file entries must be sorted by path")
    return ManagedStateBaseline(generation, files)


def managed_state_drift(root: Path, baseline: ManagedStateBaseline) -> tuple[str, ...]:
    current = managed_control_snapshot(root / STEWARD_NAMESPACE)
    relative = sorted(
        path
        for path in set(current) | set(baseline.files)
        if current.get(path) != baseline.files.get(path)
    )
    return tuple(f"{STEWARD_NAMESPACE}/{path}" for path in relative)


def assert_managed_state_integrity(
    root: Path, allowed_drift: tuple[str, ...] = ()
) -> ManagedStateBaseline:
    baseline = load_managed_state(root)
    drift = managed_state_drift(root.resolve(), baseline)
    unexpected = tuple(path for path in drift if path not in set(allowed_drift))
    if unexpected:
        raise RecoverableBlocker(
            "MANAGED_STATE_CONFLICT",
            "Steward control-plane files differ from the last successful baseline",
            unexpected,
            "inspect and reconcile only the listed Steward-managed paths; do not reset them from Git automatically",
        )
    return baseline


def prepare_managed_state_update(
    root: Path,
    writes: dict[Path, str],
    deletes: tuple[Path, ...],
    *,
    allowed_managed_drift: tuple[str, ...] = (),
) -> str | None:
    controlled_writes = {
        relative: text
        for path, text in writes.items()
        if (relative := managed_control_relative(root, path)) is not None
    }
    controlled_deletes = {
        relative
        for path in deletes
        if (relative := managed_control_relative(root, path)) is not None
    }
    if not controlled_writes and not controlled_deletes:
        return None
    baseline = assert_managed_state_integrity(root, allowed_managed_drift)
    candidate = dict(baseline.files)
    for relative in controlled_deletes:
        candidate.pop(relative, None)
    for relative, text in controlled_writes.items():
        candidate[relative] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    candidate = dict(sorted(candidate.items()))
    if candidate == baseline.files:
        return None
    return render_managed_state(baseline.generation + 1, candidate)


def parse_frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        raw = value.strip()
        try:
            metadata[key.strip()] = str(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            metadata[key.strip()] = raw.strip('"')
    return metadata


def parse_structured_frontmatter(path: Path) -> tuple[dict[str, object], str]:
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ProjectError(f"Entry lacks structured frontmatter: {path}")
    metadata: dict[str, object] = {}
    end_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
        if ":" not in line:
            raise ProjectError(
                f"Malformed structured frontmatter in {path}: {line.strip()}"
            )
        key, raw = line.split(":", 1)
        key = key.strip()
        if not key or key in metadata:
            raise ProjectError(f"Duplicate or empty frontmatter key in {path}: {key!r}")
        try:
            metadata[key] = json.loads(raw.strip())
        except json.JSONDecodeError as exc:
            raise ProjectError(
                f"Frontmatter values must use JSON syntax in {path}: {key}"
            ) from exc
    if end_index is None:
        raise ProjectError(f"Entry frontmatter is not closed: {path}")
    return metadata, "".join(lines[end_index + 1 :]).lstrip("\n")


def render_structured_entry(
    metadata: dict[str, object], heading: str, sections: list[tuple[str, str]]
) -> str:
    frontmatter = ["---"]
    frontmatter.extend(
        f"{key}: {json.dumps(value, ensure_ascii=False)}"
        for key, value in metadata.items()
    )
    frontmatter.extend(["---", "", f"# {heading}", ""])
    for name, body in sections:
        frontmatter.extend([f"## {name}", "", body.strip(), ""])
    return "\n".join(frontmatter).rstrip() + "\n"


def replace_structured_frontmatter(path: Path, metadata: dict[str, object]) -> None:
    atomic_write(path, render_replaced_structured_frontmatter(path, metadata))


def render_replaced_structured_frontmatter(
    path: Path, metadata: dict[str, object]
) -> str:
    _, body = parse_structured_frontmatter(path)
    lines = ["---"]
    lines.extend(
        f"{key}: {json.dumps(value, ensure_ascii=False)}"
        for key, value in metadata.items()
    )
    lines.extend(["---", "", body.rstrip(), ""])
    return "\n".join(lines)


def parse_fixed_sections(content: str, expected: tuple[str, ...], label: str) -> None:
    headings = list(re.finditer(r"^##\s+(.+?)\s*$", content, re.MULTILINE))
    names = tuple(match.group(1) for match in headings)
    if names != expected:
        raise ProjectError(
            f"{label} must contain exactly these sections in order: "
            + ", ".join(expected)
        )
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(content)
        if not content[match.end() : end].strip():
            raise ProjectError(f"{label} section is empty: {match.group(1)}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProjectError(f"Temporary JSON contains a duplicate key: {key}")
        result[key] = value
    return result


def load_temporary_payload(
    root: Path, payload_path: Path
) -> tuple[Path, dict[str, object]]:
    path = payload_path.expanduser().resolve()
    if not path.is_file():
        raise ProjectError(f"Temporary JSON payload does not exist: {path}")
    try:
        path.relative_to(root)
    except ValueError:
        pass
    else:
        raise ProjectError("Temporary JSON payload must stay outside the project")
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except json.JSONDecodeError as exc:
        raise ProjectError(f"Invalid temporary JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProjectError("Temporary JSON payload must be an object")
    return path, payload


def validate_payload_fields(
    payload: dict[str, object], expected: tuple[str, ...], label: str
) -> None:
    actual = set(payload)
    required = set(expected)
    if actual != required:
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unexpected: " + ", ".join(extra))
        raise ProjectError(f"Invalid {label} payload schema ({'; '.join(details)})")


def validate_semantic_text(value: object, label: str, *, title: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectError(f"{label} must be a non-empty string")
    cleaned = value.strip()
    if title and ("\n" in cleaned or "\r" in cleaned or "|" in cleaned):
        raise ProjectError(f"{label} must be a single line without table delimiters")
    if re.search(r"^##\s+", cleaned, re.MULTILINE):
        raise ProjectError(f"{label} cannot introduce level-two schema headings")
    return cleaned


def validate_id_list(
    value: object, label: str, pattern: re.Pattern[str]
) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProjectError(f"{label} must be a JSON array of IDs")
    items = tuple(value)
    if len(set(items)) != len(items):
        raise ProjectError(f"{label} cannot contain duplicate IDs")
    invalid = [item for item in items if not pattern.fullmatch(item)]
    if invalid:
        raise ProjectError(f"{label} contains invalid ID(s): {', '.join(invalid)}")
    return items


def git_repository_root(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return str(Path(result.stdout.strip()).resolve())


def adoption_preflight(root: Path) -> dict[str, object]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ProjectError(f"Existing project directory does not exist: {root}")
    report = validate_project(root)
    if report.status == "MANAGED_READY":
        status = "MANAGED_READY"
        namespace_conflict = False
    elif report.status == "ADOPTION_REQUIRED":
        status = "ADOPTION_REQUIRED"
        namespace_conflict = False
    else:
        status = "ADOPTION_BLOCKED"
        namespace_conflict = any(
            blocker.code == "NAMESPACE_CONFLICT" for blocker in report.blockers
        )
    top_level = sorted(
        path.relative_to(root).as_posix()
        for path in root.iterdir()
        if path.name not in {".git", ".DS_Store"}
    )
    documents = sorted(
        path.name
        for path in root.iterdir()
        if path.is_file()
        and (
            path.suffix.lower() in {".md", ".markdown", ".rst", ".txt"}
            or path.name in {"package.json", "pyproject.toml", "Cargo.toml"}
        )
    )
    possible_roles: dict[str, list[str]] = {}
    for role, aliases in ROLE_ALIASES.items():
        matches = [name for name in aliases if (root / name).is_dir()]
        if matches:
            possible_roles[role.casefold()] = matches
    dirty_conflicts = [
        path.as_posix()
        for path in git_dirty_paths(root)
        if path == Path(STEWARD_NAMESPACE) or Path(STEWARD_NAMESPACE) in path.parents
    ]
    blockers = [
        {
            "code": blocker.code,
            "paths": list(blocker.paths),
            "recovery": blocker.recovery,
        }
        for blocker in report.blockers
    ]
    if status == "ADOPTION_BLOCKED" and not blockers:
        blockers.append(
            {
                "code": "DAMAGED_STEWARD_STATE",
                "paths": [f"{STEWARD_NAMESPACE}/"],
                "recovery": "repair the recognizable Steward namespace before retrying adoption",
            }
        )
    return {
        "status": status,
        "git_root": git_repository_root(root),
        "steward_namespace": f"{STEWARD_NAMESPACE}/",
        "namespace_conflict": namespace_conflict,
        "existing_project_files": top_level,
        "possible_role_mappings": possible_roles,
        "existing_project_documents": documents,
        "adoption_write_set": f"{STEWARD_NAMESPACE}/**",
        "dirty_write_set_conflicts": dirty_conflicts,
        "full_project_materialization": "NO",
        "blockers": blockers,
    }


def validate_adoption_payload(
    root: Path, payload: dict[str, object]
) -> tuple[dict[str, Path], list[CanonicalEntry], list[DeliverableEntry]]:
    validate_payload_fields(payload, ADOPTION_PAYLOAD_FIELDS, "adoption")
    raw_roles = payload["role_mappings"]
    if not isinstance(raw_roles, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw_roles.items()
    ):
        raise ProjectError("Adoption role_mappings must be a JSON object of paths")
    role_names = {role.casefold(): role for role in ROLE_ALIASES}
    roles: dict[str, Path] = {}
    for raw_role, raw_path in raw_roles.items():
        role = role_names.get(raw_role.casefold())
        if role is None:
            raise ProjectError(f"Unknown optional adoption role: {raw_role}")
        path, relative = resolve_project_path(root, raw_path, f"{role} role")
        if not path.is_dir() or path.is_symlink():
            raise ProjectError(f"Adoption role must be a real directory: {relative}")
        namespace = (root / STEWARD_NAMESPACE).resolve()
        if path == namespace or namespace in path.parents:
            raise ProjectError("Adoption role cannot point into the Steward namespace")
        roles[role] = path

    raw_canonical = payload["initial_canonical_registrations"]
    if not isinstance(raw_canonical, list):
        raise ProjectError("Adoption initial_canonical_registrations must be an array")
    canonical: list[CanonicalEntry] = []
    for index, item in enumerate(raw_canonical):
        if not isinstance(item, dict):
            raise ProjectError(f"Adoption Canonical item {index} must be an object")
        validate_payload_fields(item, ADOPTION_CANONICAL_FIELDS, "adoption Canonical")
        topic = validate_key(str(item["topic"]), "canonical topic")
        owner, owner_rel = resolve_project_path(
            root, str(item["path"]), "canonical owner"
        )
        if not owner.is_file():
            raise ProjectError(f"Canonical owner must be a file: {owner_rel}")
        section_value = ""
        if item["section"] is not None:
            if not isinstance(item["section"], str):
                raise ProjectError(
                    "Adoption Canonical section must be a string or null"
                )
            section_value = validate_table_value(item["section"], "section")
            markdown_section(
                owner.read_text(encoding="utf-8", errors="replace"), section_value
            )
        status = str(item["status"]).strip().lower()
        if status not in ALLOWED_STATUSES:
            raise ProjectError(
                "Adoption Canonical status must be one of: "
                + ", ".join(sorted(ALLOWED_STATUSES))
            )
        verification, verification_rel = resolve_project_path(
            root, str(item["verification"]), "canonical verification"
        )
        error = verification_error(verification)
        if error:
            raise ProjectError(f"Invalid verification {verification_rel}: {error}")
        canonical.append(
            CanonicalEntry(topic, owner_rel, section_value, verification_rel, status)
        )
    if len({entry.topic for entry in canonical}) != len(canonical):
        raise ProjectError("Adoption Canonical topics must be unique")
    if len({(entry.path, entry.section) for entry in canonical}) != len(canonical):
        raise ProjectError("Adoption Canonical owners must be unique")

    raw_deliverables = payload["initial_deliverable_registrations"]
    if not isinstance(raw_deliverables, list):
        raise ProjectError(
            "Adoption initial_deliverable_registrations must be an array"
        )
    if raw_deliverables and "Deliverables" not in roles:
        raise ProjectError(
            "Adoption Deliverables require an explicit deliverables role mapping"
        )
    deliverables: list[DeliverableEntry] = []
    for index, item in enumerate(raw_deliverables):
        if not isinstance(item, dict):
            raise ProjectError(f"Adoption Deliverable item {index} must be an object")
        validate_payload_fields(
            item, ADOPTION_DELIVERABLE_FIELDS, "adoption Deliverable"
        )
        deliverable_id = validate_key(str(item["id"]), "deliverable id")
        kind = validate_key(str(item["kind"]), "deliverable kind")
        audience = validate_key(str(item["audience"]), "deliverable audience")
        artifact, artifact_rel = resolve_project_path(
            root, str(item["path"]), "deliverable path"
        )
        producer, producer_rel = resolve_project_path(
            root, str(item["producer"]), "deliverable producer"
        )
        if not artifact.is_file() or not producer.is_file():
            raise ProjectError("Adoption Deliverable and producer must both be files")
        artifact_error = deliverable_artifact_error(
            artifact, roles["Deliverables"].resolve()
        )
        if artifact_error:
            raise ProjectError(f"Invalid Deliverable {artifact_rel}: {artifact_error}")
        deliverables.append(
            DeliverableEntry(deliverable_id, artifact_rel, kind, audience, producer_rel)
        )
    if len({entry.deliverable_id for entry in deliverables}) != len(deliverables):
        raise ProjectError("Adoption Deliverable IDs must be unique")
    if len({entry.path for entry in deliverables}) != len(deliverables):
        raise ProjectError("Adoption Deliverable paths must be unique")
    return roles, canonical, deliverables


def apply_adoption(root: Path, payload_path: Path) -> tuple[Path, str]:
    root = root.expanduser().resolve()
    preflight = adoption_preflight(root)
    if preflight["status"] == "MANAGED_READY":
        payload_file, _ = load_temporary_payload(root, payload_path)
        payload_file.unlink(missing_ok=True)
        return steward_paths(root)[1], "ALREADY_MANAGED"
    if preflight["status"] != "ADOPTION_REQUIRED":
        raise ProjectError(
            "ADOPTION_BLOCKED: "
            + ", ".join(str(item["code"]) for item in preflight.get("blockers", []))
        )
    payload_file, raw_payload = load_temporary_payload(root, payload_path)
    roles, canonical, deliverables = validate_adoption_payload(root, raw_payload)
    registry = create_namespace_candidate(
        root,
        roles,
        canonical,
        deliverables,
        operation="adopt",
    )
    refresh_index(root)
    report = validate_project(root)
    if not report.ok:
        shutil.rmtree(root / STEWARD_NAMESPACE, ignore_errors=True)
        raise ProjectError(f"Adopted project failed validation: {report.status}")
    payload_file.unlink(missing_ok=True)
    return registry, "ADOPTED"


def parse_legacy_roles(root: Path, text: str) -> dict[str, Path]:
    rows = parse_markdown_table(
        extract_block(text, ROLE_START, ROLE_END, "role"), 3, "legacy role"
    )
    allowed = {*ROLE_ALIASES, "Audit"}
    roles: dict[str, Path] = {}
    for role, raw_path, _ in rows:
        if role not in allowed or role in roles:
            raise ProjectError(f"Legacy Steward role mapping is ambiguous: {role}")
        path, relative = resolve_project_path(root, raw_path, f"legacy {role} role")
        if not path.is_dir() or path.is_symlink():
            raise ProjectError(
                f"Legacy {role} role is not a real directory: {relative}"
            )
        roles[role] = path
    if "Audit" not in roles:
        raise ProjectError("Legacy Steward registry does not prove an Audit owner")
    if roles["Audit"].parent != root or roles["Audit"].name not in {"Audit", "audit"}:
        raise ProjectError("Legacy Steward Audit owner is not a proven root Audit path")
    return roles


def proven_legacy_optional_system(root: Path, name: str, marker: str) -> Path | None:
    path = root / name
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_dir():
        raise ProjectError(f"Legacy {name} path ownership cannot be proven")
    index = path / "index.md"
    entries = path / "entries"
    if not index.is_file() or not entries.is_dir():
        raise ProjectError(f"Legacy {name} path lacks the Steward fixed topology")
    if marker not in index.read_text(encoding="utf-8", errors="replace"):
        raise ProjectError(f"Legacy {name} index lacks its Steward ownership marker")
    return path


def legacy_layout_preflight(root: Path) -> dict[str, object]:
    root = root.expanduser().resolve()
    registry = legacy_steward_registry(root)
    if (root / STEWARD_NAMESPACE).exists():
        report = validate_project(root)
        return {
            "status": "MANAGED_READY" if report.ok else report.status,
            "legacy_paths": [],
            "upgrade_write_set": [],
            "full_project_materialization": "NO",
        }
    if registry is None:
        raise ProjectError("LEGACY_STEWARD_LAYOUT not detected")
    text = registry.read_text(encoding="utf-8", errors="replace")
    validate_registry_shape(text, "Legacy Steward registry")
    roles = parse_legacy_roles(root, text)
    memory = proven_legacy_optional_system(root, "Memory", MEMORY_INDEX_MARKER)
    attention = proven_legacy_optional_system(root, "Attention", ATTENTION_INDEX_MARKER)
    paths = [registry, roles["Audit"]]
    paths.extend(path for path in (memory, attention) if path is not None)
    dirty = git_dirty_paths(root)
    conflicts = sorted(
        path.as_posix()
        for path in dirty
        if any(
            path == source.relative_to(root) or source.relative_to(root) in path.parents
            for source in paths
        )
        or path == Path(STEWARD_NAMESPACE)
        or Path(STEWARD_NAMESPACE) in path.parents
    )
    return {
        "status": "LEGACY_STEWARD_LAYOUT",
        "legacy_paths": [path.relative_to(root).as_posix() for path in paths],
        "upgrade_write_set": [
            *[path.relative_to(root).as_posix() for path in paths],
            f"{STEWARD_NAMESPACE}/**",
        ],
        "dirty_write_set_conflicts": conflicts,
        "full_project_materialization": "NO",
    }


def apply_layout_upgrade(root: Path) -> tuple[Path, str]:
    root = root.expanduser().resolve()
    preflight = legacy_layout_preflight(root)
    if preflight["status"] == "MANAGED_READY":
        return steward_paths(root)[1], "ALREADY_UPGRADED"
    if preflight["dirty_write_set_conflicts"]:
        raise RecoverableBlocker(
            "MANAGED_WRITESET_CONFLICT",
            "upgrade-layout would overwrite dirty proven Steward paths",
            tuple(str(path) for path in preflight["dirty_write_set_conflicts"]),
            "commit, restore, or reconcile only the listed legacy Steward paths",
        )
    old_registry = root / "project.md"
    old_text = old_registry.read_text(encoding="utf-8")
    legacy_roles = parse_legacy_roles(root, old_text)
    old_audit = legacy_roles.pop("Audit")
    old_memory = proven_legacy_optional_system(root, "Memory", MEMORY_INDEX_MARKER)
    old_attention = proven_legacy_optional_system(
        root, "Attention", ATTENTION_INDEX_MARKER
    )
    canonical = parse_canonical_entries(old_text)
    upgraded_canonical: list[CanonicalEntry] = []
    for entry in canonical:
        owner, _ = resolve_project_path(root, entry.path, "legacy canonical owner")
        content = owner.read_text(encoding="utf-8", errors="replace")
        if entry.section:
            content = markdown_section(content, entry.section)
        statuses = canonical_status_values(content)
        if len(statuses) != 1 or statuses[0] not in ALLOWED_STATUSES:
            raise ProjectError(
                f"Legacy Canonical status cannot be proven: {entry.path}"
            )
        upgraded_canonical.append(
            CanonicalEntry(
                entry.topic,
                entry.path,
                entry.section,
                entry.verification,
                statuses[0],
            )
        )
    deliverables = parse_deliverable_entries(old_text)
    namespace = root / STEWARD_NAMESPACE
    sources = tuple(
        path
        for path in (old_registry, old_memory, old_attention, old_audit)
        if path is not None
    )
    write_set = managed_write_set(
        root,
        "upgrade-layout",
        exact=(old_registry,),
        trees=tuple(path for path in sources if path != old_registry) + (namespace,),
    )
    assert_managed_write_set_clean(root, write_set)
    build_transaction_plan(
        root,
        write_set,
        sources + (namespace,),
        sum(
            path.stat().st_size
            for source in sources
            for path in ((source,) if source.is_file() else source.rglob("*"))
            if path.is_file()
        ),
    )
    registry = create_namespace_candidate(
        root,
        legacy_roles,
        upgraded_canonical,
        deliverables,
        operation="upgrade-layout",
        memory_source=old_memory,
        attention_source=old_attention,
        audit_source=old_audit,
    )
    try:
        for source in sources:
            if source.is_dir():
                shutil.rmtree(source)
            else:
                source.unlink()
        refresh_index(root)
        report = validate_project(root)
        if not report.ok:
            raise ProjectError(
                f"Layout upgrade failed final validation: {report.status}"
            )
    except Exception:
        for source in sources:
            if source == old_registry:
                atomic_write(old_registry, old_text)
            else:
                if source.exists():
                    shutil.rmtree(source)
                managed_name = "Audit" if source == old_audit else source.name
                shutil.copytree(namespace / managed_name, source)
        shutil.rmtree(namespace, ignore_errors=True)
        raise
    return registry, "UPGRADED"


def role_table(root: Path, roles: dict[str, Path]) -> str:
    rows = [
        (role, roles[role].relative_to(root).as_posix(), ROLE_DESCRIPTIONS[role])
        for role in ROLE_ALIASES
        if role in roles
    ]
    return markdown_table(("Role", "Path", "Purpose"), rows)


def steward_paths(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    namespace = root / STEWARD_NAMESPACE
    return (
        namespace,
        namespace / REGISTRY_NAME,
        namespace / "Memory",
        namespace / "Attention",
        namespace / "Audit",
    )


def parse_role_mappings(root: Path, text: str) -> dict[str, Path]:
    rows = parse_markdown_table(
        extract_block(text, ROLE_START, ROLE_END, "role"), 3, "role"
    )
    roles: dict[str, Path] = {}
    for role, raw_path, purpose in rows:
        if role not in ROLE_ALIASES:
            raise ProjectError(f"Unknown optional project role: {role}")
        if role in roles:
            raise ProjectError(f"Duplicate project role mapping: {role}")
        if purpose != ROLE_DESCRIPTIONS[role]:
            raise ProjectError(f"Project role has a non-canonical purpose: {role}")
        path, relative = resolve_project_path(root, raw_path, f"{role} role")
        if not path.is_dir() or path.is_symlink():
            raise ProjectError(f"{role} role must be a real directory: {relative}")
        namespace = (root / STEWARD_NAMESPACE).resolve()
        if path == namespace or namespace in path.parents:
            raise ProjectError(f"{role} role cannot point into the Steward namespace")
        roles[role] = path
    roles["Audit"] = root / STEWARD_NAMESPACE / "Audit"
    return roles


def registry_template(
    root: Path,
    roles: dict[str, Path],
    canonical: list[CanonicalEntry] | None = None,
    deliverables: list[DeliverableEntry] | None = None,
    contract_audits: list[ContractAuditEntry] | None = None,
) -> str:
    canonical = [] if canonical is None else canonical
    deliverables = [] if deliverables is None else deliverables
    contract_audits = [] if contract_audits is None else contract_audits
    return f"""# Oppen Project Steward Registry

{SCHEMA_MARKER}

Keep this file limited to current Steward governance facts. Git stores history.

## Optional Project Roles

{ROLE_START}
{role_table(root, roles)}
{ROLE_END}

## Canonical Sources

{CANONICAL_START}
{render_canonical_entries(canonical)}
{CANONICAL_END}

## Current Deliverables

{DELIVERABLE_START}
{render_deliverable_entries(deliverables)}
{DELIVERABLE_END}

## High-Risk Contract Audits

{CONTRACT_AUDIT_START}
{render_contract_audit_entries(contract_audits)}
{CONTRACT_AUDIT_END}
"""


def validate_registry_shape(text: str, label: str) -> None:
    if SCHEMA_MARKER not in text:
        raise ProjectError(f"{label} lacks the Steward v3 marker")
    for start, end, block_label in (
        (ROLE_START, ROLE_END, "role"),
        (CANONICAL_START, CANONICAL_END, "canonical source"),
        (DELIVERABLE_START, DELIVERABLE_END, "deliverable registry"),
        (CONTRACT_AUDIT_START, CONTRACT_AUDIT_END, "contract audit index"),
    ):
        extract_block(text, start, end, block_label)


def create_namespace_candidate(
    root: Path,
    roles: dict[str, Path],
    canonical: list[CanonicalEntry],
    deliverables: list[DeliverableEntry],
    *,
    operation: str,
    memory_source: Path | None = None,
    attention_source: Path | None = None,
    audit_source: Path | None = None,
) -> Path:
    namespace, registry, _, _, _ = steward_paths(root)
    write_set = managed_write_set(root, operation, trees=(namespace,))
    assert_managed_write_set_clean(root, write_set)
    audits = (
        [
            ContractAuditEntry(
                entry.topic,
                f"{STEWARD_NAMESPACE}/Audit/Contracts/{Path(entry.audit).name}",
                entry.source,
                entry.risk_reason,
            )
            for entry in contract_audit_entries(root, audit_source)
        ]
        if audit_source
        else []
    )
    content = registry_template(root, roles, canonical, deliverables, audits)
    candidate = Path(
        tempfile.mkdtemp(prefix=".oppen-project-steward-candidate-", dir=root)
    )
    promoted = False
    try:
        atomic_write(candidate / REGISTRY_NAME, content)
        for system, index_content, source in (
            ("Memory", render_memory_index([], 0), memory_source),
            ("Attention", render_attention_index([], 0), attention_source),
        ):
            system_dir = candidate / system
            if source is None:
                (system_dir / "entries").mkdir(parents=True)
                atomic_write(system_dir / "index.md", index_content)
            else:
                shutil.copytree(source, system_dir)
        if audit_source is None:
            (candidate / "Audit/Runs").mkdir(parents=True)
            (candidate / "Audit/Contracts").mkdir()
        else:
            shutil.copytree(audit_source, candidate / "Audit")
            (candidate / "Audit/Runs").mkdir(exist_ok=True)
            (candidate / "Audit/Contracts").mkdir(exist_ok=True)
        atomic_write(
            candidate / MANAGED_STATE_NAME,
            render_managed_state_for_namespace(candidate, 1),
        )
        build_transaction_plan(
            root,
            write_set,
            (namespace,),
            sum(path.stat().st_size for path in candidate.rglob("*") if path.is_file()),
        )

        staged = {
            namespace / path.relative_to(candidate): path
            for path in candidate.rglob("*")
            if path.is_file()
        }
        overlay = CandidateOverlay(root, write_set, staged, ())
        validate_registry_shape(
            overlay.read_text(registry), "Candidate Steward registry"
        )
        if namespace.exists():
            raise ProjectError("Steward namespace appeared during candidate creation")
        try:
            candidate.rename(namespace)
        except OSError as exc:
            if namespace.exists():
                raise ProjectError(
                    "Steward namespace appeared during candidate promotion"
                ) from exc
            raise
        promoted = True
    except Exception:
        if candidate.exists():
            shutil.rmtree(candidate, ignore_errors=True)
        if promoted and namespace.exists():
            shutil.rmtree(namespace, ignore_errors=True)
        raise
    report = validate_project(root)
    if not report.ok:
        shutil.rmtree(namespace, ignore_errors=True)
        raise ProjectError(
            f"Candidate Steward namespace failed validation: {report.status}: "
            + "; ".join(report.errors)
        )
    return registry


def ensure_v3_project(root: Path, *, create: bool) -> tuple[Path, dict[str, Path]]:
    root = root.expanduser().resolve()
    namespace, registry, _, _, audit_dir = steward_paths(root)
    root_created = False
    try:
        if not root.exists():
            if not create:
                raise ProjectError(f"Project does not exist: {root}")
            root.mkdir(parents=True)
            root_created = True
        if not root.is_dir():
            raise ProjectError(f"Project path is not a directory: {root}")
        if namespace.exists():
            if namespace.is_symlink() or not namespace.is_dir():
                raise ProjectError("Steward namespace is not a real directory")
            if not registry.is_file() or registry.is_symlink():
                raise ProjectError("Steward namespace lacks a real registry.md")
            text = registry.read_text(encoding="utf-8", errors="replace")
            validate_registry_shape(text, "Steward registry")
            roles = parse_role_mappings(root, text)
            roles["Audit"] = audit_dir
            return registry, roles
        if not create:
            raise ProjectError(
                "ADOPTION_REQUIRED: no Steward namespace exists; run adopt --check"
            )
        roles = detect_roles(root, create_missing=False)
        registry = create_namespace_candidate(root, roles, [], [], operation="init")
        roles["Audit"] = audit_dir
        return registry, roles
    except Exception:
        if root_created:
            try:
                root.rmdir()
            except OSError:
                pass
        raise


def initialize_new_project(root: Path) -> Path:
    """Initialize only an empty/new target; existing projects use adoption."""
    root = root.expanduser().resolve()
    namespace = root / STEWARD_NAMESPACE
    if namespace.exists():
        report = validate_project(root)
        if report.ok:
            return steward_paths(root)[1]
        raise ProjectError(
            f"Cannot initialize existing Steward state: {report.status}; run validate"
        )
    if root.exists():
        meaningful = sorted(
            path.name
            for path in root.iterdir()
            if path.name not in {".git", ".DS_Store"}
        )
        if meaningful:
            raise ProjectError(
                "ADOPTION_REQUIRED: target already contains project content; "
                "run adopt TARGET --check"
            )
    registry, _ = ensure_v3_project(root, create=True)
    refresh_index(root)
    return registry


def managed_state_preflight(root: Path) -> dict[str, object]:
    root = root.expanduser().resolve()
    report = validate_project(root)
    generation: int | None = None
    if managed_state_path(root).is_file():
        try:
            generation = load_managed_state(root).generation
        except (ProjectError, RecoverableBlocker):
            pass
    return {
        "status": report.status,
        "baseline": f"{STEWARD_NAMESPACE}/{MANAGED_STATE_NAME}",
        "generation": generation,
        "blockers": [
            {
                "code": blocker.code,
                "paths": list(blocker.paths),
                "recovery": blocker.recovery,
            }
            for blocker in report.blockers
        ],
        "damaging_errors": list(report.damaging_errors),
        "git_commit_required": "NO",
    }


def bootstrap_managed_state(root: Path) -> Path:
    root = root.expanduser().resolve()
    baseline_path = managed_state_path(root)
    with project_write_lock(root):
        report = validate_project(root)
        if report.ok:
            return baseline_path
        eligible = (
            not report.damaging_errors
            and len(report.blockers) == 1
            and report.blockers[0].code == "MANAGED_BASELINE_MISSING"
        )
        if not eligible:
            codes = ", ".join(blocker.code for blocker in report.blockers)
            detail = codes or "; ".join(report.damaging_errors) or report.status
            raise ProjectError(
                "Managed baseline bootstrap requires one structurally valid pre-4.3 "
                f"namespace with only MANAGED_BASELINE_MISSING; found: {detail}"
            )
        if baseline_path.exists():
            raise ProjectError("Managed baseline appeared during bootstrap preflight")
        content = render_managed_state_for_namespace(root / STEWARD_NAMESPACE, 1)
        write_set = managed_write_set(
            root, "managed-state bootstrap", exact=(baseline_path,)
        )
        managed_file_transaction(
            root,
            write_set,
            {baseline_path: content},
            update_managed_baseline=False,
        )
        final = validate_project(root)
        if not final.ok:
            baseline_path.unlink(missing_ok=True)
            raise ProjectError(
                f"Managed baseline bootstrap failed final validation: {final.status}"
            )
    return baseline_path


def parse_canonical_entries(text: str) -> list[CanonicalEntry]:
    body = extract_block(text, CANONICAL_START, CANONICAL_END, "canonical source")
    table_lines = [
        line.strip() for line in body.splitlines() if line.strip().startswith("|")
    ]
    if not table_lines:
        return []
    width = len(table_lines[0].strip("|").split("|"))
    if width == 4:
        rows = parse_markdown_table(body, 4, "legacy canonical source")
        return [CanonicalEntry(*row) for row in rows]
    if width != 5:
        raise ProjectError("Malformed canonical source table")
    rows = parse_markdown_table(body, 5, "canonical source")
    return [
        CanonicalEntry(topic, path, section, verification, status)
        for topic, path, section, status, verification in rows
    ]


def render_canonical_entries(entries: list[CanonicalEntry]) -> str:
    rows = [
        (
            entry.topic,
            entry.path,
            entry.section or "-",
            entry.status,
            entry.verification,
        )
        for entry in sorted(entries, key=lambda item: item.topic)
    ]
    return markdown_table(
        ("Topic", "Canonical path", "Section", "Status", "Verification"), rows
    )


def parse_deliverable_entries(text: str) -> list[DeliverableEntry]:
    rows = parse_markdown_table(
        extract_block(text, DELIVERABLE_START, DELIVERABLE_END, "deliverable registry"),
        5,
        "deliverable registry",
    )
    return [DeliverableEntry(*row) for row in rows]


def render_deliverable_entries(entries: list[DeliverableEntry]) -> str:
    rows = [
        (entry.deliverable_id, entry.path, entry.kind, entry.audience, entry.producer)
        for entry in sorted(entries, key=lambda item: item.deliverable_id)
    ]
    return markdown_table(("ID", "Path", "Kind", "Audience", "Producer"), rows)


def contract_audit_entries(root: Path, audit_dir: Path) -> list[ContractAuditEntry]:
    contracts_dir = audit_dir / "Contracts"
    if not contracts_dir.is_dir():
        return []
    entries: list[ContractAuditEntry] = []
    for audit in sorted(contracts_dir.glob("*.md")):
        metadata = parse_frontmatter(audit)
        entries.append(
            ContractAuditEntry(
                metadata.get("steward_contract", audit.stem.removeprefix("audit_")),
                audit.relative_to(root).as_posix(),
                metadata.get("source", "UNKNOWN"),
                metadata.get("risk_reason", "UNKNOWN"),
            )
        )
    return entries


def render_contract_audit_entries(entries: list[ContractAuditEntry]) -> str:
    rows = [
        (entry.topic, entry.audit, entry.source, entry.risk_reason)
        for entry in sorted(entries, key=lambda item: item.topic)
    ]
    return markdown_table(("Topic", "Audit", "Source", "Risk reason"), rows)


def render_project_index_unlocked(root: Path) -> tuple[Path, str]:
    project_file, roles = ensure_v3_project(root, create=False)
    text = project_file.read_text(encoding="utf-8")
    canonical = parse_canonical_entries(text)
    deliverables = parse_deliverable_entries(text)
    text = replace_block(text, ROLE_START, ROLE_END, role_table(root, roles), "role")
    text = replace_block(
        text,
        CANONICAL_START,
        CANONICAL_END,
        render_canonical_entries(canonical),
        "canonical source",
    )
    text = replace_block(
        text,
        DELIVERABLE_START,
        DELIVERABLE_END,
        render_deliverable_entries(deliverables),
        "deliverable registry",
    )
    audits = contract_audit_entries(root, roles["Audit"])
    text = replace_block(
        text,
        CONTRACT_AUDIT_START,
        CONTRACT_AUDIT_END,
        render_contract_audit_entries(audits),
        "contract audit index",
    )
    return project_file, text.rstrip() + "\n"


def refresh_index(root: Path) -> Path:
    root = root.expanduser().resolve()
    with project_write_lock(root):
        baseline = load_managed_state(root)
        drift = managed_state_drift(root, baseline)
        repairable = {
            f"{STEWARD_NAMESPACE}/Attention/index.md",
            f"{STEWARD_NAMESPACE}/Memory/index.md",
        }
        unexpected = tuple(path for path in drift if path not in repairable)
        if unexpected:
            raise RecoverableBlocker(
                "MANAGED_STATE_CONFLICT",
                "Steward control-plane files differ from the last successful baseline",
                unexpected,
                "inspect and reconcile only the listed Steward-managed paths; do not reset them from Git automatically",
            )
        project_file, project_content = render_project_index_unlocked(root)
        writes: dict[Path, str] = {}
        if (
            project_file.read_text(encoding="utf-8") != project_content
            or project_file.relative_to(root).as_posix() in drift
        ):
            writes[project_file] = project_content
        if (root / STEWARD_NAMESPACE / "Attention").exists():
            attention_index, attention_content = render_attention_refresh_unlocked(root)
            if (
                attention_index.read_text(encoding="utf-8") != attention_content
                or attention_index.relative_to(root).as_posix() in drift
            ):
                writes[attention_index] = attention_content
        if (root / STEWARD_NAMESPACE / "Memory").exists():
            memory_index, memory_content = render_memory_refresh_unlocked(root)
            if (
                memory_index.read_text(encoding="utf-8") != memory_content
                or memory_index.relative_to(root).as_posix() in drift
            ):
                writes[memory_index] = memory_content
        if writes:
            write_set = managed_write_set(root, "index", exact=tuple(writes))
            assert_managed_write_set_clean(
                root,
                write_set,
                allowed_managed_drift=tuple(sorted(repairable)),
            )
            managed_file_transaction(
                root,
                write_set,
                writes,
                allowed_managed_drift=tuple(sorted(repairable)),
            )
        return project_file


def markdown_section(content: str, section: str) -> str:
    heading = re.compile(rf"^(#{{1,6}})\s+{re.escape(section)}\s*$", re.MULTILINE)
    matches = list(heading.finditer(content))
    if len(matches) != 1:
        raise ProjectError(f"Markdown section must occur exactly once: {section}")
    match = matches[0]
    level = len(match.group(1))
    next_match = re.compile(rf"^#{{1,{level}}}\s+", re.MULTILINE).search(
        content, match.end()
    )
    return content[match.start() : next_match.start() if next_match else len(content)]


def canonical_status_values(content: str) -> list[str]:
    return [
        value.strip().strip("`*_").lower()
        for value in re.findall(
            r"^(?:Status)\s*:\s*(.+?)\s*$", content, re.IGNORECASE | re.MULTILINE
        )
    ]


def canonical_status_error(content: str) -> str | None:
    statuses = canonical_status_values(content)
    if len(statuses) != 1:
        return "must contain exactly one Status field in its owned scope"
    if statuses[0] not in ALLOWED_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_STATUSES))
        return f"has invalid status {statuses[0]!r}; expected one of: {allowed}"
    return None


def verification_error(path: Path) -> str | None:
    if not path.is_file():
        return "verification must be a file"
    if path.stat().st_size == 0:
        return "verification cannot be empty"
    return None


def register_canonical(
    root: Path,
    topic: str,
    path: str,
    section: str | None,
    verification: str,
    *,
    status: str | None = None,
    replace: bool,
) -> Path:
    root = root.expanduser().resolve()
    project_file, _ = ensure_v3_project(root, create=False)
    topic = validate_key(topic, "topic")
    owner, owner_rel = resolve_project_path(root, path, "canonical path")
    if not owner.is_file():
        raise ProjectError(f"Canonical owner must be a file: {owner_rel}")
    section_value = validate_table_value(section, "section") if section else ""
    content = owner.read_text(encoding="utf-8", errors="replace")
    owned_content = (
        markdown_section(content, section_value) if section_value else content
    )
    if status is None:
        status_values = canonical_status_values(owned_content)
        if len(status_values) != 1 or status_values[0] not in ALLOWED_STATUSES:
            raise ProjectError(
                f"Canonical owner {owner_rel} must contain one valid Status field or "
                "canonical must receive --status"
            )
        status_value = status_values[0]
    else:
        status_value = status.strip().lower()
        if status_value not in ALLOWED_STATUSES:
            raise ProjectError(
                "Canonical status must be one of: "
                + ", ".join(sorted(ALLOWED_STATUSES))
            )
    verification_path, verification_rel = resolve_project_path(
        root, verification, "verification"
    )
    error = verification_error(verification_path)
    if error:
        raise ProjectError(f"Invalid verification {verification_rel}: {error}")
    new_entry = CanonicalEntry(
        topic, owner_rel, section_value, verification_rel, status_value
    )
    with project_write_lock(root):
        text = project_file.read_text(encoding="utf-8")
        entries = parse_canonical_entries(text)
        matches = [entry for entry in entries if entry.topic == topic]
        if len(matches) > 1:
            raise ProjectError(f"Duplicate canonical topic already exists: {topic}")
        if matches:
            current = matches[0]
            if current == new_entry:
                assert_managed_state_integrity(root)
                return project_file
            if (current.path, current.section) != (
                owner_rel,
                section_value,
            ) and not replace:
                raise ProjectError(
                    f"Canonical topic {topic!r} already has a different owner; use "
                    "--replace only after resolving the ownership move"
                )
            entries = [entry for entry in entries if entry.topic != topic]
        duplicate_owner = [
            entry
            for entry in entries
            if (entry.path, entry.section) == (owner_rel, section_value)
            and entry.topic != topic
        ]
        if duplicate_owner:
            raise ProjectError(
                f"Canonical owner {owner_rel!r} is already registered to topic "
                f"{duplicate_owner[0].topic!r}"
            )
        entries.append(new_entry)
        updated = replace_block(
            text,
            CANONICAL_START,
            CANONICAL_END,
            render_canonical_entries(entries),
            "canonical source",
        )
        write_set = managed_write_set(root, "canonical", exact=(project_file,))
        assert_managed_write_set_clean(root, write_set)
        managed_file_transaction(
            root, write_set, {project_file: updated.rstrip() + "\n"}
        )
    return project_file


def deliverable_artifact_error(path: Path, deliverables_dir: Path) -> str | None:
    try:
        relative = path.relative_to(deliverables_dir)
    except ValueError:
        return "artifact outside the active Deliverables directory"
    if path.suffix.lower() in FORBIDDEN_DELIVERABLE_SUFFIXES:
        return "forbidden machine artifact type"
    if path.suffix.lower() not in HUMAN_DELIVERABLE_SUFFIXES:
        return "non-human artifact type"
    if any(FORBIDDEN_DELIVERABLE_TOKEN.search(part) for part in relative.parts):
        return "machine, temporary, or historical artifact"
    return None


def register_deliverable(
    root: Path,
    deliverable_id: str,
    path: str,
    kind: str,
    audience: str,
    producer: str,
    *,
    replace: bool,
) -> Path:
    root = root.expanduser().resolve()
    project_file, roles = ensure_v3_project(root, create=False)
    deliverable_id = validate_key(deliverable_id, "deliverable id")
    kind = validate_key(kind, "deliverable kind")
    audience = validate_key(audience, "deliverable audience")
    if "Deliverables" not in roles:
        raise ProjectError(
            "A Deliverables role must be registered before registering Deliverables"
        )
    artifact, artifact_rel = resolve_project_path(root, path, "deliverable path")
    if not artifact.is_file():
        raise ProjectError(f"Registered Deliverable must be a file: {artifact_rel}")
    artifact_error = deliverable_artifact_error(
        artifact, roles["Deliverables"].resolve()
    )
    if artifact_error:
        raise ProjectError(f"Invalid Deliverable {artifact_rel}: {artifact_error}")
    producer_path, producer_rel = resolve_project_path(root, producer, "producer")
    if not producer_path.is_file():
        raise ProjectError(f"Deliverable producer must be a file: {producer_rel}")
    new_entry = DeliverableEntry(
        deliverable_id, artifact_rel, kind, audience, producer_rel
    )
    with project_write_lock(root):
        text = project_file.read_text(encoding="utf-8")
        entries = parse_deliverable_entries(text)
        matches = [entry for entry in entries if entry.deliverable_id == deliverable_id]
        if len(matches) > 1:
            raise ProjectError(
                f"Duplicate Deliverable id already exists: {deliverable_id}"
            )
        if matches:
            current = matches[0]
            if current == new_entry:
                assert_managed_state_integrity(root)
                return project_file
            if current.path != artifact_rel and not replace:
                raise ProjectError(
                    f"Deliverable id {deliverable_id!r} already points to a different path; "
                    "use --replace only after resolving the move"
                )
            entries = [
                entry for entry in entries if entry.deliverable_id != deliverable_id
            ]
        if any(entry.path == artifact_rel for entry in entries):
            raise ProjectError(
                f"Deliverable path is already registered: {artifact_rel}"
            )
        entries.append(new_entry)
        updated = replace_block(
            text,
            DELIVERABLE_START,
            DELIVERABLE_END,
            render_deliverable_entries(entries),
            "deliverable registry",
        )
        write_set = managed_write_set(root, "deliverable", exact=(project_file,))
        assert_managed_write_set_clean(root, write_set)
        managed_file_transaction(
            root, write_set, {project_file: updated.rstrip() + "\n"}
        )
    return project_file


def contract_audit_template(
    topic: str, source: str, source_sha256: str, risk_reason: str
) -> str:
    return f"""---
steward_contract: {json.dumps(topic)}
source: {json.dumps(source)}
source_sha256: {json.dumps(source_sha256)}
risk_reason: {json.dumps(risk_reason)}
---

# High-Risk Contract Audit: `{topic}`

## Purpose And Risk

TODO: Explain the behavior and why a hidden error could materially alter the project.

## Contract

TODO: State inputs, outputs, invariants, side effects, and downstream obligations.

## Edge Cases And Verification

TODO: Link executable checks for important boundaries and failure modes.

## Known Limits

TODO: State conditions outside the validated contract.
"""


def validate_contract_audit_payload(
    payload: dict[str, object],
) -> dict[str, str]:
    validate_payload_fields(payload, CONTRACT_AUDIT_PAYLOAD_FIELDS, "Contract Audit")
    return {
        field: validate_semantic_text(payload[field], f"Contract Audit {field}")
        for field in CONTRACT_AUDIT_PAYLOAD_FIELDS
    }


def complete_contract_audit(root: Path, topic: str, payload_path: Path) -> Path:
    root = root.expanduser().resolve()
    _, roles = ensure_v3_project(root, create=False)
    topic = validate_key(topic, "contract topic")
    payload_file, raw_payload = load_temporary_payload(root, payload_path)
    payload = validate_contract_audit_payload(raw_payload)
    with project_write_lock(root):
        assert_managed_state_integrity(root)
        matches = [
            entry
            for entry in contract_audit_entries(root, roles["Audit"])
            if entry.topic == topic
        ]
        if len(matches) != 1:
            raise ProjectError(
                f"Contract Audit topic must already be registered exactly once: {topic}"
            )
        entry = matches[0]
        audit_path, _ = resolve_project_path(root, entry.audit, "Contract Audit path")
        source_path, source_rel = resolve_project_path(
            root, entry.source, "Contract Audit source"
        )
        if not source_path.is_file():
            raise ProjectError(f"Contract Audit source must be a file: {source_rel}")
        content = contract_audit_template(
            topic, source_rel, file_sha256(source_path), entry.risk_reason
        )
        replacements = {
            "TODO: Explain the behavior and why a hidden error could materially alter the project.": payload[
                "purpose_and_risk"
            ],
            "TODO: State inputs, outputs, invariants, side effects, and downstream obligations.": payload[
                "contract"
            ],
            "TODO: Link executable checks for important boundaries and failure modes.": payload[
                "edge_cases_and_verification"
            ],
            "TODO: State conditions outside the validated contract.": payload[
                "known_limits"
            ],
        }
        for placeholder, replacement in replacements.items():
            content = content.replace(placeholder, replacement)
        write_set = managed_write_set(
            root, "contract-audit complete", exact=(audit_path,)
        )
        assert_managed_write_set_clean(root, write_set)
        managed_file_transaction(root, write_set, {audit_path: content})
    payload_file.unlink(missing_ok=True)
    return audit_path


def create_or_locate_contract_audit(
    root: Path, topic: str, source: str, risk_reason: str
) -> tuple[Path, str]:
    root = root.expanduser().resolve()
    project_file, roles = ensure_v3_project(root, create=False)
    topic = validate_key(topic, "contract topic")
    source_path, source_rel = resolve_project_path(root, source, "contract source")
    if not source_path.is_file():
        raise ProjectError(f"Contract source must be a file: {source_rel}")
    risk_reason = validate_table_value(risk_reason, "risk reason")
    contracts_dir = roles["Audit"] / "Contracts"
    audit_path = contracts_dir / f"audit_{topic}.md"
    with project_write_lock(root):
        if audit_path.exists():
            assert_managed_state_integrity(root)
            return audit_path, "UPDATE_REQUIRED"
        project_text = project_file.read_text(encoding="utf-8")
        entries = contract_audit_entries(root, roles["Audit"])
        entries.append(
            ContractAuditEntry(
                topic,
                audit_path.relative_to(root).as_posix(),
                source_rel,
                risk_reason,
            )
        )
        updated_project = replace_block(
            project_text,
            CONTRACT_AUDIT_START,
            CONTRACT_AUDIT_END,
            render_contract_audit_entries(entries),
            "contract audit index",
        )
        write_set = managed_write_set(
            root,
            "contract-audit",
            exact=(audit_path, project_file),
        )
        assert_managed_write_set_clean(root, write_set)
        managed_file_transaction(
            root,
            write_set,
            {
                audit_path: contract_audit_template(
                    topic, source_rel, file_sha256(source_path), risk_reason
                ),
                project_file: updated_project.rstrip() + "\n",
            },
        )
    return audit_path, "CREATED_DRAFT"


def read_high_water(index_path: Path, pattern: re.Pattern[str], label: str) -> int:
    text = index_path.read_text(encoding="utf-8", errors="replace")
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise ProjectError(f"{label} index must contain exactly one high-water marker")
    return int(matches[0])


def allocate_id(high_water: int, prefix: str) -> tuple[str, int]:
    next_number = high_water + 1
    if next_number > 9999:
        raise ProjectError(f"{prefix} ID space is exhausted")
    return f"{prefix}-{next_number:04d}", next_number


def attention_paths(root: Path) -> tuple[Path, Path, Path]:
    attention_dir = root / STEWARD_NAMESPACE / "Attention"
    return attention_dir, attention_dir / "index.md", attention_dir / "entries"


def memory_paths(root: Path) -> tuple[Path, Path, Path]:
    memory_dir = root / STEWARD_NAMESPACE / "Memory"
    return memory_dir, memory_dir / "index.md", memory_dir / "entries"


def assert_fixed_topology(
    system_dir: Path, index_path: Path, entries_dir: Path, label: str
) -> None:
    if not system_dir.is_dir():
        raise ProjectError(f"{label} must use the fixed {label}/ directory")
    if system_dir.is_symlink() or index_path.is_symlink() or entries_dir.is_symlink():
        raise ProjectError(f"{label} fixed topology cannot use symbolic links")
    if not index_path.is_file() or not entries_dir.is_dir():
        raise ProjectError(
            f"{label} must contain exactly index.md and the entries/ directory"
        )
    unexpected = [
        path.name
        for path in system_dir.iterdir()
        if path.name not in {"index.md", "entries", ".DS_Store"}
    ]
    if unexpected:
        raise ProjectError(
            f"{label} contains unexpected alternative topology: {', '.join(unexpected)}"
        )
    invalid_entries = [
        path.name
        for path in entries_dir.iterdir()
        if path.name != ".DS_Store" and (not path.is_file() or path.suffix != ".md")
    ]
    if invalid_entries:
        raise ProjectError(
            f"{label}/entries contains invalid topology: {', '.join(invalid_entries)}"
        )


def render_attention_index(entries: list[AttentionEntry], high_water: int) -> str:
    rows = [
        (entry.attention_id, entry.title, "true" if entry.blocking else "false")
        for entry in sorted(entries, key=lambda item: item.attention_id)
    ]
    table = markdown_table(("ID", "Title", "Blocking"), rows)
    return f"""# Human Attention

{ATTENTION_INDEX_MARKER}
<!-- oppen-project-steward:attention-high-water:{high_water:04d} -->

This generated index lists active unresolved issues only.

{table}
"""


def render_memory_index(entries: list[MemoryEntry], high_water: int) -> str:
    rows = [
        (
            entry.memory_id,
            entry.title,
            entry.status,
            ", ".join(entry.related_topics) if entry.related_topics else "-",
        )
        for entry in sorted(entries, key=lambda item: item.memory_id)
    ]
    table = markdown_table(("ID", "Title", "Status", "Related Topics"), rows)
    return f"""# Decision Memory

{MEMORY_INDEX_MARKER}
<!-- oppen-project-steward:memory-high-water:{high_water:04d} -->

This generated index locates consequential decision history.

{table}
"""


def ensure_attention_structure_unlocked(root: Path) -> tuple[Path, Path, Path]:
    attention_dir, index_path, entries_dir = attention_paths(root)
    if not attention_dir.exists():
        try:
            attention_dir.mkdir()
            entries_dir.mkdir()
            write_set = managed_write_set(
                root, "attention structure", exact=(index_path,)
            )
            managed_file_transaction(
                root,
                write_set,
                {index_path: render_attention_index([], 0)},
            )
        except Exception:
            index_path.unlink(missing_ok=True)
            if entries_dir.is_dir():
                entries_dir.rmdir()
            if attention_dir.is_dir():
                attention_dir.rmdir()
            raise
    assert_fixed_topology(attention_dir, index_path, entries_dir, "Attention")
    if ATTENTION_INDEX_MARKER not in index_path.read_text(
        encoding="utf-8", errors="replace"
    ):
        raise ProjectError("Attention/index.md lacks its generated index marker")
    return attention_dir, index_path, entries_dir


def ensure_memory_structure_unlocked(root: Path) -> tuple[Path, Path, Path]:
    memory_dir, index_path, entries_dir = memory_paths(root)
    if not memory_dir.exists():
        try:
            memory_dir.mkdir()
            entries_dir.mkdir()
            write_set = managed_write_set(root, "memory structure", exact=(index_path,))
            managed_file_transaction(
                root,
                write_set,
                {index_path: render_memory_index([], 0)},
            )
        except Exception:
            index_path.unlink(missing_ok=True)
            if entries_dir.is_dir():
                entries_dir.rmdir()
            if memory_dir.is_dir():
                memory_dir.rmdir()
            raise
    assert_fixed_topology(memory_dir, index_path, entries_dir, "Memory")
    if MEMORY_INDEX_MARKER not in index_path.read_text(
        encoding="utf-8", errors="replace"
    ):
        raise ProjectError("Memory/index.md lacks its generated index marker")
    return memory_dir, index_path, entries_dir


def parse_attention_entry(path: Path) -> AttentionEntry:
    metadata, body = parse_structured_frontmatter(path)
    if tuple(metadata) != ATTENTION_METADATA_FIELDS:
        raise ProjectError(
            f"Attention entry has invalid fixed schema: {path.name}; expected metadata "
            + ", ".join(ATTENTION_METADATA_FIELDS)
        )
    attention_id = metadata["id"]
    title = metadata["title"]
    blocking = metadata["blocking"]
    if not isinstance(attention_id, str) or not ATTENTION_ID.fullmatch(attention_id):
        raise ProjectError(f"Attention entry has invalid ID: {path.name}")
    if path.name != f"{attention_id}.md":
        raise ProjectError(f"Attention filename does not match its ID: {path.name}")
    title = validate_semantic_text(title, "Attention title", title=True)
    if not isinstance(blocking, bool):
        raise ProjectError(f"Attention Blocking must be boolean: {path.name}")
    if not body.startswith(f"# Human Attention {attention_id}: {title}\n"):
        raise ProjectError(f"Attention entry has an invalid heading: {path.name}")
    parse_fixed_sections(body, ATTENTION_SECTIONS, f"Attention {attention_id}")
    return AttentionEntry(attention_id, title, blocking, path)


def load_attention_entries_unlocked(entries_dir: Path) -> list[AttentionEntry]:
    return [parse_attention_entry(path) for path in sorted(entries_dir.glob("*.md"))]


def render_attention_refresh_unlocked(root: Path) -> tuple[Path, str]:
    _, index_path, entries_dir = ensure_attention_structure_unlocked(root)
    entries = load_attention_entries_unlocked(entries_dir)
    high_water = max(
        [
            read_high_water(index_path, ATTENTION_HIGH_WATER, "Attention"),
            *(
                int(ATTENTION_ID.fullmatch(entry.attention_id).group(1))
                for entry in entries
            ),
        ]
    )
    return index_path, render_attention_index(entries, high_water)


def refresh_attention_index_unlocked(root: Path) -> Path:
    index_path, content = render_attention_refresh_unlocked(root)
    if index_path.read_text(encoding="utf-8") != content:
        write_set = managed_write_set(root, "attention index", exact=(index_path,))
        managed_file_transaction(root, write_set, {index_path: content})
    return index_path


def validate_attention_payload(payload: dict[str, object]) -> dict[str, object]:
    validate_payload_fields(payload, ATTENTION_PAYLOAD_FIELDS, "Attention")
    blocking = payload["blocking"]
    if not isinstance(blocking, bool):
        raise ProjectError("Attention blocking must be a JSON boolean")
    return {
        "title": validate_semantic_text(
            payload["title"], "Attention title", title=True
        ),
        "blocking": blocking,
        "observation": validate_semantic_text(
            payload["observation"], "Attention observation"
        ),
        "evidence": validate_semantic_text(payload["evidence"], "Attention evidence"),
        "why_it_matters": validate_semantic_text(
            payload["why_it_matters"], "Attention why_it_matters"
        ),
        "why_no_action_was_taken": validate_semantic_text(
            payload["why_no_action_was_taken"],
            "Attention why_no_action_was_taken",
        ),
        "human_decision_needed": validate_semantic_text(
            payload["human_decision_needed"], "Attention human_decision_needed"
        ),
    }


def raise_attention(root: Path, payload_path: Path) -> Path:
    root = root.expanduser().resolve()
    ensure_v3_project(root, create=False)
    payload_file, raw_payload = load_temporary_payload(root, payload_path)
    payload = validate_attention_payload(raw_payload)
    attention_dir, initial_index, initial_entries = attention_paths(root)
    if not attention_dir.exists():
        assert_managed_write_set_clean(
            root,
            managed_write_set(
                root,
                "attention raise",
                exact=(initial_index, initial_entries / "A-0001.md"),
            ),
        )
    with project_write_lock(root):
        _, index_path, entries_dir = ensure_attention_structure_unlocked(root)
        entries = load_attention_entries_unlocked(entries_dir)
        normalized_title = " ".join(str(payload["title"]).casefold().split())
        if any(
            " ".join(entry.title.casefold().split()) == normalized_title
            for entry in entries
        ):
            raise ProjectError(
                "An active Attention entry already has the same normalized title"
            )
        high_water = read_high_water(index_path, ATTENTION_HIGH_WATER, "Attention")
        attention_id, high_water = allocate_id(high_water, "A")
        entry_path = entries_dir / f"{attention_id}.md"
        content = render_structured_entry(
            {
                "id": attention_id,
                "title": payload["title"],
                "blocking": payload["blocking"],
            },
            f"Human Attention {attention_id}: {payload['title']}",
            [
                ("Observation", str(payload["observation"])),
                ("Evidence", str(payload["evidence"])),
                ("Why It Matters", str(payload["why_it_matters"])),
                (
                    "Why No Action Was Taken",
                    str(payload["why_no_action_was_taken"]),
                ),
                ("Human Decision Needed", str(payload["human_decision_needed"])),
            ],
        )
        entries.append(
            AttentionEntry(
                attention_id,
                str(payload["title"]),
                bool(payload["blocking"]),
                entry_path,
            )
        )
        write_set = managed_write_set(
            root,
            "attention raise",
            exact=(entry_path, index_path),
        )
        assert_managed_write_set_clean(
            root,
            write_set,
        )
        managed_file_transaction(
            root,
            write_set,
            {
                entry_path: content,
                index_path: render_attention_index(entries, high_water),
            },
        )
    payload_file.unlink(missing_ok=True)
    return entry_path


def resolve_attention(root: Path, attention_id: str) -> Path:
    root = root.expanduser().resolve()
    ensure_v3_project(root, create=False)
    if not ATTENTION_ID.fullmatch(attention_id):
        raise ProjectError(f"Invalid Attention ID: {attention_id}")
    with project_write_lock(root):
        _, index_path, entries_dir = ensure_attention_structure_unlocked(root)
        entries = load_attention_entries_unlocked(entries_dir)
        matches = [entry for entry in entries if entry.attention_id == attention_id]
        if len(matches) != 1:
            raise ProjectError(f"Active Attention entry does not exist: {attention_id}")
        high_water = read_high_water(index_path, ATTENTION_HIGH_WATER, "Attention")
        resolved_path = matches[0].path
        remaining = [entry for entry in entries if entry.attention_id != attention_id]
        write_set = managed_write_set(
            root,
            "attention resolve",
            exact=(resolved_path, index_path),
        )
        assert_managed_write_set_clean(root, write_set)
        managed_file_transaction(
            root,
            write_set,
            {index_path: render_attention_index(remaining, high_water)},
            (resolved_path,),
        )
    return resolved_path


def parse_memory_entry(path: Path) -> MemoryEntry:
    metadata, body = parse_structured_frontmatter(path)
    if tuple(metadata) != MEMORY_METADATA_FIELDS:
        raise ProjectError(
            f"Memory entry has invalid fixed schema: {path.name}; expected metadata "
            + ", ".join(MEMORY_METADATA_FIELDS)
        )
    memory_id = metadata["id"]
    status = metadata["status"]
    title = metadata["title"]
    if not isinstance(memory_id, str) or not MEMORY_ID.fullmatch(memory_id):
        raise ProjectError(f"Memory entry has invalid ID: {path.name}")
    if path.name != f"{memory_id}.md":
        raise ProjectError(f"Memory filename does not match its ID: {path.name}")
    if not isinstance(status, str) or status not in MEMORY_STATUSES:
        raise ProjectError(f"Memory entry has invalid status: {path.name}")
    title = validate_semantic_text(title, "Memory title", title=True)
    related_topics = validate_id_list(
        metadata["related_topics"], "Memory related_topics", KEY_PATTERN
    )
    supersedes = validate_id_list(
        metadata["supersedes"], "Memory supersedes", MEMORY_ID
    )
    invalidates = validate_id_list(
        metadata["invalidates"], "Memory invalidates", MEMORY_ID
    )
    superseded_by = validate_id_list(
        metadata["superseded_by"], "Memory superseded_by", MEMORY_ID
    )
    invalidated_by = validate_id_list(
        metadata["invalidated_by"], "Memory invalidated_by", MEMORY_ID
    )
    if not body.startswith(f"# Decision Memory {memory_id}: {title}\n"):
        raise ProjectError(f"Memory entry has an invalid heading: {path.name}")
    parse_fixed_sections(body, MEMORY_SECTIONS, f"Memory {memory_id}")
    return MemoryEntry(
        memory_id,
        status,
        title,
        related_topics,
        supersedes,
        invalidates,
        superseded_by,
        invalidated_by,
        path,
    )


def memory_metadata(entry: MemoryEntry) -> dict[str, object]:
    return {
        "id": entry.memory_id,
        "status": entry.status,
        "title": entry.title,
        "related_topics": list(entry.related_topics),
        "supersedes": list(entry.supersedes),
        "invalidates": list(entry.invalidates),
        "superseded_by": list(entry.superseded_by),
        "invalidated_by": list(entry.invalidated_by),
    }


def load_memory_entries_unlocked(entries_dir: Path) -> list[MemoryEntry]:
    return [parse_memory_entry(path) for path in sorted(entries_dir.glob("*.md"))]


def render_memory_refresh_unlocked(root: Path) -> tuple[Path, str]:
    _, index_path, entries_dir = ensure_memory_structure_unlocked(root)
    entries = load_memory_entries_unlocked(entries_dir)
    high_water = max(
        [
            read_high_water(index_path, MEMORY_HIGH_WATER, "Memory"),
            *(int(MEMORY_ID.fullmatch(entry.memory_id).group(1)) for entry in entries),
        ]
    )
    return index_path, render_memory_index(entries, high_water)


def refresh_memory_index_unlocked(root: Path) -> Path:
    index_path, content = render_memory_refresh_unlocked(root)
    if index_path.read_text(encoding="utf-8") != content:
        write_set = managed_write_set(root, "memory index", exact=(index_path,))
        managed_file_transaction(root, write_set, {index_path: content})
    return index_path


def validate_memory_payload(payload: dict[str, object]) -> dict[str, object]:
    validate_payload_fields(payload, MEMORY_PAYLOAD_FIELDS, "Memory")
    related_topics = validate_id_list(
        payload["related_topics"], "Memory related_topics", KEY_PATTERN
    )
    supersedes = validate_id_list(payload["supersedes"], "Memory supersedes", MEMORY_ID)
    invalidates = validate_id_list(
        payload["invalidates"], "Memory invalidates", MEMORY_ID
    )
    overlap = sorted(set(supersedes) & set(invalidates))
    if overlap:
        raise ProjectError(
            "Memory cannot both supersede and invalidate the same ID: "
            + ", ".join(overlap)
        )
    return {
        "title": validate_semantic_text(payload["title"], "Memory title", title=True),
        "related_topics": tuple(sorted(related_topics)),
        "supersedes": tuple(sorted(supersedes)),
        "invalidates": tuple(sorted(invalidates)),
        "before": validate_semantic_text(payload["before"], "Memory before"),
        "trigger": validate_semantic_text(payload["trigger"], "Memory trigger"),
        "decision": validate_semantic_text(payload["decision"], "Memory decision"),
        "why": validate_semantic_text(payload["why"], "Memory why"),
        "rejected_or_prior_approach": validate_semantic_text(
            payload["rejected_or_prior_approach"],
            "Memory rejected_or_prior_approach",
        ),
        "consequence": validate_semantic_text(
            payload["consequence"], "Memory consequence"
        ),
    }


def add_memory(root: Path, payload_path: Path) -> Path:
    root = root.expanduser().resolve()
    ensure_v3_project(root, create=False)
    payload_file, raw_payload = load_temporary_payload(root, payload_path)
    payload = validate_memory_payload(raw_payload)
    memory_dir, initial_index, initial_entries = memory_paths(root)
    if not memory_dir.exists():
        assert_managed_write_set_clean(
            root,
            managed_write_set(
                root,
                "memory add",
                exact=(initial_index, initial_entries / "M-0001.md"),
            ),
        )
    with project_write_lock(root):
        _, index_path, entries_dir = ensure_memory_structure_unlocked(root)
        entries = load_memory_entries_unlocked(entries_dir)
        by_id = {entry.memory_id: entry for entry in entries}
        if len(by_id) != len(entries):
            raise ProjectError("Memory contains duplicate IDs")
        forward_ids = tuple(payload["supersedes"]) + tuple(payload["invalidates"])
        missing = [memory_id for memory_id in forward_ids if memory_id not in by_id]
        if missing:
            raise ProjectError(
                "Memory relationship references missing ID(s): " + ", ".join(missing)
            )
        inactive = [
            memory_id
            for memory_id in forward_ids
            if by_id[memory_id].status != "active"
        ]
        if inactive:
            raise ProjectError(
                "Memory relationships may target active entries only: "
                + ", ".join(inactive)
            )
        high_water = read_high_water(index_path, MEMORY_HIGH_WATER, "Memory")
        memory_id, high_water = allocate_id(high_water, "M")
        entry_path = entries_dir / f"{memory_id}.md"
        content = render_structured_entry(
            {
                "id": memory_id,
                "status": "active",
                "title": payload["title"],
                "related_topics": list(payload["related_topics"]),
                "supersedes": list(payload["supersedes"]),
                "invalidates": list(payload["invalidates"]),
                "superseded_by": [],
                "invalidated_by": [],
            },
            f"Decision Memory {memory_id}: {payload['title']}",
            [
                ("Before", str(payload["before"])),
                ("Trigger", str(payload["trigger"])),
                ("Decision", str(payload["decision"])),
                ("Why", str(payload["why"])),
                (
                    "Rejected or Prior Approach",
                    str(payload["rejected_or_prior_approach"]),
                ),
                ("Consequence", str(payload["consequence"])),
            ],
        )
        writes = {entry_path: content}
        updated_by_id = dict(by_id)
        for target_id in tuple(payload["supersedes"]):
            prior = by_id[target_id]
            updated = MemoryEntry(
                prior.memory_id,
                "superseded",
                prior.title,
                prior.related_topics,
                prior.supersedes,
                prior.invalidates,
                (memory_id,),
                (),
                prior.path,
            )
            updated_by_id[target_id] = updated
            writes[prior.path] = render_replaced_structured_frontmatter(
                prior.path, memory_metadata(updated)
            )
        for target_id in tuple(payload["invalidates"]):
            prior = by_id[target_id]
            updated = MemoryEntry(
                prior.memory_id,
                "invalidated",
                prior.title,
                prior.related_topics,
                prior.supersedes,
                prior.invalidates,
                (),
                (memory_id,),
                prior.path,
            )
            updated_by_id[target_id] = updated
            writes[prior.path] = render_replaced_structured_frontmatter(
                prior.path, memory_metadata(updated)
            )
        new_entry = MemoryEntry(
            memory_id,
            "active",
            str(payload["title"]),
            tuple(payload["related_topics"]),
            tuple(payload["supersedes"]),
            tuple(payload["invalidates"]),
            (),
            (),
            entry_path,
        )
        final_entries = [*updated_by_id.values(), new_entry]
        writes[index_path] = render_memory_index(final_entries, high_water)
        write_set = managed_write_set(
            root,
            "memory add",
            exact=tuple(writes),
        )
        assert_managed_write_set_clean(
            root,
            write_set,
        )
        managed_file_transaction(root, write_set, writes)
    payload_file.unlink(missing_ok=True)
    return entry_path


def directory_manifest(root: Path, label: str) -> tuple[tuple[str, int, str], ...]:
    if not root.is_dir() or root.is_symlink():
        raise ProjectError(f"{label} must be a real directory, not a symbolic link")
    rows: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ProjectError(f"{label} cannot contain symbolic links: {relative}")
        if path.is_file():
            rows.append((relative, path.stat().st_size, file_sha256(path)))
        elif not path.is_dir():
            raise ProjectError(
                f"{label} contains an unsupported filesystem entry: {relative}"
            )
    if not rows:
        raise ProjectError(f"{label} must contain at least one evidence file")
    return tuple(rows)


def promote_audit(root: Path, stage: str, input_dir: Path) -> Path:
    root = root.expanduser().resolve()
    _, roles = ensure_v3_project(root, create=False)
    stage = validate_key(stage, "audit stage")
    requested_source = input_dir.expanduser()
    if requested_source.is_symlink():
        raise ProjectError("Audit promotion input cannot be a symbolic link")
    source = requested_source.resolve()
    temporary_roots = {Path(tempfile.gettempdir()).resolve()}
    for conventional_root in (Path("/tmp"), Path("/var/tmp")):
        if conventional_root.is_dir():
            temporary_roots.add(conventional_root.resolve())
    in_temporary_root = False
    for temporary_root in temporary_roots:
        try:
            relative = source.relative_to(temporary_root)
        except ValueError:
            continue
        if relative.parts:
            in_temporary_root = True
            break
    if not in_temporary_root:
        raise ProjectError("Audit promotion input must be a system temporary directory")
    try:
        source.relative_to(root)
    except ValueError:
        pass
    else:
        raise ProjectError("Audit promotion input must stay outside the project")
    try:
        root.relative_to(source)
    except ValueError:
        pass
    else:
        raise ProjectError("Audit promotion input cannot contain the target project")
    source_manifest = directory_manifest(source, "Audit promotion input")
    runs_dir = roles["Audit"] / "Runs"
    stage_dir = runs_dir / stage
    current = stage_dir / "current"

    with project_write_lock(root):
        stage_existed = stage_dir.exists()
        if stage_existed and not stage_dir.is_dir():
            raise ProjectError(f"Audit stage path is not a directory: {stage}")
        if stage_existed:
            invalid = [
                path.name
                for path in stage_dir.iterdir()
                if path.name not in {"current", ".DS_Store"}
            ]
            if invalid:
                raise RecoverableBlocker(
                    "AUDIT_STAGING_RESIDUE",
                    f"Audit stage {stage!r} contains persistent history or staging",
                    tuple(
                        (stage_dir / name).relative_to(root).as_posix()
                        for name in invalid
                    ),
                    f"run audit recover {root} --stage {stage}",
                )
            if current.exists() and not current.is_dir():
                raise ProjectError(f"Audit current path is not a directory: {current}")
        promotion_write_set = managed_write_set(
            root,
            "audit promote",
            trees=(stage_dir,),
        )
        assert_managed_write_set_clean(root, promotion_write_set)
        build_transaction_plan(
            root,
            promotion_write_set,
            (stage_dir,),
            sum(size for _, size, _ in source_manifest),
        )
        if not stage_existed:
            stage_dir.mkdir(parents=True)

        candidate = Path(tempfile.mkdtemp(prefix=".steward-promote-", dir=stage_dir))
        candidate.rmdir()
        backup: Path | None = None
        try:
            shutil.copytree(source, candidate)
            copied_manifest = directory_manifest(candidate, "Copied Audit candidate")
            if copied_manifest != source_manifest:
                raise ProjectError(
                    "Audit candidate read-back manifest does not match input"
                )
            if current.exists():
                backup = Path(
                    tempfile.mkdtemp(prefix=".steward-previous-", dir=stage_dir)
                )
                backup.rmdir()
                current.rename(backup)
            try:
                candidate.rename(current)
            except Exception:
                if backup is not None and backup.exists():
                    backup.rename(current)
                raise
            if backup is not None:
                try:
                    shutil.rmtree(backup)
                except Exception:
                    rollback_candidate = Path(
                        tempfile.mkdtemp(prefix=".steward-rollback-", dir=stage_dir)
                    )
                    rollback_candidate.rmdir()
                    current.rename(rollback_candidate)
                    backup.rename(current)
                    shutil.rmtree(rollback_candidate, ignore_errors=True)
                    raise
        except Exception:
            if candidate.exists():
                shutil.rmtree(candidate, ignore_errors=True)
            if (
                not stage_existed
                and stage_dir.is_dir()
                and not any(stage_dir.iterdir())
            ):
                stage_dir.rmdir()
                if runs_dir.is_dir() and not any(runs_dir.iterdir()):
                    runs_dir.rmdir()
            raise

    try:
        shutil.rmtree(source)
    except OSError as exc:
        print(
            f"WARNING: Audit promotion succeeded but temporary input was not removed: "
            f"{source} ({exc})",
            file=sys.stderr,
        )
    return current


def recovery_content_manifest(
    base: Path, sources: tuple[Path, ...]
) -> tuple[tuple[str, str, int, str], ...]:
    rows: list[tuple[str, str, int, str]] = []
    for source in sorted(sources):
        candidates = (
            (source, *sorted(source.rglob("*"))) if source.is_dir() else (source,)
        )
        for path in candidates:
            relative = path.relative_to(base).as_posix()
            if path.is_symlink():
                raise ProjectError(
                    f"Audit recovery source cannot contain symbolic links: {relative}"
                )
            if path.is_dir():
                rows.append((relative, "directory", 0, ""))
            elif path.is_file():
                rows.append((relative, "file", path.stat().st_size, file_sha256(path)))
            else:
                raise ProjectError(
                    f"Audit recovery source contains unsupported entry: {relative}"
                )
    return tuple(rows)


def manifest_integrity(rows: tuple[tuple[str, str, int, str], ...]) -> str:
    encoded = json.dumps(rows, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def path_contains(container: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(container.resolve())
    except ValueError:
        return False
    return True


def audit_recovery_ambiguity(
    root: Path,
    source: Path,
    roles: dict[str, Path],
    canonical: list[CanonicalEntry],
    deliverables: list[DeliverableEntry],
) -> str | None:
    if source.is_symlink():
        return "symbolic links require human review"
    if not RECOVERABLE_AUDIT_RESIDUE.fullmatch(source.name):
        return "artifact name does not identify failed or incomplete staging"
    if "Data" in roles and (
        path_contains(roles["Data"], source) or path_contains(source, roles["Data"])
    ):
        return "artifact overlaps reusable Data"
    for entry in canonical:
        try:
            owner, _ = resolve_project_path(root, entry.path, "canonical owner")
        except ProjectError:
            return "Canonical ownership cannot be interpreted safely"
        if path_contains(source, owner):
            return f"artifact contains Canonical owner {entry.path}"
    for entry in deliverables:
        try:
            artifact, _ = resolve_project_path(root, entry.path, "Deliverable")
        except ProjectError:
            return "Deliverable ownership cannot be interpreted safely"
        if path_contains(source, artifact):
            return f"artifact contains registered Deliverable {entry.path}"
    return None


def recovery_root_for_project(root: Path) -> Path:
    candidates = [Path(tempfile.gettempdir()), Path("/tmp"), Path("/var/tmp")]
    for temporary_root in candidates:
        if not temporary_root.is_dir():
            continue
        recovery_root = temporary_root.resolve() / "oppen-project-steward-recovery"
        if not path_contains(root, recovery_root):
            return recovery_root
    raise ProjectError(
        "No system temporary recovery location exists outside the project"
    )


def restore_recovery_sources(
    stage_dir: Path, destination: Path, sources: tuple[Path, ...]
) -> None:
    for source in sources:
        recovered = destination / source.relative_to(stage_dir)
        if source.exists():
            if source.is_dir():
                shutil.rmtree(source)
            else:
                source.unlink()
        if recovered.is_dir():
            shutil.copytree(recovered, source)
        else:
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(recovered, source)


def recover_audit(root: Path, stage: str) -> Path:
    root = root.expanduser().resolve()
    try:
        project_file, roles = ensure_v3_project(root, create=False)
    except ProjectError as exc:
        raise ProjectError(
            f"DAMAGED: Audit recovery cannot interpret governance: {exc}"
        ) from exc
    stage = validate_key(stage, "audit stage")
    stage_dir = roles["Audit"] / "Runs" / stage
    current = stage_dir / "current"
    if not stage_dir.is_dir() or stage_dir.is_symlink():
        raise ProjectError(f"Audit stage is not a recoverable directory: {stage_dir}")
    initial_report = validate_project(root)
    if initial_report.damaging_errors:
        raise ProjectError(
            "DAMAGED: Audit recovery requires manual governance repair first: "
            + "; ".join(initial_report.damaging_errors)
        )
    assert_managed_state_integrity(root)

    project_text = project_file.read_text(encoding="utf-8", errors="replace")
    canonical = parse_canonical_entries(project_text)
    deliverables = parse_deliverable_entries(project_text)
    sources = tuple(
        sorted(
            path
            for path in stage_dir.iterdir()
            if path.name not in {"current", ".DS_Store"}
        )
    )
    if not sources:
        raise ProjectError(f"Audit stage has no failed staging to recover: {stage}")
    ambiguous = [
        (source, audit_recovery_ambiguity(root, source, roles, canonical, deliverables))
        for source in sources
    ]
    review = [(source, reason) for source, reason in ambiguous if reason is not None]
    if review:
        raise RecoverableBlocker(
            "AUDIT_RECOVERY_REVIEW_REQUIRED",
            "; ".join(f"{source.name}: {reason}" for source, reason in review),
            tuple(source.relative_to(root).as_posix() for source, _ in review),
            "review the affected artifacts manually; preserve current/, and rerun "
            f"audit recover {root} --stage {stage} only after classification is explicit",
        )

    recovery_write_set = managed_write_set(
        root,
        "audit recover",
        exact=tuple(source for source in sources if source.is_file()),
        trees=tuple(source for source in sources if source.is_dir()),
    )

    before_manifest = recovery_content_manifest(stage_dir, sources)
    build_transaction_plan(
        root,
        recovery_write_set,
        sources,
        sum(size for _, kind, size, _ in before_manifest if kind == "file"),
    )
    integrity = manifest_integrity(before_manifest)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    project_id = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    recovery_root = recovery_root_for_project(root)
    destination = recovery_root / project_id / stage / f"{timestamp}-{integrity[:12]}"

    with project_write_lock(root):
        current_sources = tuple(
            sorted(
                path
                for path in stage_dir.iterdir()
                if path.name not in {"current", ".DS_Store"}
            )
        )
        declared_sources = set(recovery_write_set.exact_paths) | set(
            recovery_write_set.tree_paths
        )
        if {path.resolve() for path in current_sources} != declared_sources:
            raise RecoverableBlocker(
                "AUDIT_RECOVERY_STATE_CHANGED",
                "Audit staging changed after recovery classification",
                tuple(path.relative_to(root).as_posix() for path in current_sources),
                f"rerun audit recover {root} --stage {stage}",
            )
        destination.mkdir(parents=True, exist_ok=False)
        try:
            for source in sources:
                target = destination / source.relative_to(stage_dir)
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
            copied_sources = tuple(destination / source.name for source in sources)
            copied_manifest = recovery_content_manifest(destination, copied_sources)
            if copied_manifest != before_manifest:
                raise ProjectError(
                    "Audit recovery read-back manifest does not match the source"
                )
            file_rows = [row for row in before_manifest if row[1] == "file"]
            manifest = {
                "project_id": project_id,
                "original_paths": [
                    source.relative_to(root).as_posix() for source in sources
                ],
                "recovery_path": str(destination),
                "stage": stage,
                "timestamp": timestamp,
                "file_count": len(file_rows),
                "total_size": sum(row[2] for row in file_rows),
                "integrity": {
                    "algorithm": "sha256",
                    "manifest_sha256": integrity,
                    "entries": [
                        {
                            "path": path,
                            "type": kind,
                            "size": size,
                            "sha256": digest,
                        }
                        for path, kind, size, digest in before_manifest
                    ],
                },
            }
            atomic_write(
                destination / "recovery-manifest.json",
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            )
            try:
                for source in sources:
                    if source.is_dir():
                        shutil.rmtree(source)
                    else:
                        source.unlink()
            except Exception:
                restore_recovery_sources(stage_dir, destination, sources)
                raise
        except Exception:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            raise

        if not current.exists():
            ds_store = stage_dir / ".DS_Store"
            ds_store.unlink(missing_ok=True)
            if not any(stage_dir.iterdir()):
                stage_dir.rmdir()
    return destination


def add_error(report: ValidationReport, message: str) -> None:
    if message not in report.errors:
        report.errors.append(message)
    if message not in report.damaging_errors:
        report.damaging_errors.append(message)


def add_recoverable(
    report: ValidationReport,
    code: str,
    message: str,
    paths: tuple[str, ...],
    recovery: str,
) -> None:
    if message not in report.errors:
        report.errors.append(message)
    blocker = RuntimeBlocker(code, message, paths, recovery)
    if blocker not in report.blockers:
        report.blockers.append(blocker)


def validate_stage2_root_topology(root: Path, report: ValidationReport) -> None:
    namespace = root / STEWARD_NAMESPACE
    if not namespace.is_dir():
        return
    for path in namespace.iterdir():
        if path.name.casefold() == "attention" and path.name != "Attention":
            add_error(report, f"Unexpected alternative Attention topology: {path.name}")
        if path.name.casefold() == "memory" and path.name != "Memory":
            add_error(report, f"Unexpected alternative Memory topology: {path.name}")


def validate_attention(root: Path, report: ValidationReport) -> None:
    attention_dir, index_path, entries_dir = attention_paths(root)
    if not attention_dir.exists():
        return
    try:
        assert_fixed_topology(attention_dir, index_path, entries_dir, "Attention")
    except ProjectError as exc:
        add_error(report, str(exc))
        if not index_path.is_file() or not entries_dir.is_dir():
            return
    index_text = index_path.read_text(encoding="utf-8", errors="replace")
    if index_text.count(ATTENTION_INDEX_MARKER) != 1:
        add_error(report, "Attention/index.md needs exactly one generated index marker")
    try:
        high_water = read_high_water(index_path, ATTENTION_HIGH_WATER, "Attention")
    except ProjectError as exc:
        add_error(report, str(exc))
        high_water = -1
    entries: list[AttentionEntry] = []
    ids: set[str] = set()
    for path in sorted(entries_dir.glob("*.md")):
        try:
            entry = parse_attention_entry(path)
        except ProjectError as exc:
            add_error(report, str(exc))
            continue
        if entry.attention_id in ids:
            add_error(report, f"Duplicate Attention ID: {entry.attention_id}")
        ids.add(entry.attention_id)
        entries.append(entry)
    if entries and high_water >= 0:
        maximum = max(
            int(ATTENTION_ID.fullmatch(entry.attention_id).group(1))
            for entry in entries
        )
        if high_water < maximum:
            add_error(report, "Attention index high-water is below an active entry ID")
    if high_water >= 0 and index_text != render_attention_index(entries, high_water):
        add_recoverable(
            report,
            "STALE_GENERATED_INDEX",
            "Attention/index.md does not exactly match active entries",
            (f"{STEWARD_NAMESPACE}/Attention/index.md",),
            f"review or restore the dirty generated index if needed, then run index {root}",
        )


def validate_memory_relationships(
    entries: list[MemoryEntry], report: ValidationReport
) -> None:
    by_id = {entry.memory_id: entry for entry in entries}
    for entry in entries:
        overlap = sorted(set(entry.supersedes) & set(entry.invalidates))
        if overlap:
            add_error(
                report,
                f"Memory {entry.memory_id} both supersedes and invalidates: "
                + ", ".join(overlap),
            )
        forward = set(entry.supersedes) | set(entry.invalidates)
        if entry.memory_id in forward:
            add_error(report, f"Memory entry references itself: {entry.memory_id}")
        for target_id in forward:
            target = by_id.get(target_id)
            if target is None:
                add_error(
                    report,
                    f"Memory {entry.memory_id} references missing ID: {target_id}",
                )
                continue
            source_number = int(MEMORY_ID.fullmatch(entry.memory_id).group(1))
            target_number = int(MEMORY_ID.fullmatch(target_id).group(1))
            if target_number >= source_number:
                add_error(
                    report,
                    f"Memory {entry.memory_id} must reference an earlier ID: {target_id}",
                )
        for target_id in entry.supersedes:
            target = by_id.get(target_id)
            if target is None:
                continue
            if (
                target.status != "superseded"
                or entry.memory_id not in target.superseded_by
            ):
                add_error(
                    report,
                    f"Memory supersedes relationship is not mirrored: "
                    f"{entry.memory_id} -> {target_id}",
                )
        for target_id in entry.invalidates:
            target = by_id.get(target_id)
            if target is None:
                continue
            if (
                target.status != "invalidated"
                or entry.memory_id not in target.invalidated_by
            ):
                add_error(
                    report,
                    f"Memory invalidates relationship is not mirrored: "
                    f"{entry.memory_id} -> {target_id}",
                )
        for source_id in entry.superseded_by:
            source = by_id.get(source_id)
            if source is None or entry.memory_id not in source.supersedes:
                add_error(
                    report,
                    f"Memory superseded_by relationship is not mirrored: "
                    f"{entry.memory_id} <- {source_id}",
                )
        for source_id in entry.invalidated_by:
            source = by_id.get(source_id)
            if source is None or entry.memory_id not in source.invalidates:
                add_error(
                    report,
                    f"Memory invalidated_by relationship is not mirrored: "
                    f"{entry.memory_id} <- {source_id}",
                )
        if entry.status == "active" and (entry.superseded_by or entry.invalidated_by):
            add_error(
                report, f"Active Memory has a terminal reverse link: {entry.memory_id}"
            )
        elif entry.status == "superseded" and (
            len(entry.superseded_by) != 1 or entry.invalidated_by
        ):
            add_error(
                report,
                f"Superseded Memory has inconsistent reverse links: {entry.memory_id}",
            )
        elif entry.status == "invalidated" and (
            len(entry.invalidated_by) != 1 or entry.superseded_by
        ):
            add_error(
                report,
                f"Invalidated Memory has inconsistent reverse links: {entry.memory_id}",
            )


def validate_memory(root: Path, report: ValidationReport) -> None:
    memory_dir, index_path, entries_dir = memory_paths(root)
    if not memory_dir.exists():
        return
    try:
        assert_fixed_topology(memory_dir, index_path, entries_dir, "Memory")
    except ProjectError as exc:
        add_error(report, str(exc))
        if not index_path.is_file() or not entries_dir.is_dir():
            return
    index_text = index_path.read_text(encoding="utf-8", errors="replace")
    if index_text.count(MEMORY_INDEX_MARKER) != 1:
        add_error(report, "Memory/index.md needs exactly one generated index marker")
    try:
        high_water = read_high_water(index_path, MEMORY_HIGH_WATER, "Memory")
    except ProjectError as exc:
        add_error(report, str(exc))
        high_water = -1
    entries: list[MemoryEntry] = []
    ids: set[str] = set()
    for path in sorted(entries_dir.glob("*.md")):
        try:
            entry = parse_memory_entry(path)
        except ProjectError as exc:
            add_error(report, str(exc))
            continue
        if entry.memory_id in ids:
            add_error(report, f"Duplicate Memory ID: {entry.memory_id}")
        ids.add(entry.memory_id)
        entries.append(entry)
    if entries and high_water >= 0:
        maximum = max(
            int(MEMORY_ID.fullmatch(entry.memory_id).group(1)) for entry in entries
        )
        if high_water < maximum:
            add_error(report, "Memory index high-water is below an entry ID")
    if high_water >= 0 and index_text != render_memory_index(entries, high_water):
        add_recoverable(
            report,
            "STALE_GENERATED_INDEX",
            "Memory/index.md does not exactly match entries",
            (f"{STEWARD_NAMESPACE}/Memory/index.md",),
            f"review or restore the dirty generated index if needed, then run index {root}",
        )
    validate_memory_relationships(entries, report)


def validate_project_md(
    root: Path, report: ValidationReport
) -> tuple[str, dict[str, Path], list[CanonicalEntry], list[DeliverableEntry]]:
    _, registry, _, _, audit_dir = steward_paths(root)
    if not registry.exists():
        add_error(report, "Steward registry.md is missing")
        return "", {}, [], []
    text = registry.read_text(encoding="utf-8", errors="replace")
    if SCHEMA_MARKER not in text:
        add_error(report, "registry.md is not an Oppen Project Steward v3 registry")
    blocks = (
        (ROLE_START, ROLE_END, "role"),
        (CANONICAL_START, CANONICAL_END, "canonical source"),
        (DELIVERABLE_START, DELIVERABLE_END, "deliverable registry"),
        (CONTRACT_AUDIT_START, CONTRACT_AUDIT_END, "contract audit index"),
    )
    for start, end, label in blocks:
        if text.count(start) != 1 or text.count(end) != 1:
            add_error(report, f"registry.md needs exactly one managed {label} block")
    roles: dict[str, Path] = {}
    canonical: list[CanonicalEntry] = []
    deliverables: list[DeliverableEntry] = []
    try:
        roles = parse_role_mappings(root, text)
        roles["Audit"] = audit_dir
    except ProjectError as exc:
        add_error(report, str(exc))
    try:
        canonical = parse_canonical_entries(text)
    except ProjectError as exc:
        add_error(report, str(exc))
    try:
        deliverables = parse_deliverable_entries(text)
    except ProjectError as exc:
        add_error(report, str(exc))
    return text, roles, canonical, deliverables


def validate_indexes(
    root: Path,
    roles: dict[str, Path],
    text: str,
    canonical: list[CanonicalEntry],
    deliverables: list[DeliverableEntry],
    report: ValidationReport,
) -> None:
    if not text or "Audit" not in roles:
        return
    expected = (
        (ROLE_START, ROLE_END, "role", role_table(root, roles)),
        (
            CANONICAL_START,
            CANONICAL_END,
            "canonical source",
            render_canonical_entries(canonical),
        ),
        (
            DELIVERABLE_START,
            DELIVERABLE_END,
            "deliverable registry",
            render_deliverable_entries(deliverables),
        ),
        (
            CONTRACT_AUDIT_START,
            CONTRACT_AUDIT_END,
            "contract audit index",
            render_contract_audit_entries(contract_audit_entries(root, roles["Audit"])),
        ),
    )
    for start, end, label, expected_body in expected:
        try:
            current = extract_block(text, start, end, label)
        except ProjectError:
            continue
        if current != expected_body:
            add_recoverable(
                report,
                "STALE_GENERATED_INDEX",
                f"registry.md has a stale or non-canonical {label} block",
                (f"{STEWARD_NAMESPACE}/{REGISTRY_NAME}",),
                f"review or restore dirty generated sections if needed, then run index {root}",
            )


def validate_canonical_entries(
    root: Path, entries: list[CanonicalEntry], report: ValidationReport
) -> None:
    topics: set[str] = set()
    owners: set[tuple[str, str]] = set()
    for entry in entries:
        try:
            validate_key(entry.topic, "canonical topic")
        except ProjectError as exc:
            add_error(report, str(exc))
        if entry.topic in topics:
            add_error(report, f"Duplicate canonical topic: {entry.topic}")
        topics.add(entry.topic)
        owner_key = (entry.path, entry.section)
        if owner_key in owners:
            add_error(
                report,
                f"Duplicate current canonical owner: {entry.path}"
                + (f" section {entry.section!r}" if entry.section else ""),
            )
        owners.add(owner_key)
        try:
            owner, _ = resolve_project_path(root, entry.path, "canonical owner")
            verification, _ = resolve_project_path(
                root, entry.verification, "canonical verification"
            )
        except ProjectError as exc:
            add_error(report, str(exc))
            continue
        if not owner.is_file():
            add_error(report, f"Canonical owner is not a file: {entry.path}")
            continue
        if entry.section:
            try:
                markdown_section(
                    owner.read_text(encoding="utf-8", errors="replace"),
                    entry.section,
                )
            except ProjectError as exc:
                add_error(report, f"Canonical owner {entry.path}: {exc}")
                continue
        if entry.status not in ALLOWED_STATUSES:
            add_error(
                report,
                f"Canonical owner {entry.path} has invalid registry status "
                f"{entry.status!r}",
            )
        error = verification_error(verification)
        if error:
            add_error(report, f"Invalid verification {entry.verification}: {error}")


def validate_deliverables(
    root: Path,
    roles: dict[str, Path],
    entries: list[DeliverableEntry],
    report: ValidationReport,
) -> None:
    if "Deliverables" not in roles:
        if entries:
            add_error(
                report,
                "Deliverables are registered without an optional Deliverables role",
            )
        return
    ids: set[str] = set()
    paths: set[str] = set()
    for entry in entries:
        try:
            validate_key(entry.deliverable_id, "deliverable id")
            validate_key(entry.kind, "deliverable kind")
            validate_key(entry.audience, "deliverable audience")
        except ProjectError as exc:
            add_error(report, str(exc))
        if entry.deliverable_id in ids:
            add_error(report, f"Duplicate Deliverable id: {entry.deliverable_id}")
        ids.add(entry.deliverable_id)
        if entry.path in paths:
            add_error(
                report, f"Deliverable path registered more than once: {entry.path}"
            )
        paths.add(entry.path)
        try:
            artifact, _ = resolve_project_path(root, entry.path, "Deliverable")
            producer, _ = resolve_project_path(
                root, entry.producer, "Deliverable producer"
            )
        except ProjectError as exc:
            add_error(report, str(exc))
            continue
        if not artifact.is_file():
            add_error(report, f"Registered Deliverable is not a file: {entry.path}")
        error = deliverable_artifact_error(artifact, roles["Deliverables"].resolve())
        if error:
            add_error(report, f"Invalid Deliverable {entry.path}: {error}")
        if not producer.is_file():
            add_error(report, f"Deliverable producer is not a file: {entry.producer}")
    files = [
        path
        for path in roles["Deliverables"].rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    ]
    unregistered = [
        path.relative_to(root).as_posix()
        for path in files
        if path.relative_to(root).as_posix() not in paths
    ]
    if unregistered:
        add_error(
            report,
            "Deliverables contains unregistered file(s): "
            + ", ".join(unregistered[:10]),
        )
    for path in files:
        error = deliverable_artifact_error(path, roles["Deliverables"].resolve())
        if error:
            add_error(
                report,
                f"Invalid Deliverable {path.relative_to(root).as_posix()}: {error}",
            )


def section_error(content: str, section: str) -> str | None:
    try:
        section_text = markdown_section(content, section)
    except ProjectError as exc:
        return str(exc)
    body = section_text.split("\n", 1)[1].strip() if "\n" in section_text else ""
    if not body:
        return f"section {section!r} is empty"
    return None


def validate_contract_audits(
    root: Path, roles: dict[str, Path], report: ValidationReport
) -> None:
    if "Audit" not in roles:
        return
    contracts_dir = roles["Audit"] / "Contracts"
    if not contracts_dir.exists():
        return
    if not contracts_dir.is_dir():
        add_error(report, "Audit/Contracts must be a directory")
        return
    seen: set[str] = set()
    for audit in sorted(contracts_dir.rglob("*")):
        if not audit.is_file() or audit.name == ".DS_Store":
            continue
        relative = audit.relative_to(root).as_posix()
        if audit.parent != contracts_dir or audit.suffix.lower() != ".md":
            add_error(report, f"Invalid registered contract audit path: {relative}")
            continue
        metadata = parse_frontmatter(audit)
        topic = metadata.get("steward_contract", "")
        source = metadata.get("source", "")
        source_sha256 = metadata.get("source_sha256", "")
        risk_reason = metadata.get("risk_reason", "")
        if not all((topic, source, source_sha256, risk_reason)):
            add_error(report, f"Contract Audit lacks required metadata: {relative}")
            continue
        if topic in seen:
            add_error(report, f"Duplicate Contract Audit topic: {topic}")
        seen.add(topic)
        try:
            validate_key(topic, "contract audit topic")
        except ProjectError as exc:
            add_error(report, str(exc))
        if audit.name != f"audit_{topic}.md":
            add_error(report, f"Invalid registered contract audit path: {relative}")
        try:
            source_path, _ = resolve_project_path(root, source, "contract source")
        except ProjectError as exc:
            add_error(report, str(exc))
            continue
        if not source_path.is_file():
            add_error(report, f"Contract Audit source is not a file: {source}")
            continue
        content = audit.read_text(encoding="utf-8", errors="replace")
        for section in (
            "Purpose And Risk",
            "Contract",
            "Edge Cases And Verification",
            "Known Limits",
        ):
            error = section_error(content, section)
            if error:
                add_error(report, f"Contract Audit {error}: {relative}")
        if PLACEHOLDER_PATTERN.search(content):
            add_error(
                report, f"Contract Audit contains an unfinished template: {relative}"
            )
        if source_sha256 != file_sha256(source_path):
            add_error(report, f"Contract Audit is stale for its source: {relative}")


def validate_audit_runs(
    root: Path, roles: dict[str, Path], report: ValidationReport
) -> None:
    if "Audit" not in roles:
        return
    runs_dir = roles["Audit"] / "Runs"
    if not runs_dir.exists():
        return
    if not runs_dir.is_dir():
        add_error(report, "Audit/Runs must be a directory")
        return
    root_files = [path for path in runs_dir.iterdir() if not path.is_dir()]
    if root_files:
        add_error(report, "Audit/Runs contains files outside a stage/current directory")
    for stage in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        children = [path for path in stage.iterdir() if path.name != ".DS_Store"]
        invalid_paths = [path for path in children if path.name != "current"]
        invalid = [path.name for path in invalid_paths]
        if invalid:
            add_recoverable(
                report,
                "AUDIT_STAGING_RESIDUE",
                f"Audit stage {stage.name!r} contains persistent history or staging: "
                + ", ".join(invalid),
                tuple(path.relative_to(root).as_posix() for path in invalid_paths),
                f"run audit recover {root} --stage {stage.name}",
            )
        current = stage / "current"
        if not current.is_dir() or current.is_symlink():
            if current.exists():
                add_error(
                    report,
                    f"Audit stage {stage.name!r} current is not a real directory",
                )
            elif not invalid_paths:
                add_error(
                    report, f"Audit stage {stage.name!r} has no current directory"
                )
            continue
        invalid_nested = [
            path.relative_to(root).as_posix()
            for path in current.rglob("*")
            if path.is_dir()
            and re.fullmatch(
                r"old|previous|backup|staging|legacy|superseded|obsolete|run[_-]?\d+|"
                r"v\d+|\d{8}|\d{4}-\d{2}-\d{2}",
                path.name,
                re.IGNORECASE,
            )
        ]
        if invalid_nested:
            add_error(
                report,
                "Audit current contains historical or staging directories: "
                + ", ".join(invalid_nested[:10]),
            )


def validate_parallel_copies(
    root: Path, canonical: list[CanonicalEntry], report: ValidationReport
) -> None:
    suspicious: set[str] = set()
    families: dict[tuple[Path, str, str], list[Path]] = {}
    scan_dirs: set[Path] = set()
    for entry in canonical:
        try:
            owner, _ = resolve_project_path(root, entry.path, "canonical owner")
        except ProjectError:
            continue
        scan_dirs.add(owner.parent)
    for parent in sorted(scan_dirs):
        for path in parent.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".md", ".markdown", ".qmd", ".rmd", ".txt"}:
                continue
            if PARALLEL_COPY_TOKEN.search(path.stem):
                suspicious.add(path.relative_to(root).as_posix())
            family = VERSION_SUFFIX.sub("", path.stem)
            families.setdefault((path.parent, path.suffix.lower(), family), []).append(
                path
            )
    for paths in families.values():
        if len(paths) > 1 and any(VERSION_SUFFIX.search(path.stem) for path in paths):
            suspicious.update(path.relative_to(root).as_posix() for path in paths)
    if suspicious:
        add_error(
            report,
            "Parallel old/new/backup/versioned current copies detected: "
            + ", ".join(sorted(suspicious)[:10]),
        )


def legacy_steward_registry(root: Path) -> Path | None:
    candidate = root / "project.md"
    if not candidate.is_file() or candidate.is_symlink():
        return None
    text = candidate.read_text(encoding="utf-8", errors="replace")
    if text.count(SCHEMA_MARKER) != 1:
        return None
    try:
        validate_registry_shape(text, "Legacy Steward registry")
        parse_legacy_roles(root, text)
    except ProjectError:
        return None
    return candidate


def recognizable_namespace(namespace: Path) -> bool:
    registry = namespace / REGISTRY_NAME
    if registry.is_file():
        text = registry.read_text(encoding="utf-8", errors="replace")
        if SCHEMA_MARKER in text or any(
            marker in text
            for marker in (ROLE_START, CANONICAL_START, DELIVERABLE_START)
        ):
            return True
    for index, marker in (
        (namespace / "Memory/index.md", MEMORY_INDEX_MARKER),
        (namespace / "Attention/index.md", ATTENTION_INDEX_MARKER),
    ):
        if index.is_file() and marker in index.read_text(
            encoding="utf-8", errors="replace"
        ):
            return True
    return False


def validate_namespace_topology(root: Path, report: ValidationReport) -> None:
    namespace, registry, memory_dir, attention_dir, audit_dir = steward_paths(root)
    expected = {
        REGISTRY_NAME,
        MANAGED_STATE_NAME,
        "Memory",
        "Attention",
        "Audit",
        ".DS_Store",
    }
    unexpected = [
        path.name for path in namespace.iterdir() if path.name not in expected
    ]
    if unexpected:
        add_error(
            report,
            "Steward namespace contains unexpected paths: " + ", ".join(unexpected),
        )
    if not registry.is_file() or registry.is_symlink():
        add_error(report, "Steward registry.md must be a real file")
    for label, path in (
        ("Memory", memory_dir),
        ("Attention", attention_dir),
        ("Audit", audit_dir),
        ("Audit/Runs", audit_dir / "Runs"),
        ("Audit/Contracts", audit_dir / "Contracts"),
    ):
        if not path.is_dir() or path.is_symlink():
            add_error(report, f"Steward {label} must be a real directory")


def validate_managed_state(root: Path, report: ValidationReport) -> None:
    try:
        baseline = load_managed_state(root)
    except RecoverableBlocker as blocker:
        add_recoverable(
            report,
            blocker.code,
            str(blocker.args[0]),
            blocker.paths,
            blocker.recovery,
        )
        return
    except ProjectError as exc:
        add_error(report, str(exc))
        return
    try:
        drift = managed_state_drift(root, baseline)
    except ProjectError as exc:
        add_error(report, str(exc))
        return
    if drift:
        add_recoverable(
            report,
            "MANAGED_STATE_CONFLICT",
            "Steward control-plane files differ from the last successful baseline",
            drift,
            "inspect and reconcile only the listed Steward-managed paths; do not reset them from Git automatically",
        )


def validate_project(root: Path) -> ValidationReport:
    root = root.expanduser().resolve()
    report = ValidationReport(errors=[], warnings=[], blockers=[], damaging_errors=[])
    if not root.is_dir():
        add_error(report, f"Project directory does not exist: {root}")
        return report
    namespace = root / STEWARD_NAMESPACE
    if not namespace.exists():
        if legacy_steward_registry(root) is not None:
            add_recoverable(
                report,
                "LEGACY_STEWARD_LAYOUT",
                "A proven pre-4.2 Steward registry still owns root governance paths",
                ("project.md",),
                f"run upgrade-layout {root} --check, then upgrade-layout {root} --apply",
            )
            return report
        report.project_state = "ADOPTION_REQUIRED"
        return report
    if namespace.is_symlink() or not namespace.is_dir():
        report.project_state = "ADOPTION_BLOCKED"
        add_recoverable(
            report,
            "NAMESPACE_CONFLICT",
            "The fixed Steward namespace is occupied by incompatible user content",
            (STEWARD_NAMESPACE,),
            "move or resolve that user-owned path manually, then rerun adopt --check",
        )
        return report
    if not recognizable_namespace(namespace):
        report.project_state = "ADOPTION_BLOCKED"
        add_recoverable(
            report,
            "NAMESPACE_CONFLICT",
            "The fixed Steward namespace exists but is not Steward-owned",
            (STEWARD_NAMESPACE,),
            "resolve the namespace ownership conflict manually; no alternate namespace is allowed",
        )
        return report
    validate_namespace_topology(root, report)
    validate_managed_state(root, report)
    text, roles, canonical, deliverables = validate_project_md(root, report)
    validate_indexes(root, roles, text, canonical, deliverables, report)
    validate_canonical_entries(root, canonical, report)
    validate_deliverables(root, roles, deliverables, report)
    validate_contract_audits(root, roles, report)
    validate_audit_runs(root, roles, report)
    validate_stage2_root_topology(root, report)
    validate_attention(root, report)
    validate_memory(root, report)
    validate_parallel_copies(root, canonical, report)
    return report


def print_validation(report: ValidationReport) -> None:
    print(f"Oppen Project Steward runtime status: {report.status}")
    print(f"Oppen Project Steward validation: {'PASS' if report.ok else 'FAIL'}")
    for blocker in report.blockers:
        print(f"BLOCKER: {blocker.code}: {blocker.message}")
        print(f"AFFECTED: {', '.join(blocker.paths)}")
        print(f"RECOVERY: {blocker.recovery}")
    for error in report.damaging_errors:
        print(f"ERROR: {error}")
    for warning in report.warnings:
        print(f"WARNING: {warning}")
    print(
        f"Damaging errors: {len(report.damaging_errors)}; "
        f"recoverable blockers: {len(report.blockers)}; warnings: {len(report.warnings)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Maintain deterministic current-state governance for durable projects."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser(
        "init", help="Initialize Steward governance for a genuinely new project."
    )
    init_parser.add_argument("target_dir", type=Path)
    adopt_parser = subparsers.add_parser(
        "adopt", help="Check or adopt an existing project without restructuring it."
    )
    adopt_parser.add_argument("target_dir", type=Path)
    adopt_action = adopt_parser.add_mutually_exclusive_group(required=True)
    adopt_action.add_argument("--check", action="store_true")
    adopt_action.add_argument("--apply", action="store_true")
    adopt_parser.add_argument("--input", type=Path)
    upgrade_parser = subparsers.add_parser(
        "upgrade-layout", help="Upgrade a proven pre-4.2 Steward root layout."
    )
    upgrade_parser.add_argument("target_dir", type=Path)
    upgrade_action = upgrade_parser.add_mutually_exclusive_group(required=True)
    upgrade_action.add_argument("--check", action="store_true")
    upgrade_action.add_argument("--apply", action="store_true")
    managed_state_parser = subparsers.add_parser(
        "managed-state", help="Check or bootstrap Steward control-plane continuity."
    )
    managed_state_parser.add_argument("target_dir", type=Path)
    managed_state_action = managed_state_parser.add_mutually_exclusive_group(
        required=True
    )
    managed_state_action.add_argument("--check", action="store_true")
    managed_state_action.add_argument("--bootstrap", action="store_true")
    canonical_parser = subparsers.add_parser(
        "canonical", help="Register or explicitly replace one canonical owner."
    )
    canonical_parser.add_argument("target_dir", type=Path)
    canonical_parser.add_argument("--topic", required=True)
    canonical_parser.add_argument("--path", required=True)
    canonical_parser.add_argument("--section")
    canonical_parser.add_argument("--status", choices=sorted(ALLOWED_STATUSES))
    canonical_parser.add_argument("--verification", required=True)
    canonical_parser.add_argument("--replace", action="store_true")
    deliverable_parser = subparsers.add_parser(
        "deliverable", help="Register one current human Deliverable."
    )
    deliverable_parser.add_argument("target_dir", type=Path)
    deliverable_parser.add_argument("--id", required=True, dest="deliverable_id")
    deliverable_parser.add_argument("--path", required=True)
    deliverable_parser.add_argument("--kind", required=True)
    deliverable_parser.add_argument("--audience", required=True)
    deliverable_parser.add_argument("--producer", required=True)
    deliverable_parser.add_argument("--replace", action="store_true")
    audit_parser = subparsers.add_parser(
        "contract-audit", help="Create or locate one High-Risk Contract Audit."
    )
    audit_parser.add_argument("target_dir", type=Path)
    audit_parser.add_argument("--topic", required=True)
    audit_parser.add_argument("--source")
    audit_parser.add_argument("--risk-reason")
    audit_parser.add_argument("--input", type=Path)
    run_audit_parser = subparsers.add_parser(
        "audit", help="Promote validated machine evidence to Audit current."
    )
    run_audit_actions = run_audit_parser.add_subparsers(
        dest="audit_command", required=True
    )
    audit_promote_parser = run_audit_actions.add_parser(
        "promote", help="Atomically promote one external temporary evidence tree."
    )
    audit_promote_parser.add_argument("target_dir", type=Path)
    audit_promote_parser.add_argument("--stage", required=True)
    audit_promote_parser.add_argument("--input", required=True, type=Path)
    audit_recover_parser = run_audit_actions.add_parser(
        "recover",
        help="Move clearly failed Audit staging to verified recovery storage.",
    )
    audit_recover_parser.add_argument("target_dir", type=Path)
    audit_recover_parser.add_argument("--stage", required=True)
    attention_parser = subparsers.add_parser(
        "attention", help="Raise or resolve a Human Attention entry."
    )
    attention_actions = attention_parser.add_subparsers(
        dest="attention_command", required=True
    )
    attention_raise_parser = attention_actions.add_parser(
        "raise", help="Raise one material unresolved issue from temporary JSON."
    )
    attention_raise_parser.add_argument("target_dir", type=Path)
    attention_raise_parser.add_argument("--input", required=True, type=Path)
    attention_resolve_parser = attention_actions.add_parser(
        "resolve", help="Remove one resolved active Attention entry."
    )
    attention_resolve_parser.add_argument("target_dir", type=Path)
    attention_resolve_parser.add_argument("--id", required=True, dest="attention_id")
    memory_parser = subparsers.add_parser(
        "memory", help="Record consequential Decision Memory from temporary JSON."
    )
    memory_actions = memory_parser.add_subparsers(dest="memory_command", required=True)
    memory_add_parser = memory_actions.add_parser(
        "add", help="Add one qualifying consequential decision event."
    )
    memory_add_parser.add_argument("target_dir", type=Path)
    memory_add_parser.add_argument("--input", required=True, type=Path)
    index_parser = subparsers.add_parser("index", help="Refresh generated registries.")
    index_parser.add_argument("target_dir", type=Path)
    validate_parser = subparsers.add_parser(
        "validate", help="Validate steward v3 current-state contracts."
    )
    validate_parser.add_argument("target_dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.target_dir.expanduser().resolve()
    if args.command == "init":
        project_file = initialize_new_project(root)
        print(f"Initialized Oppen Project Steward v3: {project_file}")
    elif args.command == "adopt" and args.check:
        if args.input is not None:
            raise ProjectError("adopt --check does not accept --input")
        result = adoption_preflight(root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1 if result["status"] == "ADOPTION_BLOCKED" else 0
    elif args.command == "adopt" and args.apply:
        if args.input is None:
            raise ProjectError("adopt --apply requires --input TEMP_JSON")
        path, action = apply_adoption(root, args.input)
        print(f"{action}: {path}")
    elif args.command == "upgrade-layout" and args.check:
        result = legacy_layout_preflight(root)
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.command == "upgrade-layout" and args.apply:
        path, action = apply_layout_upgrade(root)
        print(f"{action}: {path}")
    elif args.command == "managed-state" and args.check:
        result = managed_state_preflight(root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "MANAGED_READY" else 1
    elif args.command == "managed-state" and args.bootstrap:
        path = bootstrap_managed_state(root)
        print(f"Managed-state baseline ready: {path}")
    elif args.command == "canonical":
        register_canonical(
            root,
            args.topic,
            args.path,
            args.section,
            args.verification,
            status=args.status,
            replace=args.replace,
        )
        print(f"Canonical topic registered: {args.topic}")
    elif args.command == "deliverable":
        register_deliverable(
            root,
            args.deliverable_id,
            args.path,
            args.kind,
            args.audience,
            args.producer,
            replace=args.replace,
        )
        print(f"Current Deliverable registered: {args.deliverable_id}")
    elif args.command == "contract-audit":
        if args.input is not None:
            if args.source is not None or args.risk_reason is not None:
                raise ProjectError(
                    "contract-audit --input cannot be combined with --source or --risk-reason"
                )
            path = complete_contract_audit(root, args.topic, args.input)
            print(f"COMPLETED: {path}")
        else:
            if args.source is None or args.risk_reason is None:
                raise ProjectError(
                    "contract-audit creation requires --source and --risk-reason"
                )
            path, action = create_or_locate_contract_audit(
                root, args.topic, args.source, args.risk_reason
            )
            print(f"{action}: {path}")
    elif args.command == "audit" and args.audit_command == "promote":
        path = promote_audit(root, args.stage, args.input)
        print(f"Audit current promoted: {path}")
    elif args.command == "audit" and args.audit_command == "recover":
        path = recover_audit(root, args.stage)
        print(f"Audit staging recovered outside project: {path}")
        report = validate_project(root)
        print_validation(report)
        return 0 if report.ok else 1
    elif args.command == "attention" and args.attention_command == "raise":
        path = raise_attention(root, args.input)
        print(f"Attention raised: {path}")
    elif args.command == "attention" and args.attention_command == "resolve":
        path = resolve_attention(root, args.attention_id)
        print(f"Attention resolved and removed: {path}")
    elif args.command == "memory" and args.memory_command == "add":
        path = add_memory(root, args.input)
        print(f"Decision Memory added: {path}")
    elif args.command == "index":
        print(f"Updated current project map: {refresh_index(root)}")
    elif args.command == "validate":
        report = validate_project(root)
        print_validation(report)
        return 0 if report.ok else 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProjectError as exc:
        print(f"oppen-project-steward error: {exc}", file=sys.stderr)
        raise SystemExit(1)
