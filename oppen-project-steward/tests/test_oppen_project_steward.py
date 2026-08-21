from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "oppen_project_steward.py"
SPEC = importlib.util.spec_from_file_location("oppen_project_steward", SCRIPT_PATH)
assert SPEC and SPEC.loader
steward = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = steward
SPEC.loader.exec_module(steward)


class OppenProjectStewardTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        for directory in ("src", "Data", "Deliverables"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        steward.ensure_v3_project(self.root, create=True)
        steward.refresh_index(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def invoke(self, *args: str) -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return steward.main(list(args))

    def register_canonical(
        self,
        topic: str = "execution-model",
        owner: str = "docs/execution.md",
        verification: str = "tests/test_execution.py",
    ) -> None:
        self.write(owner, "# Execution Model\n\nStatus: frozen\n\nCurrent contract.\n")
        self.write(verification, "assert True\n")
        steward.register_canonical(
            self.root, topic, owner, None, verification, replace=False
        )

    def register_deliverable(
        self,
        deliverable_id: str = "release-report",
        path: str = "Deliverables/release.md",
    ) -> None:
        self.write(path, "# Release Report\n")
        self.write("src/build_report.py", "print('report')\n")
        steward.register_deliverable(
            self.root,
            deliverable_id,
            path,
            "report",
            "formal-review",
            "src/build_report.py",
            replace=False,
        )

    def complete_contract_audit(self, path: Path) -> None:
        content = path.read_text(encoding="utf-8")
        content = content.replace(
            "TODO: Explain the behavior and why a hidden error could materially alter the project.",
            "This transition controls authorization and downstream state.",
        )
        content = content.replace(
            "TODO: State inputs, outputs, invariants, side effects, and downstream obligations.",
            "Inputs are validated requests; outputs preserve the authorization invariant.",
        )
        content = content.replace(
            "TODO: Link executable checks for important boundaries and failure modes.",
            "Verified by `tests/test_permissions.py`, including denied and boundary cases.",
        )
        content = content.replace(
            "TODO: State conditions outside the validated contract.",
            "External identity-provider availability is outside this contract.",
        )
        write_set = steward.managed_write_set(
            self.root, "contract-audit complete", exact=(path,)
        )
        steward.assert_managed_write_set_clean(self.root, write_set)
        steward.managed_file_transaction(self.root, write_set, {path: content})

    def test_initialization_creates_namespace_and_registers_existing_roles(
        self,
    ) -> None:
        text = (
            self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        ).read_text(encoding="utf-8")
        self.assertIn(steward.SCHEMA_MARKER, text)
        self.assertEqual(
            {"src", "Data", "Deliverables", steward.STEWARD_NAMESPACE},
            {path.name for path in self.root.iterdir() if path.is_dir()},
        )
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_repeated_init_and_index_are_idempotent(self) -> None:
        before = (
            self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        ).read_text(encoding="utf-8")
        before_files = sorted(
            path.relative_to(self.root)
            for path in self.root.rglob("*")
            if path.is_file()
        )
        for _ in range(2):
            steward.ensure_v3_project(self.root, create=True)
            steward.refresh_index(self.root)
        after = (
            self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        ).read_text(encoding="utf-8")
        after_files = sorted(
            path.relative_to(self.root)
            for path in self.root.rglob("*")
            if path.is_file()
        )
        self.assertEqual(before, after)
        self.assertEqual(before_files, after_files)

    def test_adoption_registers_explicit_existing_role_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "aliases"
            for directory in ("app", "data", "output"):
                (root / directory).mkdir(parents=True, exist_ok=True)
            payload = Path(temp_dir) / "adopt.json"
            payload.write_text(
                '{"role_mappings":{"source":"app","data":"data",'
                '"deliverables":"output"},"initial_canonical_registrations":[],'
                '"initial_deliverable_registrations":[]}',
                encoding="utf-8",
            )
            steward.apply_adoption(root, payload)
            text = (root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME).read_text(
                encoding="utf-8"
            )
            self.assertIn("| Source | app |", text)
            self.assertIn("| Deliverables | output |", text)
            self.assertNotIn("src", {path.name for path in root.iterdir()})

    def test_init_rejects_existing_project_content_before_registry_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "ambiguous"
            (root / "src").mkdir(parents=True)
            (root / "app").mkdir()
            with self.assertRaisesRegex(steward.ProjectError, "ADOPTION_REQUIRED"):
                steward.initialize_new_project(root)
            self.assertFalse((root / steward.STEWARD_NAMESPACE).exists())

    def test_init_does_not_migrate_foreign_or_stepwise_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "legacy"
            root.mkdir()
            project_file = root / "project.md"
            original = "# Existing\n\n<!-- stepwise-r-project:v2 -->\n"
            project_file.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(steward.ProjectError, "ADOPTION_REQUIRED"):
                steward.initialize_new_project(root)
            self.assertEqual(original, project_file.read_text(encoding="utf-8"))

    def test_canonical_registration_is_idempotent(self) -> None:
        self.register_canonical()
        first = (
            self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        ).read_text(encoding="utf-8")
        self.register_canonical()
        second = (
            self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        ).read_text(encoding="utf-8")
        self.assertEqual(first, second)
        self.assertEqual(second.count("| execution-model |"), 1)
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_canonical_requires_one_valid_status_and_verification(self) -> None:
        self.write("docs/contract.md", "Status: archived\n")
        self.write("tests/test_contract.py", "assert True\n")
        with self.assertRaisesRegex(steward.ProjectError, "valid Status field"):
            steward.register_canonical(
                self.root,
                "contract",
                "docs/contract.md",
                None,
                "tests/test_contract.py",
                replace=False,
            )
        self.write("docs/contract.md", "Status: frozen\n")
        self.write("tests/test_contract.py", "")
        with self.assertRaisesRegex(steward.ProjectError, "cannot be empty"):
            steward.register_canonical(
                self.root,
                "contract",
                "docs/contract.md",
                None,
                "tests/test_contract.py",
                replace=False,
            )

    def test_canonical_section_scopes_status(self) -> None:
        self.write(
            "docs/contracts.md",
            "# Contracts\n\nStatus: draft\n\n## Auth\n\nStatus: frozen\n\nCurrent auth.\n",
        )
        self.write("tests/test_auth.py", "assert True\n")
        steward.register_canonical(
            self.root,
            "authentication-contract",
            "docs/contracts.md",
            "Auth",
            "tests/test_auth.py",
            replace=False,
        )
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_conflicting_canonical_ownership_is_rejected_and_detected(self) -> None:
        self.register_canonical()
        with self.assertRaisesRegex(steward.ProjectError, "already registered"):
            steward.register_canonical(
                self.root,
                "second-topic",
                "docs/execution.md",
                None,
                "tests/test_execution.py",
                replace=False,
            )
        project_file = self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        text = project_file.read_text(encoding="utf-8")
        entries = steward.parse_canonical_entries(text)
        entries.append(
            steward.CanonicalEntry(
                "second-topic", "docs/execution.md", "", "tests/test_execution.py"
            )
        )
        project_file.write_text(
            steward.replace_block(
                text,
                steward.CANONICAL_START,
                steward.CANONICAL_END,
                steward.render_canonical_entries(entries),
                "canonical source",
            ),
            encoding="utf-8",
        )
        report = steward.validate_project(self.root)
        self.assertTrue(
            any("Duplicate current canonical owner" in e for e in report.errors)
        )

    def test_canonical_replacement_requires_explicit_flag(self) -> None:
        self.register_canonical()
        self.write("docs/replacement.md", "Status: frozen\n\nReplacement.\n")
        with self.assertRaisesRegex(steward.ProjectError, "--replace"):
            steward.register_canonical(
                self.root,
                "execution-model",
                "docs/replacement.md",
                None,
                "tests/test_execution.py",
                replace=False,
            )
        steward.register_canonical(
            self.root,
            "execution-model",
            "docs/replacement.md",
            None,
            "tests/test_execution.py",
            replace=True,
        )
        text = (
            self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        ).read_text(encoding="utf-8")
        self.assertIn("docs/replacement.md", text)
        self.assertNotIn("docs/execution.md", text)

    def test_deliverable_registration_is_idempotent(self) -> None:
        self.register_deliverable()
        first = (
            self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        ).read_text(encoding="utf-8")
        self.register_deliverable()
        second = (
            self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        ).read_text(encoding="utf-8")
        self.assertEqual(first, second)
        self.assertEqual(second.count("| release-report |"), 1)
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_deliverable_rejects_machine_artifact(self) -> None:
        self.write("Deliverables/run_manifest.log", "machine log\n")
        self.write("src/build.py", "print('build')\n")
        with self.assertRaisesRegex(steward.ProjectError, "Invalid Deliverable"):
            steward.register_deliverable(
                self.root,
                "run-manifest",
                "Deliverables/run_manifest.log",
                "report",
                "internal",
                "src/build.py",
                replace=False,
            )
        report = steward.validate_project(self.root)
        self.assertTrue(any("Invalid Deliverable" in e for e in report.errors))

    def test_deliverable_missing_producer_fails_validation(self) -> None:
        self.register_deliverable()
        (self.root / "src/build_report.py").unlink()
        report = steward.validate_project(self.root)
        self.assertTrue(any("producer" in e.lower() for e in report.errors))

    def test_unregistered_deliverable_fails_validation(self) -> None:
        self.write("Deliverables/report.pdf", "human report\n")
        report = steward.validate_project(self.root)
        self.assertTrue(any("unregistered file" in e for e in report.errors))

    def test_audit_run_accepts_only_current_tree(self) -> None:
        self.write(
            ".oppen-project-steward/Audit/Runs/evaluation/current/summary.json", "{}\n"
        )
        self.assertTrue(steward.validate_project(self.root).ok)
        self.write(
            ".oppen-project-steward/Audit/Runs/evaluation/staging/partial.json", "{}\n"
        )
        report = steward.validate_project(self.root)
        self.assertTrue(
            any("persistent history or staging" in e for e in report.errors)
        )

    def test_audit_stage_without_current_fails_validation(self) -> None:
        (self.root / ".oppen-project-steward/Audit/Runs/build").mkdir(parents=True)
        report = steward.validate_project(self.root)
        self.assertTrue(any("has no current directory" in e for e in report.errors))

    def test_contract_audit_registration_reuses_stable_path(self) -> None:
        self.write("src/permissions.py", "def allowed():\n    return True\n")
        self.write("tests/test_permissions.py", "assert True\n")
        audit, action = steward.create_or_locate_contract_audit(
            self.root,
            "permission-logic",
            "src/permissions.py",
            "A hidden error could grant unauthorized access",
        )
        same, repeated_action = steward.create_or_locate_contract_audit(
            self.root,
            "permission-logic",
            "src/permissions.py",
            "A hidden error could grant unauthorized access",
        )
        self.assertEqual(action, "CREATED_DRAFT")
        self.assertEqual(repeated_action, "UPDATE_REQUIRED")
        self.assertEqual(audit, same)
        self.assertEqual(audit.name, "audit_permission-logic.md")
        self.complete_contract_audit(audit)
        steward.refresh_index(self.root)
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_contract_audit_stale_source_hash_fails_validation(self) -> None:
        source = self.write("src/state.py", "STATE = 'ready'\n")
        audit, _ = steward.create_or_locate_contract_audit(
            self.root, "state-transition", "src/state.py", "Controls core state"
        )
        self.complete_contract_audit(audit)
        source.write_text("STATE = 'changed'\n", encoding="utf-8")
        report = steward.validate_project(self.root)
        self.assertTrue(any("stale for its source" in e for e in report.errors))

    def test_invalid_nested_contract_audit_path_fails_validation(self) -> None:
        self.write(
            ".oppen-project-steward/Audit/Contracts/archive/audit_auth.md",
            "# Old audit\n",
        )
        report = steward.validate_project(self.root)
        self.assertTrue(
            any("Invalid registered contract audit path" in e for e in report.errors)
        )

    def test_broken_generated_markers_fail_validation_and_index(self) -> None:
        project_file = self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        original = project_file.read_text(encoding="utf-8")
        project_file.write_text(
            original.replace(steward.CANONICAL_END, ""), encoding="utf-8"
        )
        report = steward.validate_project(self.root)
        self.assertTrue(
            any("managed canonical source block" in e for e in report.errors)
        )
        with self.assertRaisesRegex(steward.ProjectError, "MANAGED_STATE_CONFLICT"):
            steward.refresh_index(self.root)

    def test_init_does_not_repair_broken_registry_or_missing_role(self) -> None:
        project_file = self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        broken = project_file.read_text(encoding="utf-8").replace(
            steward.DELIVERABLE_END, ""
        )
        project_file.write_text(broken, encoding="utf-8")
        with self.assertRaisesRegex(steward.ProjectError, "exactly one managed"):
            steward.ensure_v3_project(self.root, create=True)

        project_file.write_text(
            broken + "\n" + steward.DELIVERABLE_END + "\n", encoding="utf-8"
        )
        (self.root / "Data").rmdir()
        with self.assertRaisesRegex(steward.ProjectError, "Data role does not exist"):
            steward.ensure_v3_project(self.root, create=True)
        self.assertFalse((self.root / "Data").exists())

    def test_parallel_current_copy_fails_validation(self) -> None:
        self.write("docs/architecture.md", "Status: frozen\n")
        self.write("tests/verify_architecture.py", "assert True\n")
        steward.register_canonical(
            self.root,
            "architecture",
            "docs/architecture.md",
            None,
            "tests/verify_architecture.py",
            replace=False,
        )
        self.write("docs/architecture_final.md", "Status: frozen\n")
        report = steward.validate_project(self.root)
        self.assertTrue(any("Parallel old/new" in e for e in report.errors))

    def test_validate_cli_success_and_failure_exit_codes(self) -> None:
        self.assertEqual(self.invoke("validate", str(self.root)), 0)
        self.write("Deliverables/debug.log", "debug\n")
        self.assertEqual(self.invoke("validate", str(self.root)), 1)


if __name__ == "__main__":
    unittest.main()
