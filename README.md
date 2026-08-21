# Academic Skills / 学术技能集合

_Durable AI-assisted workflows for research, project governance, learning, and execution / 面向科研、项目治理、学习与执行的长期 AI 协作工作流_

---

[English](#english) · [中文](#中文) · [Install and use](#install-and-use) · [安装与使用](#安装与使用)

<a id="english"></a>

## 📚 English

### Purpose

This repository is a long-term collection of practical agent skills started during my first pre-doctoral year. These are working tools used in real research, learning, and software projects rather than demonstration artifacts.

The collection favors workflows that are readable, auditable, restartable, and humane. Each skill has a narrow responsibility and a clear activation boundary.

### Skill catalog

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

<a id="中文"></a>

## 📚 中文

### 项目定位

这是我从预博士一年级开始长期维护的 agent skill 集合。这些内容不是展示用的 demo，而是实际用于科研、学习和软件项目的工作工具。

整个集合强调可读、可审计、可恢复和符合人性节奏的工作流。每个 skill 都有明确的职责边界和触发条件，避免不同工具彼此越权或重复管理同一问题。

### Skill 清单

| 分类 | Skill | 适用场景 | 触发方式 |
| --- | --- | --- | --- |
| 长期项目治理 | [`oppen-project-steward`](./oppen-project-steward/SKILL.md) | 接入和治理长期、非科研型项目，维护 Canonical 当前事实、Audit 当前证据、Human Attention、Decision Memory，并保护无关未提交工作 | 可按上下文触发 |
| 科研 R 项目治理 | [`stepwise-r-project`](./stepwise-r-project/SKILL.md) | 迁移或维护可读的 R 分析项目，确保科学定义单一归属、Results 面向发表、Audit 只保留当前证据，并管理 Attention、Memory 与高风险函数审计 | 可按上下文触发 |
| 项目收束与交接 | [`project-crystallizer`](./project-crystallizer/SKILL.md) | 在不扩张原始愿景的前提下，把当前有价值的工作固化为可验证的交接包、冻结点或发布版本 | 明确或强烈隐含的收束意图 |
| 文献学习与学术写作 | [`adhd-academic-tutor`](./adhd-academic-tutor/SKILL.md) | 开展面向原文的引导式阅读、学术写作模式训练、时间校准和有证据的长期学习记忆 | 仅显式触发 |
| 任务执行 | [`adhd-tasker`](./adhd-tasker/SKILL.md) | 把令人压力过大的任务拆成微步骤、宽松时间盒、可见完成标志，并根据卡住或分心等反馈低压力调整 | 仅显式触发 |

### 快速选择

| 你的情况 | 优先使用 |
| --- | --- |
| 长期软件、AI、基础设施或混合项目需要稳定治理 | `$oppen-project-steward` |
| 科研 R 工作区需要迁移、验证或语义变更 | `$stepwise-r-project` |
| 项目需要冻结、打包、发布或交接 | `$project-crystallizer` |
| 想开展一次引导式文献阅读或学术写作学习 | `$adhd-academic-tutor` |
| 知道要做什么，但难以开始或拆解 | `$adhd-tasker` |

<a id="install-and-use"></a>

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

Repeat the final command for each skill you want to install. A symbolic link keeps the installed skill synchronized with repository updates.

### Invoke

Explicit invocation is the most predictable way to select a skill:

```text
Use $stepwise-r-project to validate and update this R analysis workspace.
Use $project-crystallizer to prepare this project for handoff.
Use $adhd-academic-tutor to start a guided literature-reading session.
Use $adhd-tasker to break this task into low-pressure micro-steps.
```

`adhd-academic-tutor` and `adhd-tasker` are intentionally explicit-only. `project-crystallizer` activates only when the request clearly indicates closure, freezing, release, packaging, or handoff.

<a id="安装与使用"></a>

## ⚙️ 安装与使用

### 安装

Codex 从 `$CODEX_HOME/skills`（通常是 `~/.codex/skills`）发现个人 skill。[^1] 可以把本仓库克隆到任意源码目录，再将需要的 skill 目录链接到 Codex skill 目录。上面的安装示例以 `stepwise-r-project` 为例；其他 skill 只需替换目录名称。

符号链接的好处是仓库更新后不需要重复复制文件。若目标位置已经存在同名目录，请先检查现有安装，不要直接覆盖。

### 调用

在提示词中使用 `$skill-name` 可以明确选择 skill，例如：

```text
使用 $oppen-project-steward 接入并验证这个长期项目。
使用 $stepwise-r-project 迁移这个 R 分析工作区。
使用 $project-crystallizer 把当前项目整理成可交接状态。
使用 $adhd-academic-tutor 开始一次引导式文献阅读。
使用 $adhd-tasker 把这项任务拆成低压力微步骤。
```

## 🔍 Repository and verification / 仓库结构与验证

### Directory contract / 目录约定

| Path | Purpose / 用途 |
| --- | --- |
| `<skill>/SKILL.md` | Required skill definition, activation boundary, workflow, and output contract / 必需的 skill 定义、触发边界、工作流与输出约定 |
| `<skill>/agents/openai.yaml` | Codex-facing display metadata and default prompt / 面向 Codex 的展示元数据与默认提示词 |
| `<skill>/references/` | Schemas, templates, protocols, or detailed guidance loaded only when needed / 按需读取的模式、模板、协议或详细说明 |
| `<skill>/scripts/` | Deterministic helpers for project mechanics / 处理确定性项目操作的辅助脚本 |
| `<skill>/tests/` | Executable regression and contract tests where the skill includes code / 对包含代码的 skill 提供回归与契约测试 |

### Verification / 验证

The two governance skills currently include Python test suites:

```bash
python3 -m pytest stepwise-r-project/tests -q
python3 -m pytest oppen-project-steward/tests -q
```

When changing a skill, update its `SKILL.md`, implementation, references, and tests together when the behavior or contract changes.

修改 skill 时，如果行为或契约发生变化，应同步更新 `SKILL.md`、实现、参考资料和测试，避免文档与运行行为失配。

## 🔗 License / 许可证

The repository root is released under the [MIT License](./LICENSE). Individual skill directories may contain additional license or attribution files; check them before redistribution.

仓库根目录采用 [MIT License](./LICENSE)。部分 skill 目录可能包含独立的许可证或署名文件，二次分发前请一并检查。

---

[^1]: OpenAI. "Agent Skills." _Codex documentation_. https://developers.openai.com/codex/skills/
