# Academic Skills 学术技能集合

[English](./README.md)

这是我用于科研、软件项目、学习和任务执行的一组 Codex skills。

## Skills

| Skill                                                       | 用途                                                        |
| ----------------------------------------------------------- | ----------------------------------------------------------- |
| [`oppen-project-steward`](./oppen-project-steward/SKILL.md) | 维护长期的软件、AI 和其他非科研项目                         |
| [`stepwise-r-project`](./stepwise-r-project/SKILL.md)       | `oppen-project-steward` 面向使用 R 的科研项目的专门分支      |
| [`project-crystallizer`](./project-crystallizer/SKILL.md)   | 在不做不必要扩张的前提下冻结、打包或交接项目                |
| [`adhd-academic-tutor`](./adhd-academic-tutor/SKILL.md)     | 引导式文献阅读与学术写作练习                                |
| [`adhd-tasker`](./adhd-tasker/SKILL.md)                     | 将困难任务拆解为可管理的步骤                                |

`stepwise-r-project` 由 `oppen-project-steward` 发展而来，延续了维护长期项目的整体方法，但针对科研 R 项目进行了专门适配，以额外处理分析定义、可重复性、结果和面向发表的输出。

每个 skill 的完整行为和使用方法请参阅对应的 `SKILL.md`。

## 安装

```bash
git clone https://github.com/HaobinZhou/academic-skills.git
cd academic-skills

mkdir -p "$HOME/.agents/skills"

ln -s "$PWD/oppen-project-steward" "$HOME/.agents/skills/oppen-project-steward"
ln -s "$PWD/stepwise-r-project" "$HOME/.agents/skills/stepwise-r-project"
ln -s "$PWD/project-crystallizer" "$HOME/.agents/skills/project-crystallizer"
ln -s "$PWD/adhd-academic-tutor" "$HOME/.agents/skills/adhd-academic-tutor"
ln -s "$PWD/adhd-tasker" "$HOME/.agents/skills/adhd-tasker"
```

## 使用

在 Codex 中显式调用 skill：

```text
$oppen-project-steward
接入并维护这个现有项目。
```

```text
$stepwise-r-project
审查并更新这个科研 R 项目。
```

```text
$project-crystallizer
准备这个项目以便交接。
```

```text
$adhd-academic-tutor
开始一次引导式文献阅读。
```

```text
$adhd-tasker
帮我把这个任务拆解为可管理的步骤。
```

## 测试

```bash
python3 -m pytest stepwise-r-project/tests -q
python3 -m pytest oppen-project-steward/tests -q
```

## 许可证

[MIT](./LICENSE)
