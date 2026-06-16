#!/usr/bin/env python3
"""Initialize and maintain Stepwise R Project scaffolds."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path


REQUIRED_DIRS = ("R", "Data", "Results", "Audit", "Memory")
VALID_MAGNITUDES = ("mini", "medium", "huge", "boom")

SCRIPT_START = "<!-- stepwise-r-project:scripts:start -->"
SCRIPT_END = "<!-- stepwise-r-project:scripts:end -->"
AUDIT_START = "<!-- stepwise-r-project:function-audits:start -->"
AUDIT_END = "<!-- stepwise-r-project:function-audits:end -->"
MEMORY_START = "<!-- stepwise-r-project:memory:start -->"
MEMORY_END = "<!-- stepwise-r-project:memory:end -->"


def project_md_template() -> str:
    return f"""# 项目总纲

## 目录规则

- `R/`: 人类可读的 R 脚本，必须适合在 RStudio 中逐行运行。
- `Data/`: 原始或派生数据文件；除非用户明确要求，不要覆盖原始数据。
- `Results/`: 导出的表格、图、摘要、模型结果和其他分析输出。
- `Audit/`: AI 创建抽象后的审计证据，尤其是 function 的 R Markdown 审计。
- `Memory/`: 每次有意义改动的 Markdown 变更记录。

## R 脚本索引

{SCRIPT_START}
_尚未发现 R 脚本。_
{SCRIPT_END}

## Function 审计索引

{AUDIT_START}
_尚未发现 function 审计文件。_
{AUDIT_END}

## Memory 变更记录索引

{MEMORY_START}
_尚未发现 Memory 记录。_
{MEMORY_END}

## 项目备注

- 在这里记录稳定的项目规则、数据定义和脚本交接契约。
"""


def ensure_project(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for dirname in REQUIRED_DIRS:
        (root / dirname).mkdir(exist_ok=True)
    (root / "Audit" / "Functions").mkdir(parents=True, exist_ok=True)

    project_file = root / "project.md"
    if not project_file.exists():
        project_file.write_text(project_md_template(), encoding="utf-8")
        return

    text = project_file.read_text(encoding="utf-8")
    additions: list[str] = []
    if SCRIPT_START not in text or SCRIPT_END not in text:
        additions.append(
            f"\n## R 脚本索引\n\n{SCRIPT_START}\n_尚未发现 R 脚本。_\n{SCRIPT_END}\n"
        )
    if AUDIT_START not in text or AUDIT_END not in text:
        additions.append(
            f"\n## Function 审计索引\n\n{AUDIT_START}\n_尚未发现 function 审计文件。_\n{AUDIT_END}\n"
        )
    if MEMORY_START not in text or MEMORY_END not in text:
        additions.append(
            f"\n## Memory 变更记录索引\n\n{MEMORY_START}\n_尚未发现 Memory 记录。_\n{MEMORY_END}\n"
        )
    if additions:
        project_file.write_text(text.rstrip() + "\n" + "\n".join(additions), encoding="utf-8")


def sanitize_summary(summary: str) -> str:
    cleaned = summary.strip().replace("_", "-")
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"[^\w\-\u4e00-\u9fff]+", "", cleaned, flags=re.UNICODE)
    cleaned = cleaned.strip("-")
    return cleaned or "change"


def sanitize_function_name(function_name: str) -> str:
    cleaned = function_name.strip()
    cleaned = re.sub(r"\(\)$", "", cleaned)
    cleaned = re.sub(r"[^\w.]+", "_", cleaned, flags=re.UNICODE)
    cleaned = cleaned.strip("_.")
    return cleaned or "function"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for i in range(2, 1000):
        candidate = path.with_name(f"{stem}-{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find an unused filename for {path}")


def create_memory(root: Path, magnitude: str, summary: str) -> Path:
    if magnitude not in VALID_MAGNITUDES:
        levels = ", ".join(VALID_MAGNITUDES)
        raise ValueError(f"Invalid magnitude '{magnitude}'. Use one of: {levels}")

    ensure_project(root)
    today = datetime.now().strftime("%Y%m%d")
    slug = sanitize_summary(summary)
    log_path = unique_path(root / "Memory" / f"{today}_{magnitude}_{slug}.md")
    log_path.write_text(
        f"""# {today} {magnitude} {summary.strip()}

## 1. 变更摘要

用可检查的语言说明本次具体改了什么。不要只写“更新了代码”。

- 

## 2. 用户意图与完成标准

复述用户真正想要什么，以及你判断“完成”的标准是什么。

- 用户意图:
- 完成标准:

## 3. 决策记录

列出你主动做出的选择；如有替代方案，说明为什么没有选。

- 决策:
- 未采用的替代方案:
- 原因:

## 4. 涉及文件

列出所有新建或修改的文件；没有文件改动时说明原因。

- 

## 5. R 可读性审计

如果涉及 R 代码，逐项确认；如果不涉及 R 代码，明确写“不涉及 R 代码”。

- 是否使用 RStudio section header 分隔主要代码块:
- 是否可以在 RStudio 中逐行运行:
- 关键步骤是否赋值给中间变量:
- 是否避免或拆分过长 pipeline:
- 是否在控制节点和数据转换处加入中文注释:
- 是否避免不必要 function；如存在 function，是否补齐 Roxygen2:
- 相关 function audit Rmd:

## 6. 数据与输出影响

说明是否影响输入数据、清洗边界、变量含义、结果文件或下游脚本衔接。

- 数据输入是否改变:
- 清洗规则或缺失值规则是否改变:
- 变量含义或 join key 是否改变:
- Results 输出是否改变:
- 下游兼容性:

## 7. 验证记录

记录实际运行的命令、人工检查、或无法验证的具体原因。

- 

## 8. 隐性预设坦白

主动坦白未由用户明示但你采用的预设，例如路径推断、编码、日期格式、缺失值策略、包依赖、输出命名、可接受风险边界。若没有新增预设，明确写“本次未引入新的隐性预设”。

- 

## 9. 风险与后续事项

写出剩余不确定性、脆弱依赖、可能需要用户确认的点，或明确说明没有后续风险。

- 
""",
        encoding="utf-8",
    )
    return log_path


def function_audit_template(function_name: str, source: str | None, memory: str | None) -> str:
    source_value = source or "TODO: 补充定义该 function 的 R 文件和 section"
    memory_value = memory or "TODO: 如有相关 Memory 记录，在这里补充路径"
    return f"""---
title: "Function Audit: {function_name}()"
output: html_document
---

# Function Audit: `{function_name}()`

## 1. 目的

说明这个 function 解决什么问题，为什么它需要被抽象，而不是保留为脚本中的扁平步骤。

- 目的:
- 抽象原因:

## 2. 来源位置与调用者

- 来源文件: `{source_value}`
- 相关 Memory 记录: `{memory_value}`
- 已知调用者:

## 3. 输入契约

逐项说明参数类型、必要列、允许值、禁止输入，以及默认值的含义。

| 参数 | 类型 | 必要结构 | 允许值 | 禁止值 |
| --- | --- | --- | --- | --- |
| TODO | TODO | TODO | TODO | TODO |

## 4. 输出契约

说明返回对象的类型、列或字段、行数是否可能变化、排序是否保持、是否有副作用。

- 返回类型:
- 必要输出列或字段:
- 行数变化规则:
- 排序规则:
- 副作用:

## 5. 逻辑拆解

逐步解释内部逻辑。必须覆盖 filter、join、mutate、case_when、NA 处理、日期处理、分组统计、模型输入准备等关键逻辑中实际存在的部分。

1. 
2. 
3. 

## 6. 最小 toy example

构造最小输入，展示 function 的实际输出。不要只写自然语言解释。

```{{r toy-input}}
# TODO: 构造最小 toy input
toy_input <- data.frame()
toy_input
```

```{{r toy-run}}
# TODO: source function 文件后，在 toy input 上运行 {function_name}()
# source("{source_value}")
# toy_output <- {function_name}(toy_input)
# toy_output
```

## 7. 边界情况

说明并测试相关边界情况；不相关的项目要写明为什么不相关。

- 缺失值:
- 空数据:
- 重复 ID:
- 异常日期:
- 未知分类:
- 数值边界:

## 8. 正确性检查

用可运行断言表达当前验证范围。不要写“100% 准确”；要写“在这些输入契约和测试样例下通过”。

```{{r correctness-checks}}
# TODO: 替换为真实断言
# stopifnot(...)
# identical(...)
# all.equal(...)
```

## 9. 已知限制

列出 function 不保证正确的情况、需要用户确认的业务规则、或依赖外部数据格式的脆弱点。

- 
"""


def create_function_audit(
    root: Path, function_name: str, source: str | None, memory: str | None
) -> Path:
    ensure_project(root)
    cleaned_name = sanitize_function_name(function_name)
    audit_path = root / "Audit" / "Functions" / f"audit_{cleaned_name}.Rmd"
    if audit_path.exists():
        return audit_path
    audit_path.write_text(
        function_audit_template(cleaned_name, source, memory),
        encoding="utf-8",
    )
    return audit_path


def first_comment(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    for line in lines[:30]:
        stripped = line.strip()
        if stripped.startswith("#'"):
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return "No leading description"


def render_script_index(root: Path) -> str:
    scripts = sorted((root / "R").glob("*.R"))
    if not scripts:
        return "_尚未发现 R 脚本。_"
    lines = []
    for script in scripts:
        rel = script.relative_to(root).as_posix()
        lines.append(f"- `{rel}`: {first_comment(script)}")
    return "\n".join(lines)


def render_memory_index(root: Path) -> str:
    logs = sorted((root / "Memory").glob("*.md"))
    if not logs:
        return "_尚未发现 Memory 记录。_"
    lines = []
    for log in logs:
        rel = log.relative_to(root).as_posix()
        lines.append(f"- `{rel}`")
    return "\n".join(lines)


def render_function_audit_index(root: Path) -> str:
    audits = sorted((root / "Audit" / "Functions").glob("*.Rmd"))
    if not audits:
        return "_尚未发现 function 审计文件。_"
    lines = []
    for audit in audits:
        rel = audit.relative_to(root).as_posix()
        lines.append(f"- `{rel}`")
    return "\n".join(lines)


def replace_or_append_block(text: str, heading: str, start: str, end: str, body: str) -> str:
    block = f"{start}\n{body}\n{end}"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(block, text)
    return text.rstrip() + f"\n\n## {heading}\n\n{block}\n"


def refresh_index(root: Path) -> Path:
    ensure_project(root)
    project_file = root / "project.md"
    text = project_file.read_text(encoding="utf-8")
    text = replace_or_append_block(
        text,
        "R Script Index",
        SCRIPT_START,
        SCRIPT_END,
        render_script_index(root),
    )
    text = replace_or_append_block(
        text,
        "Function Audit Index",
        AUDIT_START,
        AUDIT_END,
        render_function_audit_index(root),
    )
    text = replace_or_append_block(
        text,
        "Memory Ledger Index",
        MEMORY_START,
        MEMORY_END,
        render_memory_index(root),
    )
    project_file.write_text(text.rstrip() + "\n", encoding="utf-8")
    return project_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize Stepwise R Project scaffolds and maintain indexes."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create missing project scaffold.")
    init_parser.add_argument("target_dir", type=Path)

    memory_parser = subparsers.add_parser("memory", help="Create a Memory log template.")
    memory_parser.add_argument("target_dir", type=Path)
    memory_parser.add_argument("--magnitude", required=True, choices=VALID_MAGNITUDES)
    memory_parser.add_argument("--summary", required=True)

    audit_parser = subparsers.add_parser(
        "function-audit", help="Create a function audit R Markdown template."
    )
    audit_parser.add_argument("target_dir", type=Path)
    audit_parser.add_argument("--function", required=True, dest="function_name")
    audit_parser.add_argument("--source")
    audit_parser.add_argument("--memory")

    index_parser = subparsers.add_parser("index", help="Refresh project.md indexes.")
    index_parser.add_argument("target_dir", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.target_dir.expanduser().resolve()

    if args.command == "init":
        ensure_project(root)
        refresh_index(root)
        print(f"Initialized Stepwise R project: {root}")
    elif args.command == "memory":
        log_path = create_memory(root, args.magnitude, args.summary)
        refresh_index(root)
        print(f"Created Memory log: {log_path}")
    elif args.command == "function-audit":
        audit_path = create_function_audit(root, args.function_name, args.source, args.memory)
        refresh_index(root)
        print(f"Function audit ready: {audit_path}")
    elif args.command == "index":
        project_file = refresh_index(root)
        print(f"Updated index: {project_file}")
    else:
        parser.error(f"Unknown command: {args.command}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"stepwise-r-project error: {exc}", file=sys.stderr)
        raise SystemExit(1)
