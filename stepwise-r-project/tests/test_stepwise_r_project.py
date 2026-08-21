from __future__ import annotations

import contextlib
import errno
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "stepwise_r_project.py"
SPEC = importlib.util.spec_from_file_location("stepwise_r_project", SCRIPT_PATH)
assert SPEC and SPEC.loader
stepwise = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stepwise
SPEC.loader.exec_module(stepwise)


class StepwiseProjectTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        stepwise.ensure_v2_project(self.root, create=True)
        stepwise.refresh_index(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def invoke(self, *args: str) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return stepwise.main(list(args))

    def register_protocol(
        self,
        *,
        topic: str = "cohort-contract",
        content: str = "# Cohort Contract\n\nStatus: frozen\n\nCurrent definition.\n",
        section: str | None = None,
    ) -> None:
        self.write("docs/protocol.md", content)
        self.write("tests/contract_test.R", "stopifnot(TRUE)\n")
        stepwise.register_canonical(
            self.root,
            topic,
            "docs/protocol.md",
            section,
            "tests/contract_test.R",
            replace=False,
        )

    def memory_payload(self, title: str = "Revise cohort strategy", **changes: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "title": title,
            "related_topics": [],
            "supersedes": [],
            "invalidates": [],
            "before": "The analysis used the earlier strategy.",
            "trigger": "Diagnostics showed that the earlier assumption was unsafe.",
            "decision": "Use the revised strategy for the current analysis.",
            "scientific_or_technical_rationale": "The revision aligns the estimand with observed data support.",
            "basis": "Empirical diagnostic finding in Audit/Runs/model/current/diagnostics.csv.",
            "rejected_or_prior_approach": "Retain the earlier unsupported assumption.",
            "consequence": "Future analyses must use the revised strategy.",
        }
        payload.update(changes)
        return payload

    def attention_payload(self, *, blocking: bool = True, title: str = "Unresolved time zero") -> dict[str, object]:
        return {
            "title": title,
            "blocking": blocking,
            "observation": "Two scripts assign different cohort entry dates.",
            "evidence": "R/cohort.R uses enrollment_date; R/model.R uses index_date.",
            "why_it_matters": "Follow-up and event attribution may change.",
            "why_no_action_was_taken": "Choosing the scientific time zero is outside the current task.",
            "human_decision_needed": "Confirm the authoritative time-zero definition.",
        }

    def legacy_memory_text(
        self,
        task_key: str,
        *,
        topic: str = "cohort-contract",
        canonical_path: str = "docs/cohort.md",
    ) -> str:
        return f"""---
task_key: {json.dumps(task_key)}
canonical_topic: {json.dumps(topic)}
canonical_path: {json.dumps(canonical_path)}
---

# {task_key}

## Change And Reason

- Change: The analysis design changed after scientific review.
- Why: Diagnostics or collaborator input showed the prior approach was unsuitable.

## Verification

- Verification: The registered contract test passed before migration.

## Open Risks

- Risk: A material question may still require human review.
"""

    def make_v2_project(
        self,
        root: Path,
        *,
        aliases: tuple[str, str, str, str] = ("R", "Data", "Results", "Audit"),
        memory_keys: tuple[str, ...] = (),
        realistic: bool = False,
    ) -> Path:
        root = root.resolve()
        r_name, data_name, results_name, audit_name = aliases
        for dirname in aliases:
            (root / dirname).mkdir(parents=True, exist_ok=True)
        stepwise.ensure_v3_project(root, create=True)

        def write(relative: str, content: str) -> Path:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return path

        write(f"{r_name}/analysis.R", "# Existing analysis\nx <- 1\n")
        write(
            "docs/cohort.md",
            "# Cohort Contract\n\nStatus: frozen\n\nCurrent cohort definition.\n",
        )
        write("tests/cohort_contract.R", "stopifnot(TRUE)\n")
        stepwise.register_canonical(
            root,
            "cohort-contract",
            "docs/cohort.md",
            None,
            "tests/cohort_contract.R",
            replace=False,
        )
        if realistic:
            write(
                "docs/outcome.md",
                "# Outcome Contract\n\nStatus: frozen\n\nCurrent outcome definition.\n",
            )
            write("tests/outcome_contract.R", "stopifnot(TRUE)\n")
            stepwise.register_canonical(
                root,
                "outcome-contract",
                "docs/outcome.md",
                None,
                "tests/outcome_contract.R",
                replace=False,
            )
            write(f"{data_name}/source.csv", "id,value\n1,10\n")
            write(f"{results_name}/table1.csv", "term,value\nage,50\n")
            stepwise.register_result(
                root,
                "table1",
                f"{results_name}/table1.csv",
                "table",
                "publication",
                f"{r_name}/analysis.R",
                replace=False,
            )
            source = write(
                f"{r_name}/eligibility.R",
                "#' Derive eligibility\n#' @param x Logical vector\n"
                "derive_eligibility <- function(x) { x }\n",
            )
            function_dir = root / audit_name / "Functions"
            function_dir.mkdir(parents=True)
            write(
                f"{audit_name}/Functions/audit_derive_eligibility.Rmd",
                f"""---
title: "Function Audit: derive_eligibility()"
stepwise_function: "derive_eligibility"
source: "{r_name}/eligibility.R"
source_sha256: "{stepwise.file_sha256(source)}"
risk_reason: "Eligibility errors alter the cohort"
---

# Function Audit: `derive_eligibility()`

## Purpose And Risk

Derive cohort eligibility under the registered contract.

## Input And Output Contract

Accept and return a logical vector without side effects.

## Edge Cases And Contract Tests

Covered by `tests/cohort_contract.R`.

## Known Limits

Inputs must already be logical.
""",
            )
            write(
                f"{audit_name}/Runs/model/current/evidence.json",
                '{"status":"pass"}\n',
            )
        stepwise.refresh_index(root)
        shutil.rmtree(root / "Memory")
        shutil.rmtree(root / "Attention")
        project_file = root / "project.md"
        text = project_file.read_text(encoding="utf-8")
        navigation = (
            f"## Managed Navigation\n\n{stepwise.NAVIGATION_START}\n"
            f"{stepwise.managed_navigation_table()}\n"
            f"{stepwise.NAVIGATION_END}\n\n"
        )
        text = text.replace(stepwise.SCHEMA_MARKER, stepwise.V2_SCHEMA_MARKER)
        text = text.replace(navigation, "")
        project_file.write_text(text, encoding="utf-8")
        if memory_keys:
            memory_dir = root / "Memory"
            memory_dir.mkdir()
            for key in memory_keys:
                (memory_dir / f"{key}.md").write_text(
                    self.legacy_memory_text(key), encoding="utf-8"
                )
        report = stepwise.validate_v2_project(root)
        self.assertFalse(report.errors, report.errors)
        return root

    def initialize_git(self, root: Path) -> None:
        commands = (
            ("git", "init", "-q"),
            ("git", "config", "user.email", "stepwise@example.test"),
            ("git", "config", "user.name", "Stepwise Test"),
            ("git", "add", "."),
            ("git", "-c", "commit.gpgsign=false", "commit", "-qm", "v2 baseline"),
        )
        for command in commands:
            subprocess.run(command, cwd=root, check=True, capture_output=True)

    def migration_record(
        self,
        path: str,
        *,
        decisions: list[dict[str, object]] | None = None,
        attention: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        decision_entries = decisions or []
        attention_entries = attention or []
        return {
            "path": path,
            "decision_memories": decision_entries,
            "attention_entries": attention_entries,
            "no_migration_required": not decision_entries and not attention_entries,
        }

    def test_init_and_index_are_idempotent(self) -> None:
        before = (self.root / "project.md").read_text(encoding="utf-8")
        before_files = sorted(
            path.relative_to(self.root)
            for path in self.root.rglob("*")
            if path.is_file()
        )

        stepwise.ensure_v2_project(self.root, create=True)
        stepwise.refresh_index(self.root)
        stepwise.ensure_v2_project(self.root, create=True)
        stepwise.refresh_index(self.root)

        after = (self.root / "project.md").read_text(encoding="utf-8")
        after_files = sorted(
            path.relative_to(self.root)
            for path in self.root.rglob("*")
            if path.is_file()
        )
        self.assertEqual(before, after)
        self.assertEqual(before_files, after_files)
        self.assertEqual(after.count(stepwise.CANONICAL_START), 1)
        self.assertNotIn(stepwise.LEGACY_MEMORY_START, after)

    def test_index_normalizes_canonical_registration_order(self) -> None:
        self.write(
            "docs/z_protocol.md",
            "# Z Contract\n\nStatus: frozen\n\nCurrent definition.\n",
        )
        self.write(
            "docs/a_protocol.md",
            "# A Contract\n\nStatus: frozen\n\nCurrent definition.\n",
        )
        self.write("tests/contract_test.R", "stopifnot(TRUE)\n")
        stepwise.register_canonical(
            self.root, "z-topic", "docs/z_protocol.md", None,
            "tests/contract_test.R", replace=False,
        )
        stepwise.register_canonical(
            self.root, "a-topic", "docs/a_protocol.md", None,
            "tests/contract_test.R", replace=False,
        )
        project_file = self.root / "project.md"
        text = project_file.read_text(encoding="utf-8")
        entries = stepwise.parse_canonical_entries(text)
        text = stepwise.replace_block(
            text,
            stepwise.CANONICAL_START,
            stepwise.CANONICAL_END,
            stepwise.markdown_table(
                ("Topic", "Canonical path", "Section", "Contract test"),
                [
                    (entry.topic, entry.path, entry.section or "-", entry.verification)
                    for entry in reversed(entries)
                ],
            ),
            "canonical source",
        )
        project_file.write_text(text, encoding="utf-8")

        stepwise.refresh_index(self.root)

        normalized = stepwise.parse_canonical_entries(
            project_file.read_text(encoding="utf-8")
        )
        self.assertEqual([entry.topic for entry in normalized], ["a-topic", "z-topic"])
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

    def test_full_cli_sequence_is_idempotent(self) -> None:
        self.write(
            "docs/protocol.md",
            "# Cohort Contract\n\nStatus: frozen\n\nCurrent definition.\n",
        )
        self.write("tests/contract_test.R", "stopifnot(TRUE)\n")
        self.write("R/01_table.R", "# Build Table 1\n")
        self.write("Results/table1.csv", "term,value\nage,50\n")

        first_commands = (
            (
                "canonical",
                str(self.root),
                "--topic",
                "cohort-contract",
                "--path",
                "docs/protocol.md",
                "--verification",
                "tests/contract_test.R",
            ),
            (
                "result",
                str(self.root),
                "--id",
                "table1",
                "--path",
                "Results/table1.csv",
                "--kind",
                "table",
                "--audience",
                "publication",
                "--producer",
                "R/01_table.R",
            ),
            ("index", str(self.root)),
        )
        for command in first_commands:
            self.assertEqual(self.invoke(*command), 0)
        before_text = (self.root / "project.md").read_text(encoding="utf-8")
        before_files = sorted(
            path.relative_to(self.root)
            for path in self.root.rglob("*")
            if path.is_file()
        )

        self.assertEqual(self.invoke("init", str(self.root)), 0)
        for command in first_commands:
            self.assertEqual(self.invoke(*command), 0)

        after_text = (self.root / "project.md").read_text(encoding="utf-8")
        after_files = sorted(
            path.relative_to(self.root)
            for path in self.root.rglob("*")
            if path.is_file()
        )
        self.assertEqual(before_text, after_text)
        self.assertEqual(before_files, after_files)
        self.assertEqual(after_text.count("| cohort-contract |"), 1)
        self.assertEqual(after_text.count("| table1 |"), 1)

    def test_concurrent_registry_upserts_do_not_lose_rows(self) -> None:
        for key in ("cohort", "outcome"):
            self.write(
                f"docs/{key}.md",
                f"# {key.title()} Contract\n\nStatus: frozen\n\nCurrent definition.\n",
            )
            self.write(f"tests/test_{key}.R", "stopifnot(TRUE)\n")
            self.write(f"R/{key}.R", f"# Build {key} table\n")
            self.write(f"Results/{key}.csv", "term,value\nx,1\n")

        operations = (
            lambda: stepwise.register_canonical(
                self.root,
                "cohort",
                "docs/cohort.md",
                None,
                "tests/test_cohort.R",
                replace=False,
            ),
            lambda: stepwise.register_canonical(
                self.root,
                "outcome",
                "docs/outcome.md",
                None,
                "tests/test_outcome.R",
                replace=False,
            ),
            lambda: stepwise.register_result(
                self.root,
                "cohort-table",
                "Results/cohort.csv",
                "table",
                "formal-review",
                "R/cohort.R",
                replace=False,
            ),
            lambda: stepwise.register_result(
                self.root,
                "outcome-table",
                "Results/outcome.csv",
                "table",
                "formal-review",
                "R/outcome.R",
                replace=False,
            ),
        )
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(operation) for operation in operations]
            for future in futures:
                future.result()

        stepwise.refresh_index(self.root)
        text = (self.root / "project.md").read_text(encoding="utf-8")
        for key in ("cohort", "outcome", "cohort-table", "outcome-table"):
            self.assertEqual(text.count(f"| {key} |"), 1)
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

    def test_init_adopts_existing_aliases_without_parallel_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "alias-project"
            for dirname in ("r", "data", "output", "audit"):
                (root / dirname).mkdir(parents=True, exist_ok=True)
            stepwise.ensure_v2_project(root, create=True)
            text = (root / "project.md").read_text(encoding="utf-8")
            directory_names = {path.name for path in root.iterdir() if path.is_dir()}
            self.assertIn("| R | r |", text)
            self.assertIn("| Results | output |", text)
            self.assertNotIn("R", directory_names)
            self.assertNotIn("Results", directory_names)

    def test_init_rejects_ambiguous_aliases_before_writing_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ambiguous-project"
            (root / "Results").mkdir(parents=True)
            (root / "output").mkdir()
            with self.assertRaisesRegex(stepwise.ProjectError, "Ambiguous Results"):
                stepwise.ensure_v2_project(root, create=True)
            self.assertFalse((root / "project.md").exists())

    def test_init_adopts_existing_project_without_moving_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "existing-project"
            script = root / "R" / "existing.R"
            script.parent.mkdir(parents=True)
            script.write_text("# Existing analysis\nx <- 1\n", encoding="utf-8")
            original = script.read_text(encoding="utf-8")

            stepwise.ensure_v2_project(root, create=True)
            stepwise.refresh_index(root)

            self.assertEqual(script.read_text(encoding="utf-8"), original)
            self.assertTrue((root / "project.md").exists())
            self.assertEqual(
                {"Attention", "Audit", "Data", "Memory", "R", "Results"},
                {path.name for path in root.iterdir() if path.is_dir()},
            )

    def test_canonical_registration_is_idempotent_and_replace_is_explicit(self) -> None:
        self.register_protocol()
        first = (self.root / "project.md").read_text(encoding="utf-8")
        self.register_protocol()
        second = (self.root / "project.md").read_text(encoding="utf-8")
        self.assertEqual(first, second)
        self.assertEqual(second.count("| cohort-contract |"), 1)

        self.write("docs/replacement.md", "# Replacement\n\nStatus: frozen\n")
        with self.assertRaisesRegex(stepwise.ProjectError, "already exists"):
            stepwise.register_canonical(
                self.root,
                "cohort-contract",
                "docs/replacement.md",
                None,
                "tests/contract_test.R",
                replace=False,
            )
        stepwise.register_canonical(
            self.root,
            "cohort-contract",
            "docs/replacement.md",
            None,
            "tests/contract_test.R",
            replace=True,
        )
        updated = (self.root / "project.md").read_text(encoding="utf-8")
        self.assertIn("docs/replacement.md", updated)
        self.assertNotIn("docs/protocol.md", updated)

    def test_canonical_metadata_upserts_without_owner_replacement(self) -> None:
        self.register_protocol()
        self.write("tests/revised_contract_test.R", "stopifnot(1 + 1 == 2)\n")
        stepwise.register_canonical(
            self.root,
            "cohort-contract",
            "docs/protocol.md",
            None,
            "tests/revised_contract_test.R",
            replace=False,
        )
        text = (self.root / "project.md").read_text(encoding="utf-8")
        self.assertIn("tests/revised_contract_test.R", text)
        self.assertNotIn("tests/contract_test.R", text)

    def test_canonical_rejects_empty_or_non_executable_contract_test(self) -> None:
        self.write("docs/protocol.md", "# Contract\n\nStatus: frozen\n")
        self.write("tests/empty.R", "")
        with self.assertRaisesRegex(stepwise.ProjectError, "cannot be empty"):
            stepwise.register_canonical(
                self.root,
                "cohort-contract",
                "docs/protocol.md",
                None,
                "tests/empty.R",
                replace=False,
            )

        self.write("tests/notes.txt", "not an executable contract test\n")
        with self.assertRaisesRegex(stepwise.ProjectError, "must use one of"):
            stepwise.register_canonical(
                self.root,
                "cohort-contract",
                "docs/protocol.md",
                None,
                "tests/notes.txt",
                replace=False,
            )

    def test_canonical_section_limits_execution_metadata_check(self) -> None:
        content = """# Protocol

run_id: historical-page-metadata

## Current Contract

Status: frozen

Current definition.
"""
        self.register_protocol(content=content, section="Current Contract")
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

    def test_frozen_contract_rejects_unresolved_language_and_run_status(self) -> None:
        self.register_protocol(
            content="# Cohort Contract\n\nStatus: frozen\n\nTODO: 待确认并待重算。\n"
        )
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("unresolved language" in error for error in report.errors))

        self.write(
            "docs/protocol.md",
            "# Cohort Contract\n\nStatus: partially-frozen\n\nrun_id=abc PASS\n",
        )
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("execution status" in error for error in report.errors))

    def test_frozen_contract_allows_lowercase_contract_pass_and_time_function(self) -> None:
        self.register_protocol(
            content=(
                "# Cohort Contract\n\n"
                "Status: frozen\n\n"
                "The contract value is `pass` and the model is 通过时间函数定义。\n"
            )
        )
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

    def test_frozen_contract_still_rejects_uppercase_run_ledger(self) -> None:
        self.register_protocol(
            content="# Cohort Contract\n\nStatus: frozen\n\nrun_id=abc BLOCKED\n"
        )
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("execution status" in error for error in report.errors))

    def test_canonical_status_is_required_and_cannot_contradict_itself(self) -> None:
        self.register_protocol(content="# Cohort Contract\n\nCurrent definition.\n")
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("lacks Status" in error for error in report.errors))

        self.write(
            "docs/protocol.md",
            "# Cohort Contract\n\nStatus: frozen\n\nStatus: partially-frozen\n",
        )
        report = stepwise.validate_project(self.root)
        self.assertTrue(
            any("contradictory freeze states" in error for error in report.errors)
        )

    def test_unregistered_second_frozen_source_fails_validation(self) -> None:
        self.register_protocol()
        self.write(
            "docs/parallel_protocol.md",
            "# Parallel Contract\n\nStatus: frozen\n\nA competing current definition.\n",
        )
        report = stepwise.validate_project(self.root)
        self.assertTrue(
            any(
                "not registered as a canonical source" in error
                for error in report.errors
            )
        )

    def test_status_source_outside_lowercase_docs_is_detected(self) -> None:
        self.register_protocol()
        self.write(
            "docs_v2/cohort_freeze_update_v2.md",
            "# Parallel Contract\n\nStatus: frozen\n\nCompeting definition.\n",
        )
        report = stepwise.validate_project(self.root)
        self.assertTrue(
            any(
                "docs_v2/cohort_freeze_update_v2.md" in error for error in report.errors
            )
        )

    def test_frozen_checks_ignore_examples_and_allow_lowercase_contract_value(self) -> None:
        self.register_protocol(
            content="""# Cohort Contract

Status: frozen

Current definition.

```text
Status: frozen
TODO: quoted template
pass
```
"""
        )
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

        self.write(
            "docs/protocol.md",
            "# Cohort Contract\n\nStatus: frozen\n\nTBD: decide later.\npass\n",
        )
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("unresolved language" in error for error in report.errors))
        self.assertFalse(any("execution status" in error for error in report.errors))

    def test_attention_creation_resolution_blocking_and_index(self) -> None:
        first = stepwise.add_attention(self.root, self.attention_payload(blocking=True))
        second = stepwise.add_attention(
            self.root,
            self.attention_payload(blocking=False, title="Unresolved provenance label"),
        )
        self.assertEqual(first.name, "A-0001.md")
        self.assertEqual(second.name, "A-0002.md")
        index = (self.root / "Attention/index.md").read_text(encoding="utf-8")
        self.assertIn("| A-0001 | true |", index)
        self.assertIn("| A-0002 | false |", index)
        resolved = stepwise.resolve_attention(self.root, "A-0001")
        self.assertFalse(resolved.exists())
        self.assertNotIn("A-0001", (self.root / "Attention/index.md").read_text(encoding="utf-8"))
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

    def test_attention_rejects_invalid_schema_duplicate_and_topology(self) -> None:
        payload = self.attention_payload()
        stepwise.add_attention(self.root, payload)
        with self.assertRaisesRegex(stepwise.ProjectError, "Equivalent active"):
            stepwise.add_attention(self.root, payload)
        invalid = dict(payload)
        invalid["blocking"] = "yes"
        with self.assertRaisesRegex(stepwise.ProjectError, "true or false"):
            stepwise.add_attention(self.root, invalid)
        self.write("Attention/resolved/A-9999.md", "legacy\n")
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("Unexpected Attention paths" in error for error in report.errors))

    def test_memory_add_allows_empty_topics_and_generates_index(self) -> None:
        memory = stepwise.add_decision_memory(self.root, self.memory_payload())
        self.assertEqual(memory.name, "M-0001.md")
        values = stepwise.parse_managed_entry(
            memory, stepwise.MEMORY_FIELDS, "Decision Memory entry"
        )
        self.assertEqual(values["Status"], "active")
        self.assertEqual(values["Related Topics"], "[]")
        self.assertIn("M-0001", (self.root / "Memory/index.md").read_text(encoding="utf-8"))
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

    def test_memory_supersedes_and_invalidates_with_reverse_links(self) -> None:
        first = stepwise.add_decision_memory(self.root, self.memory_payload("First decision"))
        second = stepwise.add_decision_memory(
            self.root,
            self.memory_payload("Second decision", supersedes=["M-0001"]),
        )
        third = stepwise.add_decision_memory(
            self.root,
            self.memory_payload("Third decision"),
        )
        fourth = stepwise.add_decision_memory(
            self.root,
            self.memory_payload("Fourth decision", invalidates=["M-0003"]),
        )
        first_values = stepwise.parse_managed_entry(first, stepwise.MEMORY_FIELDS, "memory")
        third_values = stepwise.parse_managed_entry(third, stepwise.MEMORY_FIELDS, "memory")
        self.assertEqual(first_values["Status"], "superseded")
        self.assertEqual(first_values["Superseded By"], '["M-0002"]')
        self.assertEqual(third_values["Status"], "invalidated")
        self.assertEqual(third_values["Invalidated By"], '["M-0004"]')
        self.assertEqual(second.name, "M-0002.md")
        self.assertEqual(fourth.name, "M-0004.md")
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

    def test_memory_rejects_invalid_reference_schema_and_topology(self) -> None:
        with self.assertRaisesRegex(stepwise.ProjectError, "do not exist"):
            stepwise.add_decision_memory(
                self.root,
                self.memory_payload(supersedes=["M-9999"]),
            )
        invalid = self.memory_payload()
        invalid.pop("basis")
        with self.assertRaisesRegex(stepwise.ProjectError, "missing fields: basis"):
            stepwise.add_decision_memory(self.root, invalid)
        self.write("Memory/archive/M-0001.md", "legacy\n")
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("Unexpected Memory paths" in error for error in report.errors))

    def test_concurrent_memory_and_attention_id_allocation_is_safe(self) -> None:
        operations = []
        for number in range(8):
            operations.append(
                lambda number=number: stepwise.add_decision_memory(
                    self.root, self.memory_payload(f"Decision {number}")
                )
            )
            operations.append(
                lambda number=number: stepwise.add_attention(
                    self.root,
                    self.attention_payload(
                        blocking=bool(number % 2), title=f"Attention {number}"
                    ),
                )
            )
        with ThreadPoolExecutor(max_workers=8) as executor:
            paths = [future.result() for future in [executor.submit(op) for op in operations]]
        self.assertEqual(len({path.name for path in paths if path.name.startswith("M-")}), 8)
        self.assertEqual(len({path.name for path in paths if path.name.startswith("A-")}), 8)
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

    def test_managed_system_cli_uses_structured_payloads_end_to_end(self) -> None:
        memory_input = self.write(
            "memory-input.json", json.dumps(self.memory_payload())
        )
        attention_input = self.write(
            "attention-input.json", json.dumps(self.attention_payload())
        )
        self.assertEqual(
            self.invoke(
                "memory", "add", str(self.root), "--input", str(memory_input)
            ),
            0,
        )
        self.assertEqual(
            self.invoke(
                "attention", "raise", str(self.root), "--input", str(attention_input)
            ),
            0,
        )
        self.assertEqual(
            self.invoke("attention", "resolve", str(self.root), "--id", "A-0001"),
            0,
        )
        self.assertTrue((self.root / "Memory/entries/M-0001.md").exists())
        self.assertFalse((self.root / "Attention/entries/A-0001.md").exists())
        self.assertEqual(self.invoke("index", str(self.root)), 0)
        self.assertEqual(self.invoke("validate", str(self.root)), 0)

    def test_result_registration_and_validation(self) -> None:
        self.write("R/01_table.R", "# Build current Table 1\n")
        self.write("Results/table1.csv", "term,value\nage,50\n")
        stepwise.register_result(
            self.root,
            "table1",
            "Results/table1.csv",
            "table",
            "publication",
            "R/01_table.R",
            replace=False,
        )
        stepwise.refresh_index(self.root)
        first = (self.root / "project.md").read_text(encoding="utf-8")
        stepwise.register_result(
            self.root,
            "table1",
            "Results/table1.csv",
            "table",
            "publication",
            "R/01_table.R",
            replace=False,
        )
        self.assertEqual(first, (self.root / "project.md").read_text(encoding="utf-8"))
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

    def test_result_metadata_upserts_when_current_path_is_unchanged(self) -> None:
        self.write("R/01_table.R", "# Initial table producer\n")
        self.write("R/02_table.R", "# Revised table producer\n")
        self.write("Results/table1.csv", "term,value\nage,50\n")
        stepwise.register_result(
            self.root,
            "table1",
            "Results/table1.csv",
            "table",
            "publication",
            "R/01_table.R",
            replace=False,
        )
        stepwise.register_result(
            self.root,
            "table1",
            "Results/table1.csv",
            "table",
            "formal-review",
            "R/02_table.R",
            replace=False,
        )
        text = (self.root / "project.md").read_text(encoding="utf-8")
        self.assertIn(
            "| table1 | Results/table1.csv | table | formal-review | R/02_table.R |",
            text,
        )

    def test_results_distinguish_scientific_status_from_run_status(self) -> None:
        self.write("R/01_table.R", "# Build current status table\n")
        self.write("Results/baseline_status.csv", "status,n\nactive,10\n")
        stepwise.register_result(
            self.root,
            "baseline-status",
            "Results/baseline_status.csv",
            "table",
            "formal-review",
            "R/01_table.R",
            replace=False,
        )
        self.write("Results/run_status.csv", "status\nPASS\n")
        with self.assertRaisesRegex(stepwise.ProjectError, "machine/obsolete"):
            stepwise.register_result(
                self.root,
                "run-status",
                "Results/run_status.csv",
                "table",
                "formal-review",
                "R/01_table.R",
                replace=False,
            )

    def test_result_kind_must_match_figure_extension(self) -> None:
        self.write("R/01_figure.R", "# Build current figure\n")
        self.write("Results/figure.csv", "x,y\n1,2\n")
        with self.assertRaisesRegex(stepwise.ProjectError, "kind 'figure'"):
            stepwise.register_result(
                self.root,
                "figure1",
                "Results/figure.csv",
                "figure",
                "publication",
                "R/01_figure.R",
                replace=False,
            )

    def test_results_reject_unregistered_machine_and_binary_artifacts(self) -> None:
        self.write("R/01_table.R", "# Build current Table 1\n")
        self.write("Results/step01_audit.csv", "check,passed\nkey,true\n")
        self.write("Results/model.rds", "not-an-rds")
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("unregistered file" in error for error in report.errors))
        self.assertTrue(any("machine/obsolete" in error for error in report.errors))
        self.assertTrue(any("non-human artifact" in error for error in report.errors))

    def test_result_registration_rejects_machine_artifacts_and_non_r_producers(
        self,
    ) -> None:
        self.write("R/01_table.R", "# Build current table\n")
        self.write("Results/run_cache/table.csv", "term,value\nage,50\n")
        with self.assertRaisesRegex(stepwise.ProjectError, "machine/obsolete"):
            stepwise.register_result(
                self.root,
                "cached-table",
                "Results/run_cache/table.csv",
                "table",
                "publication",
                "R/01_table.R",
                replace=False,
            )

        self.write("Results/qa/check.csv", "check,passed\nx,true\n")
        with self.assertRaisesRegex(stepwise.ProjectError, "machine/obsolete"):
            stepwise.register_result(
                self.root,
                "qa-check",
                "Results/qa/check.csv",
                "table",
                "formal-review",
                "R/01_table.R",
                replace=False,
            )

        self.write("Results/table1.csv", "term,value\nage,50\n")
        self.write("docs/build_notes.md", "# Not an R producer\n")
        with self.assertRaisesRegex(
            stepwise.ProjectError, "inside the active R directory"
        ):
            stepwise.register_result(
                self.root,
                "table1",
                "Results/table1.csv",
                "table",
                "publication",
                "docs/build_notes.md",
                replace=False,
            )

    def test_versioned_result_directory_fails_even_when_file_is_registered(
        self,
    ) -> None:
        self.write("R/01_table.R", "# Build current table\n")
        self.write("Results/legacy/table1.csv", "term,value\nage,50\n")
        with self.assertRaisesRegex(stepwise.ProjectError, "machine/obsolete"):
            stepwise.register_result(
                self.root,
                "table1",
                "Results/legacy/table1.csv",
                "table",
                "publication",
                "R/01_table.R",
                replace=False,
            )

    def test_function_audit_is_draft_then_requires_in_place_update(self) -> None:
        source = self.write(
            "R/functions.R", "# Risky function\ncohort_filter <- function(x) x\n"
        )
        audit, action = stepwise.create_or_locate_function_audit(
            self.root,
            "cohort_filter",
            "R/functions.R",
            "Changes cohort eligibility",
        )
        original = audit.read_text(encoding="utf-8")
        same_audit, second_action = stepwise.create_or_locate_function_audit(
            self.root,
            "cohort_filter",
            "R/functions.R",
            "Changes cohort eligibility",
        )
        self.assertEqual(action, "CREATED_DRAFT")
        self.assertEqual(second_action, "UPDATE_REQUIRED")
        self.assertEqual(audit, same_audit)
        self.assertEqual(original, audit.read_text(encoding="utf-8"))
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("unfinished template" in error for error in report.errors))

        completed = (
            original.replace(
                "TODO: Explain the behavior and why an error could alter the scientific result or contract.",
                "Filters the eligible cohort; an error changes the estimand.",
            )
            .replace(
                "TODO: State required inputs, keys, allowed values, output shape, and side effects.",
                "Requires a unique patient-month key and returns a filtered data frame.",
            )
            .replace(
                "TODO: Link to executable tests for missing values, empty data, duplicates, dates, and boundaries.",
                "Covered by tests/test_cohort_filter.R for missing and boundary values.",
            )
            .replace(
                "TODO: State conditions outside the validated contract.",
                "Does not accept duplicate patient-month keys.",
            )
        )
        audit.write_text(completed, encoding="utf-8")
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

        source.write_text(
            "# Risky function\ncohort_filter <- function(x) x[!is.na(x), ]\n",
            encoding="utf-8",
        )
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("stale for its source" in error for error in report.errors))

    def test_function_audit_source_change_returns_existing_path_without_overwrite(
        self,
    ) -> None:
        self.write("R/a.R", "cohort_filter <- function(x) x\n")
        self.write("R/b.R", "cohort_filter <- function(x) x[!is.na(x)]\n")
        audit, _ = stepwise.create_or_locate_function_audit(
            self.root,
            "cohort_filter",
            "R/a.R",
            "Changes cohort eligibility",
        )
        original = audit.read_text(encoding="utf-8")
        same_audit, action = stepwise.create_or_locate_function_audit(
            self.root,
            "cohort_filter",
            "R/b.R",
            "Changes cohort eligibility and missingness",
        )
        self.assertEqual(action, "UPDATE_REQUIRED")
        self.assertEqual(same_audit, audit)
        self.assertEqual(audit.read_text(encoding="utf-8"), original)

    def test_function_audit_without_required_body_fails_validation(self) -> None:
        self.write("R/functions.R", "cohort_filter <- function(x) x\n")
        audit, _ = stepwise.create_or_locate_function_audit(
            self.root,
            "cohort_filter",
            "R/functions.R",
            "Changes cohort eligibility",
        )
        original = audit.read_text(encoding="utf-8")
        frontmatter = original.split("---", 2)[1]
        audit.write_text(f"---{frontmatter}---\n\n# Function Audit\n", encoding="utf-8")
        report = stepwise.validate_project(self.root)
        self.assertTrue(
            any(
                "requires exactly one 'Known Limits' section" in error
                for error in report.errors
            )
        )

    def test_function_audit_requires_named_function_in_source(self) -> None:
        self.write("R/functions.R", "other_function <- function(x) x\n")
        with self.assertRaisesRegex(stepwise.ProjectError, "is not defined"):
            stepwise.create_or_locate_function_audit(
                self.root,
                "cohort_filter",
                "R/functions.R",
                "Changes cohort eligibility",
            )

    def test_rendered_function_html_fails_validation(self) -> None:
        self.write("Audit/Functions/audit_example.html", "<html></html>\n")
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("rendered HTML" in error for error in report.errors))

    def test_audit_runs_allow_only_current_directory(self) -> None:
        self.write(
            "Audit/Runs/step01/current/acceptance.csv", "check,passed\nkey,true\n"
        )
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)
        self.write("Audit/Runs/step01/20260802/trace.csv", "x\n1\n")
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("historical/staging" in error for error in report.errors))

    def test_audit_runs_reject_root_files_and_stages_without_current(self) -> None:
        self.write("Audit/Runs/orphan_manifest.json", "{}\n")
        self.write("Audit/Runs/step02/staging/check.csv", "check,passed\nx,true\n")
        report = stepwise.validate_project(self.root)
        self.assertTrue(
            any("outside a stage/current" in error for error in report.errors)
        )
        self.assertTrue(
            any("has no current directory" in error for error in report.errors)
        )

    def test_audit_current_rejects_nested_historical_directories(self) -> None:
        self.write("Audit/Runs/step01/current/old/trace.csv", "x\n1\n")
        report = stepwise.validate_project(self.root)
        self.assertTrue(
            any(
                "current contains historical/version" in error
                for error in report.errors
            )
        )

    def test_parallel_old_document_copy_fails_validation(self) -> None:
        self.write("docs/protocol_old.md", "# Old protocol\n")
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("Parallel old/backup" in error for error in report.errors))

    def test_parallel_dated_document_copy_fails_validation(self) -> None:
        self.write("docs/protocol.md", "# Protocol\n")
        self.write("docs/protocol_20260802.md", "# Protocol snapshot\n")
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("old/backup/versioned" in error for error in report.errors))

    def test_validate_detects_stale_script_index(self) -> None:
        self.write("R/01_analysis.R", "# Current analysis\n")
        report = stepwise.validate_project(self.root)
        self.assertTrue(
            any(
                "stale or non-canonical script index" in error
                for error in report.errors
            )
        )
        stepwise.refresh_index(self.root)
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

    def test_script_index_escapes_markdown_table_delimiters(self) -> None:
        self.write("R/01_analysis.R", "# Compare A | B\nx <- 1\n")
        stepwise.refresh_index(self.root)
        text = (self.root / "project.md").read_text(encoding="utf-8")
        self.assertIn("Compare A &#124; B", text)
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

    def test_validate_cli_returns_nonzero_on_contract_failure(self) -> None:
        self.assertEqual(self.invoke("validate", str(self.root)), 0)
        self.write("Results/unregistered.csv", "x\n1\n")
        self.assertEqual(self.invoke("validate", str(self.root)), 1)

    def test_project_detection_distinguishes_v2_v3_unmanaged_and_damaged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            v2 = self.make_v2_project(base / "v2")
            self.assertEqual(stepwise.detect_project_state(v2), stepwise.MIGRATION_REQUIRED)
            v2_report = stepwise.validate_project(v2)
            self.assertEqual(v2_report.state, stepwise.MIGRATION_REQUIRED)
            self.assertFalse(v2_report.errors)

            v3 = base / "v3"
            stepwise.ensure_v3_project(v3, create=True)
            stepwise.refresh_index(v3)
            self.assertEqual(stepwise.detect_project_state(v3), stepwise.PROJECT_V3)
            self.assertTrue(stepwise.validate_project(v3).ok)

            unmanaged = base / "unmanaged"
            unmanaged.mkdir()
            (unmanaged / "project.md").write_text("# Project\n", encoding="utf-8")
            self.assertEqual(
                stepwise.detect_project_state(unmanaged), stepwise.PROJECT_UNMANAGED
            )
            self.assertEqual(
                stepwise.validate_project(unmanaged).state, stepwise.PROJECT_UNMANAGED
            )

            damaged = self.make_v2_project(base / "damaged")
            project_file = damaged / "project.md"
            project_file.write_text(
                project_file.read_text(encoding="utf-8")
                + f"\n{stepwise.SCHEMA_MARKER}\n",
                encoding="utf-8",
            )
            self.assertEqual(
                stepwise.detect_project_state(damaged), stepwise.PROJECT_DAMAGED
            )
            self.assertTrue(stepwise.migration_preflight(damaged)["structural_blockers"])

    def test_init_refuses_v2_without_partial_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(Path(temp_dir) / "v2", memory_keys=("history",))
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            with self.assertRaisesRegex(stepwise.ProjectError, "migrate --check"):
                stepwise.ensure_v3_project(root, create=True)
            after = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)
            self.assertFalse((root / "Attention").exists())

    def test_migration_preflight_is_read_only_and_inventory_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(
                Path(temp_dir) / "v2",
                aliases=("r", "data", "output", "audit"),
                memory_keys=("decision", "routine"),
                realistic=True,
            )
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            first = stepwise.migration_preflight(root)
            second = stepwise.migration_preflight(root)
            after = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first, second)
            self.assertEqual(before, after)
            self.assertEqual(first["state"], stepwise.MIGRATION_REQUIRED)
            self.assertEqual(first["roles"]["R"], "r")
            self.assertEqual(first["roles"]["Results"], "output")
            self.assertEqual(first["canonical_registrations"], 2)
            self.assertEqual(first["result_registrations"], 1)
            self.assertEqual(first["function_audits"], 1)
            self.assertEqual(first["audit_run_stages"], ["model"])
            self.assertEqual(
                first["legacy_memory_files"],
                ["Memory/decision.md", "Memory/routine.md"],
            )
            self.assertFalse(first["structural_blockers"])
            self.assertFalse(first["git"]["repository"])

    def test_migration_preflight_allows_unrelated_dirty_git_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(Path(temp_dir) / "v2", realistic=True)
            self.initialize_git(root)
            clean = stepwise.migration_preflight(root)
            self.assertTrue(clean["git"]["repository"])
            self.assertTrue(clean["git"]["clean"])
            self.assertFalse(clean["structural_blockers"])
            (root / "R/analysis.R").write_text("# Ongoing analysis\nx <- 2\n", encoding="utf-8")
            (root / "Results/table1.csv").write_text("term,value\nage,51\n", encoding="utf-8")
            (root / "untracked.txt").write_text("draft\n", encoding="utf-8")
            dirty = stepwise.migration_preflight(root)
            self.assertFalse(dirty["git"]["clean"])
            self.assertEqual(dirty["state"], stepwise.MIGRATION_REQUIRED)
            self.assertFalse(dirty["structural_blockers"])
            self.assertFalse(dirty["recoverable_blockers"])
            self.assertEqual(
                dirty["unrelated_dirty_paths"],
                ["R/analysis.R", "Results/table1.csv", "untracked.txt"],
            )

    def test_preflight_staging_estimate_ignores_sparse_scientific_data_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(
                Path(temp_dir) / "v2", memory_keys=("design",), realistic=True
            )
            huge_data = root / "Data/huge_dataset.rds"
            with huge_data.open("wb") as handle:
                handle.truncate(1024 * 1024)
            small = stepwise.migration_preflight(root)["transaction_plan"]
            with huge_data.open("r+b") as handle:
                handle.truncate(5 * 1024**4)
            large = stepwise.migration_preflight(root)["transaction_plan"]
            self.assertEqual(small, large)
            self.assertEqual(large["full_project_materialization"], "NO")
            self.assertEqual(large["unexpected_paths"], [])
            self.assertEqual(large["paths"], list(stepwise.MIGRATION_WRITE_SET))
            self.assertLess(
                large["estimated_staged_regular_file_bytes"],
                huge_data.stat().st_size,
            )

    def test_migration_preflight_does_not_descend_into_data_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(Path(temp_dir) / "v2", realistic=True)
            nested = root / "Data/deep/nested/scientific"
            nested.mkdir(parents=True)
            (nested / "artifact.md").write_text("not governance\n", encoding="utf-8")
            traversed_data_paths: list[Path] = []
            real_scandir = stepwise.os.scandir

            def scandir_spy(path: object) -> object:
                candidate = Path(path).resolve()
                data_root = (root / "Data").resolve()
                if candidate == data_root or data_root in candidate.parents:
                    traversed_data_paths.append(candidate)
                return real_scandir(path)

            with mock.patch.object(stepwise.os, "scandir", side_effect=scandir_spy):
                inventory = stepwise.migration_preflight(root)
            self.assertEqual(inventory["state"], stepwise.MIGRATION_REQUIRED)
            self.assertEqual(traversed_data_paths, [])

    def test_cross_filesystem_exdev_never_materializes_unrelated_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(
                Path(temp_dir) / "v2", memory_keys=("design",), realistic=True
            )
            huge_data = root / "Data/huge_dataset.rds"
            with huge_data.open("wb") as handle:
                handle.truncate(5 * 1024**4)
            payload = {
                "legacy_memory": [self.migration_record("Memory/design.md")]
            }
            copied_files: list[Path] = []
            copied_trees: list[Path] = []
            real_copy2 = stepwise.shutil.copy2
            real_copytree = stepwise.shutil.copytree

            def copy2_spy(source: object, destination: object, *args: object, **kwargs: object) -> object:
                copied_files.append(Path(source))
                return real_copy2(source, destination, *args, **kwargs)

            def copytree_spy(source: object, destination: object, *args: object, **kwargs: object) -> object:
                copied_trees.append(Path(source))
                return real_copytree(source, destination, *args, **kwargs)

            with (
                mock.patch.object(
                    stepwise.os,
                    "link",
                    side_effect=OSError(errno.EXDEV, "cross-device link"),
                ) as link_spy,
                mock.patch.object(stepwise.shutil, "copy2", side_effect=copy2_spy),
                mock.patch.object(
                    stepwise.shutil, "copytree", side_effect=copytree_spy
                ),
            ):
                result = stepwise.migration_apply(root, payload)
            self.assertEqual(result.state, stepwise.PROJECT_V3)
            link_spy.assert_not_called()
            for source in [*copied_files, *copied_trees]:
                try:
                    relative = source.resolve().relative_to(root)
                except ValueError:
                    continue
                self.assertTrue(
                    stepwise.path_overlaps_migration_write_set(relative.as_posix()),
                    f"outside write-set materialized: {relative}",
                )
            self.assertNotIn(huge_data, copied_files)
            self.assertTrue(stepwise.validate_project(root).ok)

    def test_same_filesystem_overlay_contains_only_managed_files_and_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = self.make_v2_project(base / "v2", realistic=True)
            candidate = base / "candidate"
            self.assertEqual(root.stat().st_dev, base.stat().st_dev)
            with mock.patch.object(stepwise.os, "link", wraps=stepwise.os.link) as link_spy:
                stepwise.build_migration_overlay(root, candidate)
            link_spy.assert_not_called()
            self.assertTrue((candidate / "project.md").is_file())
            for relative in ("R", "Data", "Results", "Audit"):
                self.assertTrue((candidate / relative).is_symlink())
            inspection = stepwise.inspect_migration_overlay(root, candidate)
            self.assertEqual(inspection["materialized_files"], ["project.md"])
            self.assertEqual(inspection["unexpected_paths"], [])
            self.assertEqual(inspection["full_project_materialization"], "NO")

    def test_overlay_candidate_validation_combines_staged_governance_with_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = self.make_v2_project(base / "v2", realistic=True)
            candidate = base / "candidate"
            preserved = {
                path: (root / path).read_bytes()
                for path in (
                    "R/analysis.R",
                    "Data/source.csv",
                    "Results/table1.csv",
                    "Audit/Runs/model/current/evidence.json",
                )
            }
            stepwise.build_migration_overlay(root, candidate)
            with stepwise.migration_overlay_view(candidate, root):
                stepwise.apply_staged_v3_state(candidate, [], [])
                inspection = stepwise.require_safe_migration_overlay(root, candidate)
                report = stepwise.validate_project(candidate)
            self.assertTrue(report.ok, report.errors)
            self.assertIn(stepwise.V2_SCHEMA_MARKER, (root / "project.md").read_text())
            self.assertIn(stepwise.SCHEMA_MARKER, (candidate / "project.md").read_text())
            self.assertTrue((candidate / "R").is_symlink())
            self.assertEqual(inspection["unexpected_paths"], [])
            self.assertTrue(
                all(
                    stepwise.path_overlaps_migration_write_set(path)
                    for path in inspection["materialized_files"]
                )
            )
            self.assertEqual(
                preserved,
                {path: (root / path).read_bytes() for path in preserved},
            )

    def test_unsafe_candidate_materialization_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = self.make_v2_project(base / "v2")
            candidate = base / "candidate"
            stepwise.build_migration_overlay(root, candidate)
            (candidate / "scratch-copy.bin").write_bytes(b"unexpected")
            with self.assertRaisesRegex(
                stepwise.ProjectError,
                stepwise.MIGRATION_BLOCKED_UNSAFE_STAGING_PLAN,
            ):
                stepwise.require_safe_migration_overlay(root, candidate)

    def test_staging_validation_failure_leaves_source_and_no_large_clone(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(
                Path(temp_dir) / "v2", memory_keys=("design",), realistic=True
            )
            huge_data = root / "Data/huge_dataset.rds"
            with huge_data.open("wb") as handle:
                handle.truncate(5 * 1024**4)
            preserved = {
                path: (root / path).read_bytes()
                for path in ("R/analysis.R", "Results/table1.csv")
            }
            candidates: list[Path] = []
            staged_inspections: list[dict[str, object]] = []
            real_builder = stepwise.build_migration_overlay

            def builder(source: Path, destination: Path) -> None:
                candidates.append(destination)
                real_builder(source, destination)

            def fail(phase: str) -> None:
                if phase == "after_stage_validation":
                    staged_inspections.append(
                        stepwise.inspect_migration_overlay(root, candidates[0])
                    )
                    raise RuntimeError("injected staging validation failure")

            payload = {
                "legacy_memory": [self.migration_record("Memory/design.md")]
            }
            with (
                mock.patch.object(
                    stepwise, "build_migration_overlay", side_effect=builder
                ),
                self.assertRaisesRegex(RuntimeError, "staging validation failure"),
            ):
                stepwise.migration_apply(root, payload, failure_hook=fail)
            self.assertEqual(len(staged_inspections), 1)
            self.assertEqual(staged_inspections[0]["unexpected_paths"], [])
            self.assertNotIn("Data/huge_dataset.rds", staged_inspections[0]["materialized_files"])
            self.assertFalse(candidates[0].exists())
            self.assertEqual(huge_data.stat().st_size, 5 * 1024**4)
            self.assertEqual(
                preserved,
                {path: (root / path).read_bytes() for path in preserved},
            )
            self.assertEqual(
                stepwise.detect_project_state(root), stepwise.MIGRATION_REQUIRED
            )

    def test_dirty_migration_write_set_is_a_recoverable_overlap_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            project_root = self.make_v2_project(base / "project")
            self.initialize_git(project_root)
            project_file = project_root / "project.md"
            project_file.write_text(
                project_file.read_text(encoding="utf-8") + "\nHuman note.\n",
                encoding="utf-8",
            )
            project_inventory = stepwise.migration_preflight(project_root)
            self.assertEqual(
                project_inventory["state"], stepwise.MIGRATION_BLOCKED_RECOVERABLE
            )
            self.assertEqual(
                project_inventory["dirty_write_set_overlaps"], ["project.md"]
            )
            self.assertEqual(
                project_inventory["recoverable_blockers"][0]["code"],
                stepwise.MIGRATION_BLOCKED_WORKTREE_OVERLAP,
            )
            with self.assertRaisesRegex(stepwise.ProjectError, "recoverable blockers"):
                stepwise.migration_apply(project_root, {"legacy_memory": []})

            memory_root = self.make_v2_project(
                base / "memory", memory_keys=("design",)
            )
            self.initialize_git(memory_root)
            memory_file = memory_root / "Memory/design.md"
            memory_file.write_text(
                memory_file.read_text(encoding="utf-8") + "\nAdditional rationale.\n",
                encoding="utf-8",
            )
            memory_inventory = stepwise.migration_preflight(memory_root)
            self.assertEqual(
                memory_inventory["state"], stepwise.MIGRATION_BLOCKED_RECOVERABLE
            )
            self.assertEqual(
                memory_inventory["dirty_write_set_overlaps"], ["Memory/design.md"]
            )

    def test_failed_audit_staging_is_recoverable_not_damaged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(Path(temp_dir) / "v2", realistic=True)
            failed = root / "Audit/Runs/model/failed-20260820"
            failed.mkdir()
            (failed / "partial.json").write_text('{"status":"failed"}\n', encoding="utf-8")
            report = stepwise.validate_project(root)
            inventory = stepwise.migration_preflight(root)
            self.assertEqual(
                stepwise.detect_project_state(root),
                stepwise.MIGRATION_BLOCKED_RECOVERABLE,
            )
            self.assertEqual(report.state, stepwise.MIGRATION_BLOCKED_RECOVERABLE)
            self.assertFalse(report.errors)
            self.assertEqual(inventory["state"], stepwise.MIGRATION_BLOCKED_RECOVERABLE)
            self.assertFalse(inventory["structural_blockers"])
            self.assertEqual(
                inventory["audit_staging_requiring_recovery"][0]["path"],
                "Audit/Runs/model/failed-20260820",
            )
            self.assertEqual(
                inventory["recoverable_blockers"][0]["code"],
                "MIGRATION_BLOCKED_AUDIT_STAGING",
            )

    def test_audit_recover_copies_verifies_manifests_and_preserves_current(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(Path(temp_dir) / "v2", realistic=True)
            current = root / "Audit/Runs/model/current/evidence.json"
            current_before = current.read_bytes()
            failed = root / "Audit/Runs/model/staging-failed"
            (failed / "nested").mkdir(parents=True)
            (failed / "partial.json").write_text("partial\n", encoding="utf-8")
            (failed / "nested/log.txt").write_text("log\n", encoding="utf-8")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(
                    stepwise.main(["audit-recover", str(root), "--stage", "model"]),
                    0,
                )
            manifest = json.loads(output.getvalue())
            destination = Path(manifest["recovery_path"])
            try:
                self.assertFalse(failed.exists())
                self.assertEqual(current.read_bytes(), current_before)
                self.assertTrue((destination / "staging-failed/partial.json").is_file())
                manifest_path = destination / "recovery-manifest.json"
                self.assertTrue(manifest_path.is_file())
                written = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(written["file_count"], 2)
                self.assertEqual(written["stage"], "model")
                self.assertEqual(destination.parent.name, "model")
                self.assertEqual(
                    destination.parent.parent.parent.name,
                    "stepwise-r-project-recovery",
                )
                self.assertNotEqual(root, destination)
                self.assertEqual(
                    stepwise.migration_preflight(root)["state"],
                    stepwise.MIGRATION_REQUIRED,
                )
            finally:
                shutil.rmtree(destination, ignore_errors=True)

    def test_audit_recover_refuses_ambiguous_residue_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(Path(temp_dir) / "v2", realistic=True)
            ambiguous = root / "Audit/Runs/model/candidate-output"
            ambiguous.mkdir()
            payload = ambiguous / "only-result.csv"
            payload.write_text("x\n1\n", encoding="utf-8")
            before = payload.read_bytes()
            inventory = stepwise.migration_preflight(root)
            self.assertEqual(inventory["state"], stepwise.PROJECT_DAMAGED)
            self.assertTrue(inventory["structural_blockers"])
            with self.assertRaisesRegex(stepwise.ProjectError, "human review"):
                stepwise.audit_recover(root, "model")
            self.assertEqual(payload.read_bytes(), before)

    def test_audit_recovery_failure_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(Path(temp_dir) / "v2", realistic=True)
            failed = root / "Audit/Runs/model/incomplete-run"
            failed.mkdir()
            payload = failed / "partial.txt"
            payload.write_text("preserve me\n", encoding="utf-8")
            before = payload.read_bytes()

            def fail(phase: str) -> None:
                if phase == "after_verification":
                    raise RuntimeError("injected recovery failure")

            with self.assertRaisesRegex(RuntimeError, "injected recovery failure"):
                stepwise.audit_recover(root, "model", failure_hook=fail)
            self.assertEqual(payload.read_bytes(), before)

    def test_conflicting_canonical_owners_remain_damaged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(Path(temp_dir) / "v2")
            (root / "docs/other.md").write_text(
                "# Other\n\nStatus: frozen\n\nConflicting owner.\n", encoding="utf-8"
            )
            project_file = root / "project.md"
            text = project_file.read_text(encoding="utf-8")
            duplicate = "| cohort-contract | docs/other.md | - | tests/cohort_contract.R |\n"
            text = text.replace(stepwise.CANONICAL_END, duplicate + stepwise.CANONICAL_END)
            project_file.write_text(text, encoding="utf-8")
            inventory = stepwise.migration_preflight(root)
            self.assertEqual(inventory["state"], stepwise.PROJECT_DAMAGED)
            self.assertTrue(
                any("Duplicate canonical topic" in item for item in inventory["structural_blockers"])
            )

    def test_migration_requires_explicit_review_for_every_legacy_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(
                Path(temp_dir) / "v2", memory_keys=("first", "second")
            )
            payload = {
                "legacy_memory": [
                    self.migration_record("Memory/first.md")
                ]
            }
            with self.assertRaisesRegex(stepwise.ProjectError, "unreviewed"):
                stepwise.migration_apply(root, payload)
            self.assertEqual(stepwise.detect_project_state(root), stepwise.MIGRATION_REQUIRED)

    def test_zero_memory_migration_creates_fixed_empty_topology(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(
                Path(temp_dir) / "v2",
                aliases=("r", "data", "output", "audit"),
            )
            result = stepwise.migration_apply(root, {"legacy_memory": []})
            self.assertEqual(result.reviewed_files, 0)
            self.assertEqual(list((root / "Memory/entries").glob("*.md")), [])
            self.assertEqual(list((root / "Attention/entries").glob("*.md")), [])
            project_text = (root / "project.md").read_text(encoding="utf-8")
            self.assertIn("| R | r |", project_text)
            self.assertIn("| Results | output |", project_text)
            directory_names = {path.name for path in root.iterdir() if path.is_dir()}
            self.assertNotIn("R", directory_names)
            self.assertNotIn("Results", directory_names)
            self.assertTrue(stepwise.validate_project(root).ok)

    def test_semantic_routing_supports_none_decision_attention_both_and_multiple(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            keys = ("none", "decision", "attention", "both", "multiple")
            root = self.make_v2_project(Path(temp_dir) / "v2", memory_keys=keys)
            payload = {
                "legacy_memory": [
                    self.migration_record("Memory/none.md"),
                    self.migration_record(
                        "Memory/decision.md",
                        decisions=[self.memory_payload("Decision only")],
                    ),
                    self.migration_record(
                        "Memory/attention.md",
                        attention=[self.attention_payload(title="Attention only")],
                    ),
                    self.migration_record(
                        "Memory/both.md",
                        decisions=[self.memory_payload("Decision from both")],
                        attention=[self.attention_payload(title="Attention from both")],
                    ),
                    self.migration_record(
                        "Memory/multiple.md",
                        decisions=[
                            self.memory_payload("First distinct decision"),
                            self.memory_payload("Second distinct decision"),
                        ],
                    ),
                ]
            }
            result = stepwise.migration_apply(root, payload)
            self.assertEqual(result.decision_memories, 4)
            self.assertEqual(result.attention_entries, 2)
            self.assertEqual(result.reviewed_files, 5)
            self.assertEqual(len(list((root / "Memory/entries").glob("M-*.md"))), 4)
            self.assertEqual(len(list((root / "Attention/entries").glob("A-*.md"))), 2)
            self.assertTrue(stepwise.validate_project(root).ok)

    def test_mixed_legacy_memory_extracts_events_without_evidence_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(
                Path(temp_dir) / "v2", memory_keys=("mixed",), realistic=True
            )
            legacy = root / "Memory/mixed.md"
            legacy.write_text(
                self.legacy_memory_text("mixed")
                + "\nBenchmark: 412 seconds.\nPASS: 18 tests.\nProgress: stage 4 complete.\n",
                encoding="utf-8",
            )
            payload = {
                "legacy_memory": [
                    self.migration_record(
                        "Memory/mixed.md",
                        decisions=[
                            self.memory_payload("Reject unstable execution architecture"),
                            self.memory_payload("Adopt reviewer-required estimand"),
                        ],
                        attention=[self.attention_payload(title="Choose censoring authority")],
                    )
                ]
            }
            result = stepwise.migration_apply(root, payload)
            self.assertEqual(result.decision_memories, 2)
            self.assertEqual(result.attention_entries, 1)
            generated = "\n".join(
                path.read_text(encoding="utf-8")
                for directory in (root / "Memory/entries", root / "Attention/entries")
                for path in sorted(directory.glob("*.md"))
            )
            self.assertNotIn("412 seconds", generated)
            self.assertNotIn("18 tests", generated)
            self.assertNotIn("stage 4 complete", generated)
            self.assertTrue(stepwise.validate_project(root).ok)

    def test_migration_preserves_unrelated_dirty_bytes_and_git_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(Path(temp_dir) / "v2", realistic=True)
            self.initialize_git(root)
            dirty_content = {
                "R/analysis.R": b"# In-progress analysis\nx <- 42\n",
                "Results/table1.csv": b"term,value\nage,52\n",
                "notes.txt": b"collaborator draft\n",
            }
            for relative, content in dirty_content.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            before_git = stepwise.git_migration_status(root)
            result = stepwise.migration_apply(root, {"legacy_memory": []})
            after_git = stepwise.git_migration_status(root)
            self.assertEqual(result.state, stepwise.PROJECT_V3)
            for relative, content in dirty_content.items():
                self.assertEqual((root / relative).read_bytes(), content)
                self.assertEqual(
                    before_git["path_statuses"][relative],
                    after_git["path_statuses"][relative],
                )
            self.assertTrue(stepwise.validate_project(root).ok)

    def test_v31_end_to_end_recover_preflight_extract_migrate_index_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(
                Path(temp_dir) / "v2", memory_keys=("mixed",), realistic=True
            )
            self.initialize_git(root)
            failed = root / "Audit/Runs/model/staging-incomplete"
            failed.mkdir()
            (failed / "partial.json").write_text("{}\n", encoding="utf-8")
            blocked = stepwise.migration_preflight(root)
            self.assertEqual(blocked["state"], stepwise.MIGRATION_BLOCKED_RECOVERABLE)
            self.assertEqual(
                blocked["recoverable_blockers"][0]["code"],
                "MIGRATION_BLOCKED_AUDIT_STAGING",
            )

            recovery = stepwise.audit_recover(root, "model")
            destination = Path(recovery["recovery_path"])
            try:
                (root / "R/analysis.R").write_text(
                    "# Authorized ongoing work\nx <- 9\n", encoding="utf-8"
                )
                ready = stepwise.migration_preflight(root)
                self.assertEqual(ready["state"], stepwise.MIGRATION_REQUIRED)
                self.assertEqual(ready["dirty_write_set_overlaps"], [])
                self.assertEqual(ready["unrelated_dirty_paths"], ["R/analysis.R"])
                payload = {
                    "legacy_memory": [
                        self.migration_record(
                            "Memory/mixed.md",
                            decisions=[
                                self.memory_payload("Preserve execution architecture rationale"),
                                self.memory_payload("Preserve estimand rationale"),
                            ],
                            attention=[self.attention_payload(title="Resolve material scope")],
                        )
                    ]
                }
                result = stepwise.migration_apply(root, payload)
                self.assertEqual(result.decision_memories, 2)
                self.assertEqual(result.attention_entries, 1)
                stepwise.refresh_index(root)
                self.assertTrue(stepwise.validate_project(root).ok)
            finally:
                shutil.rmtree(destination, ignore_errors=True)

    def test_skill_documents_v31_memory_and_attention_boundaries(self) -> None:
        skill_root = Path(__file__).parents[1]
        skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        reference_text = (skill_root / "references/managed-systems.md").read_text(
            encoding="utf-8"
        )
        combined = skill_text + "\n" + reference_text
        for expected in (
            "Noteworthy does not mean Attention",
            "Known pending work",
            "input container",
            "never convert a legacy file wholesale",
            "technical or execution architecture",
            "never stash the whole project automatically",
            "audit-recover TARGET --stage STAGE",
        ):
            self.assertIn(expected, combined)

    def test_realistic_end_to_end_migration_preserves_scientific_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(
                Path(temp_dir) / "v2",
                memory_keys=("design", "risk", "routine"),
                realistic=True,
            )
            preserved_paths = (
                "R/analysis.R",
                "R/eligibility.R",
                "Data/source.csv",
                "Results/table1.csv",
                "Audit/Runs/model/current/evidence.json",
                "Audit/Functions/audit_derive_eligibility.Rmd",
                "docs/cohort.md",
                "docs/outcome.md",
                "tests/cohort_contract.R",
                "tests/outcome_contract.R",
            )
            before_files = {path: (root / path).read_bytes() for path in preserved_paths}
            before_text = (root / "project.md").read_text(encoding="utf-8")
            before_canonical = stepwise.parse_canonical_entries(before_text)
            before_results = stepwise.parse_result_entries(before_text)
            inventory = stepwise.migration_preflight(root)
            self.assertFalse(inventory["structural_blockers"])
            payload = {
                "legacy_memory": [
                    self.migration_record(
                        "Memory/design.md",
                        decisions=[
                            self.memory_payload(
                                "Preserve design rationale",
                                related_topics=["cohort-contract"],
                            )
                        ],
                    ),
                    self.migration_record(
                        "Memory/risk.md",
                        attention=[self.attention_payload()],
                    ),
                    self.migration_record("Memory/routine.md"),
                ]
            }
            result = stepwise.migration_apply(root, payload)
            self.assertEqual(result.state, stepwise.PROJECT_V3)
            after_files = {path: (root / path).read_bytes() for path in preserved_paths}
            after_text = (root / "project.md").read_text(encoding="utf-8")
            self.assertEqual(before_files, after_files)
            self.assertEqual(before_canonical, stepwise.parse_canonical_entries(after_text))
            self.assertEqual(before_results, stepwise.parse_result_entries(after_text))
            self.assertNotIn(stepwise.V2_SCHEMA_MARKER, after_text)
            self.assertEqual(stepwise.detect_project_state(root), stepwise.PROJECT_V3)
            stepwise.refresh_index(root)
            self.assertTrue(stepwise.validate_project(root).ok)

    def test_migration_failure_rolls_back_without_project_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(
                Path(temp_dir) / "v2", memory_keys=("design",), realistic=True
            )
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            payload = {
                "legacy_memory": [
                    self.migration_record(
                        "Memory/design.md",
                        decisions=[self.memory_payload("Rollback decision")],
                    )
                ]
            }

            def fail(phase: str) -> None:
                if phase == "after_memory_promotion":
                    raise RuntimeError("injected promotion failure")

            with self.assertRaisesRegex(stepwise.ProjectError, "state restored"):
                stepwise.migration_apply(root, payload, failure_hook=fail)
            after = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(before, after)
            self.assertEqual(stepwise.detect_project_state(root), stepwise.MIGRATION_REQUIRED)
            self.assertFalse(
                any("migration" in path.name.lower() for path in root.iterdir())
            )
            self.assertFalse(stepwise.validate_v2_project(root).errors)

    def test_migration_is_idempotent_after_v3_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = self.make_v2_project(
                Path(temp_dir) / "v2", memory_keys=("design",)
            )
            payload = {
                "legacy_memory": [
                    self.migration_record(
                        "Memory/design.md",
                        decisions=[self.memory_payload("One decision")],
                    )
                ]
            }
            first = stepwise.migration_apply(root, payload)
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            second = stepwise.migration_apply(root, payload)
            after = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first.decision_memories, 1)
            self.assertEqual(second.state, stepwise.PROJECT_V3)
            self.assertEqual(second.decision_memories, 0)
            self.assertEqual(before, after)

    def test_migration_cli_separates_check_and_apply_and_removes_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            root = self.make_v2_project(base / "v2", memory_keys=("routine",))
            payload_path = base / "migration.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "legacy_memory": [
                            self.migration_record("Memory/routine.md")
                        ]
                    }
                ),
                encoding="utf-8",
            )
            before = (root / "project.md").read_bytes()
            self.assertEqual(self.invoke("migrate", str(root), "--check"), 0)
            self.assertEqual((root / "project.md").read_bytes(), before)
            self.assertEqual(self.invoke("validate", str(root)), 2)
            self.assertEqual(
                self.invoke(
                    "migrate",
                    str(root),
                    "--apply",
                    "--input",
                    str(payload_path),
                ),
                0,
            )
            self.assertFalse(payload_path.exists())
            self.assertEqual(self.invoke("migrate", str(root), "--check"), 0)
            self.assertEqual(self.invoke("migrate", str(root), "--apply"), 0)
            self.assertTrue(stepwise.validate_project(root).ok)

    def test_index_refuses_missing_managed_markers(self) -> None:
        project_file = self.root / "project.md"
        project_file.write_text(
            f"# Project\n\n{stepwise.SCHEMA_MARKER}\n\n## R Script Index\n",
            encoding="utf-8",
        )
        original = project_file.read_text(encoding="utf-8")
        with self.assertRaisesRegex(
            stepwise.ProjectError, "exactly one managed role block"
        ):
            stepwise.refresh_index(self.root)
        self.assertEqual(original, project_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
