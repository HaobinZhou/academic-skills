# ADHD Academic Tutor

ADHD Academic Tutor is a skill package for guided academic literature reading and writing practice. It is designed for learners who get stuck on English-language papers, lack field structure, and need a tutor-like workflow that plans sessions, assigns selected original-source reading, calibrates reading time, and maintains local memory for continuity.

## What It Does

- Runs guided thematic literature surveys.
- Assigns targeted deep-reading segments instead of whole papers by default.
- Adds a short Read-First Base before source reading.
- Uses generous early time ranges and calibrates from real feedback.
- Validates completion with low-pressure checks.
- Records evidence-backed achievements for confidence rebuilding.
- Maintains local Markdown/JSON memory outside the skill folder.

## First-Time Memory Setup

On each new machine, create the private local memory directory before first use:

```bash
python3 scripts/init_memory.py
```

By default this creates:

```text
~/.adhd-academic-tutor/memory/
```

To use a custom private memory location:

```bash
python3 scripts/init_memory.py --memory-dir /path/to/private/memory
```

The skill will run first-time onboarding if `user_cognitive_profile.md` says `Status: not onboarded`.

## Repository Layout

```text
adhd-academic-tutor/
├── SKILL.md
├── README.md
├── agents/openai.yaml
├── scripts/init_memory.py
└── references/
    ├── memory_schema.md
    ├── report_templates.md
    └── session_protocols.md
```

## Notes

The skill is designed to preserve source-facing learning. It can reduce friction around English academic papers, but it should not permanently replace reading original paper sections.
