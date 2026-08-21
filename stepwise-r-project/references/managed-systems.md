# Managed Systems Reference

Use temporary UTF-8 JSON files for long semantic payloads. The helper rejects missing or unexpected fields and owns all IDs, paths, status transitions, reverse links, indices, and atomic writes.

## Attention Payload

```json
{
  "title": "Unresolved time-zero definition",
  "blocking": true,
  "observation": "Two analysis scripts assign different cohort entry dates.",
  "evidence": "R/cohort.R uses enrollment_date; R/model.R uses index_date.",
  "why_it_matters": "Follow-up and event attribution may change.",
  "why_no_action_was_taken": "Choosing the scientific definition is outside the authorized task.",
  "human_decision_needed": "Confirm the authoritative time-zero definition."
}
```

The helper creates `Attention/entries/A-XXXX.md` and regenerates `Attention/index.md`. Resolve an active item with its ID; the helper removes it from the working tree and creates no archive. Git preserves history.

## Decision Memory Payload

```json
{
  "title": "Replace the unsupported treatment strategy",
  "related_topics": ["treatment-strategy"],
  "supersedes": ["M-0003"],
  "invalidates": [],
  "before": "The analysis used a fixed grace period.",
  "trigger": "Diagnostics showed severe support violations.",
  "decision": "Use the observed-data strategy definition.",
  "scientific_or_technical_rationale": "The revised strategy preserves the estimand under observed support.",
  "basis": "Empirical diagnostics in Audit/Runs/weights/current/diagnostics.csv.",
  "rejected_or_prior_approach": "Retain the fixed grace period despite support violations.",
  "consequence": "Current and future models use the revised strategy."
}
```

`related_topics`, `supersedes`, and `invalidates` may be omitted and default to `[]`. Use only existing `M-XXXX` IDs for relationships. A target must be active. The helper changes it to `superseded` or `invalidated`, maintains the matching reverse link, and regenerates `Memory/index.md`.

## Existing v2 Migration

Run `migrate TARGET --check` first. It is read-only and reports project status, recoverable blockers, structural/damage blockers, the migration write-set, dirty paths, dirty/write-set overlaps, every legacy Memory file, and Audit staging requiring recovery. Proceed only for `MIGRATION_REQUIRED` with no blockers.

`MIGRATION_BLOCKED_RECOVERABLE` means the scientific governance structure is still interpretable but an operational condition must be repaired. For mechanically clear failed/incomplete staging under `Audit/Runs/<stage>/`, run `audit-recover TARGET --stage STAGE`. The helper copies it to `$TMPDIR/stepwise-r-project-recovery/<project-id>/<stage>/<recovery-id>/`, verifies content, writes a manifest there, and removes the source only after verification. It preserves `current/`; ambiguous entries stay in place for human review. Rerun preflight after recovery.

Migration does not require the whole Git worktree to be clean. It blocks exact overlaps with `project.md`, `Memory/**`, `Attention/**`, and other reported helper-controlled paths. Resolve only those reported paths. Unrelated dirty R, Results, data, and documents may remain; migration inventories them and verifies their bytes and Git status are unchanged. Do not automatically stash the project.

Review every `Memory/<task-key>.md` as an input container using both the Decision Memory and Human Attention tests. Extract each qualifying causal decision independently; never convert a legacy file wholesale. One old file may produce zero, one, or multiple Decision Memories plus zero or more Attention entries. Prepare one record per inventoried file:

```json
{
  "legacy_memory": [
    {
      "path": "Memory/design-change.md",
      "decision_memories": [
        {
          "title": "Adopt the revised estimand",
          "related_topics": ["estimand"],
          "before": "The protocol targeted the earlier estimand.",
          "trigger": "A collaborator decision changed the research question.",
          "decision": "Target the revised estimand.",
          "scientific_or_technical_rationale": "The revision matches the intended clinical contrast.",
          "basis": "PI and collaborator methodological decision.",
          "rejected_or_prior_approach": "Continue targeting the earlier contrast.",
          "consequence": "Canonical definitions, implementation, and tests use the revised estimand."
        }
      ],
      "attention_entries": [],
      "no_migration_required": false
    },
    {
      "path": "Memory/routine-rerun.md",
      "decision_memories": [],
      "attention_entries": [],
      "no_migration_required": true
    }
  ]
}
```

Use the normal Decision Memory and Attention payload schemas inside the arrays. `no_migration_required` must be `true` exactly when both arrays are empty. Migration Decision Memories cannot reference helper-generated relationship IDs.

Preserve consequential causal rationale only when it passes the counterfactual test. This can include durable scientific decisions and non-obvious technical/execution architecture decisions. Routine bug fixes, package compatibility, normalization, optimization, or test improvements do not qualify by themselves.

Route a concern to Attention only when all six conditions hold: it is material, unresolved, outside ordinary authorized work, requires added human decision/authorization or substantial scope, is evidence-backed, and has no equivalent active entry. Noteworthy does not mean Attention. Known pending work whose resolution is already represented and authorized is not Attention.

Do not migrate benchmarks, PASS/test evidence, progress, file inventories, routine task/session history, information already in Canonical, or artifact history recoverable from Git. Verification belongs in current Audit when it still needs representation.

Store the JSON outside the project and run `migrate TARGET --apply --input TEMP_JSON`. The helper rejects incomplete review, stages a full v3 view in the system temporary directory, validates it, backs up managed state outside the project, promotes only v3 governance structures, runs final `index` and `validate`, and removes the payload after success. On promotion or final-validation failure it restores and validates the v2 managed state. It creates no in-project migration report, staging, backup, archive, or legacy directory.

Successful migration preserves scientific project content, removes task-based Memory from the current tree, and creates fixed Memory and Attention topology even when both are empty. Already-v3 checks and applies are no-ops; downgrade is unsupported.
