from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


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

    def complete_memory(self, path: Path) -> None:
        content = path.read_text(encoding="utf-8")
        content = content.replace(
            "- Change:", "- Change: Updated the registered contract."
        )
        content = content.replace("- Why:", "- Why: The scientific definition changed.")
        content = content.replace(
            "- Verification:", "- Verification: Contract test passed."
        )
        content = content.replace("- Risk:", "- Risk: No known remaining risk.")
        path.write_text(content, encoding="utf-8")

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
            (
                "memory",
                str(self.root),
                "--task-key",
                "cohort-contract-change",
                "--summary",
                "Revise cohort contract",
                "--canonical-topic",
                "cohort-contract",
            ),
            ("index", str(self.root)),
        )
        for command in first_commands:
            self.assertEqual(self.invoke(*command), 0)
        memory = self.root / "Memory" / "cohort-contract-change.md"
        self.complete_memory(memory)
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
                {"Audit", "Data", "R", "Results"},
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

    def test_memory_reuses_one_stable_file_per_task_key(self) -> None:
        self.register_protocol()
        first, first_action = stepwise.create_or_reuse_memory(
            self.root,
            "cohort-contract-change",
            "Revise cohort contract",
            "cohort-contract",
        )
        original = first.read_text(encoding="utf-8")
        second, second_action = stepwise.create_or_reuse_memory(
            self.root,
            "cohort-contract-change",
            "A different summary must not overwrite the record",
            "cohort-contract",
        )
        self.assertEqual(first_action, "CREATED_DRAFT")
        self.assertEqual(second_action, "REUSED")
        self.assertEqual(first, second)
        self.assertEqual(original, second.read_text(encoding="utf-8"))
        self.assertEqual(len(list((self.root / "Memory").glob("*.md"))), 1)
        self.assertIn("](<../docs/protocol.md>)", original)

        self.complete_memory(first)
        report = stepwise.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)

    def test_memory_adopts_alias_and_distinct_tasks_create_distinct_files(self) -> None:
        self.register_protocol()
        (self.root / "memory").mkdir()
        first, _ = stepwise.create_or_reuse_memory(
            self.root,
            "cohort-definition",
            "Revise cohort definition",
            "cohort-contract",
        )
        second, _ = stepwise.create_or_reuse_memory(
            self.root,
            "outcome-definition",
            "Revise outcome definition",
            "cohort-contract",
        )
        directory_names = {path.name for path in self.root.iterdir() if path.is_dir()}
        self.assertEqual(first.parent.name, "memory")
        self.assertEqual(second.parent.name, "memory")
        self.assertNotIn("Memory", directory_names)
        self.assertEqual(len(list((self.root / "memory").glob("*.md"))), 2)

    def test_memory_requires_registered_canonical_topic(self) -> None:
        with self.assertRaisesRegex(stepwise.ProjectError, "not registered"):
            stepwise.create_or_reuse_memory(
                self.root,
                "unowned-change",
                "Change without an owner",
                "missing-topic",
            )

    def test_legacy_memory_interface_has_clear_error(self) -> None:
        with self.assertRaisesRegex(stepwise.ProjectError, "--magnitude was removed"):
            stepwise.main(
                [
                    "memory",
                    str(self.root),
                    "--magnitude",
                    "huge",
                    "--summary",
                    "legacy call",
                ]
            )

        with self.assertRaisesRegex(stepwise.ProjectError, "--magnitude was removed"):
            stepwise.main(["memory", str(self.root), "--magnitude", "mini"])

    def test_legacy_memory_filenames_fail_validation(self) -> None:
        self.write("Memory/20260802_huge_old-pattern.md", "# Legacy\n")
        report = stepwise.validate_project(self.root)
        self.assertTrue(any("legacy per-change" in error for error in report.errors))

    def test_nested_duplicate_memory_task_key_fails_validation(self) -> None:
        self.register_protocol()
        memory, _ = stepwise.create_or_reuse_memory(
            self.root,
            "cohort-contract-change",
            "Revise cohort contract",
            "cohort-contract",
        )
        self.complete_memory(memory)
        duplicate = self.write(
            "Memory/archive/duplicate.md",
            memory.read_text(encoding="utf-8"),
        )
        self.assertTrue(duplicate.exists())
        report = stepwise.validate_project(self.root)
        self.assertTrue(
            any("Duplicate Memory task_key" in error for error in report.errors)
        )
        self.assertTrue(
            any("stable Memory/<task-key>.md" in error for error in report.errors)
        )

    def test_memory_without_required_body_fails_validation(self) -> None:
        self.register_protocol()
        memory, _ = stepwise.create_or_reuse_memory(
            self.root,
            "cohort-contract-change",
            "Revise cohort contract",
            "cohort-contract",
        )
        memory.write_text(
            """---
task_key: "cohort-contract-change"
canonical_topic: "cohort-contract"
canonical_path: "docs/protocol.md"
---

Canonical source: [cohort-contract](<../docs/protocol.md>)
""",
            encoding="utf-8",
        )
        report = stepwise.validate_project(self.root)
        self.assertTrue(
            any(
                "requires exactly one 'Verification' section" in error
                for error in report.errors
            )
        )

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

    def test_legacy_project_is_reported_but_not_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "legacy"
            for dirname in ("R", "Data", "Results", "Audit"):
                (root / dirname).mkdir(parents=True, exist_ok=True)
            project_file = root / "project.md"
            project_file.write_text(
                "# Project\n\n## R Script Index\n", encoding="utf-8"
            )
            original = project_file.read_text(encoding="utf-8")
            with self.assertRaisesRegex(
                stepwise.ProjectError, "not Stepwise R Project v2"
            ):
                stepwise.ensure_v2_project(root, create=True)
            self.assertEqual(original, project_file.read_text(encoding="utf-8"))
            report = stepwise.validate_project(root)
            self.assertTrue(any("legacy project" in error for error in report.errors))

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
