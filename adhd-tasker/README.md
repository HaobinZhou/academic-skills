# ADHD Tasker

ADHD Tasker is a skill package for turning broad tasks into small, concrete, ADHD-friendly execution plans.

It is designed for explicit use with `$adhd-tasker`. The skill breaks work into visible next actions, generous time boxes, low-pressure stopping points, and simple feedback loops for when the user gets stuck, distracted, overwhelmed, tired, or short on time.

## What It Does

- Converts vague tasks into concrete micro-steps.
- Creates a minimum viable completion path before polish.
- Uses generous time boxes instead of optimistic schedules.
- Gives visible completion markers for each step.
- Adjusts the plan when the user reports friction.
- Defaults to Chinese when the user writes in Chinese.

## Repository Layout

```text
.
|-- SKILL.md
|-- agents/
|   `-- openai.yaml
|-- README.md
|-- CONTRIBUTING.md
|-- LICENSE
`-- .gitignore
```

## Usage

Install, link, or copy this skill folder into a compatible skill runtime, then invoke it explicitly:

```text
$adhd-tasker Help me break down cleaning my desk.
```

Example Chinese invocation:

```text
$adhd-tasker 帮我把今天要写的报告拆成容易开始的小步骤。
```

The skill is intentionally not configured for implicit invocation. This keeps the behavior opt-in and predictable.

## Project Status

This is a small, focused open source skill. Contributions should preserve the core design: concrete next actions, generous buffers, minimal shame, and low cognitive overhead.

## License

MIT License. See [LICENSE](LICENSE).
