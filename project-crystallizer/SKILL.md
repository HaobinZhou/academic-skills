---
name: project-crystallizer
description: Turn a project's current burst of useful work into a durable, evidence-backed handoff or freeze point without expanding the original vision. Use only when the user explicitly or strongly implicitly asks to crystallize, freeze, package, archive, hand off, release, or make a project safely pausable/resumable; do not invoke for ordinary coding or open-ended exploration.
---

# Project Crystallizer

Preserve useful work while interest is present. Treat the current burst as the
scope: do not try to finish the project's larger Vision. End with either a
HANDOFF for a natural recipient or a FREEZE / RELEASE for a solo project.

## Operating Rules

- Activate only for explicit or strongly implied closure intent. Examples:
  "crystallize this project", "freeze this", "package what we have", "prepare
  this for handoff", "archive this without losing the work", and "make this
  resumable in a few months".
- State that crystallization is active and lock the scope before editing.
- Preserve information. Do not delete useful history, data, notebooks,
  experiments, outputs, or code merely because they are untidy.
- Classify any new feature, ambitious refactor, new research question, or
  optional analysis as FUTURE. During closure, implement only a blocker for
  existing functionality or a cheap change needed for usability,
  reproducibility, understanding, or safe resumption.
- Do not provide productivity coaching, artificial deadlines, shame, or
  motivation. This is artifact preservation and closure engineering.
- Do not publish, push, upload, disclose sensitive data, or create an external
  release unless the user explicitly authorizes it.

## Workflow

### 1. Inspect Before Editing

Recover context from the repository instead of making the user reconstruct it.
Inspect, as relevant:

- `git status`, recent history, branches, and tags;
- repository structure, README, `AGENTS.md`, and existing docs;
- source, tests, notebooks, scripts, configuration, dependency manifests,
  checkpoints, outputs, logs, and manuscript files;
- TODO/FIXME notes, issue files, benchmarks, and generated artifacts.

Run the bundled snapshot helper when useful:

```bash
python3 /path/to/project-crystallizer/scripts/repo_snapshot.py /path/to/repo
```

The helper reports names and Git metadata only. It does not run project code or
copy file contents. In a Git repository it reports `TRACKED` and `UNTRACKED
NON-IGNORED` files separately, surfaces a conservative list of potentially
important ignored artifact paths, and uses the actual Git root when invoked
from a subdirectory. Use normal repository tools for deeper, targeted
inspection.

### 2. Reconstruct the State

Before closure edits, write a concise evidence-backed reconstruction in the
working notes or directly in the closure report. Separate:

- **Vision**: the larger ambition inferred from the project;
- **Current Burst**: what this period actually attempted;
- **Verified**: components supported by tests, commands, outputs, or files;
- **Partial**: present but incomplete, fragile, or only partly tested;
- **Known Broken**: known failures and their evidence;
- **Unknown**: claims that cannot be determined from available evidence.

Never convert an inference into a verified claim. Record the command, file,
test, benchmark, or output that supports important statements.

Use this project-state taxonomy consistently:

- **VERIFIED**: evidence supports that the component works as claimed;
- **PARTIAL**: the component exists but works only partially, incompletely, or
  under limited conditions;
- **KNOWN BROKEN**: evidence supports that the component currently fails;
- **UNKNOWN**: available evidence is insufficient to classify it.

### 3. Define the Crystallizable Unit

Choose the smallest coherent artifact that captures the useful result. It may
be a runnable prototype, benchmarked model, reproducible experiment, analysis
pipeline, manuscript package, CLI tool, web prototype, or negative result.
Write exactly:

> The crystallizable unit for this burst is: ...

Do not select the largest possible artifact by default.

### 4. Choose the Exit Mode

Infer the mode whenever possible:

- **HANDOFF**: a supervisor, collaborator, research team, reviewer, client, or
  maintainer is the natural receiver. Optimize for review, testing, and
  continuation without reconstructing the author's memory.
- **FREEZE / RELEASE**: the user is the only active worker. Optimize for a
  stable, accurately labeled version that can survive loss of interest. A
  partial `v0.1` is valid; Vision completion is not required.

Ask only when the distinction materially changes the work and cannot be
reasonably inferred.

### 5. Set the Closure Boundary

Make three explicit buckets before implementation:

- **MUST CLOSE**: required to use, reproduce, understand, or safely resume the
  crystallizable unit;
- **NICE TO CLOSE**: cheap improvements that materially increase durability;
- **FUTURE**: everything else, including tempting features and new analyses.

Do not move FUTURE items back into active scope without explicit user
instruction. Put substantial FUTURE items in the parking lot with their value,
current evidence, blocker, and likely next experiment.

Apply this hard stop: once every MUST CLOSE item is complete or honestly
converted into a documented KNOWN BROKEN or other known limitation, stop closure
implementation and proceed to verification and HANDOFF or FREEZE. NICE TO CLOSE
items must never block crystallization. Prefer a documented limitation plus a
freeze over another development cycle.

Unless strictly required to restore existing functionality, classify these as
FUTURE: new dependencies, architecture redesign, a new major abstraction,
model, algorithm, experiment, research question, sensitivity analysis,
multi-subsystem refactor, broad cleanup, unrelated performance optimization, or
feature expansion.

### 6. Execute Cheap Closure Work

Adapt to the project. Typical allowed work includes fixing an obvious blocker,
making the principal entry point run, adding a focused smoke test, documenting
dependencies and commands, checking checkpoint compatibility, preserving a key
benchmark, clarifying configuration, or adding minimal restart-safe error
handling. Avoid broad refactors and architecture redesigns.

For research or manuscript projects, package existing figures, tables, results,
provenance, and manuscript materials. Do not invent analyses to improve the
story or silently change frozen estimands/specifications. For software or AI
projects, prioritize a runnable entry point, dependency setup, smoke tests,
configuration, checkpoints/models, benchmark preservation, limitations, and
restart instructions.

### 7. Verify Claims

Run the narrowest useful tests, build commands, example commands, benchmarks,
or reproduction steps. Record results under these labels:

- **VERIFIED**: actually run and passed, with command and expected output;
- **NOT VERIFIED**: plausible but not tested in this closure;
- **KNOWN BROKEN**: tested or clearly evidenced failure;
- **NOT APPLICABLE**: irrelevant to this project.

Do not claim reproducibility without testing when testing is practical. Do not
turn a failed test into a reason to expand scope; document it and decide whether
it is a MUST CLOSE blocker or a known limitation.

Keep verification actions separate from project state. Use `VERIFIED`, `NOT
VERIFIED`, `KNOWN BROKEN`, and `NOT APPLICABLE` only for commands, tests, or
reproduction checks attempted during crystallization.

### 8. Write Durable Project Memory

Follow good existing documentation conventions. Otherwise create one compact
closure location, normally `docs/PROJECT_CRYSTALLIZATION.md`. Use
`references/closure-report.md` as the minimum-content template. The durable
memory must include:

- project identity, Vision, Current Burst, and crystallizable unit;
- what works, what is partial, what is broken, and what is unknown;
- architecture and important decisions with rationale;
- key results and benchmark evidence;
- important file locations and environment assumptions;
- exact setup, run, test, benchmark, and expected-output commands;
- data, checkpoint, and result locations plus platform limitations;
- verification labels and evidence;
- unresolved risks and why work stopped here;
- a compact **Dead Ends / Rejected Directions** section for every meaningful
  rejected approach, not only projects whose main outcome is negative;
- a FUTURE / NEXT IDEAS parking lot;
- the mandatory sentence: **If this project is reopened months later, begin
  here.** Follow it with the first 1-3 concrete actions.

For HANDOFF, add a concise receiver-facing summary using
`references/handoff-summary.md`: changes since the previous state, ready-for-
review items, major decisions, decisions needing receiver input, exact files,
and limitations. For FREEZE / RELEASE, use
`references/freeze-release.md` to label the boundary, release contents, known
limitations, verification, and restart point.

For research, use `references/negative-result.md` when a failed or low-value
direction is part of the result. Preserve negative knowledge: failed methods,
slow approaches, contradicted hypotheses, rejected architectures, and the
evidence and conditions behind each conclusion.

For every project, use `references/closure-report.md` to record each meaningful
dead end with only: direction, what was tried, evidence, why it was rejected,
and conditions that could justify reopening it. Keep the separate negative
result template for projects whose main crystallized outcome is itself negative.

### 9. Establish a Local Freeze Point

If Git is used, inspect the diff and keep unrelated user changes separate. When
appropriate for the repository and requested closure, create a local, clearly
identified commit or version marker. Do not rewrite history. Suggest a tag or
release note when useful, but do not tag, push, publish, or expose private data
without explicit authorization.

### 10. Perform a Cold-Start Review

Evaluate only the repository and its durable documents as if a fresh Codex
instance had roughly ten minutes and no conversation memory. Confirm it can
answer:

- what the project is and what the Vision was;
- what the Current Burst accomplished;
- what works, what does not, and what remains unknown;
- how to run and verify it;
- why work stopped;
- where to restart.

If any answer requires recovering the author's private memory, improve the
closure package. Use `references/cold-start-checklist.md` to record this pass.

## Output Contract

End with a short closure summary containing:

1. exit mode and crystallizable unit;
2. files changed or created;
3. VERIFIED / NOT VERIFIED / KNOWN BROKEN items;
4. FUTURE parking-lot location;
5. exact restart point;
6. local Git freeze point, if created;
7. material blockers or privacy concerns.

For a negative-result project, explicitly state that stopping is a valid
crystallization outcome when the evidence supports it. Lossless means useful
work is externalized, reproducible or honestly bounded, dead ends are recorded,
future ideas are parked, and the next restart action is clear. It does not mean
perfect, production-ready, publication-ready, or Vision-complete.
