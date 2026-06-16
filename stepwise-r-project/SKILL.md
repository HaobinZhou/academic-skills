---
name: stepwise-r-project
description: Maintain human-readable, stepwise R analysis projects. Use when an assistant needs to initialize or standardize an R work directory, create or modify R scripts, audit functions with R Markdown, audit existing R code for readable RStudio line-by-line execution, create Memory ledger entries, or keep project.md synchronized with R/ scripts, Audit/ function audits, and Memory/ logs.
---

# Stepwise R Project

Use this skill to keep an R analysis workspace readable to humans and durable across later AI edits. The project must remain easy to inspect in RStudio, with explicit intermediate variables, clear Chinese annotations, function audits for any abstraction, a Memory ledger for every change, and a synchronized `project.md` index.

## Required Workflow

1. Receive the target project path from the user, or infer it from the active workspace only when unambiguous.
2. Inspect the target directory before editing:
   - If it is empty or missing required structure, initialize it.
   - If it already contains work, preserve existing files and add only missing scaffold pieces.
3. Use `scripts/stepwise_r_project.py init <target_dir>` before R work unless the scaffold is already confirmed complete.
4. Write or modify R code under `R/` using the code rules below.
5. If a function is created or materially changed, create or update its R Markdown audit under `Audit/Functions/` before considering the function acceptable.
6. Create one Memory log for every meaningful change with `scripts/stepwise_r_project.py memory <target_dir> --magnitude <level> --summary <short-summary>`.
   Fill every section before considering the task complete; do not leave prompts, placeholders, or empty bullets in the log.
7. Update `project.md` after code, Audit, or Memory changes with `scripts/stepwise_r_project.py index <target_dir>`.
8. In the final response, mention the Memory log path, any function audit path, and any assumptions disclosed there.

## Standard Project Shape

Every managed project uses exactly these top-level entries:

- `R/`: readable R scripts, ordered by filename when sequencing matters.
- `Data/`: user-provided or derived data files. Do not overwrite raw data unless explicitly asked.
- `Results/`: tables, figures, model outputs, and exported artifacts.
- `Audit/`: audit evidence for AI-created abstractions, especially `Audit/Functions/*.Rmd`.
- `Memory/`: Markdown change logs.
- `project.md`: project rules, script index, function audit index, Memory index, and project-specific notes.

Do not add alternative top-level folders for the same roles unless the user explicitly requests them. If a project already has similar folders, keep them intact but still create the standard folders.

## R Writing Rules

- Organize scripts the way a human would in RStudio, using section headers inserted with `Alt+Shift+R` to separate import, cleaning, analysis, and export blocks.
- Make scripts runnable line by line in RStudio. Avoid wrapping a whole analysis in one large function, one sourced block, or one deeply nested expression.
- Prefer visible intermediate variables at important checkpoints: import, filtering, joins, recoding, summaries, modeling, exports.
- Limit pipelines. A short pipeline is acceptable for local transformations; break long or conceptually important pipelines into named objects.
- Use clear Chinese comments at control points and data transformations. Comments should explain why a step exists, not repeat the syntax.
- Keep object names descriptive and stable across scripts when they represent the same concept.
- Avoid hidden global state. Set file paths near the top of the script and make package loading visible.
- Save outputs into `Results/`, and make output filenames informative enough to inspect without opening the script.

## Function Rules

- Do not create functions preemptively. Write flat, readable script code first.
- Create a function only when the same logic is reused across multiple scripts or a repeated block is meaningfully error-prone.
- Every function must have Roxygen2 documentation immediately above it, including `@param`, `@return`, and side effects when relevant.
- Keep functions small and domain-specific. Do not hide the main analysis flow inside helper abstractions.
- Treat every function as an auditable abstraction. A new function is incomplete until it has a matching `Audit/Functions/audit_<function_name>.Rmd`.
- Update the matching function audit whenever parameters, return shape, side effects, internal branching, missing-value handling, joins, date parsing, filtering, or core calculation logic changes.
- Do not claim a function is "100% accurate" without boundaries. State the validated input contract, output contract, toy examples, assertions, edge cases, and known limits.

## Function Audit R Markdown

Use R Markdown only for function audits, not as the main analysis workflow. The source of truth remains the readable `.R` scripts under `R/`.
Write explanatory text in `Audit/Functions/*.Rmd`, `Memory/*.md`, and `project.md` primarily in Chinese. Keep code, function names, parameter names, file paths, column names, package names, and assertions in their original technical language.

Create a template with:

```bash
python3 scripts/stepwise_r_project.py function-audit /path/to/project --function clean_index_date --source R/02_cleaning.R --memory Memory/20260616_huge_refactor.md
```

Each `Audit/Functions/audit_<function_name>.Rmd` must include:

- Purpose: what the function does and why it is not left as flat script code.
- Source location: defining file and known callers.
- Input contract: parameter types, required columns, allowed values, and invalid inputs.
- Output contract: return type, columns or fields, row-count behavior, and side effects.
- Logic walkthrough: step-by-step explanation of filtering, joins, mutation, date handling, missing-value handling, and branching.
- Minimal toy examples: small inputs and visible outputs.
- Edge cases: missing values, empty data, duplicate IDs, abnormal dates, unknown categories, and boundary values when relevant.
- Correctness checks: runnable assertions such as `stopifnot()`, `identical()`, or `all.equal()`.
- Known limits: where the function is not guaranteed to be correct and what must be confirmed by the user or data owner.

Memory logs must cite related function audits when a function is created or changed.

## Memory Ledger

Every change log must be a Markdown file in `Memory/` named:

```text
YYYYMMDD_<magnitude>_<short-summary>.md
```

Use these magnitudes:

- `mini`: comments, spelling, tiny presentation changes, or harmless cleanup.
- `medium`: local logic change that does not alter cross-script handoff contracts.
- `huge`: cross-script data flow, variable semantics, output contract, or analysis result changes.
- `boom`: architectural rebuild, project rule rewrite, or restart from a new foundation.

Each Memory log must include a forced reflection template:

- Change summary: state what changed in concrete, inspectable terms.
- User intent: restate the user request and the success criterion the assistant used.
- Decision record: list choices the assistant made, including alternatives rejected when relevant.
- Files touched: list every modified or created file.
- Code readability audit: confirm whether R code remains line-by-line runnable, uses named intermediate objects, limits pipelines, and has Chinese comments at key transformations.
- Function audit linkage: cite any related `Audit/Functions/*.Rmd`, or explicitly state that no function was created or changed.
- Data and output impact: state whether data inputs, cleaning rules, variable meanings, or output files changed.
- Verification: record commands, manual checks, or reasons verification was not run.
- Implicit assumptions: disclose unstated choices such as cleaning boundaries, missing-value policy, date parsing, package dependency, encoding, file format, output naming, directory inference, or acceptable risk.
- Risk and follow-up: name any remaining uncertainty, fragile dependency, or future action.

If a section does not apply, write a short explicit sentence explaining why. If no implicit assumptions were introduced, write that explicitly instead of omitting the section. A Memory log with generic filler such as "N/A" everywhere is invalid.

## Helper Script

Use the bundled helper for mechanical tasks:

```bash
python3 scripts/stepwise_r_project.py init /path/to/project
python3 scripts/stepwise_r_project.py function-audit /path/to/project --function clean_index_date --source R/02_cleaning.R
python3 scripts/stepwise_r_project.py memory /path/to/project --magnitude medium --summary revise-cohort-filter
python3 scripts/stepwise_r_project.py index /path/to/project
```

The helper is intentionally conservative: it creates missing scaffold pieces, creates function audit templates without overwriting existing audits, appends missing managed sections to `project.md`, and refreshes only marked index blocks.
