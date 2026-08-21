# Academic Skills 学术技能集合

_面向科研、项目治理、学习与执行的长期 AI 协作工作流_

---

[English](./README.md)

## 📋 项目概览

这是我从预博士一年级开始长期维护的 agent skill 集合。这些内容不是展示用的 demo，而是实际用于科研、学习和软件项目的工作工具。

整个集合强调可读、可审计、可恢复和符合人性节奏的工作流。每个 skill 都有明确的职责边界和触发条件，避免不同工具彼此越权或重复管理同一问题。

## 📚 Skill 清单

### 完整目录

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

## ⚙️ 安装与使用

### 安装

Codex 从 `$CODEX_HOME/skills`（通常是 `~/.codex/skills`）发现个人 skill。[^1] 可以把本仓库克隆到任意源码目录，再将需要的 skill 目录链接到 Codex skill 目录：

```bash
git clone https://github.com/HaobinZhou/academic-skills.git
cd academic-skills

skills_dir="${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "$skills_dir"
ln -s "$PWD/stepwise-r-project" "$skills_dir/stepwise-r-project"
```

需要安装其他 skill 时，替换最后一行中的目录名称即可。符号链接能让已安装的 skill 随仓库更新而同步。若目标位置已经存在同名目录，请先检查现有安装，不要直接覆盖。

### 调用

在提示词中使用 `$skill-name` 可以最明确地选择 skill：

```text
使用 $oppen-project-steward 接入并验证这个长期项目。
使用 $stepwise-r-project 迁移这个 R 分析工作区。
使用 $project-crystallizer 把当前项目整理成可交接状态。
使用 $adhd-academic-tutor 开始一次引导式文献阅读。
使用 $adhd-tasker 把这项任务拆成低压力微步骤。
```

`adhd-academic-tutor` 和 `adhd-tasker` 只允许显式触发。`project-crystallizer` 仅在请求明确表达收束、冻结、发布、打包或交接意图时触发。

## 🔍 仓库结构与验证

### 目录约定

| 路径 | 用途 |
| --- | --- |
| `<skill>/SKILL.md` | 必需的 skill 定义、触发边界、工作流与输出约定 |
| `<skill>/agents/openai.yaml` | 面向 Codex 的展示元数据与默认提示词 |
| `<skill>/references/` | 按需读取的模式、模板、协议或详细说明 |
| `<skill>/scripts/` | 处理确定性项目操作的辅助脚本 |
| `<skill>/tests/` | 对包含代码的 skill 提供回归与契约测试 |

### 验证

当前两个项目治理 skill 提供 Python 测试套件：

```bash
python3 -m pytest stepwise-r-project/tests -q
python3 -m pytest oppen-project-steward/tests -q
```

修改 skill 时，如果行为或契约发生变化，应同步更新 `SKILL.md`、实现、参考资料和测试，避免文档与运行行为失配。

## 🔗 许可证

仓库根目录采用 [MIT License](./LICENSE)。部分 skill 目录可能包含独立的许可证或署名文件，二次分发前请一并检查。

---

[^1]: OpenAI. "Agent Skills." _Codex documentation_. https://developers.openai.com/codex/skills/
