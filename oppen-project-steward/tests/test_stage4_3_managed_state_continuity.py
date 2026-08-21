from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "oppen_project_steward.py"
SPEC = importlib.util.spec_from_file_location(
    "oppen_project_steward_stage4_3", SCRIPT_PATH
)
assert SPEC and SPEC.loader
steward = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = steward
SPEC.loader.exec_module(steward)


class Stage43ManagedStateContinuityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temporary.name).resolve()
        self.root = self.temp_root / "project"
        self.root.mkdir()
        self.payload_number = 0

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def payload(self, value: dict[str, object]) -> Path:
        self.payload_number += 1
        path = self.temp_root / f"payload-{self.payload_number}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def adoption_payload(self) -> Path:
        return self.payload(
            {
                "role_mappings": {"source": "src"},
                "initial_canonical_registrations": [],
                "initial_deliverable_registrations": [],
            }
        )

    def memory_payload(self, title: str) -> Path:
        return self.payload(
            {
                "title": title,
                "related_topics": [],
                "supersedes": [],
                "invalidates": [],
                "before": "The previous execution boundary was credible.",
                "trigger": "Runtime evidence established a durable constraint.",
                "decision": "Use the explicit bounded execution boundary.",
                "why": "The boundary prevents recurrence of the observed failure.",
                "rejected_or_prior_approach": "The implicit boundary was rejected.",
                "consequence": "Future work must preserve the explicit boundary.",
            }
        )

    def attention_payload(self, title: str) -> Path:
        return self.payload(
            {
                "title": title,
                "blocking": False,
                "observation": "An external integration bypasses the approval contract.",
                "evidence": "The integration invokes execution without approval state.",
                "why_it_matters": "The bypass could affect production users.",
                "why_no_action_was_taken": "The integration is outside current scope.",
                "human_decision_needed": "Decide whether to redesign the integration.",
            }
        )

    def existing_project(self) -> None:
        self.write("project.md", "# Product Contract\n\nUser-owned current contract.\n")
        self.write("src/app.ts", "export const state = 'ready';\n")
        self.write("docs/architecture.md", "# Architecture\n")
        self.write("tests/verify.py", "assert True\n")
        steward.apply_adoption(self.root, self.adoption_payload())

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def initialize_git(self) -> None:
        self.git("init", "-q")
        self.git("config", "user.email", "stage43@example.invalid")
        self.git("config", "user.name", "Stage 4.3 Test")

    def managed_bytes(self) -> dict[str, bytes]:
        namespace = self.root / steward.STEWARD_NAMESPACE
        return {
            path.relative_to(namespace).as_posix(): path.read_bytes()
            for path in namespace.rglob("*")
            if path.is_file()
        }

    def test_uncommitted_adoption_supports_full_sequential_workflow(self) -> None:
        self.existing_project()
        baseline = steward.load_managed_state(self.root)
        self.assertEqual(baseline.generation, 1)

        steward.register_canonical(
            self.root,
            "product-contract",
            "project.md",
            None,
            "tests/verify.py",
            status="frozen",
            replace=False,
        )
        self.write("docs/product-contract.md", "# Replacement Product Contract\n")
        steward.register_canonical(
            self.root,
            "product-contract",
            "docs/product-contract.md",
            None,
            "tests/verify.py",
            status="frozen",
            replace=True,
        )
        steward.add_memory(self.root, self.memory_payload("Bound execution continuity"))
        steward.raise_attention(
            self.root, self.attention_payload("Approval boundary decision")
        )
        steward.refresh_index(self.root)

        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")
        self.assertGreater(steward.load_managed_state(self.root).generation, 1)

    def test_init_then_memory_requires_no_commit(self) -> None:
        empty = self.temp_root / "new-project"
        steward.initialize_new_project(empty)
        entry = steward.add_memory(
            empty, self.memory_payload("Initialize bounded runtime policy")
        )
        self.assertTrue(entry.is_file())
        self.assertEqual(steward.validate_project(empty).status, "MANAGED_READY")

    def test_git_untracked_staged_and_committed_states_are_equivalent(self) -> None:
        for state in ("untracked", "staged", "committed", "committed-then-staged"):
            with self.subTest(state=state):
                case = self.temp_root / state
                case.mkdir()
                original_root = self.root
                self.root = case
                self.existing_project()
                self.initialize_git()
                if state in {"staged", "committed", "committed-then-staged"}:
                    self.git("add", steward.STEWARD_NAMESPACE)
                if state in {"committed", "committed-then-staged"}:
                    self.git("add", "-A")
                    self.git("commit", "-q", "-m", "managed baseline")
                if state == "committed-then-staged":
                    steward.add_memory(
                        self.root, self.memory_payload("First staged operation")
                    )
                    self.git("add", steward.STEWARD_NAMESPACE)
                steward.add_memory(
                    self.root, self.memory_payload(f"Continuity in {state} state")
                )
                self.assertEqual(
                    steward.validate_project(self.root).status, "MANAGED_READY"
                )
                self.root = original_root

    def test_manual_registry_drift_blocks_without_overwrite(self) -> None:
        self.existing_project()
        registry = self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        registry.write_text(
            registry.read_text(encoding="utf-8") + "manual edit\n", encoding="utf-8"
        )
        before = registry.read_bytes()

        with self.assertRaises(steward.RecoverableBlocker) as caught:
            steward.add_memory(
                self.root, self.memory_payload("Must not overwrite drift")
            )

        self.assertEqual(caught.exception.code, "MANAGED_STATE_CONFLICT")
        self.assertEqual(
            caught.exception.paths,
            (".oppen-project-steward/registry.md",),
        )
        self.assertEqual(registry.read_bytes(), before)

    def test_manual_memory_drift_blocks_next_mutation(self) -> None:
        self.existing_project()
        entry = steward.add_memory(self.root, self.memory_payload("Initial decision"))
        entry.write_text(entry.read_text(encoding="utf-8") + "manual edit\n")

        with self.assertRaises(steward.RecoverableBlocker) as caught:
            steward.raise_attention(
                self.root, self.attention_payload("Must preserve memory drift")
            )

        self.assertEqual(caught.exception.code, "MANAGED_STATE_CONFLICT")
        self.assertIn(entry.relative_to(self.root).as_posix(), caught.exception.paths)

    def test_no_op_managed_command_still_detects_baseline_drift(self) -> None:
        self.existing_project()
        steward.register_canonical(
            self.root,
            "product-contract",
            "project.md",
            None,
            "tests/verify.py",
            status="frozen",
            replace=False,
        )
        registry = self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        registry.write_text(
            registry.read_text(encoding="utf-8") + "manual drift\n",
            encoding="utf-8",
        )

        with self.assertRaises(steward.RecoverableBlocker) as caught:
            steward.register_canonical(
                self.root,
                "product-contract",
                "project.md",
                None,
                "tests/verify.py",
                status="frozen",
                replace=False,
            )

        self.assertEqual(caught.exception.code, "MANAGED_STATE_CONFLICT")

    def test_contract_audit_completion_updates_baseline_without_commit(self) -> None:
        self.existing_project()
        audit, action = steward.create_or_locate_contract_audit(
            self.root,
            "execution-boundary",
            "src/app.ts",
            "A hidden state error could alter production behavior",
        )
        self.assertEqual(action, "CREATED_DRAFT")
        payload = self.payload(
            {
                "purpose_and_risk": "This boundary controls production state transitions.",
                "contract": "Validated input produces one bounded state transition.",
                "edge_cases_and_verification": "tests/verify.py covers the transition boundary.",
                "known_limits": "External service availability is outside this contract.",
            }
        )

        with contextlib.redirect_stdout(io.StringIO()):
            result = steward.main(
                [
                    "contract-audit",
                    str(self.root),
                    "--topic",
                    "execution-boundary",
                    "--input",
                    str(payload),
                ]
            )

        self.assertEqual(result, 0)
        self.assertFalse(payload.exists())
        self.assertNotIn("TODO", audit.read_text(encoding="utf-8"))
        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")

    def test_dirty_user_canonical_owner_is_referenced_without_mutation(self) -> None:
        self.existing_project()
        self.initialize_git()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "existing project")
        owner = self.write("project.md", "# Product Contract\n\nDirty user revision.\n")
        source = self.write("src/app.ts", "export const state = 'dirty';\n")
        owner_before = owner.read_bytes()
        source_before = source.read_bytes()

        steward.register_canonical(
            self.root,
            "product-contract",
            "project.md",
            None,
            "tests/verify.py",
            status="frozen",
            replace=False,
        )

        self.assertEqual(owner.read_bytes(), owner_before)
        self.assertEqual(source.read_bytes(), source_before)
        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")

    def test_dirty_user_path_still_blocks_when_in_write_set(self) -> None:
        self.existing_project()
        self.initialize_git()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "existing project")
        owner = self.write("project.md", "# Dirty user contract\n")
        write_set = steward.managed_write_set(
            self.root, "user content update", exact=(owner,)
        )

        with self.assertRaises(steward.RecoverableBlocker) as caught:
            steward.assert_managed_write_set_clean(self.root, write_set)

        self.assertEqual(caught.exception.code, "MANAGED_WRITESET_CONFLICT")
        self.assertEqual(caught.exception.paths, ("project.md",))

    def test_pre43_bootstrap_ignores_unrelated_dirty_work(self) -> None:
        self.existing_project()
        baseline = self.root / steward.STEWARD_NAMESPACE / steward.MANAGED_STATE_NAME
        baseline.unlink()
        self.initialize_git()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "pre-4.3 project")
        self.write("src/app.ts", "export const state = 'dirty';\n")
        self.write("notes.md", "untracked user notes\n")

        check = steward.managed_state_preflight(self.root)
        self.assertEqual(check["status"], "BLOCKED_RECOVERABLE")
        self.assertEqual(check["blockers"][0]["code"], "MANAGED_BASELINE_MISSING")
        result = steward.bootstrap_managed_state(self.root)

        self.assertEqual(result, baseline)
        self.assertEqual(steward.load_managed_state(self.root).generation, 1)
        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")
        self.assertIn(Path("src/app.ts"), steward.git_dirty_paths(self.root))

    def test_invalid_namespace_cannot_be_bootstrapped(self) -> None:
        namespace = self.root / steward.STEWARD_NAMESPACE
        namespace.mkdir()
        self.write(".oppen-project-steward/registry.md", "unrelated content\n")

        with self.assertRaisesRegex(steward.ProjectError, "structurally valid"):
            steward.bootstrap_managed_state(self.root)
        self.assertFalse((namespace / steward.MANAGED_STATE_NAME).exists())

    def test_baseline_excludes_large_project_and_audit_run_payloads(self) -> None:
        self.existing_project()
        model = self.root / "models/huge-model.bin"
        model.parent.mkdir()
        with model.open("wb") as handle:
            handle.truncate(5 * 1024**4)
        audit = (
            self.root / steward.STEWARD_NAMESPACE / "Audit/Runs/build/current/huge.bin"
        )
        audit.parent.mkdir(parents=True)
        with audit.open("wb") as handle:
            handle.truncate(4 * 1024**4)
        original_hash = steward.file_sha256

        def reject_large_hash(path: Path) -> str:
            if path in {model, audit}:
                raise AssertionError(f"large payload was hashed: {path}")
            return original_hash(path)

        with mock.patch.object(steward, "file_sha256", side_effect=reject_large_hash):
            steward.add_memory(self.root, self.memory_payload("Small control update"))

        files = steward.load_managed_state(self.root).files
        self.assertFalse(any(path.startswith("Audit/Runs/") for path in files))
        self.assertNotIn("models/huge-model.bin", files)

    def test_baseline_is_written_last_and_rolls_back_with_managed_files(self) -> None:
        self.existing_project()
        before = self.managed_bytes()
        baseline = self.root / steward.STEWARD_NAMESPACE / steward.MANAGED_STATE_NAME
        path_type = type(baseline)
        original_replace = path_type.replace
        promoted: list[Path] = []

        def fail_baseline(path: Path, target: Path) -> Path:
            target = Path(target)
            if "steward-transaction" in path.name:
                promoted.append(target)
            if target == baseline:
                raise OSError("injected baseline promotion failure")
            return original_replace(path, target)

        payload = self.memory_payload("Transactional baseline rollback")
        with mock.patch.object(path_type, "replace", fail_baseline):
            with self.assertRaisesRegex(OSError, "baseline promotion failure"):
                steward.add_memory(self.root, payload)

        self.assertEqual(promoted[-1], baseline)
        self.assertEqual(self.managed_bytes(), before)
        self.assertTrue(payload.exists())
        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")

    def test_baseline_schema_and_generation_are_deterministic(self) -> None:
        self.existing_project()
        baseline_path = (
            self.root / steward.STEWARD_NAMESPACE / steward.MANAGED_STATE_NAME
        )
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["generation"], 1)
        paths = [item["path"] for item in payload["files"]]
        self.assertEqual(paths, sorted(paths))
        self.assertNotIn(steward.MANAGED_STATE_NAME, paths)

        steward.add_memory(self.root, self.memory_payload("Advance one generation"))
        self.assertEqual(steward.load_managed_state(self.root).generation, 2)

    def test_malformed_baseline_fields_are_damaging_and_not_bootstrappable(
        self,
    ) -> None:
        self.existing_project()
        baseline_path = (
            self.root / steward.STEWARD_NAMESPACE / steward.MANAGED_STATE_NAME
        )
        original = json.loads(baseline_path.read_text(encoding="utf-8"))
        cases = {
            "schema": {**original, "schema_version": 99},
            "generation": {**original, "generation": 0},
            "path": {
                **original,
                "files": [{"path": "../escape.md", "sha256": "0" * 64}],
            },
            "hash": {
                **original,
                "files": [{"path": "registry.md", "sha256": "invalid"}],
            },
        }
        for label, payload in cases.items():
            with self.subTest(label=label):
                baseline_path.write_text(json.dumps(payload), encoding="utf-8")
                report = steward.validate_project(self.root)
                self.assertEqual(report.status, "DAMAGED")
                with self.assertRaisesRegex(steward.ProjectError, "structurally valid"):
                    steward.bootstrap_managed_state(self.root)
        baseline_path.write_text(
            json.dumps(original, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")

    def test_managed_state_cli_check_and_bootstrap(self) -> None:
        self.existing_project()
        baseline = self.root / steward.STEWARD_NAMESPACE / steward.MANAGED_STATE_NAME
        baseline.unlink()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            check_code = steward.main(["managed-state", str(self.root), "--check"])
        self.assertEqual(check_code, 1)
        self.assertIn("MANAGED_BASELINE_MISSING", output.getvalue())

        with contextlib.redirect_stdout(io.StringIO()):
            bootstrap_code = steward.main(
                ["managed-state", str(self.root), "--bootstrap"]
            )
            ready_code = steward.main(["managed-state", str(self.root), "--check"])
        self.assertEqual(bootstrap_code, 0)
        self.assertEqual(ready_code, 0)
        self.assertEqual(steward.load_managed_state(self.root).generation, 1)

    def test_managed_transaction_promotes_baseline_last_on_success(self) -> None:
        self.existing_project()
        baseline = self.root / steward.STEWARD_NAMESPACE / steward.MANAGED_STATE_NAME
        path_type = type(baseline)
        original_replace = path_type.replace
        promoted: list[Path] = []

        def record_replace(path: Path, target: Path) -> Path:
            target = Path(target)
            if "steward-transaction" in path.name:
                promoted.append(target)
            return original_replace(path, target)

        with mock.patch.object(path_type, "replace", record_replace):
            entry = steward.add_memory(
                self.root, self.memory_payload("Successful atomic baseline")
            )

        self.assertEqual(promoted[-1], baseline)
        self.assertIn(entry, promoted[:-1])
        self.assertEqual(
            steward.managed_state_drift(
                self.root, steward.load_managed_state(self.root)
            ),
            (),
        )

    def test_managed_only_continuity_invokes_no_git_commands(self) -> None:
        self.existing_project()
        with mock.patch.object(
            steward.subprocess,
            "run",
            side_effect=AssertionError("managed continuity invoked Git"),
        ):
            steward.add_memory(
                self.root, self.memory_payload("No Git runtime dependency")
            )
            steward.raise_attention(
                self.root, self.attention_payload("No Git status dependency")
            )
            steward.refresh_index(self.root)
        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")

    def test_audit_recovery_refuses_managed_state_drift_before_mutation(self) -> None:
        self.existing_project()
        stage = (
            self.root
            / steward.STEWARD_NAMESPACE
            / "Audit/Runs/build/.steward-promote-interrupted"
        )
        stage.mkdir(parents=True)
        evidence = stage / "evidence.json"
        evidence.write_text("{}\n", encoding="utf-8")
        registry = self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        registry.write_text(
            registry.read_text(encoding="utf-8") + "manual drift\n",
            encoding="utf-8",
        )

        with self.assertRaises(steward.RecoverableBlocker) as caught:
            steward.recover_audit(self.root, "build")

        self.assertEqual(caught.exception.code, "MANAGED_STATE_CONFLICT")
        self.assertTrue(evidence.exists())


if __name__ == "__main__":
    unittest.main()
