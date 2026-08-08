---
name: stepwise-r-project
description: Maintain lean, human-readable R analysis projects with one canonical owner per scientific definition, current publication-facing Results, current-only machine QA, conditional semantic Memory, and audits only for high-risk functions. Use when initializing, modifying, freezing, indexing, or validating an R analysis workspace, or when reviewing existing R code for readable line-by-line RStudio execution.
---

# Stepwise R Project

Keep one current truth for humans. Keep history in Git. Do not create documents merely to prove that work occurred.

## Core Workflow

1. Resolve and inspect the target project before writing. Read `project.md`, existing documentation, R scripts, Results registrations, Audit, relevant tests, and any applicable Memory.
2. Treat the default budget for new Markdown files as zero. Search the canonical registry and existing documents before proposing a new document.
3. Run `init` only for a new project or an existing confirmed v2 project. Adopt one existing directory alias per role. Stop on ambiguous aliases.
4. If `project.md` lacks the v2 marker, run `validate` read-only and report migration needs. Do not initialize over it, append managed blocks, move files, or delete files.
5. Register one owner for every scientific definition or cross-script contract. Edit that registered file or section in place.
6. Write readable R code and update the canonical definition, implementation, and contract test together for every semantic change.
7. Route human deliverables to Results and machine evidence to Audit. Keep failed runs in a temporary location, not in the project.
8. Create Memory or a Function Audit only when its trigger below is met.
9. Run relevant tests, refresh `project.md` with `index`, then run `validate`. Do not claim completion while validation fails.

## Project Roles

- `R/` or its adopted alias: human-readable R scripts.
- `Data/` or its adopted alias: raw and derived machine-readable data, including RDS/RData. Never overwrite raw inputs without explicit authorization.
- `Results/` or its adopted alias: current publication or formal-review tables, figures, cohort flows, codebooks, and collaborator reports only.
- `Audit/` or its adopted alias: machine QA, traces, acceptance checks, manifests, session information, diagnostics, and high-risk Function Audits.
- `Memory/` or an existing `memory/`: optional rationale for semantic contract changes. Create it only on demand.
- `project.md`: current directory roles, canonical sources, R scripts, current Results, and high-risk Function Audits.

Do not create a standard directory beside an existing synonymous directory. If two directories already claim the same role, stop and ask the user to resolve ownership.

## Canonical Ownership

- Register each scientific definition, data definition, variable meaning, or cross-script/output contract under one stable topic key.
- Use exactly one canonical Markdown, QMD, or Rmd path or section per topic.
- Search `project.md` and existing documents before creating anything. If the topic exists, update its registered source in place.
- Treat `frozen` as "current authority", not "immutable file". Revise the same source when the authority changes.
- Use only `Status: draft`, `Status: partially-frozen`, or `Status: frozen` in the owned document or section.
- Use `partially-frozen` when some scope remains unresolved, and identify that scope explicitly.
- Keep `frozen` content free of TODOs, pending decisions, stale counts, `run_id`, PASS/BLOCKED entries, and execution history.
- Keep run state under Audit and formal findings under Results. Never insert execution ledgers into a canonical protocol.
- Before changing frozen semantics, set the same source to `draft` or `partially-frozen`; update the definition, implementation, and contract test; run the test; then restore the justified status.
- Treat the verification path in the registry as a contract, not proof that the test ran. Execute it after every related semantic change.
- Use `canonical --replace` only for an explicit ownership migration. Resolve the former owner in the same task.
- If multiple files claim the same current fact or contain conflicting definitions, stop and report the paths. Do not create a third summary or reconciliation document.
- Never create `_old`, `_new`, `_updated`, `_backup`, dated, versioned, or separate "freeze update" copies. Use Git for history.
- Treat rendered HTML/PDF as a view or registered Result, never as a second editable source.

## R Writing Rules

- Make scripts runnable line by line in RStudio.
- Use RStudio section headers to separate import, cleaning, analysis, validation, and export blocks.
- Keep important intermediate objects visible and descriptively named.
- Keep pipelines short; split scientifically important transformations into named steps.
- Use concise Chinese comments to explain why control points and transformations exist.
- Keep package loading, paths, seeds, inputs, and outputs visible.
- Avoid hidden global state, deeply nested expressions, and whole-analysis wrapper functions.
- Preserve stable object names when they represent the same concept across scripts.

## Results And Run Audit

- Retain a file in Results only when a publication reader, reviewer, or collaborator is its direct audience.
- Register every retained Results file with a stable ID, `kind`, `audience`, and producing R script.
- Use `kind` values `table`, `figure`, `cohort-flow`, `codebook`, or `report`; use audience `publication` or `formal-review`.
- Rebuild or overwrite the same registered path when a deliverable changes. Use `result --replace` only when its stable ID intentionally moves to a different path or contract.
- Permit genuinely different human formats, such as CSV and Markdown, only when each has its own reader-facing use and registration.
- Never place audit, trace, acceptance, manifest, session, log, status, cache, staging, backup, legacy, invalidated, RDS, or RData artifacts in Results.
- Put reusable machine data in Data. Put current QA and provenance in `Audit/Runs/<stage>/current/`.
- Build each run in a stage-specific temporary directory. Do not stream partial outputs into Results or Audit `current`.
- Run acceptance, schema, provenance, and read-back checks against staging.
- After all checks pass, replace the whole `Audit/Runs/<stage>/current/` directory as one promotion. Do not merge new files into an old `current` tree.
- Publish and register Results only after successful Audit promotion.
- On failure, leave the prior `current` untouched. Keep diagnostics in the system temporary directory only, and report that path or the relevant diagnostics in the response.
- Remove transient staging before normal handoff. Any historical, dated, or staging sibling beside `current` makes the project invalid.

## Memory Trigger

Create or update Memory only when at least one of these semantics changes:

- data inclusion, derivation, or source definition;
- analysis logic or scientific assumption;
- variable meaning;
- output contract;
- cross-script interface.

Do not create Memory for comments, formatting, equivalent refactors, test additions, index refreshes, pure reruns, unchanged numerical results, or presentation-only revisions.

- Register the related canonical topic before creating Memory.
- Use one stable `Memory/<task-key>.md` per scientific or technical contract. Reuse it across sessions.
- Update that file in place. Never use dates, magnitude labels, or `-2`/`-3` suffixes.
- Keep the current full definition in the canonical source, not in Memory.
- Record only the durable reason for change, canonical link, verification, and remaining risk.
- Record completed verification commands and outcomes, not instructions for a future run.
- Complete every generated placeholder before validation.
- Do not index every Memory file in `project.md`.

## Function Policy

- Do not create functions preemptively. Use them for genuine reuse or meaningfully error-prone repeated logic.
- Give every function Roxygen documentation and executable tests.
- Create a Function Audit only when an error could alter eligibility, time windows, key joins/deduplication, exposure/strategy, outcomes, missingness/imputation, censoring, weighting/modeling, aggregation/denominators, or a cross-script/output contract.
- Require only Roxygen and tests for formatting, paths, labels, display helpers, and other low-risk utilities.
- Keep one stable `Audit/Functions/audit_<function>.Rmd` per high-risk function.
- Update the same Rmd whenever relevant source behavior changes. Update its `source_sha256` after reviewing the current source.
- Record purpose and risk, input/output contract, edge cases and executable tests, and known limits.
- Do not retain rendered Function Audit HTML.
- Treat `UPDATE_REQUIRED` as an instruction to edit the returned existing Rmd, not permission to create another audit.

## Helper Commands

Run the bundled `scripts/stepwise_r_project.py` with its absolute Skill path:

```text
init TARGET
canonical TARGET --topic KEY --path PATH [--section HEADING] --verification TEST_PATH [--replace]
result TARGET --id KEY --path PATH --kind KIND --audience AUDIENCE --producer PATH [--replace]
memory TARGET --task-key KEY --summary TEXT --canonical-topic TOPIC
function-audit TARGET --function NAME --source PATH --risk-reason TEXT
index TARGET
validate TARGET
```

- Expect these commands to be idempotent for unchanged inputs.
- Do not use the removed `--magnitude` interface.
- Do not use `init` as a migration command.
- Use `index` only on a v2 `project.md` with intact managed markers. Resolve legacy or duplicate sections explicitly.

## Completion Gate

1. Run relevant R tests, unit tests, and every contract test linked to changed canonical topics.
2. Confirm no second current definition, stale frozen content, or parallel old/versioned document exists.
3. Confirm Results contains only registered current human deliverables.
4. Confirm each Audit run stage contains at most one `current/` tree and no persistent staging or historical siblings.
5. Complete any Memory or Function Audit that was actually triggered.
6. Run `index`, then require `validate` to exit zero.
7. Report current deliverables, verification performed, and unresolved blockers. Mention Memory or Function Audit only when one was genuinely required.
