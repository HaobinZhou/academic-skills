# Academic Skills

Academic Skills is a small collection of skill packages for scholarly work, readable analysis, literature tutoring, and ADHD-friendly execution support. The collection is organized as a multi-skill repository: each skill lives in its own folder and keeps its own README, metadata, scripts, and references.

These skills are designed for workflows where humans and AI assistants collaborate over time. The emphasis is on readable process, auditable decisions, source-facing learning, and gentle execution scaffolding rather than one-shot automation.

## Included Skills

| Skill | Purpose |
| --- | --- |
| `stepwise-r-project` | Maintains human-readable, auditable R analysis projects with standard folders, Memory logs, and function-level R Markdown audits. |
| `adhd-academic-tutor` | Guides academic literature reading and writing practice with source-facing assignments, local memory, time calibration, and achievement tracking. |
| `adhd-tasker` | Breaks broad tasks into concrete, ADHD-friendly micro-steps with generous time boxes and low-pressure feedback loops. |

## Repository Layout

```text
academic-skills/
├── stepwise-r-project/
├── adhd-academic-tutor/
├── adhd-tasker/
├── README.md
├── LICENSE
└── .gitignore
```

Each skill folder can be installed, linked, copied, or packaged independently by tools that support skill-style folders. Read the README inside each skill folder for details.

## Design Principles

- Keep each skill self-contained.
- Preserve human-readable artifacts such as Markdown logs, R Markdown audits, and project indexes.
- Prefer explicit invocation when a skill changes the interaction style significantly.
- Keep project-facing explanations in the language that best supports the user's workflow.
- Treat AI-generated abstraction as something that must be auditable, not hidden.

## Installation Pattern

Use the installation mechanism supported by your assistant or runtime. A common local pattern is to symlink a skill folder into the runtime's skill directory:

```bash
ln -s /path/to/academic-skills/stepwise-r-project /path/to/skills/stepwise-r-project
ln -s /path/to/academic-skills/adhd-academic-tutor /path/to/skills/adhd-academic-tutor
ln -s /path/to/academic-skills/adhd-tasker /path/to/skills/adhd-tasker
```

## License

MIT License. See [LICENSE](LICENSE).

---

# Academic Skills 学术技能集合

Academic Skills 是一组面向学术工作、可读分析、文献学习和 ADHD 友好执行支持的 skill package。这个仓库采用多 skill 管理方式：每个 skill 都放在自己的文件夹中，并保留自己的 README、元数据、脚本和参考资料。

这些 skill 适合长期的人机协作工作流。它们强调过程可读、决策可审计、学习面向原始来源，以及低压力的执行脚手架，而不是一次性自动化。

## 包含的 Skills

| Skill | 用途 |
| --- | --- |
| `stepwise-r-project` | 维护人类可读、可审计的 R 分析项目，包括标准目录、Memory 记录和 function 级 R Markdown 审计。 |
| `adhd-academic-tutor` | 通过原文导向阅读任务、本地记忆、时间校准和成就记录，辅助学术文献阅读与写作训练。 |
| `adhd-tasker` | 将宽泛任务拆成 ADHD 友好的微步骤，提供宽松时间盒和低压力反馈循环。 |

## 仓库结构

```text
academic-skills/
├── stepwise-r-project/
├── adhd-academic-tutor/
├── adhd-tasker/
├── README.md
├── LICENSE
└── .gitignore
```

每个 skill 文件夹都可以被支持 skill 文件夹的工具独立安装、链接、复制或打包。具体用法请阅读各自文件夹中的 README。

## 设计原则

- 每个 skill 保持自包含。
- 保留 Markdown 记录、R Markdown 审计、项目索引等人类可读产物。
- 当 skill 会显著改变交互方式时，优先使用显式调用。
- 面向项目的解释文字使用最适合用户工作流的语言。
- AI 生成的抽象必须可审计，不能被隐藏在黑箱里。

## 安装方式

使用你的助手或运行环境支持的安装机制即可。常见的本地方式是将某个 skill 文件夹软链接到运行环境的 skill 目录：

```bash
ln -s /path/to/academic-skills/stepwise-r-project /path/to/skills/stepwise-r-project
ln -s /path/to/academic-skills/adhd-academic-tutor /path/to/skills/adhd-academic-tutor
ln -s /path/to/academic-skills/adhd-tasker /path/to/skills/adhd-tasker
```

## 许可证

MIT License。见 [LICENSE](LICENSE)。
