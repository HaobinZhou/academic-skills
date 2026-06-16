#!/usr/bin/env python3
"""Initialize ADHD Academic Tutor local memory files."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_MEMORY_DIR = Path.home() / ".adhd-academic-tutor" / "memory"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_file(path: Path, content: str, force: bool) -> str:
    if path.exists() and not force:
        return "exists"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "created" if not path.exists() else "written"


def user_cognitive_profile() -> str:
    ts = now_iso()
    return f"""# User Cognitive Profile

Status: not onboarded
Created at: {ts}
Updated at: {ts}

## Stable Context

- Field:
- Project:
- Degree stage:
- Current deliverable:
- Supervisor expectations:
- Deadline:

## English Pain Profile

- Painful segment types:
- Vocabulary obstacles:
- Sentence patterns that overload working memory:
- Helpful read-first base patterns:

## Startup and Resistance Pattern

- Startup barriers:
- Task types that trigger avoidance:
- Task types that allow startup:
- Resistance-reducing wording that worked:

## Time Calibration

| id | task_type | assigned_range | actual_duration | completion | friction | next_adjustment |
| --- | --- | --- | --- | --- | --- | --- |

## Recovery Moves

- Effective recovery move:
- Ineffective recovery move:

## Corrections

- Add corrections here instead of overwriting old memory.
"""


def academic_knowledge_graph() -> str:
    return """# Academic Knowledge Graph

## Topic Curriculum

## Concept Mastery

| id | concept | evidence | confidence | status | next_action |
| --- | --- | --- | --- | --- | --- |

## Deep Reading Bank

| id | paper | segment | why_it_matters | writing_move | status | next_action |
| --- | --- | --- | --- | --- | --- | --- |

## Writing Pattern Bank

### Gap Framing

### Contribution Language

### Method Rationale

### Causal Wording

### Hedging

### Transition Logic

### Limitation Language

## Supervisor-Ready Talking Points

| id | talking_point | source | evidence | status |
| --- | --- | --- | --- |
"""


def reading_backlog_master() -> str:
    return """# Reading Backlog Master

## Pending Broad Survey Papers

| id | paper | topic | reason | status | next_segment |
| --- | --- | --- | --- | --- | --- |

## Pending Deep-Reading Papers

| id | paper | segment | reason | time_range | status |
| --- | --- | --- | --- | --- | --- |

## Completed Source Segments

| id | paper | segment | completed_at | evidence | achievement_id |
| --- | --- | --- | --- | --- | --- |

## Skipped or Deferred

| id | paper | reason | revisit_condition |
| --- | --- | --- | --- |

## Source Reading Log

| id | created_at | paper | segment | assigned_range | actual_duration | completion | friction | next_action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""


def achievement_log() -> str:
    return """# Achievement Log

This file records evidence-backed academic wins. It is for confidence rebuilding, not empty praise.

## Unlocked Achievements

| id | created_at | achievement | evidence | why_it_matters | related_skill | next_unlock |
| --- | --- | --- | --- | --- | --- | --- |

## Achievement Types

- Original-source segment completed
- Gap-framing move identified
- Figure or table interpreted
- Useful academic phrase saved
- Returned after getting stuck
- Time estimate improved
- Supervisor-ready talking point created

## Recent Confidence Evidence

- Add concrete wins here when the user asks to review progress.
"""


def session_context() -> str:
    return json.dumps(
        {
            "active_mode": "",
            "active_paper_id": "",
            "assigned_segment": "",
            "assigned_time_range": "",
            "start_time": "",
            "soft_checkin_due": "",
            "pending_validation": False,
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"


def manifest(memory_dir: Path) -> str:
    data = {
        "memory_dir": str(memory_dir),
        "created_at": now_iso(),
        "schema": "adhd-academic-tutor-memory-v1",
        "files": [
            "user_cognitive_profile.md",
            "academic_knowledge_graph.md",
            "reading_backlog_master.md",
            "achievement_log.md",
            "session_context.json",
            "memory_manifest.json",
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--memory-dir",
        default=os.environ.get("ADHD_TUTOR_MEMORY_DIR", str(DEFAULT_MEMORY_DIR)),
        help="Directory for local tutor memory. Defaults to ADHD_TUTOR_MEMORY_DIR or ~/.adhd-academic-tutor/memory.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing memory files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    memory_dir = Path(args.memory_dir).expanduser().resolve()
    templates = {
        "user_cognitive_profile.md": user_cognitive_profile(),
        "academic_knowledge_graph.md": academic_knowledge_graph(),
        "reading_backlog_master.md": reading_backlog_master(),
        "achievement_log.md": achievement_log(),
        "session_context.json": session_context(),
        "memory_manifest.json": manifest(memory_dir),
    }

    print(f"Initializing ADHD Academic Tutor memory at: {memory_dir}")
    for name, content in templates.items():
        path = memory_dir / name
        existed = path.exists()
        if existed and not args.force:
            print(f"exists  {path}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"{'updated' if existed else 'created'} {path}")
    print("Done. Keep this directory private; it contains personal learning memory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
