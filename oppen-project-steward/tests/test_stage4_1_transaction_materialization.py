from __future__ import annotations

import errno
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "oppen_project_steward.py"
SKILL_PATH = Path(__file__).parents[1] / "SKILL.md"
SPEC = importlib.util.spec_from_file_location(
    "oppen_project_steward_stage4_1", SCRIPT_PATH
)
assert SPEC and SPEC.loader
steward = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = steward
SPEC.loader.exec_module(steward)


class Stage41TransactionMaterializationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temp_dir.name)
        self.root = self.temp_root / "project"
        steward.ensure_v3_project(self.root, create=True)
        steward.refresh_index(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def payload(self, title: str = "Adopt bounded worker memory") -> Path:
        path = self.temp_root / f"payload-{title.replace(' ', '-')}.json"
        path.write_text(
            json.dumps(
                {
                    "title": title,
                    "related_topics": [],
                    "supersedes": [],
                    "invalidates": [],
                    "before": "Workers used an execution model that was credible at small scale.",
                    "trigger": "Production-scale load exposed a durable reliability limit.",
                    "decision": "Bound worker memory and concurrency as one operating policy.",
                    "why": "The bounded policy prevents recurring spill and instability.",
                    "rejected_or_prior_approach": "Unbounded concurrency was rejected.",
                    "consequence": "Future tuning must preserve the bounded reliability policy.",
                }
            ),
            encoding="utf-8",
        )
        return path

    def create_sparse_unrelated_file(self, root: Path, size: int) -> Path:
        path = root / "models/huge-model.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            handle.truncate(size)
        return path

    def test_large_unrelated_artifact_is_never_materialized(self) -> None:
        steward.ensure_memory_structure_unlocked(self.root)
        huge = self.create_sparse_unrelated_file(self.root, 5 * 1024**4)
        before = huge.stat()
        plans: list[steward.ManagedTransactionPlan] = []
        original_transaction = steward.managed_file_transaction

        def record_plan(*args, **kwargs):
            plan = original_transaction(*args, **kwargs)
            plans.append(plan)
            return plan

        with (
            mock.patch.object(
                steward, "managed_file_transaction", side_effect=record_plan
            ),
            mock.patch.object(steward.os, "link", wraps=os.link) as link_spy,
            mock.patch.object(
                steward.shutil, "copy", wraps=steward.shutil.copy
            ) as copy_spy,
            mock.patch.object(
                steward.shutil, "copy2", wraps=steward.shutil.copy2
            ) as copy2_spy,
            mock.patch.object(
                steward.shutil, "copytree", wraps=steward.shutil.copytree
            ) as copytree_spy,
        ):
            entry = steward.add_memory(self.root, self.payload())

        self.assertTrue(entry.is_file())
        self.assertEqual(huge.stat().st_size, before.st_size)
        self.assertEqual(huge.stat().st_mtime_ns, before.st_mtime_ns)
        link_spy.assert_not_called()
        copy_spy.assert_not_called()
        copytree_spy.assert_not_called()
        copied_sources = {
            Path(call.args[0]).resolve() for call in copy2_spy.call_args_list
        }
        self.assertEqual(
            copied_sources,
            {
                (self.root / ".oppen-project-steward/Memory/index.md").resolve(),
                (
                    self.root / steward.STEWARD_NAMESPACE / steward.MANAGED_STATE_NAME
                ).resolve(),
            },
        )
        memory_plan = next(plan for plan in plans if plan.operation == "memory add")
        self.assertEqual(
            {
                path.relative_to(self.root.resolve()).as_posix()
                for path in memory_plan.materialized_paths
            },
            {
                ".oppen-project-steward/Memory/index.md",
                ".oppen-project-steward/Memory/entries/M-0001.md",
                ".oppen-project-steward/.managed-state.json",
            },
        )
        self.assertLess(memory_plan.estimated_staged_regular_file_bytes, 1024 * 1024)

    def test_exdev_cannot_expand_a_managed_file_transaction(self) -> None:
        steward.ensure_memory_structure_unlocked(self.root)
        huge = self.create_sparse_unrelated_file(self.root, 1024**4)
        before = huge.stat()
        with (
            mock.patch.object(
                steward.os,
                "link",
                side_effect=OSError(errno.EXDEV, "cross-device link"),
            ) as link_spy,
            mock.patch.object(
                steward.shutil, "copytree", wraps=steward.shutil.copytree
            ) as copytree_spy,
        ):
            steward.add_memory(self.root, self.payload("Use cross-filesystem staging"))

        link_spy.assert_not_called()
        copytree_spy.assert_not_called()
        self.assertEqual(huge.stat().st_size, before.st_size)
        self.assertEqual(huge.stat().st_mtime_ns, before.st_mtime_ns)

    def test_same_filesystem_does_not_create_a_hardlink_tree(self) -> None:
        steward.ensure_memory_structure_unlocked(self.root)
        self.create_sparse_unrelated_file(self.root, 1024**3)
        with mock.patch.object(steward.os, "link", wraps=os.link) as link_spy:
            steward.add_memory(self.root, self.payload("Keep same-filesystem scope"))
        link_spy.assert_not_called()

    def test_candidate_overlay_reads_original_plus_only_staged_managed_files(
        self,
    ) -> None:
        steward.ensure_memory_structure_unlocked(self.root)
        huge = self.create_sparse_unrelated_file(self.root, 2 * 1024**4)
        project_file = self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        entry = self.root / ".oppen-project-steward/Memory/entries/M-0001.md"
        index = self.root / ".oppen-project-steward/Memory/index.md"
        writes = {
            entry: "candidate memory entry\n",
            index: "candidate memory index\n",
        }
        write_set = steward.managed_write_set(
            self.root, "overlay regression", exact=tuple(writes)
        )
        observed: dict[str, object] = {}

        def validate(overlay: steward.CandidateOverlay) -> None:
            observed["entry"] = overlay.read_text(entry)
            observed["index"] = overlay.read_text(index)
            observed["project"] = overlay.read_text(project_file)
            observed["huge"] = overlay.resolve(huge)

        plan = steward.managed_file_transaction(
            self.root,
            write_set,
            writes,
            validate_candidate=validate,
        )

        self.assertEqual(observed["entry"], writes[entry])
        self.assertEqual(observed["index"], writes[index])
        self.assertIn(steward.SCHEMA_MARKER, str(observed["project"]))
        self.assertEqual(observed["huge"], huge.resolve())
        baseline = self.root / steward.STEWARD_NAMESPACE / steward.MANAGED_STATE_NAME
        self.assertEqual(
            set(plan.materialized_paths),
            {entry.resolve(), index.resolve(), baseline.resolve()},
        )

    def test_unsafe_transaction_plan_blocks_before_mutation(self) -> None:
        index = self.root / ".oppen-project-steward/Memory/index.md"
        outside_write_set = self.root / "Data/unrelated.txt"
        write_set = steward.managed_write_set(
            self.root, "unsafe regression", exact=(index,)
        )
        with self.assertRaises(steward.RecoverableBlocker) as caught:
            steward.managed_file_transaction(
                self.root,
                write_set,
                {outside_write_set: "must not be written\n"},
            )
        self.assertEqual(caught.exception.code, "BLOCKED_UNSAFE_TRANSACTION_PLAN")
        self.assertFalse(outside_write_set.exists())

    def test_failure_rolls_back_only_affected_managed_files(self) -> None:
        steward.ensure_memory_structure_unlocked(self.root)
        index = self.root / ".oppen-project-steward/Memory/index.md"
        entry = self.root / ".oppen-project-steward/Memory/entries/M-0001.md"
        initial_write_set = steward.managed_write_set(
            self.root, "rollback fixture", exact=(entry,)
        )
        steward.managed_file_transaction(
            self.root, initial_write_set, {entry: "existing entry\n"}
        )
        huge = self.create_sparse_unrelated_file(self.root, 3 * 1024**4)
        index_before = index.read_bytes()
        entry_before = entry.read_bytes()
        huge_before = (huge.stat().st_size, huge.stat().st_mtime_ns)
        write_set = steward.managed_write_set(
            self.root, "rollback regression", exact=(index, entry)
        )
        original_unlink = Path.unlink

        def fail_entry_delete(path: Path, *args, **kwargs):
            if path.resolve() == entry.resolve():
                raise OSError("injected delete failure")
            return original_unlink(path, *args, **kwargs)

        with (
            mock.patch.object(
                Path, "unlink", autospec=True, side_effect=fail_entry_delete
            ),
            mock.patch.object(
                steward.shutil, "copytree", wraps=steward.shutil.copytree
            ) as copytree_spy,
            self.assertRaises(OSError),
        ):
            steward.managed_file_transaction(
                self.root,
                write_set,
                {index: "replacement index\n"},
                (entry,),
            )

        copytree_spy.assert_not_called()
        self.assertEqual(index.read_bytes(), index_before)
        self.assertEqual(entry.read_bytes(), entry_before)
        self.assertEqual((huge.stat().st_size, huge.stat().st_mtime_ns), huge_before)
        self.assertFalse(
            any("steward-transaction" in path.name for path in self.root.rglob("*"))
        )

    def test_transaction_storage_does_not_scale_with_unrelated_content(self) -> None:
        plans: list[steward.ManagedTransactionPlan] = []
        for name, size in (("small", 1024**2), ("large", 5 * 1024**4)):
            root = self.temp_root / name
            steward.ensure_v3_project(root, create=True)
            steward.ensure_memory_structure_unlocked(root)
            self.create_sparse_unrelated_file(root, size)
            index = root / ".oppen-project-steward/Memory/index.md"
            entry = root / ".oppen-project-steward/Memory/entries/M-0001.md"
            write_set = steward.managed_write_set(
                root, "scaling regression", exact=(entry, index)
            )
            plans.append(
                steward.managed_file_transaction(
                    root,
                    write_set,
                    {
                        entry: "same candidate entry\n",
                        index: "same candidate index\n",
                    },
                )
            )

        self.assertEqual(
            plans[0].estimated_staged_regular_file_bytes,
            plans[1].estimated_staged_regular_file_bytes,
        )
        self.assertEqual(len(plans[0].materialized_paths), 3)
        self.assertEqual(len(plans[1].materialized_paths), 3)

    def test_audit_promotion_materializes_only_its_owned_stage(self) -> None:
        huge = self.create_sparse_unrelated_file(self.root, 4 * 1024**4)
        huge_before = (huge.stat().st_size, huge.stat().st_mtime_ns)
        source = self.temp_root / "audit-input"
        source.mkdir()
        (source / "summary.json").write_text('{"ready": true}\n', encoding="utf-8")
        plans: list[steward.ManagedTransactionPlan] = []
        original_plan = steward.build_transaction_plan

        def record_plan(*args, **kwargs):
            plan = original_plan(*args, **kwargs)
            plans.append(plan)
            return plan

        with mock.patch.object(
            steward, "build_transaction_plan", side_effect=record_plan
        ):
            current = steward.promote_audit(self.root, "evaluation", source)

        audit_plan = next(plan for plan in plans if plan.operation == "audit promote")
        self.assertEqual(
            tuple(
                path.relative_to(self.root.resolve()).as_posix()
                for path in audit_plan.materialized_paths
            ),
            (".oppen-project-steward/Audit/Runs/evaluation",),
        )
        self.assertEqual(
            audit_plan.estimated_staged_regular_file_bytes,
            len('{"ready": true}\n'.encode("utf-8")),
        )
        self.assertEqual((huge.stat().st_size, huge.stat().st_mtime_ns), huge_before)
        self.assertEqual(
            (current / "summary.json").read_text(encoding="utf-8"),
            '{"ready": true}\n',
        )

    def test_skill_persists_transaction_materialization_boundary(self) -> None:
        text = SKILL_PATH.read_text(encoding="utf-8")
        for phrase in (
            "declared Managed Operation Write Set",
            "Never clone, recursively copy, hardlink, reflink",
            "candidate overlay",
            "EXDEV",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
