# Memory Schema

Default memory root resolution:

1. `ADHD_TUTOR_MEMORY_DIR` environment variable
2. `~/.adhd-academic-tutor/memory`
3. workspace-local `state/adhd-academic-tutor/` only if the user explicitly asks for project-local memory

On a new machine, initialize memory with:

```bash
python3 adhd-academic-tutor/scripts/init_memory.py
```

To choose a custom private memory location:

```bash
python3 adhd-academic-tutor/scripts/init_memory.py --memory-dir /path/to/private/memory
```

Do not commit memory files. They contain personal learning context.

## Memory Files

Use this 4+1 structure:

| File | Purpose |
| --- | --- |
| `user_cognitive_profile.md` | Stable learner profile, English pain profile, time calibration, resistance triggers, preferred recovery moves |
| `academic_knowledge_graph.md` | Field map, topic curriculum, concept mastery, deep-reading bank, writing pattern bank, supervisor-ready talking points |
| `reading_backlog_master.md` | Paper backlog, source-reading log, task status, skipped/deferred items |
| `achievement_log.md` | User-visible record of evidence-backed academic wins, unlocked skills, and confidence-building milestones |
| `session_context.json` | Current-session state only |
| `memory_manifest.json` | Initialization metadata and schema marker |

If any required file is missing, run `scripts/init_memory.py` before continuing. If the script cannot be run, create the required files manually from this reference.

## Durable Entry Fields

Every durable memory entry should include these fields when possible:

```text
id:
created_at:
updated_at:
source_session:
evidence:
confidence:
status:
next_action:
```

Allowed `confidence` values:

- `low`
- `medium`
- `high`

Useful `status` values:

- `active`
- `mastered`
- `uncertain`
- `stale`
- `blocked`
- `deferred`

## File-Level Rules

### user_cognitive_profile.md

Record how the user learns:

- onboarding status
- field, project, degree stage, current deliverable
- English pain points
- startup difficulty patterns
- time calibration
- task types that trigger avoidance
- task types that allow startup
- effective recovery moves
- resistance-reducing wording that worked

### academic_knowledge_graph.md

Use stable sections:

```text
## Topic Curriculum
## Concept Mastery
## Deep Reading Bank
## Writing Pattern Bank
## Supervisor-Ready Talking Points
```

Do not let this file become an undifferentiated note dump.

### reading_backlog_master.md

Record literature state:

- pending broad survey papers
- pending deep-reading papers
- completed source segments
- skipped or deferred papers with reasons
- next source segment to read
- how each paper fits the knowledge graph

### achievement_log.md

Record only evidence-backed wins:

- completed original-source segment
- concept unlocked
- writing move learned
- figure or table understood
- returned after getting stuck
- time estimate improved
- supervisor-ready talking point created

Avoid empty praise.

### session_context.json

Use only for current-session state:

```json
{
  "active_mode": "",
  "active_paper_id": "",
  "assigned_segment": "",
  "assigned_time_range": "",
  "start_time": "",
  "soft_checkin_due": "",
  "pending_validation": false
}
```

Do not use this file as long-term memory.

## Write Timing

Write memory at these moments:

1. After onboarding is completed.
2. After assigning a source-facing task.
3. When the user says `start` or `开始`.
4. When the user returns with completion, partial completion, or failure.
5. After low-pressure validation.
6. At session close.

## First-Run Onboarding Write

After the first onboarding, update `user_cognitive_profile.md`:

- Change `Status: not onboarded` to `Status: onboarded`.
- Fill field, project, degree stage, current deliverable, supervisor expectations, and deadline.
- Record English pain points and startup barriers.
- Record the first starter task type and why it was chosen.

Then assign a starter source-facing task. Do not assign a task before onboarding if the profile is missing or incomplete.

## Update Rules

- Save durable, reusable facts; do not save full chat transcripts.
- Prefer appending corrections over overwriting old memory.
- Mark stale or wrong memory instead of deleting it.
- Record failure without shame: `blocked`, `partial`, and `deferred` are valid states.
- Convert vague self-report into concrete evidence before saving.
- Keep entries short enough to be read in future sessions.
- If memory conflicts with the user's latest statement, follow the latest statement and record the correction.

## Software Policy

Use Markdown and JSON as the default memory substrate.

Recommended lightweight validation:

- JSON Schema or Pydantic-style validation for `session_context.json`.
- Optional schema checks for structured blocks inside memory files.

Do not introduce Notion, database systems, vector stores, or heavy knowledge-base software in the first version.

Zotero may be used separately for PDF, DOI, and BibTeX management, but it is not the tutor memory system.
