# Academic Skills

_Durable AI-assisted workflows for research, project governance, learning, and execution_

---

[简体中文](./README.zh-CN.md)

## 📋 Overview

This repository is a long-term collection of practical agent skills started during my first pre-doctoral year. These are working tools used in real research, learning, and software projects rather than demonstration artifacts.

The collection favors workflows that are readable, auditable, restartable, and humane. Each skill has a narrow responsibility and a clear activation boundary.

## 📚 Skills

### Catalog

| Category | Skill | Use it for | Activation |
| --- | --- | --- | --- |
| Long-lived project governance | [`oppen-project-steward`](./oppen-project-steward/SKILL.md) | Adopt and govern durable non-scientific projects with Canonical ownership, current Audit evidence, Human Attention, Decision Memory, and path-scoped dirty-work protection | Context-aware |
| Scientific R governance | [`stepwise-r-project`](./stepwise-r-project/SKILL.md) | Maintain or migrate readable R analysis projects with one owner per scientific definition, publication-facing Results, current Audit evidence, Human Attention, Decision Memory, and high-risk function audits | Context-aware |
| Project closure and handoff | [`project-crystallizer`](./project-crystallizer/SKILL.md) | Turn a useful burst of project work into an evidence-backed handoff, freeze point, or release without expanding the original vision | Explicit or strongly implied closure intent |
| Literature learning and writing | [`adhd-academic-tutor`](./adhd-academic-tutor/SKILL.md) | Run guided source-facing literature reading, academic writing pattern practice, time calibration, and evidence-backed learning memory | Explicit only |
| Task execution | [`adhd-tasker`](./adhd-tasker/SKILL.md) | Convert an overwhelming task into concrete micro-steps, generous time boxes, visible completion markers, and low-pressure replanning | Explicit only |

### Choose quickly

| Situation | Start with |
| --- | --- |
| A long-lived software, AI, infrastructure, or mixed project needs durable governance | `$oppen-project-steward` |
| A scientific R workspace needs migration, validation, or a semantic change | `$stepwise-r-project` |
| A project should be frozen, packaged, released, or handed to another person | `$project-crystallizer` |
| You want a guided literature-reading or academic-writing learning session | `$adhd-academic-tutor` |
| You know the task but cannot get it started or broken into manageable actions | `$adhd-tasker` |

## ⚙️ Install and use

### Install

Codex discovers personal skills under `$CODEX_HOME/skills` (normally `~/.codex/skills`).[^1] Clone this repository anywhere you maintain source code, then link the skill directories you want to use:

```bash
git clone https://github.com/HaobinZhou/academic-skills.git
cd academic-skills

skills_dir="${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "$skills_dir"
ln -s "$PWD/stepwise-r-project" "$skills_dir/stepwise-r-project"
```

Repeat the final command for each skill you want to install. A symbolic link keeps the installed skill synchronized with repository updates. If the destination already exists, inspect the existing installation instead of overwriting it.

### Invoke

Explicit invocation is the most predictable way to select a skill:

```text
Use $oppen-project-steward to adopt and validate this durable project.
Use $stepwise-r-project to migrate this R analysis workspace.
Use $project-crystallizer to prepare this project for handoff.
Use $adhd-academic-tutor to start a guided literature-reading session.
Use $adhd-tasker to break this task into low-pressure micro-steps.
```

`adhd-academic-tutor` and `adhd-tasker` are intentionally explicit-only. `project-crystallizer` activates only when the request clearly indicates closure, freezing, release, packaging, or handoff.

## 🔍 Repository and verification

### Directory contract

| Path | Purpose |
| --- | --- |
| `<skill>/SKILL.md` | Required skill definition, activation boundary, workflow, and output contract |
| `<skill>/agents/openai.yaml` | Codex-facing display metadata and default prompt |
| `<skill>/references/` | Schemas, templates, protocols, or detailed guidance loaded only when needed |
| `<skill>/scripts/` | Deterministic helpers for project mechanics |
| `<skill>/tests/` | Executable regression and contract tests where the skill includes code |

### Verification

The two governance skills currently include Python test suites:

```bash
python3 -m pytest stepwise-r-project/tests -q
python3 -m pytest oppen-project-steward/tests -q
```

When changing a skill, update its `SKILL.md`, implementation, references, and tests together when the behavior or contract changes.

## 🔗 License

The repository root is released under the [MIT License](./LICENSE). Individual skill directories may contain additional license or attribution files; check them before redistribution.

---

[^1]: OpenAI. "Agent Skills." _Codex documentation_. https://developers.openai.com/codex/skills/
