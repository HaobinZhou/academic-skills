#!/usr/bin/env python3
"""Maintain lean, canonical, human-readable Stepwise R projects."""

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
from datetime import datetime, timezone
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback retains atomic single writes.
    fcntl = None  # type: ignore[assignment]


SCHEMA_MARKER = "<!-- stepwise-r-project:v3 -->"
V2_SCHEMA_MARKER = "<!-- stepwise-r-project:v2 -->"

ROLE_START = "<!-- stepwise-r-project:roles:start -->"
ROLE_END = "<!-- stepwise-r-project:roles:end -->"
CANONICAL_START = "<!-- stepwise-r-project:canonical:start -->"
CANONICAL_END = "<!-- stepwise-r-project:canonical:end -->"
SCRIPT_START = "<!-- stepwise-r-project:scripts:start -->"
SCRIPT_END = "<!-- stepwise-r-project:scripts:end -->"
RESULT_START = "<!-- stepwise-r-project:results:start -->"
RESULT_END = "<!-- stepwise-r-project:results:end -->"
FUNCTION_START = "<!-- stepwise-r-project:function-audits:start -->"
FUNCTION_END = "<!-- stepwise-r-project:function-audits:end -->"
NAVIGATION_START = "<!-- stepwise-r-project:managed-navigation:start -->"
NAVIGATION_END = "<!-- stepwise-r-project:managed-navigation:end -->"

LEGACY_MEMORY_START = "<!-- stepwise-r-project:memory:start -->"
LEGACY_MEMORY_END = "<!-- stepwise-r-project:memory:end -->"

ROLE_ALIASES = {
    "R": ("R", "r"),
    "Data": ("Data", "data"),
    "Results": ("Results", "results", "Output", "output", "Outputs", "outputs"),
    "Audit": ("Audit", "audit"),
}
MEMORY_ALIASES = ("Memory", "memory")
MEMORY_DIRECTORY = "Memory"
ATTENTION_DIRECTORY = "Attention"
ENTRY_DIRECTORY = "entries"
MEMORY_ID_PATTERN = re.compile(r"^M-[0-9]{4,}$")
ATTENTION_ID_PATTERN = re.compile(r"^A-[0-9]{4,}$")
MEMORY_STATUSES = ("active", "superseded", "invalidated")
PROJECT_V3 = "V3"
MIGRATION_REQUIRED = "MIGRATION_REQUIRED"
MIGRATION_BLOCKED_RECOVERABLE = "MIGRATION_BLOCKED_RECOVERABLE"
MIGRATION_BLOCKED_WORKTREE_OVERLAP = "MIGRATION_BLOCKED_WORKTREE_OVERLAP"
MIGRATION_BLOCKED_UNSAFE_STAGING_PLAN = "MIGRATION_BLOCKED_UNSAFE_STAGING_PLAN"
PROJECT_UNMANAGED = "UNMANAGED"
PROJECT_DAMAGED = "DAMAGED"

MIGRATION_WRITE_SET = (
    "project.md",
    "Memory/**",
    "memory/**",
    "Attention/**",
    "attention/**",
)
MIGRATION_STAGING_ESTIMATE_OVERHEAD = 64 * 1024
_MIGRATION_OVERLAY: ContextVar[tuple[Path, Path] | None] = ContextVar(
    "stepwise_migration_overlay", default=None
)
RECOVERABLE_AUDIT_NAME = re.compile(
    r"(?:^|[._-])(?:staging|stage|failed|failure|incomplete|partial|tmp|temp)"
    r"(?:$|[._-])",
    re.IGNORECASE,
)

ATTENTION_FIELDS = (
    "ID",
    "Title",
    "Blocking",
    "Observation",
    "Evidence",
    "Why It Matters",
    "Why No Action Was Taken",
    "Human Decision Needed",
)
MEMORY_FIELDS = (
    "ID",
    "Status",
    "Title",
    "Related Topics",
    "Supersedes",
    "Invalidates",
    "Superseded By",
    "Invalidated By",
    "Before",
    "Trigger",
    "Decision",
    "Scientific or Technical Rationale",
    "Basis",
    "Rejected or Prior Approach",
    "Consequence",
)

RESULT_KINDS = ("table", "figure", "cohort-flow", "codebook", "report")
RESULT_AUDIENCES = ("publication", "formal-review")
ALLOWED_RESULT_SUFFIXES = {
    ".csv",
    ".tsv",
    ".xlsx",
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
}
ALLOWED_CONTRACT_TEST_SUFFIXES = {".r", ".py", ".sh"}
RESULT_KIND_SUFFIXES = {
    "table": {".csv", ".tsv", ".xlsx", ".md", ".html", ".pdf", ".docx"},
    "figure": {".pdf", ".png", ".jpg", ".jpeg", ".svg", ".tif", ".tiff"},
    "codebook": {".csv", ".tsv", ".xlsx", ".md", ".html", ".pdf", ".docx"},
    "report": {".md", ".html", ".pdf", ".docx"},
}
IGNORED_PROJECT_DIRS = {
    ".git",
    ".agents",
    ".codex",
    ".quarto",
    ".Rproj.user",
    ".venv",
    "venv",
    "renv",
    "node_modules",
    "tests",
    "test",
}

FORBIDDEN_RESULT_TOKEN = re.compile(
    r"(?:^|[_\-.])(?:audit|trace|acceptance|manifest|session|cache|qa|qc|"
    r"diagnostic|debug|intermediate|draft|staging|tmp|old|backup|legacy|"
    r"invalidated)(?:[_\-.]|$)",
    re.IGNORECASE,
)
EXECUTION_RESULT_TOKEN = re.compile(
    r"(?:^|[_\-.])(?:run|runtime|execution|pipeline|stage)[_\-.]?(?:status|log)"
    r"(?:[_\-.]|$)|(?:^|[_\-.])(?:status|log)[_\-.]?"
    r"(?:run|runtime|execution|pipeline|stage)(?:[_\-.]|$)",
    re.IGNORECASE,
)
PARALLEL_COPY_TOKEN = re.compile(
    r"(?:^|[_\-.])(?:old|backup|copy|legacy|superseded|obsolete)"
    r"(?:[_\-.](?:\d{8}|\d{4}-\d{2}-\d{2}))?$|"
    r"(?:副本|备份|旧版)",
    re.IGNORECASE,
)
VERSION_SUFFIX = re.compile(
    r"(?:[_\-.](?:v\d+|\d{8}|\d{4}-\d{2}-\d{2}))$",
    re.IGNORECASE,
)
LEGACY_MEMORY_NAME = re.compile(
    r"^\d{8}_(?:mini|medium|huge|boom)_.*\.md$",
    re.IGNORECASE,
)
KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
UNRESOLVED_PATTERN = re.compile(
    r"TODO|TBD|pending|decide\s+later|待确认|待重算|尚未冻结|"
    r"需(?:要)?后续冻结|待补充|待定|未决定|未确定|稍后决定|"
    r"(?<!通)过时|旧(?:版|口径|队列|结果|数字|分母)|stale",
    re.IGNORECASE,
)
RUN_STATUS_PATTERN = re.compile(
    r"(?i:run[_ -]?id)|正式执行状态|\bPASS\b|\bBLOCKED\b",
)
PLACEHOLDER_PATTERN = re.compile(
    r"TODO|请填写|^-\s*(?:Change|Why|Verification|Risk|变更|原因|验证|风险):\s*$|"
    r"^-\s*$",
    re.IGNORECASE | re.MULTILINE,
)


class ProjectError(RuntimeError):
    """Raised when a managed project violates a deterministic contract."""


def detect_project_marker_state(root: Path) -> str:
    root = root.expanduser().resolve()
    project_file = root / "project.md"
    if not project_file.is_file():
        return PROJECT_UNMANAGED
    text = project_file.read_text(encoding="utf-8", errors="replace")
    v3_count = text.count(SCHEMA_MARKER)
    v2_count = text.count(V2_SCHEMA_MARKER)
    if v3_count == 1 and v2_count == 0:
        return PROJECT_V3
    if v2_count == 1 and v3_count == 0:
        return MIGRATION_REQUIRED
    if v2_count or v3_count or "<!-- stepwise-r-project:" in text:
        return PROJECT_DAMAGED
    return PROJECT_UNMANAGED


def detect_project_state(root: Path) -> str:
    marker_state = detect_project_marker_state(root)
    if marker_state == MIGRATION_REQUIRED:
        return str(migration_preflight(root)["state"])
    return marker_state


@dataclass(frozen=True)
class CanonicalEntry:
    topic: str
    path: str
    section: str
    verification: str


@dataclass(frozen=True)
class ResultEntry:
    result_id: str
    path: str
    kind: str
    audience: str
    producer: str


@dataclass
class ValidationReport:
    errors: list[str]
    warnings: list[str]
    state: str = PROJECT_V3

    @property
    def ok(self) -> bool:
        return self.state == PROJECT_V3 and not self.errors


@dataclass(frozen=True)
class MigrationResult:
    state: str
    decision_memories: int = 0
    attention_entries: int = 0
    reviewed_files: int = 0


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
    root: Path,
    raw_path: str,
    label: str,
    *,
    must_exist: bool = True,
) -> tuple[Path, str]:
    root = root.expanduser().resolve()
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ProjectError(f"{label} must stay inside the project: {raw_path}") from exc
    resolved = candidate.resolve()
    allowed_roots = [root]
    overlay = _MIGRATION_OVERLAY.get()
    if overlay is not None and overlay[0] == root:
        allowed_roots.append(overlay[1])
    if not any(
        resolved == allowed or allowed in resolved.parents for allowed in allowed_roots
    ):
        raise ProjectError(f"{label} must stay inside the project: {raw_path}")
    if must_exist and not candidate.exists():
        raise ProjectError(f"{label} does not exist: {relative.as_posix()}")
    return (candidate if overlay is not None and overlay[0] == root else resolved), relative.as_posix()


def path_resolves_within_project_view(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    allowed_roots = [root]
    overlay = _MIGRATION_OVERLAY.get()
    if overlay is not None and overlay[0] == root:
        allowed_roots.append(overlay[1])
    return any(
        resolved == allowed or allowed in resolved.parents for allowed in allowed_roots
    )


@contextmanager
def migration_overlay_view(candidate_root: Path, source_root: Path):
    candidate_root = candidate_root.expanduser().resolve()
    source_root = source_root.expanduser().resolve()
    token = _MIGRATION_OVERLAY.set((candidate_root, source_root))
    try:
        yield
    finally:
        _MIGRATION_OVERLAY.reset(token)


def detect_roles(root: Path, *, create_missing: bool) -> dict[str, Path]:
    root = root.expanduser().resolve()
    roles: dict[str, Path] = {}
    missing: list[tuple[str, str]] = []
    existing_directories = (
        {path.name: path for path in root.iterdir() if path.is_dir()}
        if root.is_dir()
        else {}
    )
    for role, aliases in ROLE_ALIASES.items():
        matches = [
            existing_directories[name]
            for name in aliases
            if name in existing_directories
        ]
        if len(matches) > 1:
            paths = ", ".join(path.name for path in matches)
            raise ProjectError(f"Ambiguous {role} directories: {paths}")
        if matches:
            if not path_resolves_within_project_view(matches[0], root):
                raise ProjectError(
                    f"{role} directory resolves outside the project: {matches[0]}"
                )
            roles[role] = matches[0]
        else:
            missing.append((role, aliases[0]))

    if create_missing:
        for role, preferred in missing:
            path = root / preferred
            path.mkdir(exist_ok=True)
            roles[role] = path
    return roles


def detect_optional_directory(
    root: Path, aliases: tuple[str, ...], label: str
) -> Path | None:
    if not root.is_dir():
        return None
    existing = {path.name: path for path in root.iterdir() if path.is_dir()}
    matches = [existing[name] for name in aliases if name in existing]
    if len(matches) > 1:
        paths = ", ".join(path.name for path in matches)
        raise ProjectError(f"Ambiguous {label} directories: {paths}")
    if matches:
        try:
            matches[0].resolve().relative_to(root)
        except ValueError as exc:
            raise ProjectError(
                f"{label} directory resolves outside the project: {matches[0]}"
            ) from exc
    return matches[0] if matches else None


def markdown_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    if not rows:
        return "_None registered._"

    def clean(value: str) -> str:
        return value.replace("|", "&#124;").replace("\n", " ")

    header = "| " + " | ".join(clean(value) for value in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(clean(value) if value else "-" for value in row) + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def parse_markdown_table(body: str, width: int, label: str) -> list[tuple[str, ...]]:
    table_lines = [
        line.strip() for line in body.splitlines() if line.strip().startswith("|")
    ]
    if not table_lines:
        return []
    if len(table_lines) < 2:
        raise ProjectError(f"Malformed {label} table")
    rows: list[tuple[str, ...]] = []
    for line in table_lines[2:]:
        values = tuple(value.strip() for value in line.strip("|").split("|"))
        if len(values) != width:
            raise ProjectError(f"Malformed {label} row: {line}")
        rows.append(tuple("" if value == "-" else value.strip("`") for value in values))
    return rows


def extract_block(text: str, start: str, end: str, label: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise ProjectError(
            f"project.md must contain exactly one managed {label} block; refusing to append "
            "or guess a migration"
        )
    start_index = text.index(start) + len(start)
    end_index = text.index(end)
    if end_index < start_index:
        raise ProjectError(f"Managed {label} block markers are out of order")
    return text[start_index:end_index].strip()


def replace_block(text: str, start: str, end: str, body: str, label: str) -> str:
    extract_block(text, start, end, label)
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    replacement = f"{start}\n{body}\n{end}"
    return pattern.sub(lambda _: replacement, text, count=1)


def atomic_write(path: Path, text: str) -> None:
    staging_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.stepwise-staging-",
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


@contextmanager
def project_write_lock(root: Path):
    if fcntl is None:
        yield
        return
    lock_root = Path(tempfile.gettempdir()) / "stepwise-r-project-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_key = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()
    lock_path = lock_root / f"{lock_key}.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
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


def result_artifact_error(path: Path, results_dir: Path) -> str | None:
    if path.suffix.lower() not in ALLOWED_RESULT_SUFFIXES:
        return "non-human artifact type"
    try:
        relative = path.relative_to(results_dir)
    except ValueError:
        return "artifact outside the active Results directory"
    if any(
        FORBIDDEN_RESULT_TOKEN.search(part) or EXECUTION_RESULT_TOKEN.search(part)
        for part in relative.parts
    ):
        return "machine/obsolete artifact"
    return None


def result_kind_error(path: Path, kind: str) -> str | None:
    allowed = RESULT_KIND_SUFFIXES.get(kind)
    if allowed is not None and path.suffix.lower() not in allowed:
        expected = ", ".join(sorted(allowed))
        return f"kind {kind!r} requires one of: {expected}"
    return None


def result_producer_error(path: Path, r_dir: Path) -> str | None:
    if not path.is_file():
        return "producer must be a file"
    try:
        path.relative_to(r_dir)
    except ValueError:
        return "producer must be inside the active R directory"
    if path.suffix.lower() != ".r":
        return "producer must be an R script"
    return None


def contract_test_error(path: Path) -> str | None:
    if not path.is_file():
        return "contract test must be a file"
    if path.suffix.lower() not in ALLOWED_CONTRACT_TEST_SUFFIXES:
        expected = ", ".join(sorted(ALLOWED_CONTRACT_TEST_SUFFIXES))
        return f"contract test must use one of: {expected}"
    if (
        path.stat().st_size == 0
        or not path.read_text(encoding="utf-8", errors="replace").strip()
    ):
        return "contract test cannot be empty"
    return None


def source_defines_r_function(path: Path, function_name: str) -> bool:
    escaped = re.escape(function_name)
    pattern = re.compile(
        rf"^\s*(?:`{escaped}`|{escaped})\s*(?:<-|=)\s*function\s*\(",
        re.MULTILINE,
    )
    content = path.read_text(encoding="utf-8", errors="replace")
    return bool(pattern.search(content))


def role_table(root: Path, roles: dict[str, Path]) -> str:
    descriptions = {
        "R": "Human-readable R scripts",
        "Data": "Raw or derived data; do not overwrite raw inputs",
        "Results": "Current publication or formal-review deliverables only",
        "Audit": "Current machine QA and high-risk function audits",
    }
    rows = [
        (role, path.relative_to(root).as_posix(), descriptions[role])
        for role, path in roles.items()
    ]
    return markdown_table(("Role", "Path", "Purpose"), rows)


def managed_navigation_table() -> str:
    return markdown_table(
        ("System", "Index", "Purpose"),
        [
            (
                "Human Attention",
                "Attention/index.md",
                "Active material issues requiring human awareness or decision",
            ),
            (
                "Decision Memory",
                "Memory/index.md",
                "Causal history of consequential decisions",
            ),
        ],
    )


def project_md_template(root: Path, roles: dict[str, Path]) -> str:
    return f"""# Project Map

{SCHEMA_MARKER}

Keep this file limited to the current project state and ownership map. Git stores history.

## Managed Navigation

{NAVIGATION_START}
{managed_navigation_table()}
{NAVIGATION_END}

## Directory Roles

{ROLE_START}
{role_table(root, roles)}
{ROLE_END}

## Canonical Sources

{CANONICAL_START}
_None registered._
{CANONICAL_END}

## R Script Index

{SCRIPT_START}
_No R scripts found._
{SCRIPT_END}

## Current Results Deliverables

{RESULT_START}
_None registered._
{RESULT_END}

## High-Risk Function Audits

{FUNCTION_START}
_No high-risk function audits found._
{FUNCTION_END}
"""


def ensure_v3_project(root: Path, *, create: bool) -> tuple[Path, dict[str, Path]]:
    root = root.expanduser().resolve()
    project_file = root / "project.md"
    if project_file.exists():
        text = project_file.read_text(encoding="utf-8")
        if V2_SCHEMA_MARKER in text and SCHEMA_MARKER not in text:
            raise ProjectError(
                "Existing project.md is Stepwise R Project v2. Run migrate --check, review "
                "every legacy Memory, then run migrate --apply; init is not migration."
            )
        if SCHEMA_MARKER not in text:
            raise ProjectError(
                "Existing project.md is not Stepwise R Project v3. Run validate for a "
                "read-only migration report; automatic migration is intentionally disabled."
            )
    elif not create:
        raise ProjectError("project.md does not exist; run init first")

    if not root.exists():
        if not create:
            raise ProjectError(f"Project does not exist: {root}")
        root.mkdir(parents=True)

    roles = detect_roles(root, create_missing=create)
    missing_roles = [role for role in ROLE_ALIASES if role not in roles]
    if missing_roles:
        raise ProjectError(
            "Missing project role directories: " + ", ".join(missing_roles)
        )
    if not project_file.exists():
        atomic_write(project_file, project_md_template(root, roles))
    ensure_managed_topology(root)
    return project_file, roles


def ensure_v2_project(root: Path, *, create: bool) -> tuple[Path, dict[str, Path]]:
    """Compatibility alias retained for callers of the v2 helper API."""
    return ensure_v3_project(root, create=create)


def first_comment(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[:40]:
        stripped = line.strip()
        if stripped.startswith("#'"):
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return "No leading description"


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
            decoded = json.loads(raw)
            metadata[key.strip()] = str(decoded)
        except (json.JSONDecodeError, TypeError):
            metadata[key.strip()] = raw.strip('"')
    return metadata


def render_script_index(root: Path, r_dir: Path) -> str:
    scripts = sorted(r_dir.rglob("*.R"))
    rows = [
        (script.relative_to(root).as_posix(), first_comment(script))
        for script in scripts
    ]
    return markdown_table(("Script", "Description"), rows)


def render_function_index(root: Path, audit_dir: Path) -> str:
    function_dir = audit_dir / "Functions"
    if not function_dir.exists():
        return "_No high-risk function audits found._"
    rows: list[tuple[str, ...]] = []
    for audit in sorted(function_dir.glob("*.Rmd")):
        metadata = parse_frontmatter(audit)
        rows.append(
            (
                metadata.get("stepwise_function", audit.stem.removeprefix("audit_")),
                audit.relative_to(root).as_posix(),
                metadata.get("source", "UNKNOWN"),
                metadata.get("risk_reason", "UNKNOWN"),
            )
        )
    return markdown_table(("Function", "Audit", "Source", "Risk reason"), rows)


def _refresh_index_unlocked(root: Path) -> Path:
    root = root.expanduser().resolve()
    project_file, roles = ensure_v3_project(root, create=False)
    text = project_file.read_text(encoding="utf-8")
    if LEGACY_MEMORY_START in text or LEGACY_MEMORY_END in text:
        raise ProjectError(
            "Legacy Memory index detected. Remove it during an explicit v2 migration; index "
            "will not silently rewrite project history."
        )
    text = replace_block(text, ROLE_START, ROLE_END, role_table(root, roles), "role")
    text = replace_block(
        text,
        NAVIGATION_START,
        NAVIGATION_END,
        managed_navigation_table(),
        "managed navigation",
    )
    canonical_entries = parse_canonical_entries(text)
    text = replace_block(
        text,
        CANONICAL_START,
        CANONICAL_END,
        render_canonical_entries(canonical_entries),
        "canonical source",
    )
    result_entries = parse_result_entries(text)
    text = replace_block(
        text,
        RESULT_START,
        RESULT_END,
        render_result_entries(result_entries),
        "result registry",
    )
    text = replace_block(
        text,
        SCRIPT_START,
        SCRIPT_END,
        render_script_index(root, roles["R"]),
        "script index",
    )
    text = replace_block(
        text,
        FUNCTION_START,
        FUNCTION_END,
        render_function_index(root, roles["Audit"]),
        "function audit index",
    )
    atomic_write(project_file, text.rstrip() + "\n")
    refresh_managed_indexes_unlocked(root)
    return project_file


def refresh_index(root: Path) -> Path:
    root = root.expanduser().resolve()
    with project_write_lock(root):
        return _refresh_index_unlocked(root)


def parse_canonical_entries(text: str) -> list[CanonicalEntry]:
    body = extract_block(text, CANONICAL_START, CANONICAL_END, "canonical source")
    rows = parse_markdown_table(body, 4, "canonical source")
    return [CanonicalEntry(*row) for row in rows]


def render_canonical_entries(entries: list[CanonicalEntry]) -> str:
    rows = [
        (entry.topic, entry.path, entry.section or "-", entry.verification)
        for entry in sorted(entries, key=lambda item: item.topic)
    ]
    return markdown_table(("Topic", "Canonical path", "Section", "Contract test"), rows)


def parse_result_entries(text: str) -> list[ResultEntry]:
    body = extract_block(text, RESULT_START, RESULT_END, "result registry")
    rows = parse_markdown_table(body, 5, "result registry")
    return [ResultEntry(*row) for row in rows]


def render_result_entries(entries: list[ResultEntry]) -> str:
    rows = [
        (entry.result_id, entry.path, entry.kind, entry.audience, entry.producer)
        for entry in sorted(entries, key=lambda item: item.result_id)
    ]
    return markdown_table(
        ("ID", "Path", "Kind", "Audience", "Producer"),
        rows,
    )


def register_canonical(
    root: Path,
    topic: str,
    path: str,
    section: str | None,
    verification: str,
    *,
    replace: bool,
) -> Path:
    root = root.expanduser().resolve()
    project_file, _ = ensure_v2_project(root, create=False)
    topic = validate_key(topic, "topic")
    canonical_path, canonical_rel = resolve_project_path(root, path, "canonical path")
    if not canonical_path.is_file():
        raise ProjectError(f"Canonical source must be a file: {canonical_rel}")
    if canonical_path.suffix.lower() not in {".md", ".qmd", ".rmd"}:
        raise ProjectError(
            "Canonical sources must be Markdown, Quarto Markdown, or R Markdown"
        )
    verification_path, verification_rel = resolve_project_path(
        root,
        verification,
        "contract test",
    )
    verification_error = contract_test_error(verification_path)
    if verification_error:
        raise ProjectError(
            f"Invalid canonical contract test {verification_rel}: {verification_error}"
        )
    section_value = validate_table_value(section, "section") if section else ""
    if section_value:
        content = canonical_path.read_text(encoding="utf-8", errors="replace")
        heading = re.compile(
            rf"^#{{1,6}}\s+{re.escape(section_value)}\s*$",
            re.MULTILINE,
        )
        if not heading.search(content):
            raise ProjectError(
                f"Canonical section not found in {canonical_rel}: {section_value}"
            )

    with project_write_lock(root):
        text = project_file.read_text(encoding="utf-8")
        entries = parse_canonical_entries(text)
        new_entry = CanonicalEntry(
            topic, canonical_rel, section_value, verification_rel
        )
        matches = [entry for entry in entries if entry.topic == topic]
        if matches:
            if len(matches) > 1:
                raise ProjectError(f"Duplicate canonical topic already exists: {topic}")
            current = matches[0]
            if current == new_entry:
                return project_file
            if current.path != canonical_rel and not replace:
                raise ProjectError(
                    f"Canonical topic {topic!r} already exists with a different owner; use "
                    "--replace only after explicitly resolving the ownership change"
                )
            entries = [entry for entry in entries if entry.topic != topic]
        entries.append(new_entry)
        updated = replace_block(
            text,
            CANONICAL_START,
            CANONICAL_END,
            render_canonical_entries(entries),
            "canonical source",
        )
        atomic_write(project_file, updated.rstrip() + "\n")
    return project_file


def markdown_section(content: str, section: str) -> str:
    """Return one Markdown heading section, including all nested subsections."""
    heading = re.compile(
        rf"^(#{{1,6}})\s+{re.escape(section)}\s*$",
        re.MULTILINE,
    )
    match = heading.search(content)
    if not match:
        raise ProjectError(f"Markdown section not found: {section}")
    level = len(match.group(1))
    next_heading = re.compile(rf"^#{{1,{level}}}\s+", re.MULTILINE)
    next_match = next_heading.search(content, match.end())
    end = next_match.start() if next_match else len(content)
    return content[match.start() : end]


def required_section_error(content: str, section: str) -> str | None:
    heading = re.compile(rf"^#{{1,6}}\s+{re.escape(section)}\s*$", re.MULTILINE)
    matches = list(heading.finditer(content))
    if len(matches) != 1:
        return f"requires exactly one {section!r} section"
    section_text = markdown_section(content, section)
    body = section_text.split("\n", 1)[1].strip() if "\n" in section_text else ""
    if not body:
        return f"section {section!r} is empty"
    return None


def required_labeled_field_error(content: str, label: str) -> str | None:
    pattern = re.compile(rf"^-\s*{re.escape(label)}:\s*(\S.+|\S)\s*$", re.MULTILINE)
    if not pattern.search(content):
        return f"field {label!r} is missing or empty"
    return None


def authoritative_markdown_text(content: str) -> str:
    kept: list[str] = []
    fence: str | None = None
    in_comment = False
    for line in content.splitlines():
        stripped = line.lstrip()
        if fence is not None:
            if stripped.startswith(fence):
                fence = None
            continue
        if stripped.startswith("```"):
            fence = "```"
            continue
        if stripped.startswith("~~~"):
            fence = "~~~"
            continue
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if "<!--" in line:
            if "-->" not in line.split("<!--", 1)[1]:
                in_comment = True
            line = line.split("<!--", 1)[0]
            stripped = line.lstrip()
        if stripped.startswith(">"):
            continue
        kept.append(line)
    return "\n".join(kept)


def contract_status_values(content: str) -> tuple[list[str], list[str]]:
    aliases = {
        "draft": "draft",
        "草稿": "draft",
        "partially-frozen": "partially-frozen",
        "部分冻结": "partially-frozen",
        "frozen": "frozen",
        "已冻结": "frozen",
    }
    normalized: list[str] = []
    invalid: list[str] = []
    authoritative = authoritative_markdown_text(content)
    for raw in re.findall(
        r"^(?:状态|Status)\s*[:：]\s*(.+?)\s*$",
        authoritative,
        re.IGNORECASE | re.MULTILINE,
    ):
        cleaned = raw.strip().strip("`*_").strip().lower()
        value = aliases.get(cleaned)
        if value is None:
            invalid.append(raw.strip())
        else:
            normalized.append(value)
    return normalized, invalid


def register_result(
    root: Path,
    result_id: str,
    path: str,
    kind: str,
    audience: str,
    producer: str,
    *,
    replace: bool,
) -> Path:
    root = root.expanduser().resolve()
    project_file, roles = ensure_v2_project(root, create=False)
    result_id = validate_key(result_id, "result id")
    result_path, result_rel = resolve_project_path(root, path, "result path")
    try:
        result_path.relative_to(roles["Results"].resolve())
    except ValueError as exc:
        raise ProjectError(
            "Registered result must be inside the active Results directory"
        ) from exc
    if not result_path.is_file():
        raise ProjectError(f"Registered result must be a file: {result_rel}")
    if kind not in RESULT_KINDS:
        raise ProjectError(f"Invalid result kind: {kind}")
    if audience not in RESULT_AUDIENCES:
        raise ProjectError(f"Invalid result audience: {audience}")
    artifact_error = result_artifact_error(result_path, roles["Results"].resolve())
    if artifact_error:
        raise ProjectError(f"Registered result is a {artifact_error}: {result_rel}")
    kind_error = result_kind_error(result_path, kind)
    if kind_error:
        raise ProjectError(f"Registered result has incompatible metadata: {kind_error}")
    producer_path, producer_rel = resolve_project_path(
        root, producer, "result producer"
    )
    producer_error = result_producer_error(producer_path, roles["R"].resolve())
    if producer_error:
        raise ProjectError(f"Invalid result producer {producer_rel}: {producer_error}")
    with project_write_lock(root):
        text = project_file.read_text(encoding="utf-8")
        entries = parse_result_entries(text)
        new_entry = ResultEntry(result_id, result_rel, kind, audience, producer_rel)
        matches = [entry for entry in entries if entry.result_id == result_id]
        if matches:
            if len(matches) > 1:
                raise ProjectError(f"Duplicate result id already exists: {result_id}")
            current = matches[0]
            if current == new_entry:
                return project_file
            if current.path != result_rel and not replace:
                raise ProjectError(
                    f"Result id {result_id!r} already points to a different path; use "
                    "--replace only after resolving the deliverable move"
                )
            entries = [entry for entry in entries if entry.result_id != result_id]
        entries.append(new_entry)
        updated = replace_block(
            text,
            RESULT_START,
            RESULT_END,
            render_result_entries(entries),
            "result registry",
        )
        atomic_write(project_file, updated.rstrip() + "\n")
    return project_file


def load_json_payload(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProjectError(f"Cannot read structured payload: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectError(f"Invalid JSON payload {path}: {exc}") from exc


def require_payload_object(payload: object, label: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ProjectError(f"{label} payload must be a JSON object")
    return payload


def payload_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectError(f"{label} must be a non-empty string")
    cleaned = value.strip()
    if re.search(r"^#{1,6}\s+", cleaned, re.MULTILINE):
        raise ProjectError(f"{label} cannot contain Markdown headings")
    return cleaned


def payload_string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ProjectError(f"{label} must be an array of strings")
    cleaned = [item.strip() for item in value]
    if any(not item for item in cleaned):
        raise ProjectError(f"{label} cannot contain empty values")
    if len(cleaned) != len(set(cleaned)):
        raise ProjectError(f"{label} cannot contain duplicates")
    return cleaned


def validate_exact_payload_keys(
    payload: dict[str, object], required: set[str], optional: set[str], label: str
) -> None:
    missing = sorted(required - payload.keys())
    unexpected = sorted(payload.keys() - required - optional)
    if missing:
        raise ProjectError(f"{label} payload is missing fields: {', '.join(missing)}")
    if unexpected:
        raise ProjectError(
            f"{label} payload has unexpected fields: {', '.join(unexpected)}"
        )


def normalize_attention_payload(payload: object) -> dict[str, object]:
    data = require_payload_object(payload, "Attention")
    required = {
        "title",
        "blocking",
        "observation",
        "evidence",
        "why_it_matters",
        "why_no_action_was_taken",
        "human_decision_needed",
    }
    validate_exact_payload_keys(data, required, set(), "Attention")
    if type(data["blocking"]) is not bool:
        raise ProjectError("Attention blocking must be true or false")
    return {
        "Title": payload_text(data["title"], "Attention title"),
        "Blocking": data["blocking"],
        "Observation": payload_text(data["observation"], "Attention observation"),
        "Evidence": payload_text(data["evidence"], "Attention evidence"),
        "Why It Matters": payload_text(
            data["why_it_matters"], "Attention why_it_matters"
        ),
        "Why No Action Was Taken": payload_text(
            data["why_no_action_was_taken"],
            "Attention why_no_action_was_taken",
        ),
        "Human Decision Needed": payload_text(
            data["human_decision_needed"], "Attention human_decision_needed"
        ),
    }


def normalize_memory_payload(payload: object) -> dict[str, object]:
    data = require_payload_object(payload, "Decision Memory")
    required = {
        "title",
        "before",
        "trigger",
        "decision",
        "scientific_or_technical_rationale",
        "basis",
        "rejected_or_prior_approach",
        "consequence",
    }
    optional = {"related_topics", "supersedes", "invalidates"}
    validate_exact_payload_keys(data, required, optional, "Decision Memory")
    related_topics = payload_string_list(
        data.get("related_topics", []), "Decision Memory related_topics"
    )
    for topic in related_topics:
        validate_key(topic, "related topic")
    supersedes = payload_string_list(
        data.get("supersedes", []), "Decision Memory supersedes"
    )
    invalidates = payload_string_list(
        data.get("invalidates", []), "Decision Memory invalidates"
    )
    overlap = sorted(set(supersedes) & set(invalidates))
    if overlap:
        raise ProjectError(
            "Decision Memory cannot both supersede and invalidate: " + ", ".join(overlap)
        )
    for relation_id in (*supersedes, *invalidates):
        if not valid_managed_id(relation_id, "M"):
            raise ProjectError(f"Invalid Decision Memory relationship ID: {relation_id}")
    return {
        "Title": payload_text(data["title"], "Decision Memory title"),
        "Related Topics": related_topics,
        "Supersedes": supersedes,
        "Invalidates": invalidates,
        "Before": payload_text(data["before"], "Decision Memory before"),
        "Trigger": payload_text(data["trigger"], "Decision Memory trigger"),
        "Decision": payload_text(data["decision"], "Decision Memory decision"),
        "Scientific or Technical Rationale": payload_text(
            data["scientific_or_technical_rationale"],
            "Decision Memory scientific_or_technical_rationale",
        ),
        "Basis": payload_text(data["basis"], "Decision Memory basis"),
        "Rejected or Prior Approach": payload_text(
            data["rejected_or_prior_approach"],
            "Decision Memory rejected_or_prior_approach",
        ),
        "Consequence": payload_text(
            data["consequence"], "Decision Memory consequence"
        ),
    }


def render_managed_entry(fields: tuple[str, ...], values: dict[str, object]) -> str:
    parts: list[str] = []
    for field in fields:
        value = values[field]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, list):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = str(value)
        parts.append(f"## {field}\n\n{rendered}")
    return "\n\n".join(parts) + "\n"


def parse_managed_entry(
    path: Path, fields: tuple[str, ...], label: str
) -> dict[str, str]:
    content = path.read_text(encoding="utf-8", errors="replace")
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", content, re.MULTILINE))
    all_headings = list(re.finditer(r"^#{1,6}\s+(.+?)\s*$", content, re.MULTILINE))
    headings = [match.group(1) for match in matches]
    if (
        headings != list(fields)
        or len(all_headings) != len(matches)
        or (matches and content[: matches[0].start()].strip())
    ):
        raise ProjectError(
            f"{label} must contain exactly the fixed fields in order: {path.name}"
        )
    values: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        values[match.group(1)] = content[start:end].strip()
    return values


def parse_json_list_field(value: str, label: str) -> list[str]:
    try:
        return payload_string_list(json.loads(value), label)
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{label} must be a JSON array") from exc


def managed_paths(root: Path, system: str) -> tuple[Path, Path, Path]:
    directory = root / system
    return directory, directory / "index.md", directory / ENTRY_DIRECTORY


def valid_managed_id(value: str, prefix: str) -> bool:
    pattern = MEMORY_ID_PATTERN if prefix == "M" else ATTENTION_ID_PATTERN
    if not pattern.fullmatch(value):
        return False
    number = int(value.split("-", 1)[1])
    return number > 0 and value == f"{prefix}-{number:04d}"


def ensure_managed_topology(root: Path) -> None:
    actual_directory_names = {
        path.name for path in root.iterdir() if path.is_dir()
    } if root.is_dir() else set()
    invalid_case_names = actual_directory_names & {"memory", "attention"}
    if invalid_case_names:
        raise ProjectError(
            "Legacy lowercase managed topology exists: "
            + ", ".join(sorted(invalid_case_names))
            + ". Use migrate --check for memory/; v3 requires exact Memory/ and Attention/."
        )
    for system in (MEMORY_DIRECTORY, ATTENTION_DIRECTORY):
        directory, index_path, entries_dir = managed_paths(root, system)
        directory.mkdir(exist_ok=True)
        entries_dir.mkdir(exist_ok=True)
        if not index_path.exists():
            atomic_write(index_path, render_memory_index(root) if system == MEMORY_DIRECTORY else render_attention_index(root))


def entry_paths(root: Path, system: str) -> list[Path]:
    _, _, entries_dir = managed_paths(root, system)
    return sorted(entries_dir.glob("*.md")) if entries_dir.is_dir() else []


def allocate_entry_id(paths: list[Path], prefix: str) -> str:
    numbers = [
        int(path.stem.split("-", 1)[1])
        for path in paths
        if valid_managed_id(path.stem, prefix)
    ]
    return f"{prefix}-{max(numbers, default=0) + 1:04d}"


def render_attention_index(root: Path) -> str:
    rows: list[tuple[str, ...]] = []
    for path in entry_paths(root, ATTENTION_DIRECTORY):
        try:
            values = parse_managed_entry(path, ATTENTION_FIELDS, "Attention entry")
        except ProjectError:
            continue
        rows.append(
            (
                values["ID"],
                values["Blocking"],
                values["Title"],
                f"entries/{path.name}",
            )
        )
    table = markdown_table(
        ("ID", "Blocking", "Title", "Path"),
        sorted(rows, key=lambda row: row[0]),
    )
    return "# Human Attention\n\nActive material issues only. Git preserves resolved history.\n\n" + table + "\n"


def render_memory_index(root: Path) -> str:
    rows: list[tuple[str, ...]] = []
    for path in entry_paths(root, MEMORY_DIRECTORY):
        try:
            values = parse_managed_entry(path, MEMORY_FIELDS, "Decision Memory entry")
        except ProjectError:
            continue
        rows.append(
            (
                values["ID"],
                values["Status"],
                values["Title"],
                values["Related Topics"],
                f"entries/{path.name}",
            )
        )
    table = markdown_table(
        ("ID", "Status", "Title", "Related Topics", "Path"),
        sorted(rows, key=lambda row: row[0]),
    )
    return "# Decision Memory\n\nConsequential causal decision history only.\n\n" + table + "\n"


def refresh_managed_indexes_unlocked(root: Path) -> None:
    _, memory_index, _ = managed_paths(root, MEMORY_DIRECTORY)
    _, attention_index, _ = managed_paths(root, ATTENTION_DIRECTORY)
    atomic_write(memory_index, render_memory_index(root))
    atomic_write(attention_index, render_attention_index(root))


def add_attention(root: Path, payload: object) -> Path:
    root = root.expanduser().resolve()
    ensure_v3_project(root, create=False)
    normalized = normalize_attention_payload(payload)
    with project_write_lock(root):
        ensure_managed_topology(root)
        paths = entry_paths(root, ATTENTION_DIRECTORY)
        for path in paths:
            current = parse_managed_entry(path, ATTENTION_FIELDS, "Attention entry")
            if current["Title"].casefold() == str(normalized["Title"]).casefold():
                raise ProjectError(f"Equivalent active Attention already exists: {current['ID']}")
        attention_id = allocate_entry_id(paths, "A")
        values = {"ID": attention_id, **normalized}
        _, _, entries_dir = managed_paths(root, ATTENTION_DIRECTORY)
        destination = entries_dir / f"{attention_id}.md"
        atomic_write(destination, render_managed_entry(ATTENTION_FIELDS, values))
        refresh_managed_indexes_unlocked(root)
    return destination


def resolve_attention(root: Path, attention_id: str) -> Path:
    root = root.expanduser().resolve()
    ensure_v3_project(root, create=False)
    if not valid_managed_id(attention_id, "A"):
        raise ProjectError(f"Invalid Attention ID: {attention_id}")
    with project_write_lock(root):
        _, _, entries_dir = managed_paths(root, ATTENTION_DIRECTORY)
        path = entries_dir / f"{attention_id}.md"
        if not path.is_file():
            raise ProjectError(f"Active Attention does not exist: {attention_id}")
        path.unlink()
        refresh_managed_indexes_unlocked(root)
    return path


def add_decision_memory(root: Path, payload: object) -> Path:
    root = root.expanduser().resolve()
    project_file, _ = ensure_v3_project(root, create=False)
    normalized = normalize_memory_payload(payload)
    with project_write_lock(root):
        ensure_managed_topology(root)
        project_text = project_file.read_text(encoding="utf-8")
        registered_topics = {entry.topic for entry in parse_canonical_entries(project_text)}
        unknown_topics = sorted(set(normalized["Related Topics"]) - registered_topics)
        if unknown_topics:
            raise ProjectError(
                "Decision Memory references unregistered related topics: "
                + ", ".join(unknown_topics)
            )
        paths = entry_paths(root, MEMORY_DIRECTORY)
        entries: dict[str, tuple[Path, dict[str, str]]] = {}
        for path in paths:
            values = parse_managed_entry(path, MEMORY_FIELDS, "Decision Memory entry")
            entries[values["ID"]] = (path, values)
        relation_ids = [*normalized["Supersedes"], *normalized["Invalidates"]]
        missing = sorted(set(relation_ids) - entries.keys())
        if missing:
            raise ProjectError(
                "Decision Memory relationship targets do not exist: " + ", ".join(missing)
            )
        for relation_id in relation_ids:
            prior = entries[relation_id][1]
            if prior["Status"] != "active":
                raise ProjectError(
                    f"Decision Memory relationship target is not active: {relation_id}"
                )
        memory_id = allocate_entry_id(paths, "M")
        for field, status, reverse_field in (
            ("Supersedes", "superseded", "Superseded By"),
            ("Invalidates", "invalidated", "Invalidated By"),
        ):
            for relation_id in normalized[field]:
                prior_path, prior = entries[relation_id]
                prior["Status"] = status
                prior[reverse_field] = json.dumps([memory_id])
                typed_prior: dict[str, object] = dict(prior)
                for list_field in (
                    "Related Topics",
                    "Supersedes",
                    "Invalidates",
                    "Superseded By",
                    "Invalidated By",
                ):
                    typed_prior[list_field] = parse_json_list_field(
                        prior[list_field], f"{relation_id} {list_field}"
                    )
                atomic_write(
                    prior_path, render_managed_entry(MEMORY_FIELDS, typed_prior)
                )
        values = {
            "ID": memory_id,
            "Status": "active",
            "Superseded By": [],
            "Invalidated By": [],
            **normalized,
        }
        _, _, entries_dir = managed_paths(root, MEMORY_DIRECTORY)
        destination = entries_dir / f"{memory_id}.md"
        atomic_write(destination, render_managed_entry(MEMORY_FIELDS, values))
        refresh_managed_indexes_unlocked(root)
    return destination


def create_or_reuse_memory(*args: object, **kwargs: object) -> tuple[Path, str]:
    raise ProjectError(
        "The v2 task-key Memory API is retired. Use memory add TARGET --input TEMP_JSON."
    )


def project_relative_git_path(
    repository_root: Path, project_root: Path, raw_path: str
) -> str | None:
    candidate = repository_root / raw_path
    try:
        return candidate.relative_to(project_root).as_posix()
    except ValueError:
        return None


def parse_git_porcelain_z(
    output: bytes, repository_root: Path, project_root: Path
) -> tuple[list[str], dict[str, str]]:
    records = output.split(b"\0")
    paths: dict[str, str] = {}
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        decoded = record.decode("utf-8", errors="surrogateescape")
        if len(decoded) < 4 or decoded[2] != " ":
            continue
        status = decoded[:2]
        raw_paths = [decoded[3:]]
        if "R" in status or "C" in status:
            if index < len(records) and records[index]:
                raw_paths.append(
                    records[index].decode("utf-8", errors="surrogateescape")
                )
                index += 1
        for raw_path in raw_paths:
            relative = project_relative_git_path(
                repository_root, project_root, raw_path
            )
            if relative is not None:
                paths[relative] = status
    dirty_paths = sorted(paths)
    return dirty_paths, {path: paths[path] for path in dirty_paths}


def git_migration_status(root: Path) -> dict[str, object]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        repository = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
    except OSError:
        return {
            "repository": False,
            "clean": None,
            "root": None,
            "changes": [],
            "dirty_paths": [],
            "path_statuses": {},
        }
    if repository.returncode != 0:
        return {
            "repository": False,
            "clean": None,
            "root": None,
            "changes": [],
            "dirty_paths": [],
            "path_statuses": {},
        }
    repository_root = Path(repository.stdout.strip()).resolve()
    try:
        relative = root.relative_to(repository_root)
    except ValueError:
        return {
            "repository": False,
            "clean": None,
            "root": None,
            "changes": [],
            "dirty_paths": [],
            "path_statuses": {},
        }
    pathspec = "." if relative == Path(".") else relative.as_posix()
    status = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            pathspec,
        ],
        check=False,
        capture_output=True,
        env=environment,
    )
    if status.returncode != 0:
        return {
            "repository": True,
            "clean": False,
            "root": str(repository_root),
            "changes": ["Git status failed"],
            "dirty_paths": [],
            "path_statuses": {},
            "error": status.stderr.decode("utf-8", errors="replace").strip(),
        }
    dirty_paths, path_statuses = parse_git_porcelain_z(
        status.stdout, repository_root, root
    )
    changes = [f"{path_statuses[path]} {path}" for path in dirty_paths]
    return {
        "repository": True,
        "clean": not changes,
        "root": str(repository_root),
        "changes": changes,
        "dirty_paths": dirty_paths,
        "path_statuses": path_statuses,
    }


def path_overlaps_migration_write_set(path: str) -> bool:
    parts = Path(path).parts
    if not parts:
        return False
    return path == "project.md" or parts[0].casefold() in {"memory", "attention"}


def path_snapshot(path: Path) -> dict[str, object]:
    if path.is_symlink():
        return {"kind": "symlink", "target": os.readlink(path)}
    if path.is_file():
        return {
            "kind": "file",
            "size": path.stat().st_size,
            "sha256": file_sha256(path),
        }
    if path.is_dir():
        return {"kind": "directory"}
    return {"kind": "missing"}


def snapshot_project_paths(root: Path, paths: list[str]) -> dict[str, dict[str, object]]:
    return {path: path_snapshot(root / path) for path in paths}


def verify_unrelated_dirty_state(
    root: Path,
    paths: list[str],
    before_content: dict[str, dict[str, object]],
    before_statuses: dict[str, str],
) -> None:
    after_content = snapshot_project_paths(root, paths)
    if after_content != before_content:
        changed = sorted(
            path
            for path in paths
            if before_content.get(path) != after_content.get(path)
        )
        raise ProjectError(
            "Migration changed unrelated dirty paths: " + ", ".join(changed)
        )
    after_git = git_migration_status(root)
    if after_git["repository"]:
        after_statuses = after_git["path_statuses"]
        changed_status = sorted(
            path
            for path in paths
            if before_statuses.get(path) != after_statuses.get(path)
        )
        if changed_status:
            raise ProjectError(
                "Migration changed Git state for unrelated dirty paths: "
                + ", ".join(changed_status)
            )


def audit_recovery_classification(
    root: Path,
    roles: dict[str, Path],
    result_entries: list[ResultEntry],
) -> dict[str, list[dict[str, object]]]:
    recoverable: list[dict[str, object]] = []
    ambiguous: list[dict[str, object]] = []
    if "Audit" not in roles:
        return {"recoverable": recoverable, "ambiguous": ambiguous}
    runs_dir = roles["Audit"] / "Runs"
    if not runs_dir.is_dir():
        return {"recoverable": recoverable, "ambiguous": ambiguous}
    result_paths = [Path(entry.path) for entry in result_entries]
    for entry in sorted(runs_dir.iterdir(), key=lambda path: path.name):
        if entry.name == ".DS_Store":
            continue
        if not entry.is_dir() or entry.is_symlink():
            ambiguous.append(
                {
                    "stage": None,
                    "path": entry.relative_to(root).as_posix(),
                    "reason": "Audit/Runs entry is not an ordinary stage directory",
                }
            )
            continue
        stage = entry
        children = sorted(
            (path for path in stage.iterdir() if path.name != ".DS_Store"),
            key=lambda path: path.name,
        )
        current = stage / "current"
        non_current = [path for path in children if path.name != "current"]
        for candidate in non_current:
            relative = candidate.relative_to(root)
            registered_conflict = any(
                result_path == relative or candidate == root / result_path
                or candidate in (root / result_path).parents
                for result_path in result_paths
            )
            has_unsafe_entry = candidate.is_symlink() or (
                candidate.is_dir()
                and any(
                    path.is_symlink() or not (path.is_file() or path.is_dir())
                    for path in candidate.rglob("*")
                )
            )
            if (
                candidate.is_dir()
                and RECOVERABLE_AUDIT_NAME.search(candidate.name)
                and not registered_conflict
                and not has_unsafe_entry
            ):
                recoverable.append(
                    {
                        "stage": stage.name,
                        "path": relative.as_posix(),
                        "recovery_command": (
                            f"audit-recover {root} --stage {stage.name}"
                        ),
                    }
                )
            else:
                reasons: list[str] = []
                if not candidate.is_dir() or candidate.is_symlink():
                    reasons.append("not an ordinary directory")
                if not RECOVERABLE_AUDIT_NAME.search(candidate.name):
                    reasons.append("name does not identify failed/incomplete staging")
                if registered_conflict:
                    reasons.append("overlaps a registered Result")
                if has_unsafe_entry:
                    reasons.append("contains a symlink or special entry")
                ambiguous.append(
                    {
                        "stage": stage.name,
                        "path": relative.as_posix(),
                        "reason": "; ".join(reasons),
                    }
                )
        if not current.exists() and not non_current:
            ambiguous.append(
                {
                    "stage": stage.name,
                    "path": stage.relative_to(root).as_posix(),
                    "reason": "empty Audit stage has no current output or recoverable residue",
                }
            )
        elif current.exists() and (not current.is_dir() or current.is_symlink()):
            ambiguous.append(
                {
                    "stage": stage.name,
                    "path": current.relative_to(root).as_posix(),
                    "reason": "current is not an ordinary directory",
                }
            )
    return {"recoverable": recoverable, "ambiguous": ambiguous}


def recovery_tree_integrity(paths: list[Path], base: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    file_count = 0
    total_size = 0
    for source in sorted(paths, key=lambda path: path.name):
        entries = [source, *sorted(source.rglob("*"))]
        for entry in entries:
            relative = entry.relative_to(base).as_posix()
            if entry.is_symlink() or not (entry.is_file() or entry.is_dir()):
                raise ProjectError(
                    f"Audit recovery source contains an unsafe entry: {entry}"
                )
            kind = b"D" if entry.is_dir() else b"F"
            digest.update(kind + b"\0" + relative.encode("utf-8") + b"\0")
            if entry.is_file():
                file_count += 1
                size = entry.stat().st_size
                total_size += size
                digest.update(str(size).encode("ascii") + b"\0")
                with entry.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
    return {
        "file_count": file_count,
        "total_bytes": total_size,
        "sha256": digest.hexdigest(),
    }


def _audit_recover_unlocked(
    root: Path,
    stage_name: str,
    *,
    failure_hook: object | None = None,
) -> dict[str, object]:
    root = root.expanduser().resolve()
    if (
        not stage_name
        or stage_name in {".", "..", "current"}
        or Path(stage_name).name != stage_name
        or "/" in stage_name
        or "\\" in stage_name
    ):
        raise ProjectError(f"Invalid Audit stage name: {stage_name!r}")
    marker_state = detect_project_marker_state(root)
    if marker_state not in {MIGRATION_REQUIRED, PROJECT_V3}:
        raise ProjectError("Audit recovery requires a recognized managed project")
    roles = detect_roles(root, create_missing=False)
    project_text = (root / "project.md").read_text(encoding="utf-8", errors="replace")
    result_entries = parse_result_entries(project_text)
    classification = audit_recovery_classification(root, roles, result_entries)
    ambiguous = [
        item for item in classification["ambiguous"] if item["stage"] == stage_name
    ]
    if ambiguous:
        details = "; ".join(
            f"{item['path']}: {item['reason']}" for item in ambiguous
        )
        raise ProjectError(
            "Audit recovery requires human review; no source was moved: " + details
        )
    candidates = [
        root / str(item["path"])
        for item in classification["recoverable"]
        if item["stage"] == stage_name
    ]
    if not candidates:
        raise ProjectError(
            f"Audit stage {stage_name!r} has no mechanically recoverable staging"
        )
    stage_dir = roles["Audit"] / "Runs" / stage_name
    source_integrity = recovery_tree_integrity(candidates, stage_dir)
    timestamp = datetime.now(timezone.utc)
    project_id = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    recovery_id = (
        timestamp.strftime("%Y%m%dT%H%M%S.%fZ")
        + "-"
        + str(source_integrity["sha256"])[:12]
    )
    recovery_parent = (
        Path(tempfile.gettempdir())
        / "stepwise-r-project-recovery"
        / project_id
        / stage_name
    )
    recovery_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = recovery_parent / recovery_id
    suffix = 1
    while destination.exists():
        destination = recovery_parent / f"{recovery_id}-{suffix}"
        suffix += 1
    destination.mkdir(mode=0o700)
    source_removal_started = False
    try:
        for source in candidates:
            shutil.copytree(source, destination / source.name, copy_function=shutil.copy2)
        if callable(failure_hook):
            failure_hook("after_copy")
        recovered_paths = [destination / source.name for source in candidates]
        recovered_integrity = recovery_tree_integrity(recovered_paths, destination)
        if recovered_integrity != source_integrity:
            raise ProjectError("Recovered Audit staging failed content verification")
        if callable(failure_hook):
            failure_hook("after_verification")
        manifest = {
            "original_project": str(root),
            "original_paths": [str(path) for path in candidates],
            "recovery_path": str(destination),
            "stage": stage_name,
            "recovery_timestamp": timestamp.isoformat(),
            "file_count": source_integrity["file_count"],
            "total_bytes": source_integrity["total_bytes"],
            "integrity": {"algorithm": "sha256", "tree": source_integrity["sha256"]},
        }
        (destination / "recovery-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if callable(failure_hook):
            failure_hook("before_source_removal")
        source_removal_started = True
        for source in candidates:
            shutil.rmtree(source)
        if not (stage_dir / "current").exists():
            (stage_dir / ".DS_Store").unlink(missing_ok=True)
            if not any(stage_dir.iterdir()):
                stage_dir.rmdir()
    except Exception as exc:
        if source_removal_started:
            try:
                for source in candidates:
                    recovered = destination / source.name
                    if source.exists():
                        shutil.rmtree(source)
                    shutil.copytree(recovered, source, copy_function=shutil.copy2)
                if recovery_tree_integrity(candidates, stage_dir) != source_integrity:
                    raise ProjectError("restored source failed integrity verification")
            except Exception as restore_exc:
                raise ProjectError(
                    "HARD BLOCKER: Audit recovery failed and source restoration could "
                    f"not be verified; recovery copy remains at {destination}: {restore_exc}"
                ) from exc
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return manifest


def audit_recover(
    root: Path,
    stage_name: str,
    *,
    failure_hook: object | None = None,
) -> dict[str, object]:
    root = root.expanduser().resolve()
    with project_write_lock(root):
        return _audit_recover_unlocked(
            root, stage_name, failure_hook=failure_hook
        )


def migration_preflight(root: Path) -> dict[str, object]:
    root = root.expanduser().resolve()
    marker_state = detect_project_marker_state(root)
    inventory: dict[str, object] = {
        "state": marker_state,
        "project_status": marker_state,
        "roles": {},
        "canonical_registrations": 0,
        "result_registrations": 0,
        "function_audits": 0,
        "audit_run_stages": [],
        "audit_staging_requiring_recovery": [],
        "legacy_memory_files": [],
        "migration_write_set": list(MIGRATION_WRITE_SET),
        "transaction_plan": migration_transaction_plan(root),
        "git": git_migration_status(root),
        "dirty_paths": [],
        "unrelated_dirty_paths": [],
        "dirty_write_set_overlaps": [],
        "recoverable_blockers": [],
        "structural_blockers": [],
        "warnings": [],
    }
    blockers: list[str] = inventory["structural_blockers"]  # type: ignore[assignment]
    recoverable_blockers: list[dict[str, object]] = inventory[
        "recoverable_blockers"
    ]  # type: ignore[assignment]
    warnings: list[str] = inventory["warnings"]  # type: ignore[assignment]
    if marker_state == PROJECT_V3:
        report = validate_project(root)
        blockers.extend(report.errors)
        if report.errors:
            inventory["state"] = PROJECT_DAMAGED
            inventory["project_status"] = PROJECT_DAMAGED
        return inventory
    if marker_state == PROJECT_UNMANAGED:
        blockers.append("Project is unmanaged; automatic migration is unsupported")
        return inventory
    if marker_state == PROJECT_DAMAGED:
        blockers.append("Managed project markers are ambiguous or damaged")
        return inventory

    report = validate_v2_project(root)
    blockers.extend(report.errors)
    warnings.extend(report.warnings)
    if report.errors:
        inventory["state"] = PROJECT_DAMAGED
        inventory["project_status"] = PROJECT_DAMAGED
    try:
        roles = detect_roles(root, create_missing=False)
        inventory["roles"] = {
            role: path.relative_to(root).as_posix()
            for role, path in sorted(roles.items())
        }
    except ProjectError as exc:
        blockers.append(str(exc))
        roles = {}
    project_file = root / "project.md"
    if project_file.is_file():
        text = project_file.read_text(encoding="utf-8", errors="replace")
        try:
            canonical_entries = parse_canonical_entries(text)
            inventory["canonical_registrations"] = len(canonical_entries)
        except ProjectError:
            canonical_entries = []
        try:
            result_entries = parse_result_entries(text)
            inventory["result_registrations"] = len(result_entries)
        except ProjectError:
            result_entries = []
    else:
        canonical_entries = []
        result_entries = []
    if "Audit" in roles:
        function_dir = roles["Audit"] / "Functions"
        inventory["function_audits"] = (
            len(list(function_dir.glob("*.Rmd"))) if function_dir.is_dir() else 0
        )
        runs_dir = roles["Audit"] / "Runs"
        inventory["audit_run_stages"] = (
            sorted(path.name for path in runs_dir.iterdir() if path.is_dir())
            if runs_dir.is_dir()
            else []
        )
        audit_classification = audit_recovery_classification(
            root, roles, result_entries
        )
        recoverable_audit = audit_classification["recoverable"]
        inventory["audit_staging_requiring_recovery"] = recoverable_audit
        stages: dict[str, list[str]] = {}
        for item in recoverable_audit:
            stages.setdefault(str(item["stage"]), []).append(str(item["path"]))
        for stage, paths in sorted(stages.items()):
            recoverable_blockers.append(
                {
                    "code": "MIGRATION_BLOCKED_AUDIT_STAGING",
                    "message": f"Audit stage {stage!r} contains recoverable failed staging",
                    "paths": sorted(paths),
                    "action": f"audit-recover {root} --stage {stage}",
                }
            )
    memory_files = validate_v2_memory(
        root, canonical_entries, ValidationReport(errors=[], warnings=[])
    )
    inventory["legacy_memory_files"] = [
        path.relative_to(root).as_posix() for path in memory_files
    ]
    git_state: dict[str, object] = inventory["git"]  # type: ignore[assignment]
    dirty_paths = list(git_state.get("dirty_paths", []))
    overlaps = [path for path in dirty_paths if path_overlaps_migration_write_set(path)]
    unrelated = [path for path in dirty_paths if path not in overlaps]
    inventory["dirty_paths"] = dirty_paths
    inventory["dirty_write_set_overlaps"] = overlaps
    inventory["unrelated_dirty_paths"] = unrelated
    if git_state["repository"] and git_state.get("error"):
        recoverable_blockers.append(
            {
                "code": "MIGRATION_BLOCKED_GIT_STATUS",
                "message": "Git status could not be read for the project write-set",
                "paths": [],
                "action": "Repair Git status access and rerun migrate --check",
            }
        )
    elif overlaps:
        recoverable_blockers.append(
            {
                "code": MIGRATION_BLOCKED_WORKTREE_OVERLAP,
                "message": "Dirty paths overlap the migration write-set",
                "paths": overlaps,
                "action": "Resolve or commit only the reported migration-controlled paths",
            }
        )
    elif not git_state["repository"]:
        warnings.append(
            "Project is not inside Git; migration will rely on transactional staging and rollback"
        )
    transaction_plan: dict[str, object] = inventory[
        "transaction_plan"
    ]  # type: ignore[assignment]
    unsafe_staging_paths = list(transaction_plan["unexpected_paths"])
    if unsafe_staging_paths:
        recoverable_blockers.append(
            {
                "code": MIGRATION_BLOCKED_UNSAFE_STAGING_PLAN,
                "message": "Migration write-set contains unsafe staging paths",
                "paths": unsafe_staging_paths,
                "action": "Repair the reported managed paths and rerun migrate --check",
            }
        )
    inventory["structural_blockers"] = sorted(set(blockers))
    if inventory["structural_blockers"]:
        inventory["state"] = PROJECT_DAMAGED
        inventory["project_status"] = PROJECT_DAMAGED
    elif recoverable_blockers:
        inventory["state"] = MIGRATION_BLOCKED_RECOVERABLE
        inventory["project_status"] = MIGRATION_BLOCKED_RECOVERABLE
    else:
        inventory["state"] = MIGRATION_REQUIRED
        inventory["project_status"] = MIGRATION_REQUIRED
    return inventory


def normalize_migration_payload(
    payload: object,
    legacy_paths: list[str],
    canonical_topics: set[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    data = require_payload_object(payload, "v3 migration")
    validate_exact_payload_keys(data, {"legacy_memory"}, set(), "v3 migration")
    plan = data["legacy_memory"]
    if not isinstance(plan, list):
        raise ProjectError("v3 migration legacy_memory must be an array")
    decisions: list[dict[str, object]] = []
    attention_entries: list[dict[str, object]] = []
    reviewed: set[str] = set()
    for item in plan:
        record = require_payload_object(item, "legacy Memory semantic review")
        validate_exact_payload_keys(
            record,
            {
                "path",
                "decision_memories",
                "attention_entries",
                "no_migration_required",
            },
            set(),
            "legacy Memory semantic review",
        )
        raw_path = record["path"]
        if not isinstance(raw_path, str):
            raise ProjectError("Legacy Memory review path must be a string")
        relative = Path(raw_path).as_posix()
        if relative in reviewed:
            raise ProjectError(f"Legacy Memory reviewed more than once: {relative}")
        reviewed.add(relative)
        decision_payloads = record["decision_memories"]
        attention_payloads = record["attention_entries"]
        no_migration = record["no_migration_required"]
        if not isinstance(decision_payloads, list):
            raise ProjectError(f"decision_memories must be an array: {relative}")
        if not isinstance(attention_payloads, list):
            raise ProjectError(f"attention_entries must be an array: {relative}")
        if type(no_migration) is not bool:
            raise ProjectError(f"no_migration_required must be boolean: {relative}")
        if no_migration != (not decision_payloads and not attention_payloads):
            raise ProjectError(
                f"no_migration_required disagrees with semantic outputs: {relative}"
            )
        for decision_payload in decision_payloads:
            decision = normalize_memory_payload(decision_payload)
            if decision["Supersedes"] or decision["Invalidates"]:
                raise ProjectError(
                    "Migration Decision Memory cannot declare generated-ID relationships"
                )
            unknown = sorted(set(decision["Related Topics"]) - canonical_topics)
            if unknown:
                raise ProjectError(
                    "Migrated Decision Memory references unregistered topics: "
                    + ", ".join(unknown)
                )
            decisions.append(decision)
        attention_entries.extend(
            normalize_attention_payload(entry) for entry in attention_payloads
        )
    expected = set(legacy_paths)
    if reviewed != expected:
        missing = sorted(expected - reviewed)
        extra = sorted(reviewed - expected)
        detail: list[str] = []
        if missing:
            detail.append("unreviewed: " + ", ".join(missing))
        if extra:
            detail.append("not found: " + ", ".join(extra))
        raise ProjectError(
            "Migration payload must review every legacy Memory file; " + "; ".join(detail)
        )
    titles = [str(entry["Title"]).casefold() for entry in attention_entries]
    if len(titles) != len(set(titles)):
        raise ProjectError("Migration contains equivalent active Attention titles")
    return decisions, attention_entries, len(reviewed)


def existing_migration_write_set(root: Path) -> tuple[list[str], int, list[str]]:
    files: list[str] = []
    total_bytes = 0
    unsafe_paths: list[str] = []
    project_file = root / "project.md"
    if project_file.is_symlink():
        unsafe_paths.append("project.md")
    elif project_file.is_file():
        files.append("project.md")
        total_bytes += project_file.stat().st_size
    if not root.is_dir():
        return files, total_bytes, unsafe_paths
    managed_roots = [
        path
        for path in root.iterdir()
        if path.name.casefold() in {"memory", "attention"}
    ]
    for managed_root in managed_roots:
        if managed_root.is_symlink() or not managed_root.is_dir():
            unsafe_paths.append(managed_root.name)
            continue
        for current_root, dirnames, filenames in os.walk(
            managed_root, followlinks=False
        ):
            current = Path(current_root)
            for dirname in list(dirnames):
                path = current / dirname
                if path.is_symlink():
                    unsafe_paths.append(path.relative_to(root).as_posix())
                    dirnames.remove(dirname)
            for filename in filenames:
                path = current / filename
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() or not path.is_file():
                    unsafe_paths.append(relative)
                    continue
                files.append(relative)
                total_bytes += path.stat().st_size
    return sorted(files), total_bytes, sorted(unsafe_paths)


def migration_transaction_plan(root: Path) -> dict[str, object]:
    root = root.expanduser().resolve()
    existing_files, existing_bytes, unsafe_paths = existing_migration_write_set(root)
    transaction_root = Path(tempfile.gettempdir()).resolve()
    return {
        "paths": list(MIGRATION_WRITE_SET),
        "existing_files": existing_files,
        "existing_bytes_touched": existing_bytes,
        "estimated_staged_regular_file_bytes": (
            existing_bytes + MIGRATION_STAGING_ESTIMATE_OVERHEAD
        ),
        "source_filesystem": {
            "path": str(root),
            "device": root.stat().st_dev if root.exists() else None,
        },
        "transaction_filesystem": {
            "path": str(transaction_root),
            "device": transaction_root.stat().st_dev,
        },
        "full_project_materialization": "NO",
        "unexpected_paths": unsafe_paths,
    }


def build_migration_overlay(root: Path, destination: Path) -> None:
    root = root.expanduser().resolve()
    destination.mkdir()
    shutil.copy2(root / "project.md", destination / "project.md")
    excluded = {".git", "project.md", "memory", "attention"}
    for source in root.iterdir():
        if source.name.casefold() in excluded:
            continue
        (destination / source.name).symlink_to(
            source, target_is_directory=source.is_dir()
        )


def inspect_migration_overlay(root: Path, candidate: Path) -> dict[str, object]:
    root = root.expanduser().resolve()
    candidate = candidate.expanduser().resolve()
    materialized_files: list[str] = []
    overlay_references: list[str] = []
    unexpected_paths: list[str] = []
    staged_bytes = 0
    for top_level in sorted(candidate.iterdir(), key=lambda path: path.name):
        relative = top_level.relative_to(candidate).as_posix()
        if top_level.is_symlink():
            source = root / top_level.name
            if (
                path_overlaps_migration_write_set(relative)
                or not source.exists()
                or top_level.resolve() != source.resolve()
            ):
                unexpected_paths.append(relative)
            else:
                overlay_references.append(relative)
            continue
        if not path_overlaps_migration_write_set(relative):
            unexpected_paths.append(relative)
            continue
        if top_level.is_file():
            materialized_files.append(relative)
            staged_bytes += top_level.stat().st_size
            continue
        if not top_level.is_dir():
            unexpected_paths.append(relative)
            continue
        for current_root, dirnames, filenames in os.walk(
            top_level, followlinks=False
        ):
            current = Path(current_root)
            for dirname in list(dirnames):
                path = current / dirname
                if path.is_symlink():
                    unexpected_paths.append(
                        path.relative_to(candidate).as_posix()
                    )
                    dirnames.remove(dirname)
            for filename in filenames:
                path = current / filename
                path_relative = path.relative_to(candidate).as_posix()
                if path.is_symlink() or not path.is_file():
                    unexpected_paths.append(path_relative)
                    continue
                materialized_files.append(path_relative)
                staged_bytes += path.stat().st_size
    return {
        "materialized_files": sorted(materialized_files),
        "overlay_references": sorted(overlay_references),
        "staged_regular_file_bytes": staged_bytes,
        "unexpected_paths": sorted(unexpected_paths),
        "full_project_materialization": "NO",
    }


def require_safe_migration_overlay(root: Path, candidate: Path) -> dict[str, object]:
    inspection = inspect_migration_overlay(root, candidate)
    unexpected_paths = inspection["unexpected_paths"]
    if unexpected_paths:
        raise ProjectError(
            f"{MIGRATION_BLOCKED_UNSAFE_STAGING_PLAN}: candidate staging contains "
            "content outside the migration write-set: "
            + ", ".join(unexpected_paths)
        )
    return inspection


def apply_staged_v3_state(
    root: Path,
    decisions: list[dict[str, object]],
    attention_entries: list[dict[str, object]],
) -> None:
    root = root.resolve()
    project_file = root / "project.md"
    text = project_file.read_text(encoding="utf-8")
    legacy_dir = detect_optional_directory(root, MEMORY_ALIASES, "legacy Memory")
    if legacy_dir is not None:
        shutil.rmtree(legacy_dir)
    memory_dir, _, memory_entries = managed_paths(root, MEMORY_DIRECTORY)
    memory_entries.mkdir(parents=True)
    _, _, attention_directory = managed_paths(root, ATTENTION_DIRECTORY)
    attention_directory.mkdir(parents=True)
    for number, decision in enumerate(decisions, start=1):
        memory_id = f"M-{number:04d}"
        values = {
            "ID": memory_id,
            "Status": "active",
            "Superseded By": [],
            "Invalidated By": [],
            **decision,
        }
        atomic_write(
            memory_entries / f"{memory_id}.md",
            render_managed_entry(MEMORY_FIELDS, values),
        )
    for number, attention in enumerate(attention_entries, start=1):
        attention_id = f"A-{number:04d}"
        atomic_write(
            attention_directory / f"{attention_id}.md",
            render_managed_entry(
                ATTENTION_FIELDS, {"ID": attention_id, **attention}
            ),
        )
    text = text.replace(V2_SCHEMA_MARKER, SCHEMA_MARKER, 1)
    navigation = (
        f"## Managed Navigation\n\n{NAVIGATION_START}\n"
        f"{managed_navigation_table()}\n{NAVIGATION_END}\n\n"
    )
    role_heading = "## Directory Roles\n"
    if role_heading not in text:
        raise ProjectError("v2 project.md lacks the Directory Roles heading")
    text = text.replace(role_heading, navigation + role_heading, 1)
    atomic_write(project_file, text.rstrip() + "\n")
    ensure_managed_topology(root)
    _refresh_index_unlocked(root)


def copy_managed_backup(root: Path, backup: Path) -> list[str]:
    backup.mkdir()
    shutil.copy2(root / "project.md", backup / "project.md")
    names: list[str] = []
    for path in root.iterdir():
        if path.is_dir() and path.name in {
            "Memory",
            "memory",
            "Attention",
            "attention",
        }:
            shutil.copytree(path, backup / path.name, symlinks=True)
            names.append(path.name)
    return sorted(names)


def remove_current_managed_directories(root: Path) -> None:
    for path in list(root.iterdir()):
        if path.is_dir() and path.name in {
            "Memory",
            "memory",
            "Attention",
            "attention",
        }:
            shutil.rmtree(path)


def restore_managed_backup(root: Path, backup: Path, directory_names: list[str]) -> None:
    remove_current_managed_directories(root)
    atomic_write(
        root / "project.md", (backup / "project.md").read_text(encoding="utf-8")
    )
    for name in directory_names:
        shutil.copytree(backup / name, root / name, symlinks=True)


def migration_apply(
    root: Path,
    payload: object,
    *,
    failure_hook: object | None = None,
) -> MigrationResult:
    root = root.expanduser().resolve()
    state = detect_project_marker_state(root)
    if state == PROJECT_V3:
        return MigrationResult(state=PROJECT_V3)
    if state != MIGRATION_REQUIRED:
        raise ProjectError("Automatic migration requires a recognized v2 project")
    with project_write_lock(root):
        inventory = migration_preflight(root)
        structural_blockers = inventory["structural_blockers"]
        recoverable_blockers = inventory["recoverable_blockers"]
        if structural_blockers:
            raise ProjectError(
                "Migration preflight blocked by damaged structure: "
                + "; ".join(structural_blockers)
            )
        if recoverable_blockers:
            details = "; ".join(
                f"{item['code']}: {item['message']}"
                + (
                    " [" + ", ".join(item["paths"]) + "]"
                    if item["paths"]
                    else ""
                )
                for item in recoverable_blockers
            )
            raise ProjectError("Migration preflight has recoverable blockers: " + details)
        unrelated_dirty_paths = list(inventory["unrelated_dirty_paths"])
        git_state: dict[str, object] = inventory["git"]  # type: ignore[assignment]
        before_unrelated = snapshot_project_paths(root, unrelated_dirty_paths)
        before_statuses = {
            path: git_state["path_statuses"][path]
            for path in unrelated_dirty_paths
        }
        project_text = (root / "project.md").read_text(encoding="utf-8")
        canonical_topics = {
            entry.topic for entry in parse_canonical_entries(project_text)
        }
        decisions, attention_entries, reviewed_count = normalize_migration_payload(
            payload,
            inventory["legacy_memory_files"],
            canonical_topics,
        )
        with tempfile.TemporaryDirectory(prefix="stepwise-r-project-migration-") as temp:
            transaction_root = Path(temp).resolve()
            staged = transaction_root / "candidate-overlay"
            backup = transaction_root / "managed-backup"
            build_migration_overlay(root, staged)
            with migration_overlay_view(staged, root):
                apply_staged_v3_state(staged, decisions, attention_entries)
                staged_inspection = require_safe_migration_overlay(root, staged)
                staged_report = validate_project(staged)
                if inspect_migration_overlay(root, staged) != staged_inspection:
                    raise ProjectError(
                        f"{MIGRATION_BLOCKED_UNSAFE_STAGING_PLAN}: candidate validation "
                        "modified migration staging"
                    )
            if not staged_report.ok:
                raise ProjectError(
                    "Staged v3 migration failed validation: "
                    + "; ".join(staged_report.errors)
                )
            if callable(failure_hook):
                failure_hook("after_stage_validation")
            backup_names = copy_managed_backup(root, backup)
            promotion_started = False
            try:
                promotion_started = True
                atomic_write(
                    root / "project.md",
                    (staged / "project.md").read_text(encoding="utf-8"),
                )
                if callable(failure_hook):
                    failure_hook("after_project_promotion")
                remove_current_managed_directories(root)
                shutil.copytree(staged / MEMORY_DIRECTORY, root / MEMORY_DIRECTORY)
                if callable(failure_hook):
                    failure_hook("after_memory_promotion")
                shutil.copytree(staged / ATTENTION_DIRECTORY, root / ATTENTION_DIRECTORY)
                if callable(failure_hook):
                    failure_hook("before_final_validation")
                _refresh_index_unlocked(root)
                final_report = validate_project(root)
                if not final_report.ok:
                    raise ProjectError(
                        "Promoted v3 migration failed validation: "
                        + "; ".join(final_report.errors)
                    )
                verify_unrelated_dirty_state(
                    root,
                    unrelated_dirty_paths,
                    before_unrelated,
                    before_statuses,
                )
            except Exception as exc:
                if promotion_started:
                    try:
                        restore_managed_backup(root, backup, backup_names)
                        rollback_report = validate_v2_project(root)
                        if rollback_report.errors:
                            raise ProjectError("; ".join(rollback_report.errors))
                    except Exception as rollback_exc:
                        raise ProjectError(
                            "HARD BLOCKER: migration failed and rollback could not be "
                            f"validated: {rollback_exc}"
                        ) from exc
                raise ProjectError(
                    f"Migration failed; pre-migration managed state restored: {exc}"
                ) from exc
    return MigrationResult(
        state=PROJECT_V3,
        decision_memories=len(decisions),
        attention_entries=len(attention_entries),
        reviewed_files=reviewed_count,
    )


def migrate_v3(root: Path, payload: object) -> tuple[int, int, int]:
    """Compatibility wrapper for callers of the initial v3 migration API."""
    result = migration_apply(root, payload)
    return (
        result.decision_memories,
        result.reviewed_files,
        result.attention_entries,
    )


def function_audit_template(
    function_name: str,
    source: str,
    source_sha256: str,
    risk_reason: str,
) -> str:
    return f"""---
title: {json.dumps(f"Function Audit: {function_name}()")}
stepwise_function: {json.dumps(function_name)}
source: {json.dumps(source)}
source_sha256: {json.dumps(source_sha256)}
risk_reason: {json.dumps(risk_reason)}
---

# Function Audit: `{function_name}()`

## Purpose And Risk

TODO: Explain the behavior and why an error could alter the scientific result or contract.

## Input And Output Contract

TODO: State required inputs, keys, allowed values, output shape, and side effects.

## Edge Cases And Contract Tests

TODO: Link to executable tests for missing values, empty data, duplicates, dates, and boundaries.

## Known Limits

TODO: State conditions outside the validated contract.
"""


def create_or_locate_function_audit(
    root: Path,
    function_name: str,
    source: str,
    risk_reason: str,
) -> tuple[Path, str]:
    root = root.expanduser().resolve()
    _, roles = ensure_v2_project(root, create=False)
    function_name = function_name.strip()
    if not re.fullmatch(r"[A-Za-z.][A-Za-z0-9._]*", function_name):
        raise ProjectError(f"Invalid R function name: {function_name!r}")
    source_path, source_rel = resolve_project_path(root, source, "function source")
    if not source_path.is_file() or source_path.suffix.lower() != ".r":
        raise ProjectError(f"Function source must be an R script: {source_rel}")
    if not source_defines_r_function(source_path, function_name):
        raise ProjectError(f"Function {function_name!r} is not defined in {source_rel}")
    risk_reason = validate_table_value(risk_reason, "risk reason")
    function_dir = roles["Audit"] / "Functions"
    audit_path = function_dir / f"audit_{function_name}.Rmd"
    with project_write_lock(root):
        if audit_path.exists():
            return audit_path, "UPDATE_REQUIRED"
        function_dir.mkdir(parents=True, exist_ok=True)
        atomic_write(
            audit_path,
            function_audit_template(
                function_name,
                source_rel,
                file_sha256(source_path),
                risk_reason,
            ),
        )
    refresh_index(root)
    return audit_path, "CREATED_DRAFT"


def add_error(report: ValidationReport, message: str) -> None:
    if message not in report.errors:
        report.errors.append(message)


def add_warning(report: ValidationReport, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)


def validate_project_structure(root: Path, report: ValidationReport) -> dict[str, Path]:
    try:
        roles = detect_roles(root, create_missing=False)
    except ProjectError as exc:
        add_error(report, str(exc))
        return {}
    for role in ROLE_ALIASES:
        if role not in roles:
            add_error(report, f"Missing project role directory: {role}")
    return roles


def validate_project_md(
    root: Path,
    report: ValidationReport,
) -> tuple[str, list[CanonicalEntry], list[ResultEntry]]:
    project_file = root / "project.md"
    if not project_file.exists():
        add_error(report, "project.md is missing")
        return "", [], []
    text = project_file.read_text(encoding="utf-8", errors="replace")
    if SCHEMA_MARKER not in text:
        if V2_SCHEMA_MARKER in text:
            add_error(
                report,
                "project.md is v2 and requires the explicit migrate workflow",
            )
        else:
            add_error(report, "project.md is a legacy project without the v3 schema marker")
    if LEGACY_MEMORY_START in text or LEGACY_MEMORY_END in text:
        add_error(report, "project.md still contains the legacy full Memory index")

    blocks = (
        (NAVIGATION_START, NAVIGATION_END, "managed navigation"),
        (ROLE_START, ROLE_END, "role"),
        (CANONICAL_START, CANONICAL_END, "canonical source"),
        (SCRIPT_START, SCRIPT_END, "script index"),
        (RESULT_START, RESULT_END, "result registry"),
        (FUNCTION_START, FUNCTION_END, "function audit index"),
    )
    for start, end, label in blocks:
        if text.count(start) != 1 or text.count(end) != 1:
            add_error(report, f"project.md needs exactly one managed {label} block")

    canonical_entries: list[CanonicalEntry] = []
    result_entries: list[ResultEntry] = []
    try:
        canonical_entries = parse_canonical_entries(text)
    except ProjectError as exc:
        add_error(report, str(exc))
    try:
        result_entries = parse_result_entries(text)
    except ProjectError as exc:
        add_error(report, str(exc))
    return text, canonical_entries, result_entries


def validate_current_indexes(
    root: Path,
    roles: dict[str, Path],
    text: str,
    canonical_entries: list[CanonicalEntry],
    result_entries: list[ResultEntry],
    report: ValidationReport,
) -> None:
    if not text or any(role not in roles for role in ROLE_ALIASES):
        return
    expected_blocks = (
        (
            NAVIGATION_START,
            NAVIGATION_END,
            "managed navigation",
            managed_navigation_table(),
        ),
        (ROLE_START, ROLE_END, "role", role_table(root, roles)),
        (
            CANONICAL_START,
            CANONICAL_END,
            "canonical source",
            render_canonical_entries(canonical_entries),
        ),
        (
            SCRIPT_START,
            SCRIPT_END,
            "script index",
            render_script_index(root, roles["R"]),
        ),
        (
            RESULT_START,
            RESULT_END,
            "result registry",
            render_result_entries(result_entries),
        ),
        (
            FUNCTION_START,
            FUNCTION_END,
            "function audit index",
            render_function_index(root, roles["Audit"]),
        ),
    )
    for start, end, label, expected in expected_blocks:
        try:
            current = extract_block(text, start, end, label)
        except ProjectError:
            continue
        if current != expected:
            add_error(report, f"project.md has a stale or non-canonical {label} block")


def validate_canonical_entries(
    root: Path,
    entries: list[CanonicalEntry],
    report: ValidationReport,
) -> None:
    topics: set[str] = set()
    for entry in entries:
        try:
            validate_key(entry.topic, "canonical topic")
        except ProjectError as exc:
            add_error(report, str(exc))
        if entry.topic in topics:
            add_error(report, f"Duplicate canonical topic: {entry.topic}")
        topics.add(entry.topic)
        try:
            path, _ = resolve_project_path(root, entry.path, "canonical path")
            verification, _ = resolve_project_path(
                root,
                entry.verification,
                "canonical contract test",
            )
        except ProjectError as exc:
            add_error(report, str(exc))
            continue
        if not path.is_file():
            add_error(report, f"Canonical source is not a file: {entry.path}")
            continue
        verification_error = contract_test_error(verification)
        if verification_error:
            add_error(
                report,
                f"Invalid canonical contract test {entry.verification}: {verification_error}",
            )
        content = path.read_text(encoding="utf-8", errors="replace")
        contract_content = content
        if entry.section:
            heading = re.compile(
                rf"^#{{1,6}}\s+{re.escape(entry.section)}\s*$",
                re.MULTILINE,
            )
            if not heading.search(content):
                add_error(
                    report,
                    f"Missing canonical section {entry.section!r} in {entry.path}",
                )
            else:
                contract_content = markdown_section(content, entry.section)
        authoritative_content = authoritative_markdown_text(contract_content)
        statuses, invalid_statuses = contract_status_values(authoritative_content)
        if invalid_statuses:
            add_error(
                report,
                f"Canonical source has invalid freeze status {invalid_statuses!r}: {entry.path}",
            )
        if not statuses and not invalid_statuses:
            add_error(
                report,
                f"Canonical source lacks Status: draft, partially-frozen, or frozen: {entry.path}",
            )
        if len(set(statuses)) > 1:
            add_error(
                report,
                f"Canonical source has contradictory freeze states: {entry.path}",
            )
        frozen = "frozen" in statuses
        if frozen and UNRESOLVED_PATTERN.search(authoritative_content):
            add_error(
                report,
                f"Frozen canonical source contains unresolved language: {entry.path}",
            )
        if RUN_STATUS_PATTERN.search(authoritative_content):
            add_error(
                report,
                f"Canonical source contains execution status/run metadata: {entry.path}",
            )


def validate_unregistered_protocols(
    root: Path,
    roles: dict[str, Path],
    entries: list[CanonicalEntry],
    report: ValidationReport,
) -> None:
    registered_paths = {entry.path for entry in entries}
    excluded_roots = [
        roles[role].resolve() for role in ("Data", "Results", "Audit") if role in roles
    ]
    try:
        memory_dir = detect_optional_directory(root, MEMORY_ALIASES, "Memory")
    except ProjectError:
        memory_dir = None
    if memory_dir is not None:
        excluded_roots.append(memory_dir.resolve())
    attention_dir = root / ATTENTION_DIRECTORY
    if attention_dir.exists():
        excluded_roots.append(attention_dir.resolve())
    excluded_roots.extend(
        path.resolve()
        for path in (root / name for name in IGNORED_PROJECT_DIRS)
        if path.exists()
    )
    documents: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(current_root)
        retained_directories: list[str] = []
        for dirname in dirnames:
            resolved = (current / dirname).resolve()
            if any(
                resolved == excluded or excluded in resolved.parents
                for excluded in excluded_roots
            ):
                continue
            retained_directories.append(dirname)
        dirnames[:] = retained_directories
        for filename in filenames:
            path = current / filename
            if path.suffix.lower() not in {".md", ".qmd", ".rmd"}:
                continue
            if path == root / "project.md":
                continue
            documents.append(path)
    for path in documents:
        content = path.read_text(encoding="utf-8", errors="replace")
        authoritative_content = authoritative_markdown_text(content)
        statuses, invalid_statuses = contract_status_values(authoritative_content)
        relative = path.relative_to(root).as_posix()
        if (statuses or invalid_statuses) and relative not in registered_paths:
            add_error(
                report,
                f"Status-bearing document is not registered as a canonical source: {relative}",
            )
        frozen = "frozen" in statuses
        if frozen and UNRESOLVED_PATTERN.search(authoritative_content):
            add_error(
                report,
                "Frozen document contains unresolved language: " + relative,
            )


def validate_results(
    root: Path,
    roles: dict[str, Path],
    entries: list[ResultEntry],
    report: ValidationReport,
) -> None:
    if "Results" not in roles:
        return
    registered_paths: dict[str, ResultEntry] = {}
    ids: set[str] = set()
    for entry in entries:
        try:
            validate_key(entry.result_id, "result id")
        except ProjectError as exc:
            add_error(report, str(exc))
        if entry.result_id in ids:
            add_error(report, f"Duplicate result id: {entry.result_id}")
        ids.add(entry.result_id)
        if entry.path in registered_paths:
            add_error(report, f"Result path registered more than once: {entry.path}")
        registered_paths[entry.path] = entry
        try:
            path, _ = resolve_project_path(root, entry.path, "registered result")
            producer, _ = resolve_project_path(root, entry.producer, "result producer")
        except ProjectError as exc:
            add_error(report, str(exc))
            continue
        if entry.kind not in RESULT_KINDS:
            add_error(report, f"Invalid registered result kind: {entry.kind}")
        if entry.audience not in RESULT_AUDIENCES:
            add_error(report, f"Invalid registered result audience: {entry.audience}")
        try:
            path.resolve().relative_to(roles["Results"].resolve())
        except ValueError:
            add_error(report, f"Registered result is outside Results: {entry.path}")
        if not path.is_file():
            add_error(report, f"Registered result is not a file: {entry.path}")
        artifact_error = result_artifact_error(
            path.resolve(), roles["Results"].resolve()
        )
        if artifact_error:
            add_error(report, f"Results contains a {artifact_error}: {entry.path}")
        kind_error = result_kind_error(path, entry.kind)
        if kind_error:
            add_error(
                report, f"Registered result has incompatible metadata: {kind_error}"
            )
        if "R" in roles:
            producer_error = result_producer_error(
                producer.resolve(), roles["R"].resolve()
            )
            if producer_error:
                add_error(
                    report,
                    f"Invalid result producer {entry.producer}: {producer_error}",
                )

    files = [
        path
        for path in roles["Results"].rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    ]
    unregistered = [
        path.relative_to(root).as_posix()
        for path in files
        if path.relative_to(root).as_posix() not in registered_paths
    ]
    if unregistered:
        preview = ", ".join(unregistered[:10])
        suffix = (
            "" if len(unregistered) <= 10 else f" ... and {len(unregistered) - 10} more"
        )
        add_error(
            report,
            f"Results contains {len(unregistered)} unregistered file(s): {preview}{suffix}",
        )
    for path in files:
        relative = path.relative_to(root).as_posix()
        artifact_error = result_artifact_error(
            path.resolve(), roles["Results"].resolve()
        )
        if artifact_error:
            add_error(report, f"Results contains a {artifact_error}: {relative}")


def validate_managed_topology(
    root: Path, system: str, report: ValidationReport
) -> tuple[Path | None, list[Path]]:
    directory, index_path, entries_dir = managed_paths(root, system)
    if not directory.is_dir():
        add_error(report, f"Missing managed directory: {system}")
        return None, []
    allowed_children = {"index.md", ENTRY_DIRECTORY, ".DS_Store"}
    unexpected = sorted(
        path.relative_to(root).as_posix()
        for path in directory.iterdir()
        if path.name not in allowed_children
    )
    if unexpected:
        add_error(
            report,
            f"Unexpected {system} paths: {', '.join(unexpected[:10])}",
        )
    if not index_path.is_file():
        add_error(report, f"Missing generated index: {system}/index.md")
    if not entries_dir.is_dir():
        add_error(report, f"Missing managed entries directory: {system}/entries")
        return index_path if index_path.is_file() else None, []
    nested = sorted(
        path.relative_to(root).as_posix()
        for path in entries_dir.rglob("*")
        if path.name != ".DS_Store"
        and (path.is_dir() or (path.is_file() and path.suffix.lower() != ".md"))
    )
    if nested:
        add_error(
            report,
            f"Unexpected {system} entry topology: {', '.join(nested[:10])}",
        )
    paths = sorted(path for path in entries_dir.glob("*.md") if path.is_file())
    return index_path if index_path.is_file() else None, paths


def validate_attention(root: Path, report: ValidationReport) -> None:
    if any(path.is_dir() and path.name == "attention" for path in root.iterdir()):
        add_error(report, "Legacy or alternative Attention topology exists: attention/")
    index_path, paths = validate_managed_topology(
        root, ATTENTION_DIRECTORY, report
    )
    seen: set[str] = set()
    for path in paths:
        try:
            values = parse_managed_entry(path, ATTENTION_FIELDS, "Attention entry")
        except ProjectError as exc:
            add_error(report, str(exc))
            continue
        attention_id = values["ID"]
        if not valid_managed_id(attention_id, "A"):
            add_error(report, f"Invalid Attention ID: {attention_id}")
        if attention_id in seen:
            add_error(report, f"Duplicate Attention ID: {attention_id}")
        seen.add(attention_id)
        if path.stem != attention_id:
            add_error(report, f"Attention filename does not match ID: {path.name}")
        if values["Blocking"] not in {"true", "false"}:
            add_error(report, f"Attention Blocking must be true or false: {path.name}")
        for field in ATTENTION_FIELDS:
            if not values[field]:
                add_error(report, f"Attention {field} cannot be empty: {path.name}")
    if index_path is not None:
        current = index_path.read_text(encoding="utf-8", errors="replace")
        if current != render_attention_index(root):
            add_error(report, "Attention/index.md does not match active entries")


def validate_memory(
    root: Path,
    canonical_entries: list[CanonicalEntry],
    report: ValidationReport,
) -> None:
    if any(path.is_dir() and path.name == "memory" for path in root.iterdir()):
        add_error(report, "Legacy or alternative Memory topology exists: memory/")
    index_path, paths = validate_managed_topology(root, MEMORY_DIRECTORY, report)
    canonical_topics = {entry.topic for entry in canonical_entries}
    entries: dict[str, dict[str, object]] = {}
    for path in paths:
        try:
            raw = parse_managed_entry(path, MEMORY_FIELDS, "Decision Memory entry")
        except ProjectError as exc:
            add_error(report, str(exc))
            continue
        memory_id = raw["ID"]
        if not valid_managed_id(memory_id, "M"):
            add_error(report, f"Invalid Decision Memory ID: {memory_id}")
        if memory_id in entries:
            add_error(report, f"Duplicate Decision Memory ID: {memory_id}")
        if path.stem != memory_id:
            add_error(report, f"Decision Memory filename does not match ID: {path.name}")
        if raw["Status"] not in MEMORY_STATUSES:
            add_error(report, f"Invalid Decision Memory status: {path.name}")
        typed: dict[str, object] = dict(raw)
        for field in (
            "Related Topics",
            "Supersedes",
            "Invalidates",
            "Superseded By",
            "Invalidated By",
        ):
            try:
                typed[field] = parse_json_list_field(
                    raw[field], f"Decision Memory {field}"
                )
            except ProjectError as exc:
                add_error(report, f"{exc}: {path.name}")
                typed[field] = []
        unknown_topics = sorted(set(typed["Related Topics"]) - canonical_topics)
        if unknown_topics:
            add_error(
                report,
                f"Decision Memory has unregistered related topics {unknown_topics}: {path.name}",
            )
        for field in MEMORY_FIELDS:
            if field not in {
                "Related Topics",
                "Supersedes",
                "Invalidates",
                "Superseded By",
                "Invalidated By",
            } and not raw[field]:
                add_error(report, f"Decision Memory {field} cannot be empty: {path.name}")
        entries[memory_id] = typed

    for memory_id, entry in entries.items():
        supersedes = entry["Supersedes"]
        invalidates = entry["Invalidates"]
        superseded_by = entry["Superseded By"]
        invalidated_by = entry["Invalidated By"]
        overlap = sorted(set(supersedes) & set(invalidates))
        if overlap:
            add_error(
                report,
                f"Decision Memory both supersedes and invalidates {overlap}: {memory_id}",
            )
        for field, relation_ids in (
            ("Supersedes", supersedes),
            ("Invalidates", invalidates),
            ("Superseded By", superseded_by),
            ("Invalidated By", invalidated_by),
        ):
            for relation_id in relation_ids:
                if not valid_managed_id(relation_id, "M"):
                    add_error(report, f"Invalid {field} target {relation_id}: {memory_id}")
                elif relation_id not in entries:
                    add_error(report, f"Missing {field} target {relation_id}: {memory_id}")
        status = entry["Status"]
        if status == "active" and (superseded_by or invalidated_by):
            add_error(report, f"Active Decision Memory has reverse transition: {memory_id}")
        if status == "superseded" and (len(superseded_by) != 1 or invalidated_by):
            add_error(report, f"Superseded status disagrees with relationships: {memory_id}")
        if status == "invalidated" and (len(invalidated_by) != 1 or superseded_by):
            add_error(report, f"Invalidated status disagrees with relationships: {memory_id}")
        for relation_id in supersedes:
            target = entries.get(relation_id)
            if target is not None and (
                target["Status"] != "superseded"
                or target["Superseded By"] != [memory_id]
            ):
                add_error(report, f"Supersedes reverse relationship disagrees: {memory_id}")
        for relation_id in invalidates:
            target = entries.get(relation_id)
            if target is not None and (
                target["Status"] != "invalidated"
                or target["Invalidated By"] != [memory_id]
            ):
                add_error(report, f"Invalidates reverse relationship disagrees: {memory_id}")
        for relation_id in superseded_by:
            source = entries.get(relation_id)
            if source is not None and memory_id not in source["Supersedes"]:
                add_error(report, f"Superseded By forward relationship disagrees: {memory_id}")
        for relation_id in invalidated_by:
            source = entries.get(relation_id)
            if source is not None and memory_id not in source["Invalidates"]:
                add_error(report, f"Invalidated By forward relationship disagrees: {memory_id}")
    if index_path is not None:
        current = index_path.read_text(encoding="utf-8", errors="replace")
        if current != render_memory_index(root):
            add_error(report, "Memory/index.md does not match entries")


def validate_function_audits(
    root: Path, roles: dict[str, Path], report: ValidationReport
) -> None:
    if "Audit" not in roles:
        return
    function_dir = roles["Audit"] / "Functions"
    if not function_dir.is_dir():
        return
    html_files = sorted(function_dir.rglob("*.html"))
    if html_files:
        add_error(
            report,
            f"Function Audit contains {len(html_files)} rendered HTML file(s); keep Rmd only",
        )
    functions: set[str] = set()
    for audit in sorted(function_dir.rglob("*.Rmd")):
        metadata = parse_frontmatter(audit)
        function_name = metadata.get("stepwise_function", "")
        source_value = metadata.get("source", "")
        source_sha256 = metadata.get("source_sha256", "")
        risk_reason = metadata.get("risk_reason", "")
        relative = audit.relative_to(root).as_posix()
        if (
            not function_name
            or not source_value
            or not source_sha256
            or not risk_reason
        ):
            add_error(report, f"Function Audit lacks v2 metadata: {relative}")
            continue
        if audit.parent != function_dir or audit.name != f"audit_{function_name}.Rmd":
            add_error(
                report, f"Function Audit does not use its stable path: {relative}"
            )
        if function_name in functions:
            add_error(report, f"Duplicate Function Audit for {function_name}")
        functions.add(function_name)
        try:
            source_path, _ = resolve_project_path(root, source_value, "function source")
        except ProjectError as exc:
            add_error(report, str(exc))
            continue
        if not source_path.is_file() or source_path.suffix.lower() != ".r":
            add_error(
                report, f"Function Audit source is not an R script: {source_value}"
            )
            continue
        if not source_defines_r_function(source_path, function_name):
            add_error(
                report,
                f"Function Audit source does not define {function_name}: {relative}",
            )
        content = audit.read_text(encoding="utf-8", errors="replace")
        for section in (
            "Purpose And Risk",
            "Input And Output Contract",
            "Edge Cases And Contract Tests",
            "Known Limits",
        ):
            section_error = required_section_error(content, section)
            if section_error:
                add_error(report, f"Function Audit {section_error}: {relative}")
        if PLACEHOLDER_PATTERN.search(content):
            add_error(
                report, f"Function Audit contains an unfinished template: {relative}"
            )
        if source_sha256 != file_sha256(source_path):
            add_error(report, f"Function Audit is stale for its source: {relative}")


def validate_audit_runs(
    root: Path,
    roles: dict[str, Path],
    report: ValidationReport,
    *,
    recoverable_paths: set[str] | None = None,
    recoverable_stages_without_current: set[str] | None = None,
) -> None:
    recoverable_paths = recoverable_paths or set()
    recoverable_stages_without_current = recoverable_stages_without_current or set()
    if "Audit" not in roles:
        return
    runs_dir = roles["Audit"] / "Runs"
    if not runs_dir.is_dir():
        return
    root_files = [
        path
        for path in runs_dir.iterdir()
        if (not path.is_dir() or path.is_symlink()) and path.name != ".DS_Store"
    ]
    if root_files:
        names = ", ".join(path.name for path in root_files)
        add_error(
            report,
            f"Audit/Runs contains files outside a stage/current directory: {names}",
        )
    for stage in sorted(
        path for path in runs_dir.iterdir() if path.is_dir() and not path.is_symlink()
    ):
        children = [path for path in stage.iterdir() if path.name != ".DS_Store"]
        invalid = [
            path
            for path in children
            if path.name != "current"
            and path.relative_to(root).as_posix() not in recoverable_paths
        ]
        if invalid:
            names = ", ".join(path.name for path in invalid)
            add_error(
                report,
                f"Audit stage {stage.name!r} contains historical/staging entries: {names}",
            )
        current = stage / "current"
        if not current.exists():
            if stage.name not in recoverable_stages_without_current:
                add_error(report, f"Audit stage {stage.name!r} has no current directory")
        elif not current.is_dir() or current.is_symlink():
            add_error(report, f"Audit current path is not a directory: {current}")
        else:
            version_directories = [
                path.relative_to(root).as_posix()
                for path in current.rglob("*")
                if path.is_dir()
                and re.fullmatch(
                    r"old|backup|staging|legacy|superseded|obsolete|v\d+|"
                    r"\d{8}|\d{4}-\d{2}-\d{2}",
                    path.name,
                    re.IGNORECASE,
                )
            ]
            if version_directories:
                preview = ", ".join(version_directories[:10])
                add_error(
                    report,
                    f"Audit current contains historical/version directories: {preview}",
                )


def validate_parallel_copies(root: Path, report: ValidationReport) -> None:
    excluded = (
        IGNORED_PROJECT_DIRS | set(ROLE_ALIASES["Results"]) | set(ROLE_ALIASES["Data"])
    )
    suspicious: list[str] = []
    document_families: dict[tuple[Path, str, str], list[Path]] = {}
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [dirname for dirname in dirnames if dirname not in excluded]
        current_path = Path(current_root)
        for filename in filenames:
            path = current_path / filename
            if path.suffix.lower() not in {".md", ".html", ".qmd", ".rmd"}:
                continue
            if PARALLEL_COPY_TOKEN.search(path.stem):
                suspicious.append(path.relative_to(root).as_posix())
            family_stem = VERSION_SUFFIX.sub("", path.stem)
            key = (path.parent, path.suffix.lower(), family_stem)
            document_families.setdefault(key, []).append(path)
    for paths in document_families.values():
        if len(paths) < 2 or not any(
            VERSION_SUFFIX.search(path.stem) for path in paths
        ):
            continue
        suspicious.extend(path.relative_to(root).as_posix() for path in paths)
    if suspicious:
        unique = sorted(set(suspicious))
        preview = ", ".join(unique[:10])
        add_error(
            report, f"Parallel old/backup/versioned document copies detected: {preview}"
        )


def validate_v2_project_md(
    root: Path, report: ValidationReport
) -> tuple[str, list[CanonicalEntry], list[ResultEntry]]:
    project_file = root / "project.md"
    if not project_file.is_file():
        add_error(report, "project.md is missing")
        return "", [], []
    text = project_file.read_text(encoding="utf-8", errors="replace")
    if text.count(V2_SCHEMA_MARKER) != 1 or SCHEMA_MARKER in text:
        add_error(report, "project.md does not contain one unambiguous v2 marker")
    if NAVIGATION_START in text or NAVIGATION_END in text:
        add_error(report, "v2 project contains partial v3 managed navigation")
    if LEGACY_MEMORY_START in text or LEGACY_MEMORY_END in text:
        add_error(report, "project.md contains unsupported pre-v2 Memory markers")
    blocks = (
        (ROLE_START, ROLE_END, "role"),
        (CANONICAL_START, CANONICAL_END, "canonical source"),
        (SCRIPT_START, SCRIPT_END, "script index"),
        (RESULT_START, RESULT_END, "result registry"),
        (FUNCTION_START, FUNCTION_END, "function audit index"),
    )
    for start, end, label in blocks:
        if text.count(start) != 1 or text.count(end) != 1:
            add_error(report, f"v2 project.md needs exactly one managed {label} block")
    canonical_entries: list[CanonicalEntry] = []
    result_entries: list[ResultEntry] = []
    try:
        canonical_entries = parse_canonical_entries(text)
    except ProjectError as exc:
        add_error(report, str(exc))
    try:
        result_entries = parse_result_entries(text)
    except ProjectError as exc:
        add_error(report, str(exc))
    return text, canonical_entries, result_entries


def validate_v2_current_indexes(
    root: Path,
    roles: dict[str, Path],
    text: str,
    canonical_entries: list[CanonicalEntry],
    result_entries: list[ResultEntry],
    report: ValidationReport,
) -> None:
    if not text or any(role not in roles for role in ROLE_ALIASES):
        return
    expected_blocks = (
        (ROLE_START, ROLE_END, "role", role_table(root, roles)),
        (
            CANONICAL_START,
            CANONICAL_END,
            "canonical source",
            render_canonical_entries(canonical_entries),
        ),
        (
            RESULT_START,
            RESULT_END,
            "result registry",
            render_result_entries(result_entries),
        ),
        (
            FUNCTION_START,
            FUNCTION_END,
            "function audit index",
            render_function_index(root, roles["Audit"]),
        ),
    )
    for start, end, label, expected in expected_blocks:
        try:
            current = extract_block(text, start, end, label)
        except ProjectError:
            continue
        if current != expected:
            add_error(report, f"v2 project.md has a stale or non-canonical {label} block")


def validate_v2_memory(
    root: Path,
    canonical_entries: list[CanonicalEntry],
    report: ValidationReport,
) -> list[Path]:
    try:
        memory_dir = detect_optional_directory(root, MEMORY_ALIASES, "Memory")
    except ProjectError as exc:
        add_error(report, str(exc))
        return []
    if memory_dir is None:
        return []
    unexpected = sorted(
        path.relative_to(root).as_posix()
        for path in memory_dir.rglob("*")
        if path.name != ".DS_Store"
        and (path.is_dir() or (path.is_file() and path.suffix.lower() != ".md"))
    )
    if unexpected:
        add_error(report, "Invalid v2 Memory topology: " + ", ".join(unexpected[:10]))
    memory_files = sorted(
        path
        for path in memory_dir.glob("*.md")
        if path.is_file() and path.name != ".DS_Store"
    )
    canonical_topics = {entry.topic: entry for entry in canonical_entries}
    seen: set[str] = set()
    for path in memory_files:
        metadata = parse_frontmatter(path)
        task_key = metadata.get("task_key", "")
        if not task_key:
            add_error(report, f"v2 Memory lacks task_key frontmatter: {path.name}")
            continue
        try:
            validate_key(task_key, "v2 Memory task key")
        except ProjectError as exc:
            add_error(report, str(exc))
        if task_key in seen:
            add_error(report, f"Duplicate v2 Memory task_key: {task_key}")
        seen.add(task_key)
        if path.stem != task_key:
            add_error(report, f"v2 Memory filename does not match task_key: {path.name}")
        topic = metadata.get("canonical_topic", "")
        canonical_entry = canonical_topics.get(topic)
        if canonical_entry is None:
            add_error(report, f"v2 Memory references an unregistered topic: {path.name}")
        elif metadata.get("canonical_path", "") != canonical_entry.path:
            add_error(report, f"v2 Memory has a stale canonical path: {path.name}")
        content = path.read_text(encoding="utf-8", errors="replace")
        for section in ("Change And Reason", "Verification", "Open Risks"):
            section_error = required_section_error(content, section)
            if section_error:
                add_error(report, f"v2 Memory {section_error}: {path.name}")
        for label in ("Change", "Why", "Verification", "Risk"):
            field_error = required_labeled_field_error(content, label)
            if field_error:
                add_error(report, f"v2 Memory {field_error}: {path.name}")
        if PLACEHOLDER_PATTERN.search(content):
            add_error(report, f"v2 Memory contains an unfinished template: {path.name}")
    return memory_files


def validate_v2_project(root: Path) -> ValidationReport:
    root = root.expanduser().resolve()
    report = ValidationReport(errors=[], warnings=[], state=MIGRATION_REQUIRED)
    if detect_project_marker_state(root) != MIGRATION_REQUIRED:
        add_error(report, "Project is not an unambiguous Stepwise R Project v2 workspace")
        report.state = PROJECT_DAMAGED
        return report
    roles = validate_project_structure(root, report)
    if any(
        path.is_dir() and path.name in {"Attention", "attention"}
        for path in root.iterdir()
    ):
        add_error(report, "v2 project contains partial v3 Attention topology")
    project_text, canonical_entries, result_entries = validate_v2_project_md(root, report)
    validate_v2_current_indexes(
        root,
        roles,
        project_text,
        canonical_entries,
        result_entries,
        report,
    )
    validate_canonical_entries(root, canonical_entries, report)
    validate_unregistered_protocols(root, roles, canonical_entries, report)
    validate_results(root, roles, result_entries, report)
    validate_v2_memory(root, canonical_entries, report)
    validate_function_audits(root, roles, report)
    audit_classification = audit_recovery_classification(root, roles, result_entries)
    recoverable_paths = {
        str(item["path"]) for item in audit_classification["recoverable"]
    }
    recoverable_stages_without_current = {
        str(item["stage"])
        for item in audit_classification["recoverable"]
        if not (roles["Audit"] / "Runs" / str(item["stage"]) / "current").exists()
    } if "Audit" in roles else set()
    for item in audit_classification["ambiguous"]:
        add_error(
            report,
            f"Ambiguous Audit residue at {item['path']}: {item['reason']}",
        )
    validate_audit_runs(
        root,
        roles,
        report,
        recoverable_paths=recoverable_paths,
        recoverable_stages_without_current=recoverable_stages_without_current,
    )
    validate_parallel_copies(root, report)
    if report.errors:
        report.state = PROJECT_DAMAGED
    elif audit_classification["recoverable"]:
        report.state = MIGRATION_BLOCKED_RECOVERABLE
        report.warnings.append(
            "Recoverable Audit staging blocks migration; run audit-recover for each stage"
        )
    return report


def validate_project(root: Path) -> ValidationReport:
    root = root.expanduser().resolve()
    state = detect_project_marker_state(root)
    if state == MIGRATION_REQUIRED:
        report = validate_v2_project(root)
        if report.state == MIGRATION_REQUIRED and not report.errors:
            report.warnings.append(
                "Recognized healthy Stepwise R Project v2 workspace; run migrate --check"
            )
        return report
    if state == PROJECT_UNMANAGED:
        return ValidationReport(
            errors=["Project is unmanaged; no recognized Stepwise R Project marker"],
            warnings=[],
            state=PROJECT_UNMANAGED,
        )
    if state == PROJECT_DAMAGED:
        return ValidationReport(
            errors=["Managed project markers are ambiguous or damaged"],
            warnings=[],
            state=PROJECT_DAMAGED,
        )
    report = ValidationReport(errors=[], warnings=[])
    if not root.is_dir():
        add_error(report, f"Project directory does not exist: {root}")
        return report
    roles = validate_project_structure(root, report)
    project_text, canonical_entries, result_entries = validate_project_md(root, report)
    validate_current_indexes(
        root,
        roles,
        project_text,
        canonical_entries,
        result_entries,
        report,
    )
    validate_canonical_entries(root, canonical_entries, report)
    validate_unregistered_protocols(root, roles, canonical_entries, report)
    validate_results(root, roles, result_entries, report)
    validate_memory(root, canonical_entries, report)
    validate_attention(root, report)
    validate_function_audits(root, roles, report)
    validate_audit_runs(root, roles, report)
    validate_parallel_copies(root, report)
    return report


def print_validation(report: ValidationReport) -> None:
    status = (
        report.state
        if report.state in {MIGRATION_REQUIRED, MIGRATION_BLOCKED_RECOVERABLE}
        and not report.errors
        else "PASS" if report.ok else "FAIL"
    )
    print(f"Stepwise R Project validation: {status}")
    for error in report.errors:
        print(f"ERROR: {error}")
    for warning in report.warnings:
        print(f"WARNING: {warning}")
    print(f"Errors: {len(report.errors)}; warnings: {len(report.warnings)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Maintain lean Stepwise R projects with canonical ownership and outputs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="Initialize an idempotent v3 project map."
    )
    init_parser.add_argument("target_dir", type=Path)

    canonical_parser = subparsers.add_parser(
        "canonical",
        help="Register or explicitly replace one canonical topic owner.",
    )
    canonical_parser.add_argument("target_dir", type=Path)
    canonical_parser.add_argument("--topic", required=True)
    canonical_parser.add_argument("--path", required=True)
    canonical_parser.add_argument("--section")
    canonical_parser.add_argument("--verification", required=True)
    canonical_parser.add_argument("--replace", action="store_true")

    result_parser = subparsers.add_parser(
        "result",
        help="Register one current human-facing Results deliverable.",
    )
    result_parser.add_argument("target_dir", type=Path)
    result_parser.add_argument("--id", required=True, dest="result_id")
    result_parser.add_argument("--path", required=True)
    result_parser.add_argument("--kind", required=True, choices=RESULT_KINDS)
    result_parser.add_argument("--audience", required=True, choices=RESULT_AUDIENCES)
    result_parser.add_argument("--producer", required=True)
    result_parser.add_argument("--replace", action="store_true")

    memory_parser = subparsers.add_parser(
        "memory", help="Manage consequential Decision Memory entries."
    )
    memory_subparsers = memory_parser.add_subparsers(
        dest="memory_command", required=True
    )
    memory_add_parser = memory_subparsers.add_parser(
        "add", help="Add one helper-ID Decision Memory entry from JSON."
    )
    memory_add_parser.add_argument("target_dir", type=Path)
    memory_add_parser.add_argument("--input", required=True, type=Path)

    attention_parser = subparsers.add_parser(
        "attention", help="Manage active Human Attention entries."
    )
    attention_subparsers = attention_parser.add_subparsers(
        dest="attention_command", required=True
    )
    attention_raise_parser = attention_subparsers.add_parser(
        "raise", help="Raise one helper-ID Attention entry from JSON."
    )
    attention_raise_parser.add_argument("target_dir", type=Path)
    attention_raise_parser.add_argument("--input", required=True, type=Path)
    attention_resolve_parser = attention_subparsers.add_parser(
        "resolve", help="Resolve and remove one active Attention entry."
    )
    attention_resolve_parser.add_argument("target_dir", type=Path)
    attention_resolve_parser.add_argument("--id", required=True, dest="attention_id")

    migration_parser = subparsers.add_parser(
        "migrate",
        help="Check or transactionally apply a v2 to v3 governance migration.",
    )
    migration_parser.add_argument("target_dir", type=Path)
    migration_mode = migration_parser.add_mutually_exclusive_group(required=True)
    migration_mode.add_argument("--check", action="store_true")
    migration_mode.add_argument("--apply", action="store_true")
    migration_parser.add_argument("--input", type=Path)

    audit_recover_parser = subparsers.add_parser(
        "audit-recover",
        help="Recover mechanically identifiable failed Audit staging outside the project.",
    )
    audit_recover_parser.add_argument("target_dir", type=Path)
    audit_recover_parser.add_argument("--stage", required=True, dest="stage_name")

    audit_parser = subparsers.add_parser(
        "function-audit",
        help="Create or locate an audit for one high-risk function.",
    )
    audit_parser.add_argument("target_dir", type=Path)
    audit_parser.add_argument("--function", required=True, dest="function_name")
    audit_parser.add_argument("--source", required=True)
    audit_parser.add_argument("--risk-reason", required=True)

    index_parser = subparsers.add_parser(
        "index", help="Refresh the current project map."
    )
    index_parser.add_argument("target_dir", type=Path)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate v3 ownership, managed systems, and current-only contracts.",
    )
    validate_parser.add_argument("target_dir", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.target_dir.expanduser().resolve()

    if args.command == "init":
        project_file, _ = ensure_v3_project(root, create=True)
        refresh_index(root)
        print(f"Initialized Stepwise R Project v3: {project_file}")
    elif args.command == "canonical":
        project_file = register_canonical(
            root,
            args.topic,
            args.path,
            args.section,
            args.verification,
            replace=args.replace,
        )
        print(f"Canonical topic registered: {args.topic} -> {project_file}")
    elif args.command == "result":
        project_file = register_result(
            root,
            args.result_id,
            args.path,
            args.kind,
            args.audience,
            args.producer,
            replace=args.replace,
        )
        print(f"Current result registered: {args.result_id} -> {project_file}")
    elif args.command == "memory":
        if args.memory_command == "add":
            memory_path = add_decision_memory(root, load_json_payload(args.input))
            print(f"Decision Memory created: {memory_path}")
    elif args.command == "attention":
        if args.attention_command == "raise":
            attention_path = add_attention(root, load_json_payload(args.input))
            print(f"Human Attention raised: {attention_path}")
        elif args.attention_command == "resolve":
            attention_path = resolve_attention(root, args.attention_id)
            print(f"Human Attention resolved: {attention_path}")
    elif args.command == "migrate":
        if args.check:
            inventory = migration_preflight(root)
            print(json.dumps(inventory, indent=2, sort_keys=True, ensure_ascii=False))
            return (
                0
                if not inventory["structural_blockers"]
                and not inventory["recoverable_blockers"]
                else 1
            )
        if detect_project_marker_state(root) == PROJECT_V3:
            print(json.dumps({"state": PROJECT_V3, "action": "none"}, sort_keys=True))
            return 0
        if args.input is None:
            raise ProjectError("migrate --apply requires --input for a v2 project")
        input_path = args.input.expanduser().resolve()
        try:
            input_path.relative_to(root)
        except ValueError:
            pass
        else:
            raise ProjectError("Migration semantic payload must be outside the project")
        result = migration_apply(root, load_json_payload(input_path))
        input_path.unlink(missing_ok=True)
        print(
            json.dumps(
                {
                    "state": result.state,
                    "decision_memories": result.decision_memories,
                    "attention_entries": result.attention_entries,
                    "reviewed_files": result.reviewed_files,
                },
                sort_keys=True,
            )
        )
    elif args.command == "audit-recover":
        result = audit_recover(root, args.stage_name)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    elif args.command == "function-audit":
        audit_path, action = create_or_locate_function_audit(
            root,
            args.function_name,
            args.source,
            args.risk_reason,
        )
        print(f"{action}: {audit_path}")
    elif args.command == "index":
        project_file = refresh_index(root)
        print(f"Updated current project map: {project_file}")
    elif args.command == "validate":
        report = validate_project(root)
        print_validation(report)
        if report.state == MIGRATION_REQUIRED and not report.errors:
            return 2
        return 0 if report.ok else 1
    else:
        parser.error(f"Unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProjectError as exc:
        print(f"stepwise-r-project error: {exc}", file=sys.stderr)
        raise SystemExit(1)
