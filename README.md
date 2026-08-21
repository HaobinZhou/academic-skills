# Academic Skills

[简体中文](./README.zh-CN.md)

A collection of Codex skills I use for research, software projects, learning, and task execution.

## Skills

| Skill                                                       | Purpose                                                                            |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| [`oppen-project-steward`](./oppen-project-steward/SKILL.md) | Maintain long-lived software, AI, and other non-scientific projects                |
| [`stepwise-r-project`](./stepwise-r-project/SKILL.md)       | A specialized branch of `oppen-project-steward` for scientific projects that use R |
| [`project-crystallizer`](./project-crystallizer/SKILL.md)   | Freeze, package, or hand off a project without unnecessary expansion               |
| [`adhd-academic-tutor`](./adhd-academic-tutor/SKILL.md)     | Guided literature reading and academic writing practice                            |
| [`adhd-tasker`](./adhd-tasker/SKILL.md)                     | Break difficult tasks into manageable steps                                        |

`stepwise-r-project` grew out of `oppen-project-steward` and keeps the same general approach to long-lived project maintenance, but is adapted specifically for scientific R projects, where analysis definitions, reproducibility, results, and publication-facing outputs need additional handling.

See each `SKILL.md` for full behavior and usage.

## Install

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

## Use

Invoke a skill explicitly in Codex:

```text
$oppen-project-steward
Adopt and maintain this existing project.
```

```text
$stepwise-r-project
Review and update this scientific R project.
```

```text
$project-crystallizer
Prepare this project for handoff.
```

```text
$adhd-academic-tutor
Start a guided literature reading session.
```

```text
$adhd-tasker
Help me break this task into manageable steps.
```

## Tests

```bash
python3 -m pytest stepwise-r-project/tests -q
python3 -m pytest oppen-project-steward/tests -q
```

## License

[MIT](./LICENSE)
