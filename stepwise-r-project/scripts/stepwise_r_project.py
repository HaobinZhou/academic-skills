#!/usr/bin/env python3
"""Maintain lean, canonical, human-readable Stepwise R projects."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback retains atomic single writes.
    fcntl = None  # type: ignore[assignment]


SCHEMA_MARKER = "<!-- stepwise-r-project:v2 -->"

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

LEGACY_MEMORY_START = "<!-- stepwise-r-project:memory:start -->"
LEGACY_MEMORY_END = "<!-- stepwise-r-project:memory:end -->"

ROLE_ALIASES = {
    "R": ("R", "r"),
    "Data": ("Data", "data"),
    "Results": ("Results", "results", "Output", "output", "Outputs", "outputs"),
    "Audit": ("Audit", "audit"),
}
MEMORY_ALIASES = ("Memory", "memory")

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

    @property
    def ok(self) -> bool:
        return not self.errors


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
            try:
                matches[0].resolve().relative_to(root)
            except ValueError as exc:
                raise ProjectError(
                    f"{role} directory resolves outside the project: {matches[0]}"
                ) from exc
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


def project_md_template(root: Path, roles: dict[str, Path]) -> str:
    return f"""# Project Map

{SCHEMA_MARKER}

Keep this file limited to the current project state and ownership map. Git stores history.

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


def ensure_v2_project(root: Path, *, create: bool) -> tuple[Path, dict[str, Path]]:
    root = root.expanduser().resolve()
    project_file = root / "project.md"
    if project_file.exists():
        text = project_file.read_text(encoding="utf-8")
        if SCHEMA_MARKER not in text:
            raise ProjectError(
                "Existing project.md is not Stepwise R Project v2. Run validate for a "
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
    return project_file, roles


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
    project_file, roles = ensure_v2_project(root, create=False)
    text = project_file.read_text(encoding="utf-8")
    if LEGACY_MEMORY_START in text or LEGACY_MEMORY_END in text:
        raise ProjectError(
            "Legacy Memory index detected. Remove it during an explicit v2 migration; index "
            "will not silently rewrite project history."
        )
    text = replace_block(text, ROLE_START, ROLE_END, role_table(root, roles), "role")
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


def memory_template(
    task_key: str,
    summary: str,
    canonical_topic: str,
    canonical_path: str,
    canonical_section: str,
) -> str:
    section_note = f" (section: `{canonical_section}`)" if canonical_section else ""
    return f"""---
task_key: {json.dumps(task_key)}
canonical_topic: {json.dumps(canonical_topic)}
canonical_path: {json.dumps(canonical_path)}
---

# {summary.strip()}

Canonical source: [{canonical_topic}](<../{canonical_path}>){section_note}

Current definitions belong in that source. Keep only the durable rationale here.

## Change And Reason

- Change:
- Why:

## Verification

Record completed commands and outcomes, not future instructions.

- Verification:

## Open Risks

- Risk:
"""


def create_or_reuse_memory(
    root: Path,
    task_key: str,
    summary: str,
    canonical_topic: str,
) -> tuple[Path, str]:
    root = root.expanduser().resolve()
    project_file, _ = ensure_v2_project(root, create=False)
    task_key = validate_key(task_key, "task key")
    canonical_topic = validate_key(canonical_topic, "canonical topic")
    summary = validate_table_value(summary, "summary")
    with project_write_lock(root):
        text = project_file.read_text(encoding="utf-8")
        topics = {entry.topic: entry for entry in parse_canonical_entries(text)}
        canonical_entry = topics.get(canonical_topic)
        if canonical_entry is None:
            raise ProjectError(
                f"Canonical topic {canonical_topic!r} is not registered; register the "
                "current source before creating semantic change memory"
            )

        memory_dir = detect_optional_directory(root, MEMORY_ALIASES, "Memory")
        if memory_dir is None:
            memory_dir = root / MEMORY_ALIASES[0]
        memory_path = memory_dir / f"{task_key}.md"
        if memory_path.exists():
            metadata = parse_frontmatter(memory_path)
            if metadata.get("task_key") != task_key:
                raise ProjectError(
                    f"Memory task_key does not match filename: {memory_path}"
                )
            if metadata.get("canonical_topic") != canonical_topic:
                raise ProjectError(
                    f"Memory {task_key!r} already belongs to canonical topic "
                    f"{metadata.get('canonical_topic')!r}; refusing to create a parallel "
                    "record"
                )
            return memory_path, "REUSED"

        memory_dir.mkdir(exist_ok=True)
        atomic_write(
            memory_path,
            memory_template(
                task_key,
                summary,
                canonical_topic,
                canonical_entry.path,
                canonical_entry.section,
            ),
        )
        return memory_path, "CREATED_DRAFT"


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
        add_error(report, "project.md is a legacy project without the v2 schema marker")
    if LEGACY_MEMORY_START in text or LEGACY_MEMORY_END in text:
        add_error(report, "project.md still contains the legacy full Memory index")

    blocks = (
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
    excluded_roots.extend(
        path.resolve()
        for path in (root / name for name in IGNORED_PROJECT_DIRS)
        if path.exists()
    )
    documents: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".qmd", ".rmd"}:
            continue
        if path == root / "project.md":
            continue
        resolved = path.resolve()
        if any(
            resolved == excluded or excluded in resolved.parents
            for excluded in excluded_roots
        ):
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
            path.relative_to(roles["Results"].resolve())
        except ValueError:
            add_error(report, f"Registered result is outside Results: {entry.path}")
        if not path.is_file():
            add_error(report, f"Registered result is not a file: {entry.path}")
        artifact_error = result_artifact_error(path, roles["Results"].resolve())
        if artifact_error:
            add_error(report, f"Results contains a {artifact_error}: {entry.path}")
        kind_error = result_kind_error(path, entry.kind)
        if kind_error:
            add_error(
                report, f"Registered result has incompatible metadata: {kind_error}"
            )
        if "R" in roles:
            producer_error = result_producer_error(producer, roles["R"].resolve())
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
        artifact_error = result_artifact_error(path, roles["Results"].resolve())
        if artifact_error:
            add_error(report, f"Results contains a {artifact_error}: {relative}")


def validate_memory(
    root: Path,
    canonical_entries: list[CanonicalEntry],
    report: ValidationReport,
) -> None:
    try:
        memory_dir = detect_optional_directory(root, MEMORY_ALIASES, "Memory")
    except ProjectError as exc:
        add_error(report, str(exc))
        return
    if memory_dir is None:
        return
    canonical_topics = {entry.topic: entry for entry in canonical_entries}
    seen: set[str] = set()
    memory_files = sorted(memory_dir.rglob("*.md"))
    legacy_files = [
        path.name for path in memory_files if LEGACY_MEMORY_NAME.match(path.name)
    ]
    if legacy_files:
        add_error(
            report,
            f"Memory contains {len(legacy_files)} legacy per-change filename(s); v2 requires "
            "one stable file per task key",
        )
    for path in memory_files:
        if path.parent != memory_dir:
            add_error(
                report,
                "Memory files must use the stable Memory/<task-key>.md path: "
                + path.relative_to(root).as_posix(),
            )
        metadata = parse_frontmatter(path)
        task_key = metadata.get("task_key", "")
        if not task_key:
            add_error(report, f"Memory lacks task_key frontmatter: {path.name}")
            continue
        if task_key in seen:
            add_error(report, f"Duplicate Memory task_key: {task_key}")
        seen.add(task_key)
        if path.stem != task_key:
            add_error(report, f"Memory filename does not match task_key: {path.name}")
        topic = metadata.get("canonical_topic", "")
        canonical_entry = canonical_topics.get(topic)
        if canonical_entry is None:
            add_error(
                report,
                f"Memory references an unregistered canonical topic: {path.name}",
            )
        else:
            canonical_path = metadata.get("canonical_path", "")
            if canonical_path != canonical_entry.path:
                add_error(
                    report,
                    f"Memory has a stale canonical path: {path.name}",
                )
        content = path.read_text(encoding="utf-8", errors="replace")
        if canonical_entry is not None:
            expected_link = f"](<../{canonical_entry.path}>)"
            if expected_link not in content:
                add_error(report, f"Memory lacks its canonical link: {path.name}")
        for section in ("Change And Reason", "Verification", "Open Risks"):
            section_error = required_section_error(content, section)
            if section_error:
                add_error(report, f"Memory {section_error}: {path.name}")
        for label in ("Change", "Why", "Verification", "Risk"):
            field_error = required_labeled_field_error(content, label)
            if field_error:
                add_error(report, f"Memory {field_error}: {path.name}")
        if PLACEHOLDER_PATTERN.search(content):
            add_error(report, f"Memory contains an unfinished template: {path.name}")


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
    root: Path, roles: dict[str, Path], report: ValidationReport
) -> None:
    if "Audit" not in roles:
        return
    runs_dir = roles["Audit"] / "Runs"
    if not runs_dir.is_dir():
        return
    root_files = [
        path
        for path in runs_dir.iterdir()
        if not path.is_dir() and path.name != ".DS_Store"
    ]
    if root_files:
        names = ", ".join(path.name for path in root_files)
        add_error(
            report,
            f"Audit/Runs contains files outside a stage/current directory: {names}",
        )
    for stage in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        children = [path for path in stage.iterdir() if path.name != ".DS_Store"]
        invalid = [path for path in children if path.name != "current"]
        if invalid:
            names = ", ".join(path.name for path in invalid)
            add_error(
                report,
                f"Audit stage {stage.name!r} contains historical/staging entries: {names}",
            )
        current = stage / "current"
        if not current.exists():
            add_error(report, f"Audit stage {stage.name!r} has no current directory")
        elif not current.is_dir():
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


def validate_project(root: Path) -> ValidationReport:
    root = root.expanduser().resolve()
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
    validate_function_audits(root, roles, report)
    validate_audit_runs(root, roles, report)
    validate_parallel_copies(root, report)
    return report


def print_validation(report: ValidationReport) -> None:
    status = "PASS" if report.ok else "FAIL"
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
        "init", help="Initialize an idempotent v2 project map."
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
        "memory",
        help="Create or reuse one semantic-change record per stable task key.",
    )
    memory_parser.add_argument("target_dir", type=Path)
    memory_parser.add_argument("--task-key")
    memory_parser.add_argument("--summary")
    memory_parser.add_argument("--canonical-topic")
    memory_parser.add_argument("--magnitude", help=argparse.SUPPRESS)

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
        help="Validate v2 ownership, artifact routing, and current-only contracts.",
    )
    validate_parser.add_argument("target_dir", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.target_dir.expanduser().resolve()

    if args.command == "init":
        project_file, _ = ensure_v2_project(root, create=True)
        refresh_index(root)
        print(f"Initialized Stepwise R Project v2: {project_file}")
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
        if args.magnitude:
            raise ProjectError(
                "--magnitude was removed in v2. Use --task-key and --canonical-topic; one "
                "semantic contract reuses one Memory file."
            )
        if not args.task_key or not args.summary or not args.canonical_topic:
            raise ProjectError(
                "memory requires --task-key, --summary, and --canonical-topic in v2; "
                "per-change logs are not supported"
            )
        memory_path, action = create_or_reuse_memory(
            root,
            args.task_key,
            args.summary,
            args.canonical_topic,
        )
        print(f"{action}: {memory_path}")
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
