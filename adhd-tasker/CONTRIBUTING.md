# Contributing

Thanks for improving ADHD Tasker. This project is intentionally small, so contributions should keep the skill direct, practical, and easy to scan.

## Guidelines

- Keep user-facing output concrete and action-oriented.
- Preserve explicit invocation through `$adhd-tasker`.
- Prefer small improvements to broad rewrites.
- Avoid medical diagnosis, medication guidance, or clinical claims.
- Keep examples inclusive and low-pressure.
- Match the existing language behavior: Chinese for Chinese input, otherwise follow the user's language.

## Local Checks

Before opening a pull request:

1. Read `SKILL.md` end to end.
2. Check that the default output structure is still valid Markdown.
3. Make sure examples do not imply clinical treatment or diagnosis.
4. Confirm `agents/openai.yaml` still sets `allow_implicit_invocation: false`.

## Pull Requests

Include a short summary of what changed and why. If you changed the skill behavior, include one example prompt and the expected style of response.
