# Managed Payload Schemas

Create payloads as temporary JSON files outside the target project. Use exactly the fields shown; unknown or missing fields fail validation. The helper removes a valid payload after successfully creating its entry and leaves an invalid payload available for correction.

## Existing Project Adoption

```json
{
  "role_mappings": {
    "source": "src",
    "deliverables": "reports"
  },
  "initial_canonical_registrations": [
    {
      "topic": "product-contract",
      "path": "project.md",
      "section": null,
      "status": "frozen",
      "verification": "tests/verify_contract.py"
    }
  ],
  "initial_deliverable_registrations": []
}
```

- Use only optional `source`, `data`, and `deliverables` role mappings to existing real directories. Empty mappings are valid.
- Register only clear existing Canonical owners with an existing real verification. Do not fabricate verification; an empty registration array is valid.
- Supply `status` in the Steward registry without modifying the existing owner. Use `section: null` for whole-file ownership.
- Register a Deliverable only when its role is explicitly mapped and its artifact and producer already exist.

Run `adopt TARGET --check` first, then:

```text
adopt TARGET --apply --input /absolute/path/to/temporary.json
```

## Contract Audit Completion

Create or locate the stable audit first, then complete it with exactly these fields:

```json
{
  "purpose_and_risk": "This boundary controls production authorization behavior.",
  "contract": "Validated requests produce one authorized state transition.",
  "edge_cases_and_verification": "tests/test_permissions.py covers denied and boundary cases.",
  "known_limits": "External identity-provider availability is outside this contract."
}
```

Run:

```text
contract-audit TARGET --topic KEY --input /absolute/path/to/temporary.json
```

The helper preserves registered ownership and risk metadata, refreshes the current source hash, writes the completed audit transactionally, advances the managed-state baseline, and removes the payload after success. Do not edit `Audit/Contracts/**` directly.

## Attention Raise

```json
{
  "title": "Unresolved permission boundary",
  "blocking": false,
  "observation": "The fallback path bypasses the documented permission boundary.",
  "evidence": "src/permissions.py:42 permits fallback access without an identity check.",
  "why_it_matters": "A future release decision could expose unauthorized data.",
  "why_no_action_was_taken": "Changing authorization behavior is outside the current task.",
  "human_decision_needed": "Decide whether fallback access should be removed."
}
```

- Use a JSON boolean for `blocking`, normally `false`.
- Keep `title` on one line. The helper rejects an exact normalized title duplicate among active entries.
- Provide concise project facts, not internal reasoning or a scratchpad.

Run:

```text
attention raise TARGET --input /absolute/path/to/temporary.json
```

Resolve only after the issue is actually resolved:

```text
attention resolve TARGET --id A-0001
```

## Memory Add

```json
{
  "title": "Require explicit permission checks",
  "related_topics": ["authentication-contract"],
  "supersedes": ["M-0001"],
  "invalidates": [],
  "before": "The project favored implicit permission inheritance.",
  "trigger": "Observed production behavior made inherited access ambiguous.",
  "decision": "Require explicit permission checks at every boundary.",
  "why": "Explicit checks make authorization behavior inspectable and stable.",
  "rejected_or_prior_approach": "Implicit inheritance was rejected after the observed ambiguity.",
  "consequence": "New boundaries must declare and test their permission behavior."
}
```

- Use arrays for `related_topics`, `supersedes`, and `invalidates`; empty arrays are valid.
- Reference only existing active Memory IDs. Do not place the same ID in both relationship arrays.
- Do not provide `status`, reverse links, IDs, filenames, or paths. The helper owns them.
- Do not include unresolved risks, verification logs, commands, file lists, session summaries, or chain of thought.

Run:

```text
memory add TARGET --input /absolute/path/to/temporary.json
```
