---
name: oppen-project-steward
description: Maintain durable, non-scientific AI-assisted projects with canonical ownership, Git-owned history, current Deliverables, recoverable machine Audit evidence, Human Attention escalation, consequential Decision Memory, deterministic registries, and path-scoped dirty-work protection. Use when initializing or adopting an existing project, upgrading a legacy Steward layout, governing, recovering Audit staging, indexing, escalating material unresolved concerns, recording non-reconstructable decision context, or validating long-lived software, AI application, quantitative engineering, infrastructure, or mixed code/document projects.
---

# Oppen Project Steward

Keep one understandable current project truth. Keep artifact history in Git. Use AI judgment for meaning and the bundled helper for mechanics.

## Core Workflow

1. Resolve and classify the target with `validate` before managed work. For `MANAGED_READY`, read `.oppen-project-steward/registry.md`, relevant Canonical sources, implementation, tests, current Audit, and relevant Deliverables. Navigate active Attention and Decision Memory through their generated indices; do not load every Memory entry.
2. Treat an ordinary unmanaged project as `ADOPTION_REQUIRED`, not damaged. Use `adopt --check`, make only the necessary semantic mappings, then use `adopt --apply`. Stop on `ADOPTION_BLOCKED`; do not invent another namespace.
3. Confirm the project is Git-backed when applicable; the helper never initializes, commits, or rewrites Git history. Use `init` only for a genuinely new project. Use `upgrade-layout` only for a proven `LEGACY_STEWARD_LAYOUT`.
4. Search the canonical registry before adding documentation. Update the registered owner in place instead of creating a parallel version.
5. For a semantic change, update the canonical definition, implementation, and linked verification together, then execute the verification.
6. Retain direct human outputs in Deliverables. Route machine evidence, traces, provenance, diagnostics, and acceptance checks to Audit.
7. Create a High-Risk Contract Audit only when a hidden error could materially alter core behavior, results, safety-relevant contracts, or downstream interpretation.
8. Evaluate Attention only for a material unresolved concern outside current authorization. Raising it does not grant authority to resolve it.
9. Evaluate Memory only at a consequential decision boundary. Never create it merely because a task, session, code change, or test run ended.
10. Do not widen scope when inspection reveals an adjacent issue. Complete the authorized work, then use Attention only if the separate trigger passes.
11. Run relevant tests and registered verification, then run `index` and `validate`. Do not claim completion while validation fails.

## Five Information Systems

- Canonical states what is true now.
- Git preserves historical artifact changes.
- Audit holds machine verification for the current implementation.
- Human Attention exposes material unresolved concerns needing awareness or decision.
- Decision Memory records why a consequential decision happened.

Keep each fact in its owning system. Deliverables are registered current outputs for direct human use, not another history or verification system.

## Runtime State And Managed Writes

- Treat valid current Steward state as `MANAGED_READY`.
- Treat an ordinary existing project with no Steward state as `ADOPTION_REQUIRED`; use `ADOPTION_BLOCKED` only for a concrete adoption conflict.
- Treat deterministic operational blockers as `BLOCKED_RECOVERABLE`; report the blocker, affected paths, and recovery action. Recoverable residue is not governance damage.
- Reserve `DAMAGED` for authority or metadata that cannot be interpreted without semantic or manual repair.
- Use `audit recover` only for clearly failed or incomplete staging. Let the helper verify the external recovery copy and manifest before removing the source; never move `current/` or create an in-project archive.
- Let every mutation use its Managed Operation Write Set. Permit unrelated tracked or untracked Git work and leave it byte-for-byte untouched.
- Stage transaction content and rollback only for the declared Managed Operation Write Set. Never clone, recursively copy, hardlink, reflink, or otherwise materialize the full project. Read unchanged project content in place through a read-only candidate overlay when candidate validation needs it.
- Support cross-filesystem transactions without widening their scope. Treat `EXDEV` as permission to copy only an individual managed file, never the project tree.
- Stop with `MANAGED_WRITESET_CONFLICT` when dirty user-owned paths overlap operation-owned paths. Reconcile only those paths; never stash the whole repository automatically.

## Steward-Owned State

`.oppen-project-steward/**` is Steward-owned managed state. Steward continuity is determined by the helper-managed `.oppen-project-steward/.managed-state.json` baseline, not by comparison with Git HEAD.

- Continue normal Steward operations when managed files match the last successful baseline, whether Git sees them as committed, staged, modified, or untracked. A Git commit is never required merely to continue governance.
- Stop with `MANAGED_STATE_CONFLICT` when `registry.md`, `Memory/**`, `Attention/**`, or `Audit/Contracts/**` differs from the baseline. Inspect and reconcile only the reported paths; never reset them from Git or overwrite unexplained drift.
- Keep user-owned project paths under Managed Operation Write Set Git conflict protection. Referencing a dirty user-owned Canonical owner is allowed; writing a dirty user-owned path is not.
- Exclude `.managed-state.json`, `Audit/Runs/**`, and user project content from the baseline. Let Audit retain its own evidence-integrity checks.
- For a valid pre-4.3 managed project missing only the baseline, run `managed-state TARGET --check`, then `managed-state TARGET --bootstrap`. Bootstrap creates generation 1 without re-adoption, Git mutation, or a required commit. Never bootstrap a damaged or otherwise blocked namespace.

## Project Roles

- Steward owns only `.oppen-project-steward/`, containing `registry.md`, `Memory/`, `Attention/`, and `Audit/` with fixed topology.
- Source, Data, and Deliverables are optional logical roles mapped only to useful existing directories.
- Do not create standard role directories or reject a project because a role is absent.
- Treat root `project.md`, `Memory/`, `Attention/`, and `Audit/` as user-owned unless the legacy upgrade preflight proves old Steward ownership.

Never create a standard directory beside an existing path already serving the same role. Stop on ambiguous supplied mappings.

## Existing Projects

An existing project without Steward metadata is not damaged. If `.oppen-project-steward/` is absent and the target is ordinary, classify it as `ADOPTION_REQUIRED`.

Run `adopt TARGET --check` read-only, then `adopt TARGET --apply --input TEMP_JSON`. Leave root `project.md`, directories, documentation, dirty work, and naming conventions unchanged. Register useful existing roles and authoritative documents by reference; all payload sections may be empty. Adoption stages only `.oppen-project-steward/**`, never materializes the full project, and creates no Attention or Memory merely for adoption.

If validation reports `LEGACY_STEWARD_LAYOUT`, run `upgrade-layout TARGET --check` and then `upgrade-layout TARGET --apply`. Move only mechanically proven old Steward state; never infer ownership from root filenames alone.

## Canonical Ownership

- Register each important semantic definition or cross-component contract under one stable topic key.
- Use one stable file or one stable Markdown section per topic.
- Store one `draft`, `partially-frozen`, or `frozen` status in the registry. Existing files may be registered non-invasively with `--status`; otherwise infer exactly one valid `Status:` field from the owned scope.
- Treat `frozen` as current authority, not immutable history. Revise the same owner when the authority changes.
- Use `canonical --replace` only for an explicit ownership move after resolving the former owner.
- Stop on conflicting owners. Never create `_old`, `_new`, `_updated`, `_final`, `_backup`, dated, or version-number copies. Git stores history.

## Deliverables And Audit

- Register every retained Deliverable with a stable ID, path, kind, audience, and producer.
- Replace the same current output path when it changes. Use `deliverable --replace` only for an intentional path move.
- Keep logs, caches, traces, manifests, staging, backups, historical versions, temporary diagnostics, and serialized machine state out of Deliverables.
- Build run evidence in a system temporary directory, validate it, and atomically promote it to `.oppen-project-steward/Audit/Runs/<stage>/current/`.
- On failure, leave the prior `current/` untouched and keep failed staging outside the project.
- Do not retain siblings such as `previous/`, `run_001/`, dated runs, or `staging/` beside `current/`.
- Promote validated external staging with `audit promote`; let the helper perform internal SHA-256/size read-back verification and replace the whole current tree. No user-authored manifest is required.
- If failed staging already blocks a stage, run `audit recover`, inspect the reported external manifest, then rerun the blocked operation or validation.

## High-Risk Contract Audit

Ask: could a hidden error materially alter core behavior, results, a safety-relevant contract, or downstream interpretation?

If yes, use `contract-audit` to create or locate one stable audit. Complete its four required sections through a temporary JSON payload and `contract-audit --input`; the helper refreshes the reviewed source hash and advances the managed-state baseline transactionally. Reuse the same audit for later changes. If no, normal executable tests are sufficient.

## Human Attention

- Raise Attention only when a concrete, material issue remains unresolved, ordinary task work does not cover it, and resolution needs human judgment, additional authorization, or substantial scope expansion.
- Do not use Attention for upgrades, cleanup, routine debt, naming preferences, speculative ideas, or generic improvement suggestions.
- Keep an item normally non-blocking. If it undermines the requested deliverable's correctness or trustworthiness, do not claim the task complete merely because an item was raised.
- Check `.oppen-project-steward/Attention/index.md` for an equivalent active issue before raising another.
- Resolve an item only after the underlying human decision or authorized work is complete. Resolution deletes the active file; Git preserves history.
- Yes: a critical downstream component violates an intended contract, but correcting its architecture is outside current authorization. No: a package is outdated or naming is slightly inconsistent.
- Noteworthy does not mean Attention. Known pending work is not Attention when the current authorized workflow already defines and permits its resolution.
- Attention is not a TODO system. Exclude planned stages, expected temporary staleness, roadmap work, normal debt, and generic improvements unless the full material, unresolved, out-of-scope, evidence-backed trigger requires a new human decision.

## Decision Memory

- Apply the counterfactual test: without an explicit record, could a future agent with the current project and complete Git history fail to explain a consequential decision or repeat a rejected direction?
- Create one Memory entry only when the answer is yes and the decision is consequential. Do not create one per task, conversation, change, commit, rerun, verification, or unresolved concern.
- Use `supersedes` when a later decision changes direction. Use `invalidates` when later evidence shows a key fact or assumption was wrong. Let the helper update prior status and reverse links.
- Allow zero related canonical topics. Memory records causal history; Canonical records current belief, Audit records verification, and Attention records unresolved significance.
- Never store chain of thought, scratchpads, deliberation transcripts, unresolved-risk fields, or verification logs in Attention or Memory.
- Yes: a real failure or user experience causes an important architectural direction to be abandoned and replaced. No: a routine bug fix passes tests and Git fully explains the change.
- Technical difficulty alone does not justify Decision Memory. Exclude subtle compatibility, parser, optimization, refactor, and isolated defect work when code, tests, and Git explain it.
- Allow consequential architecture, execution, storage, concurrency, reliability, performance policy, operational safety, dependency, deployment, or state-management decisions when the counterfactual test passes.
- An incident alone is Audit, logs, or Git as appropriate. Create Memory only when the incident causes a durable consequential decision whose causal context would otherwise be lost.

## Helper Commands

Run `scripts/oppen_project_steward.py` with its absolute skill path:

```text
init TARGET
adopt TARGET --check
adopt TARGET --apply --input TEMP_JSON
upgrade-layout TARGET --check
upgrade-layout TARGET --apply
managed-state TARGET --check
managed-state TARGET --bootstrap
canonical TARGET --topic KEY --path PATH [--section HEADING] [--status STATUS] --verification TEST_PATH [--replace]
deliverable TARGET --id KEY --path PATH --kind KIND --audience AUDIENCE --producer PATH [--replace]
contract-audit TARGET --topic KEY --source PATH --risk-reason TEXT
contract-audit TARGET --topic KEY --input TEMP_JSON
audit promote TARGET --stage KEY --input STAGING_DIR
audit recover TARGET --stage KEY
attention raise TARGET --input TEMP_JSON
attention resolve TARGET --id A-XXXX
memory add TARGET --input TEMP_JSON
index TARGET
validate TARGET
```

Before using `adopt`, `contract-audit --input`, `attention`, or `memory`, read [references/payload-schemas.md](references/payload-schemas.md). Create the JSON outside the project; the helper validates and removes it after a successful write.

Expect unchanged indexing commands to be idempotent. Do not use `init` as a migration command. Do not edit generated registries, indices, IDs, paths, statuses, or relationship reverse links manually.

## Completion Gate

1. Run relevant implementation tests and every verification linked to changed canonical topics.
2. Confirm one current owner per topic and no parallel old/versioned copies.
3. If a Deliverables role is registered, confirm it contains only registered current human outputs.
4. Confirm every `.oppen-project-steward/Audit/Runs/` stage contains only one `current/` tree.
5. Complete any High-Risk Contract Audit that was actually triggered.
6. Raise any qualifying non-blocking Attention without expanding scope. Treat blocking Attention as a completion blocker.
7. Add Decision Memory only for qualifying consequential decisions; never automate it from task completion.
8. Recover deterministic operational residue, run `index`, then require `validate` to report `MANAGED_READY` and exit zero.
9. Report current deliverables, verification performed, active Attention, and unresolved blockers.
