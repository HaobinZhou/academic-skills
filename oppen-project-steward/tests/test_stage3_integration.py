from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "oppen_project_steward.py"
FIXTURES = Path(__file__).parent / "fixtures"
SPEC = importlib.util.spec_from_file_location(
    "oppen_project_steward_stage3", SCRIPT_PATH
)
assert SPEC and SPEC.loader
steward = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = steward
SPEC.loader.exec_module(steward)


class Stage3IntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temp_dir.name)
        self.root = self.temp_root / "project"
        self.payload_number = 0

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def init_empty(self) -> None:
        steward.ensure_v3_project(self.root, create=True)
        steward.refresh_index(self.root)

    def copy_fixture(self, name: str) -> None:
        shutil.copytree(FIXTURES / name, self.root)
        if name == "quant-engineering":
            (self.root / "Deliverables").mkdir()
        steward.ensure_v3_project(self.root, create=True)
        steward.refresh_index(self.root)

    def payload(self, data: dict[str, object]) -> Path:
        self.payload_number += 1
        path = self.temp_root / f"payload-{self.payload_number}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def attention_payload(self, title: str) -> dict[str, object]:
        return {
            "title": title,
            "blocking": False,
            "observation": "A downstream exporter bypasses the registered editor-state contract.",
            "evidence": "src/export.py emits content without calling may_generate().",
            "why_it_matters": "Users could receive content that lacks required approval.",
            "why_no_action_was_taken": "The exporter was outside the authorized editor-state task.",
            "human_decision_needed": "Decide whether to authorize an exporter contract change.",
        }

    def memory_payload(
        self,
        title: str,
        *,
        related_topics: list[str] | None = None,
        supersedes: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "title": title,
            "related_topics": [] if related_topics is None else related_topics,
            "supersedes": [] if supersedes is None else supersedes,
            "invalidates": [],
            "before": "The prior direction appeared sufficient from static inspection.",
            "trigger": "Observed behavior exposed a consequential ambiguity.",
            "decision": "Adopt the explicit contract represented by this decision.",
            "why": "The new direction prevents recurrence of the observed failure.",
            "rejected_or_prior_approach": "The previously credible implicit behavior was rejected.",
            "consequence": "Future components must preserve and test the explicit boundary.",
        }

    def complete_contract_audit(self, path: Path) -> None:
        content = path.read_text(encoding="utf-8")
        replacements = {
            "TODO: Explain the behavior and why a hidden error could materially alter the project.": "Same-bar execution would introduce look-ahead and materially alter results.",
            "TODO: State inputs, outputs, invariants, side effects, and downstream obligations.": "A signal bar integer maps to exactly the following execution bar with no side effects.",
            "TODO: Link executable checks for important boundaries and failure modes.": "`tests/verify_execution_model.py` checks zero and later-bar boundaries.",
            "TODO: State conditions outside the validated contract.": "Exchange outages and partial fills remain outside this timing contract.",
        }
        for old, new in replacements.items():
            content = content.replace(old, new)
        write_set = steward.managed_write_set(
            self.root, "contract-audit complete", exact=(path,)
        )
        steward.assert_managed_write_set_clean(self.root, write_set)
        steward.managed_file_transaction(self.root, write_set, {path: content})

    def run_verification(self, relative: str) -> None:
        subprocess.run(
            [sys.executable, str(self.root / relative)],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_software_ai_product_end_to_end(self) -> None:
        self.copy_fixture("software-ai-product")
        steward.register_canonical(
            self.root,
            "editor-state",
            "canonical/editor-state.md",
            None,
            "tests/verify_editor_state.py",
            replace=False,
        )
        self.run_verification("tests/verify_editor_state.py")

        (self.root / "src/export.py").write_text(
            "def export(content):\n    return content\n", encoding="utf-8"
        )
        steward.raise_attention(
            self.root,
            self.payload(self.attention_payload("Exporter bypasses approval")),
        )

        for relative in (
            "src/editor_state.py",
            "canonical/editor-state.md",
            "tests/verify_editor_state.py",
        ):
            path = self.root / relative
            path.write_text(
                path.read_text(encoding="utf-8").replace("ready", "reviewed"),
                encoding="utf-8",
            )
        steward.register_canonical(
            self.root,
            "editor-state",
            "canonical/editor-state.md",
            None,
            "tests/verify_editor_state.py",
            replace=False,
        )
        self.run_verification("tests/verify_editor_state.py")
        steward.add_memory(
            self.root,
            self.payload(
                self.memory_payload(
                    "Replace ambiguous ready state with reviewed state",
                    related_topics=["editor-state"],
                )
            ),
        )

        (self.root / "src/export.py").write_text(
            "from editor_state import may_generate\n\n"
            "def export(content, state, approved):\n"
            "    return content if may_generate(state, approved) else None\n",
            encoding="utf-8",
        )
        steward.resolve_attention(self.root, "A-0001")
        steward.refresh_index(self.root)
        report = steward.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(
            {
                path.name
                for path in (
                    self.root / ".oppen-project-steward/Memory/entries"
                ).iterdir()
            },
            {"M-0001.md"},
        )

    def test_initialization_failure_removes_new_managed_state(self) -> None:
        with mock.patch.object(
            steward, "atomic_write", side_effect=OSError("injected init failure")
        ):
            with self.assertRaisesRegex(OSError, "injected init failure"):
                steward.ensure_v3_project(self.root, create=True)
        self.assertFalse(self.root.exists())

    def test_quant_engineering_end_to_end(self) -> None:
        self.copy_fixture("quant-engineering")
        steward.register_canonical(
            self.root,
            "execution-model",
            "canonical/execution-model.md",
            None,
            "tests/verify_execution_model.py",
            replace=False,
        )
        self.run_verification("tests/verify_execution_model.py")
        audit, _ = steward.create_or_locate_contract_audit(
            self.root,
            "execution-timing",
            "src/execution.py",
            "A hidden timing error would introduce look-ahead",
        )
        self.complete_contract_audit(audit)

        deliverable = self.root / "Deliverables/benchmark-summary.md"
        deliverable.write_text(
            "# Benchmark Summary\n\nNext-bar timing verified on representative cases.\n",
            encoding="utf-8",
        )
        steward.register_deliverable(
            self.root,
            "timing-benchmark",
            "Deliverables/benchmark-summary.md",
            "benchmark-summary",
            "engineering-review",
            "src/execution.py",
            replace=False,
        )

        staging = self.temp_root / "audit-staging"
        staging.mkdir()
        (staging / "manifest.json").write_text(
            '{"timing": "next-bar", "accepted": true}\n', encoding="utf-8"
        )
        steward.promote_audit(self.root, "backtest", staging)
        self.assertFalse(staging.exists())
        steward.add_memory(
            self.root,
            self.payload(
                self.memory_payload(
                    "Reject same-bar execution after look-ahead review",
                    related_topics=["execution-model"],
                )
            ),
        )
        steward.refresh_index(self.root)
        report = steward.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)
        self.assertTrue(
            (
                self.root
                / ".oppen-project-steward/Audit/Runs/backtest/current/manifest.json"
            ).is_file()
        )

    def test_audit_promotion_replaces_whole_current_tree(self) -> None:
        self.init_empty()
        first = self.temp_root / "first-audit"
        first.mkdir()
        (first / "old.json").write_text("{}\n", encoding="utf-8")
        steward.promote_audit(self.root, "build", first)

        second = self.temp_root / "second-audit"
        second.mkdir()
        (second / "new.json").write_text('{"pass": true}\n', encoding="utf-8")
        current = steward.promote_audit(self.root, "build", second)
        self.assertEqual({path.name for path in current.iterdir()}, {"new.json"})
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_audit_promotion_failure_preserves_previous_current(self) -> None:
        self.init_empty()
        first = self.temp_root / "accepted-audit"
        first.mkdir()
        (first / "accepted.json").write_text('{"pass": true}\n', encoding="utf-8")
        steward.promote_audit(self.root, "build", first)
        current = self.root / ".oppen-project-steward/Audit/Runs/build/current"
        before = (current / "accepted.json").read_text(encoding="utf-8")

        failing = self.temp_root / "failing-audit"
        failing.mkdir()
        (failing / "replacement.json").write_text("{}\n", encoding="utf-8")
        with mock.patch.object(
            steward.shutil, "copytree", side_effect=OSError("copy failed")
        ):
            with self.assertRaisesRegex(OSError, "copy failed"):
                steward.promote_audit(self.root, "build", failing)
        self.assertEqual(
            before, (current / "accepted.json").read_text(encoding="utf-8")
        )
        self.assertEqual({path.name for path in current.parent.iterdir()}, {"current"})
        self.assertTrue(failing.exists())
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_audit_promotion_rejects_unsafe_staging_roots(self) -> None:
        self.init_empty()
        with self.assertRaisesRegex(
            steward.ProjectError, "cannot contain the target project"
        ):
            steward.promote_audit(self.root, "build", self.temp_root)
        with self.assertRaisesRegex(steward.ProjectError, "system temporary"):
            steward.promote_audit(self.root, "build", FIXTURES / "software-ai-product")

    def test_audit_promotion_rejects_top_level_symlink(self) -> None:
        self.init_empty()
        staging = self.temp_root / "real-audit"
        staging.mkdir()
        (staging / "evidence.json").write_text("{}\n", encoding="utf-8")
        linked = self.temp_root / "linked-audit"
        linked.symlink_to(staging, target_is_directory=True)
        with self.assertRaisesRegex(steward.ProjectError, "symbolic link"):
            steward.promote_audit(self.root, "build", linked)
        self.assertTrue(staging.exists())
        self.assertFalse(
            (self.root / ".oppen-project-steward/Audit/Runs/build").exists()
        )

    def test_contract_audit_transaction_rolls_back_on_index_failure(self) -> None:
        self.copy_fixture("quant-engineering")
        project_file = self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        before = project_file.read_text(encoding="utf-8")
        path_type = type(project_file)
        original_replace = path_type.replace
        failed = False

        def fail_index_once(path: Path, target: Path) -> Path:
            nonlocal failed
            if Path(target).resolve() == project_file.resolve() and not failed:
                failed = True
                raise OSError("injected contract index failure")
            return original_replace(path, target)

        with mock.patch.object(path_type, "replace", fail_index_once):
            with self.assertRaisesRegex(OSError, "injected contract index failure"):
                steward.create_or_locate_contract_audit(
                    self.root,
                    "execution-timing",
                    "src/execution.py",
                    "A hidden timing error would introduce look-ahead",
                )
        self.assertEqual(before, project_file.read_text(encoding="utf-8"))
        self.assertFalse(
            (
                self.root
                / ".oppen-project-steward/Audit/Contracts/audit_execution-timing.md"
            ).exists()
        )
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_attention_raise_transaction_rolls_back_on_index_failure(self) -> None:
        self.init_empty()
        payload = self.payload(self.attention_payload("Transactional attention"))
        steward.ensure_attention_structure_unlocked(self.root)
        index_path = self.root / ".oppen-project-steward/Attention/index.md"
        before = index_path.read_text(encoding="utf-8")
        path_type = type(index_path)
        original_replace = path_type.replace
        failed = False

        def fail_index_once(path: Path, target: Path) -> Path:
            nonlocal failed
            if Path(target).resolve() == index_path.resolve() and not failed:
                failed = True
                raise OSError("injected index failure")
            return original_replace(path, target)

        with mock.patch.object(path_type, "replace", fail_index_once):
            with self.assertRaisesRegex(OSError, "injected index failure"):
                steward.raise_attention(self.root, payload)
        self.assertTrue(payload.exists())
        self.assertEqual(before, index_path.read_text(encoding="utf-8"))
        self.assertEqual(
            list((self.root / ".oppen-project-steward/Attention/entries").iterdir()), []
        )
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_attention_resolve_transaction_rolls_back_on_delete_failure(self) -> None:
        self.init_empty()
        entry = steward.raise_attention(
            self.root, self.payload(self.attention_payload("Persistent attention"))
        )
        index_path = self.root / ".oppen-project-steward/Attention/index.md"
        before = index_path.read_text(encoding="utf-8")
        original_unlink = Path.unlink
        failed = False

        def fail_delete_once(path: Path, *args: object, **kwargs: object) -> None:
            nonlocal failed
            if path == entry and not failed:
                failed = True
                raise OSError("injected delete failure")
            original_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", fail_delete_once):
            with self.assertRaisesRegex(OSError, "injected delete failure"):
                steward.resolve_attention(self.root, "A-0001")
        self.assertTrue(entry.exists())
        self.assertEqual(before, index_path.read_text(encoding="utf-8"))
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_memory_relationship_transaction_rolls_back_on_index_failure(self) -> None:
        self.init_empty()
        first = steward.add_memory(
            self.root, self.payload(self.memory_payload("First direction"))
        )
        payload = self.payload(
            self.memory_payload("Second direction", supersedes=["M-0001"])
        )
        index_path = self.root / ".oppen-project-steward/Memory/index.md"
        before_index = index_path.read_text(encoding="utf-8")
        before_first = first.read_text(encoding="utf-8")
        path_type = type(index_path)
        original_replace = path_type.replace
        failed = False

        def fail_index_once(path: Path, target: Path) -> Path:
            nonlocal failed
            if Path(target).resolve() == index_path.resolve() and not failed:
                failed = True
                raise OSError("injected memory index failure")
            return original_replace(path, target)

        with mock.patch.object(path_type, "replace", fail_index_once):
            with self.assertRaisesRegex(OSError, "injected memory index failure"):
                steward.add_memory(self.root, payload)
        self.assertTrue(payload.exists())
        self.assertEqual(before_first, first.read_text(encoding="utf-8"))
        self.assertEqual(before_index, index_path.read_text(encoding="utf-8"))
        self.assertFalse(
            (self.root / ".oppen-project-steward/Memory/entries/M-0002.md").exists()
        )
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_concurrent_memory_allocation_never_reuses_id(self) -> None:
        self.init_empty()
        payloads = [
            self.payload(self.memory_payload("Concurrent decision one")),
            self.payload(self.memory_payload("Concurrent decision two")),
        ]
        with ThreadPoolExecutor(max_workers=2) as executor:
            paths = list(
                executor.map(lambda path: steward.add_memory(self.root, path), payloads)
            )
        self.assertEqual({path.name for path in paths}, {"M-0001.md", "M-0002.md"})
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_fixed_topology_and_compact_indices_scale_to_one_thousand_entries(
        self,
    ) -> None:
        self.init_empty()
        _, attention_index, attention_entries = (
            steward.ensure_attention_structure_unlocked(self.root)
        )
        _, memory_index, memory_entries = steward.ensure_memory_structure_unlocked(
            self.root
        )
        for number in range(1, 1001):
            attention_id = f"A-{number:04d}"
            (attention_entries / f"{attention_id}.md").write_text(
                steward.render_structured_entry(
                    {"id": attention_id, "title": f"Issue {number}", "blocking": False},
                    f"Human Attention {attention_id}: Issue {number}",
                    [
                        (section, f"Fact {number} for {section}.")
                        for section in steward.ATTENTION_SECTIONS
                    ],
                ),
                encoding="utf-8",
            )
            memory_id = f"M-{number:04d}"
            (memory_entries / f"{memory_id}.md").write_text(
                steward.render_structured_entry(
                    {
                        "id": memory_id,
                        "status": "active",
                        "title": f"Decision {number}",
                        "related_topics": [],
                        "supersedes": [],
                        "invalidates": [],
                        "superseded_by": [],
                        "invalidated_by": [],
                    },
                    f"Decision Memory {memory_id}: Decision {number}",
                    [
                        (section, f"Context {number} for {section}.")
                        for section in steward.MEMORY_SECTIONS
                    ],
                ),
                encoding="utf-8",
            )
        attention_entries_data = steward.load_attention_entries_unlocked(
            attention_entries
        )
        memory_entries_data = steward.load_memory_entries_unlocked(memory_entries)
        attention_index.write_text(
            steward.render_attention_index(attention_entries_data, 1000),
            encoding="utf-8",
        )
        memory_index.write_text(
            steward.render_memory_index(memory_entries_data, 1000),
            encoding="utf-8",
        )
        (self.root / steward.STEWARD_NAMESPACE / steward.MANAGED_STATE_NAME).unlink()
        steward.bootstrap_managed_state(self.root)
        report = steward.validate_project(self.root)
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(len(list(attention_entries.iterdir())), 1000)
        self.assertEqual(len(list(memory_entries.iterdir())), 1000)
        self.assertNotIn("Fact 1000", attention_index.read_text(encoding="utf-8"))
        self.assertNotIn("Context 1000", memory_index.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
