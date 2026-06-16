# Stepwise R Project

Stepwise R Project is a skill package for maintaining human-readable, auditable R analysis workspaces. It helps AI agents write R code the way a careful human would work in RStudio: organized by sections, runnable line by line, documented in Chinese for project-facing explanations, and backed by explicit change and function-audit records.

## What It Enforces

- A standard project scaffold: `R/`, `Data/`, `Results/`, `Audit/`, `Memory/`, and `project.md`.
- R scripts that are readable in RStudio, with `Alt+Shift+R` style section headers.
- Stepwise code with named intermediate objects instead of opaque long pipelines.
- Chinese explanatory comments at key control points and data transformations.
- Restrained function abstraction: functions are allowed only when reuse or risk justifies them.
- Roxygen2 documentation for every function.
- Function-level R Markdown audits under `Audit/Functions/`.
- Mandatory Memory logs for meaningful changes, including implicit-assumption disclosure.
- A synchronized `project.md` index for scripts, function audits, and Memory records.

## Helper Script

The bundled helper automates the mechanical parts of the workflow:

```bash
python3 scripts/stepwise_r_project.py init /path/to/project
python3 scripts/stepwise_r_project.py function-audit /path/to/project --function clean_index_date --source R/02_cleaning.R
python3 scripts/stepwise_r_project.py memory /path/to/project --magnitude medium --summary revise-cohort-filter
python3 scripts/stepwise_r_project.py index /path/to/project
```

The helper is conservative: it creates missing scaffold pieces, writes templates without overwriting existing function audits, and refreshes only marked index blocks in `project.md`.

## Function Audits

Every new or materially changed function must have a matching R Markdown audit:

```text
Audit/Functions/audit_<function_name>.Rmd
```

The audit explains the function purpose, source location, input contract, output contract, internal logic, toy examples, edge cases, runnable assertions, and known limits. The skill explicitly forbids unbounded claims such as "100% accurate"; correctness must be stated within validated inputs, examples, and assumptions.

## Memory Ledger

Memory logs are stored in:

```text
Memory/YYYYMMDD_<mini|medium|huge|boom>_<short-summary>.md
```

Each log forces reflection on user intent, decisions, files touched, R readability, function audit linkage, data/output impact, verification, implicit assumptions, and remaining risks.

## Language Policy

Project-facing explanations in `project.md`, `Memory/*.md`, and `Audit/Functions/*.Rmd` should be primarily Chinese. Code, function names, parameter names, file paths, column names, package names, and assertions should remain in their original technical language.

## Skill Metadata

- Skill name: `stepwise-r-project`
- Display name: Stepwise R Project
- Recommended use: R analysis projects where readability, auditability, and long-term AI-human collaboration matter more than compact code.
