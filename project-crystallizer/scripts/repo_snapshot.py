#!/usr/bin/env python3
"""Create a conservative, metadata-only repository snapshot for closure work."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "target",
    "build",
    "dist",
}

IMPORTANT_IGNORED_DIRS = {
    "artifacts",
    "benchmarks",
    "checkpoints",
    "experiments",
    "figures",
    "logs",
    "models",
    "outputs",
    "reports",
    "results",
    "runs",
}

MANIFEST_NAMES = {
    "AGENTS.md",
    "README.md",
    "Makefile",
    "justfile",
    "pyproject.toml",
    "requirements.txt",
    "environment.yml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "composer.json",
    "DESCRIPTION",
    "renv.lock",
    "Dockerfile",
    "docker-compose.yml",
    "compose.yml",
}

MAX_STATUS_PATHS = 100
MAX_CANDIDATE_DEPTH = 4
MAX_IGNORED_PATHS = 200
MAX_TEST_PATHS = 100


def run_git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def normalize_paths(paths: list[str]) -> list[str]:
    return sorted({Path(path).as_posix() for path in paths if path})


def detect_git_root(requested: Path) -> Path | None:
    root = run_git(requested, "rev-parse", "--show-toplevel")
    return Path(root).resolve() if root else None


def walk_non_git_files(repo: Path) -> list[str]:
    files: list[str] = []
    for root, dirs, names in os.walk(repo):
        dirs[:] = sorted(name for name in dirs if name not in SKIP_DIRS)
        for name in sorted(names):
            path = Path(root, name)
            files.append(path.relative_to(repo).as_posix())
    return normalize_paths(files)


def git_file_lists(repo: Path) -> tuple[list[str], list[str]]:
    tracked = run_git(repo, "ls-files") or ""
    untracked = run_git(repo, "ls-files", "--others", "--exclude-standard") or ""
    return normalize_paths(tracked.splitlines()), normalize_paths(untracked.splitlines())


def candidate_ignored_dirs(repo: Path) -> list[Path]:
    candidates: list[Path] = []
    for root, dirs, _ in os.walk(repo):
        relative = Path(root).relative_to(repo)
        if len(relative.parts) >= MAX_CANDIDATE_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = sorted(name for name in dirs if name not in SKIP_DIRS)
        nested_dirs: list[str] = []
        for name in dirs:
            if name.lower() in IMPORTANT_IGNORED_DIRS:
                candidates.append(Path(root, name))
            else:
                nested_dirs.append(name)
        dirs[:] = nested_dirs
    return sorted(candidates)


def ignored_artifacts(repo: Path) -> tuple[list[str], bool]:
    """Surface ignored files only inside likely artifact directories."""
    paths: set[str] = set()
    for candidate in candidate_ignored_dirs(repo):
        relative = candidate.relative_to(repo).as_posix()
        output = run_git(
            repo,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "--",
            relative,
        )
        if not output:
            continue
        for path in output.splitlines():
            normalized = Path(path).as_posix()
            if not any(part in SKIP_DIRS for part in Path(normalized).parts):
                paths.add(normalized)
    ordered = sorted(paths)
    return ordered[:MAX_IGNORED_PATHS], len(ordered) > MAX_IGNORED_PATHS


def format_lines(value: str, limit: int = 10) -> str:
    lines = value.splitlines()
    shown = lines[:limit]
    output = [f"  - `{line}`" for line in shown] or ["  - (none)"]
    if len(lines) > limit:
        output.append(f"  - Showing {limit} of {len(lines)} entries.")
    return "\n".join(output)


def format_status(status: list[str]) -> str:
    shown = status[:MAX_STATUS_PATHS]
    lines = [f"- Changed paths: {len(status)}", f"- Showing {len(shown)} of {len(status)} changed paths."]
    lines.extend(f"  - `{entry}`" for entry in shown)
    if not status:
        lines.append("  - (clean or unavailable)")
    return "\n".join(lines)


def format_paths(paths: list[str], limit: int | None = None) -> list[str]:
    shown = paths if limit is None else paths[:limit]
    lines = [f"- `{path}`" for path in shown] or ["- (none found)"]
    if limit is not None and len(paths) > limit:
        lines.append(f"- Showing {limit} of {len(paths)} entries.")
    return lines


def render(requested: Path) -> str:
    git_root = detect_git_root(requested)
    repo = git_root or requested
    is_git = git_root is not None

    if is_git:
        tracked, untracked = git_file_lists(repo)
        inventoried: list[str] = []
        ignored, ignored_truncated = ignored_artifacts(repo)
    else:
        tracked = []
        untracked = []
        inventoried = walk_non_git_files(repo)
        ignored = []
        ignored_truncated = False

    all_files = normalize_paths(tracked + untracked + inventoried)
    manifests = [path for path in all_files if Path(path).name in MANIFEST_NAMES]
    tests = [
        path
        for path in all_files
        if any(part.lower() in {"test", "tests", "spec", "specs"} for part in Path(path).parts)
        or Path(path).name.startswith("test_")
    ]
    top_level = sorted({path.split("/", 1)[0] for path in all_files})
    status = (run_git(repo, "status", "--short", "--untracked-files=all") or "").splitlines()
    root_note = [f"- Requested path: `{requested}`"]
    if is_git:
        root_note.append(f"- Detected Git root: `{repo}`")
    else:
        root_note.append(f"- Repository root: `{repo}` (non-Git)")

    lines = [
        f"# Repository Snapshot: `{repo.name}`",
        "",
        "Metadata-only inventory generated by `repo_snapshot.py`. No project code was executed and no file contents were copied.",
        "",
        "## Repository",
        *root_note,
        f"- Git repository: {'yes' if is_git else 'no'}",
        f"- Tracked files: {len(tracked)}",
        f"- Untracked non-ignored files: {len(untracked)}",
        f"- Inventoried files: {len(inventoried)}" if not is_git else "",
        "",
        "## Git State",
        format_status(status) if is_git else "- Not applicable: target is not a Git repository.",
        f"- Branch: `{run_git(repo, 'branch', '--show-current') or '(detached or unavailable)'}`" if is_git else "",
        f"- Recent commits:\n{format_lines(run_git(repo, 'log', '-5', '--oneline') or '(unavailable)')}" if is_git else "",
        f"- Tags:\n{format_lines(run_git(repo, 'tag', '--sort=-creatordate') or '(none or unavailable)', limit=20)}" if is_git else "",
        "",
        "## Structure",
        "- Top-level entries:",
        *[f"  - `{entry}`" for entry in top_level],
        "- Candidate manifests and project instructions:",
        *([f"  - `{path}`" for path in manifests] or ["  - (none found)"]),
        "- Candidate tests/specs:",
        *([f"  - `{path}`" for path in tests[:MAX_TEST_PATHS]] or ["  - (none found)"]),
    ]
    if len(tests) > MAX_TEST_PATHS:
        lines.append(f"  - Showing {MAX_TEST_PATHS} of {len(tests)} entries.")

    if is_git:
        lines.extend(
            [
                "",
                "## File Inventory",
                "### TRACKED",
                *format_paths(tracked),
                "",
                "### UNTRACKED NON-IGNORED",
                *format_paths(untracked),
            ]
        )
    else:
        lines.extend(["", "## File Inventory", "### INVENTORIED (NON-GIT)", *format_paths(inventoried)])

    lines.extend(["", "## Potential Important Ignored Artifacts"])
    if not is_git:
        lines.append("- Not applicable: ignored files are a Git concept.")
    else:
        lines.extend(format_paths(ignored))
        if ignored_truncated:
            lines.append(f"- Showing {MAX_IGNORED_PATHS} of more than {MAX_IGNORED_PATHS} entries; candidates are conservatively bounded.")
        lines.append("- Heuristic scope: likely artifact directories only; dependency/cache directories are excluded.")

    return "\n".join(line for line in lines if line != "") + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--output", type=Path, help="Write Markdown to this file instead of stdout")
    args = parser.parse_args()
    requested = args.repo.expanduser().resolve()
    if not requested.is_dir():
        parser.error(f"repository directory not found: {requested}")
    output = render(requested)
    if args.output:
        args.output.expanduser().resolve().write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
