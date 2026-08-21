---
name: stepwise-r-project
description: Maintain strict, human-readable scientific R analysis projects with one canonical owner per definition, current publication-facing Results, current-only Audit evidence, Human Attention escalation, consequential Decision Memory, and audits for high-risk functions. Use when initializing, migrating, modifying, freezing, indexing, or validating an R analysis workspace, or when reviewing R code for readable line-by-line RStudio execution.
---

# Stepwise R Project

Keep one current truth for humans. Keep artifact history in Git. Use AI discretion for scientific meaning, not project mechanics. If a decision does not require project-specific scientific or semantic context, let the helper make it deterministically.

## Core Workflow

1. Resolve the target before writing. Inspect `project.md`, relevant canonical sources, R code, Results, Audit, tests, relevant active Attention, and only relevant Decision Memory identified through `Memory/index.md`.
2. Treat the default budget for new Markdown documents as zero. Search the canonical registry and existing documents first.
3. Classify the project as v3, migration required, migration blocked but recoverable, unmanaged, or damaged. Run `init` only for a new unmanaged project; never use it as migration.
4. Resolve one current authority for every scientific definition and cross-script contract. Stop on conflicting owners or ambiguous directory aliases.
5. Perform the authorized work. For every semantic change, update the canonical definition, R implementation, and contract test together.
6. Route current human deliverables to Results and machine verification to Audit. Publish only after staging validation and atomic promotion.
7. Apply the Decision Memory counterfactual test and Human Attention trigger. Do not create either merely because a task ended.
8. Run relevant R, unit, and registered contract tests; run `index`; then require `validate` to exit zero.

## Existing v2 Projects

If the target has a recognized v2 marker, do not run `init` or edit v3 managed state directly. A healthy v2 project is `MIGRATION_REQUIRED`, not an invalid v3 project.

1. Run `migrate TARGET --check` read-only. Read project status, recoverable and structural blockers, migration write-set, dirty paths and overlaps, legacy Memory, and Audit staging separately.
2. Treat mechanically clear failed/incomplete Audit staging as `MIGRATION_BLOCKED_RECOVERABLE`, not project damage. Run `audit-recover TARGET --stage STAGE`, confirm the recovery manifest is outside the project, and rerun preflight. Never recover an ambiguous entry automatically.
3. Require only migration write-set paths (`project.md`, Memory, Attention, and reported helper metadata) to be free of conflicting changes. Unrelated dirty R, Results, or document paths may remain and must stay byte-for-byte and Git-state unchanged; never stash the whole project automatically.
4. Review every inventoried legacy Memory as an input container, not a migration unit. Extract each qualifying consequential decision independently and apply the Human Attention test separately; never convert a whole file merely because it exists. Ask the human only when genuine scientific ambiguity prevents classification.
5. Read [managed-systems.md](references/managed-systems.md) and create the complete semantic JSON payload outside the project. Explicitly account for every old file, including files producing no v3 entry.
6. Run `migrate TARGET --apply --input TEMP_JSON`. Let the helper stage, validate, promote, protect unrelated dirty paths, and roll back; never create migration backups or staging inside the project.
7. Require the promoted project to pass v3 `index` and `validate` before continuing normal work. Treat rollback failure as a hard blocker.

Preserve adopted R/Data/Results/Audit aliases, canonical topics and owners, verification paths, statuses, Result IDs and files, Function Audits, Audit `current/`, R code, data, and scientific content. Migration upgrades governance state only; it does not rerun analyses or redesign the research project.

Migration transactions stage only the managed migration write set. Never clone, copy, hardlink, or otherwise materialize the full scientific project; unchanged R, Data, Results, Audit current evidence, and other content remain in place and are read only as needed for candidate validation. Cross-filesystem migration is supported, and `EXDEV` must never trigger recursive full-project copying.

For already-v3 projects, `migrate --check` and repeated `--apply` perform no migration. For unmanaged, ambiguous, or damaged projects, do not guess; report the required repair.

## Current-State Ownership

- Canonical answers what the current scientific truth or project contract is.
- Git answers what files and code changed.
- Audit holds verification, provenance, diagnostics, and current run state.
- Attention holds unresolved material issues requiring human awareness or decision.
- Decision Memory explains why a consequential design decision happened.

Never route verification to Memory, unresolved risk to Memory, decision rationale to Audit, or current definitions to history records.

## Canonical Ownership

- Register one stable topic key and exactly one Markdown, QMD, or Rmd owner for each scientific definition, variable meaning, or cross-script/output contract.
- Use only `Status: draft`, `Status: partially-frozen`, or `Status: frozen`. Treat frozen as current authority, not immutable history.
- Keep frozen content free of unresolved scope, stale counts, execution status, and run history.
- Before changing frozen semantics, lower the status; revise definition, implementation, and contract test; run the test; then restore the justified status.
- Treat the registered verification path as a contract to execute, not proof of execution.
- Use `canonical --replace` only for an explicit ownership migration and resolve the former owner in the same task.
- Never create `_old`, `_new`, `_updated`, backup, dated, or versioned copies. Revise the current owner and rely on Git.
- Treat rendered HTML/PDF as a view or registered Result, never a second editable source.

## R Writing Rules

- Keep scripts runnable line by line in RStudio with visible packages, paths, seeds, inputs, outputs, and important intermediate objects.
- Use RStudio section headers for import, cleaning, analysis, validation, and export blocks.
- Keep scientifically important transformations in short pipelines or named steps.
- Use concise Chinese comments to explain why control points and transformations exist.
- Avoid hidden global state, deeply nested expressions, and whole-analysis wrapper functions.
- Preserve stable object names when they carry the same meaning across scripts.

## Results And Audit

- Retain only publication or formal-review tables, figures, cohort flows, codebooks, and reports in Results. Register each with a stable ID, kind, audience, and producing R script.
- Rebuild the same registered path when a deliverable changes. Use `result --replace` only for an intentional contract move.
- Put reusable machine data in Data. Put QA, provenance, manifests, diagnostics, traces, and session state in Audit.
- Build run output in a stage-specific system temporary directory. Validate schema, provenance, acceptance, and read-back there.
- Atomically replace the whole `Audit/Runs/<stage>/current/` tree only after checks pass. Publish Results afterward.
- Leave the prior `current/` untouched on failure. Keep no persistent staging, dated, historical, or backup sibling.

## Human Attention

Raise Attention only when a concern is material, unresolved, outside ordinary authorized work, requires added authorization/scientific judgment/substantial scope, has concrete evidence, and has no equivalent active entry. Raising an issue never grants authority to resolve it.

Noteworthy does not mean Attention. Known pending work is not Attention when no new human decision is required, current Canonical/Audit state already represents it, and an authorized workflow already contains its resolution.

Use `blocking: true` when the issue could materially undermine analysis correctness or interpretation, including eligibility, time zero, exposure, outcomes, joins, missingness, censoring, weighting, models, inference, denominators, provenance, or reported numbers. Do not claim the affected analysis complete while such an issue remains unresolved.

Do not use Attention for formatting, naming, package upgrades, routine refactoring, generic debt, or speculative improvements. Read [managed-systems.md](references/managed-systems.md) before raising or resolving an entry.

## Decision Memory

Create Decision Memory only when a consequential scientific or technical decision passes this test:

> Without an explicit record, could a future AI with the current project and Git history plausibly fail to explain why the decision was made, or unknowingly reintroduce a rejected approach?

Valid events preserve non-obvious causal history such as failed prior designs, diagnostic-driven strategy changes, collaborator/reviewer requirements, data-imposed compromises, or deliberately rejected credible methods. Prefer the pattern: previously X; observed Y; therefore decided Z.

Consequential technical or execution architecture also qualifies when its causal rationale is durable and cannot be reconstructed from current code, Canonical, and Git. For example: the project previously used one execution architecture; real resource behavior made it unsafe at project scale; the project therefore changed storage, concurrency, worker memory, or spill policy; future maintainers should not restore the former design without new evidence.

Do not record routine bugs, package compatibility fixes, ordinary normalization, local optimization, refactors, tests, reruns, commands, file lists, benchmarks, progress/status summaries, unchanged results, information already in Canonical or Git, Audit evidence, or unresolved concerns unless they caused a durable consequential design decision whose rationale would otherwise be lost. A task ending is never a trigger. `related_topics: []` is valid. Read [managed-systems.md](references/managed-systems.md) before adding an entry or declaring relationships.

## Function Policy

- Create functions only for genuine reuse or meaningfully error-prone repeated logic. Give every function Roxygen documentation and executable tests.
- Create a Function Audit when an error could alter eligibility, time windows, joins/deduplication, exposure, outcomes, missingness, censoring, weighting/modeling, aggregation/denominators, or a cross-script/output contract.
- Keep one `Audit/Functions/audit_<function>.Rmd` per high-risk function. Update it in place with its source hash, purpose/risk, contract, edge cases/tests, and known limits.
- Do not retain rendered Function Audit HTML. Treat `UPDATE_REQUIRED` as an instruction to update the returned Rmd.

## Helper Commands

Run `scripts/stepwise_r_project.py` using its absolute skill path:

```text
init TARGET
migrate TARGET --check
migrate TARGET --apply --input TEMP_JSON
audit-recover TARGET --stage STAGE
canonical TARGET --topic KEY --path PATH [--section HEADING] --verification TEST_PATH [--replace]
result TARGET --id KEY --path PATH --kind KIND --audience AUDIENCE --producer PATH [--replace]
attention raise TARGET --input TEMP_JSON
attention resolve TARGET --id A-XXXX
memory add TARGET --input TEMP_JSON
function-audit TARGET --function NAME --source PATH --risk-reason TEXT
index TARGET
validate TARGET
```

Let the helper own IDs, paths, fixed schemas, indices, relationships, lifecycle mechanics, and atomic writes. Never hand-edit managed indices or relationship reverse links.

## Completion Gate

1. Run relevant R/unit tests and every contract test linked to changed canonical topics.
2. Confirm no second current definition, stale frozen content, parallel old/versioned document, unregistered Result, or invalid Audit run tree remains.
3. Complete any triggered Function Audit. Evaluate Decision Memory and Attention explicitly; "none required" is normal.
4. Do not claim an affected analysis complete while a relevant blocking Attention undermines correctness.
5. Require Memory and Attention indices to match entries and no legacy/alternative managed topology to remain.
6. Run `index`, then require `validate` to exit zero.
7. Report current deliverables, verification, migration behavior when applicable, and unresolved blockers.
