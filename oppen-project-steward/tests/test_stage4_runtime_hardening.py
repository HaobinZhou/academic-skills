from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "oppen_project_steward.py"
SKILL_PATH = Path(__file__).parents[1] / "SKILL.md"
FIXTURES = Path(__file__).parent / "fixtures"
SPEC = importlib.util.spec_from_file_location(
    "oppen_project_steward_stage4", SCRIPT_PATH
)
assert SPEC and SPEC.loader
steward = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = steward
SPEC.loader.exec_module(steward)


class Stage4RuntimeHardeningTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temp_dir.name)
        self.root = self.temp_root / "project"
        self.payload_number = 0

    def tearDown(self) -> None:
        if self.root.exists():
            project_id = steward.hashlib.sha256(
                str(self.root.resolve()).encode("utf-8")
            ).hexdigest()[:16]
            recovery_root = steward.recovery_root_for_project(self.root)
            shutil.rmtree(recovery_root / project_id, ignore_errors=True)
        self.temp_dir.cleanup()

    def init_empty(self) -> None:
        steward.ensure_v3_project(self.root, create=True)
        steward.refresh_index(self.root)

    def copy_fixture(self, name: str) -> None:
        shutil.copytree(FIXTURES / name, self.root)
        payload = self.payload(
            {
                "role_mappings": {
                    "source": "src",
                    "data": "Data",
                    "deliverables": "Deliverables",
                },
                "initial_canonical_registrations": [],
                "initial_deliverable_registrations": [
                    {
                        "id": "operator-guide",
                        "path": "Deliverables/operator-guide.md",
                        "kind": "operator-guide",
                        "audience": "service-operators",
                        "producer": "src/router.py",
                    }
                ],
            }
        )
        steward.apply_adoption(self.root, payload)
        legacy_audit = self.root / "Audit"
        shutil.copytree(
            legacy_audit,
            self.root / steward.STEWARD_NAMESPACE / "Audit",
            dirs_exist_ok=True,
        )
        shutil.rmtree(legacy_audit)

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def payload(self, data: dict[str, object]) -> Path:
        self.payload_number += 1
        path = self.temp_root / f"payload-{self.payload_number}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def memory_payload(self, title: str) -> dict[str, object]:
        return {
            "title": title,
            "related_topics": [],
            "supersedes": [],
            "invalidates": [],
            "before": "The earlier architecture was credible before runtime evidence.",
            "trigger": "Production-scale behavior exposed a durable reliability constraint.",
            "decision": "Adopt the safer execution and storage boundary.",
            "why": "The revised boundary prevents recurrence under realistic load.",
            "rejected_or_prior_approach": "The former high-concurrency design was rejected.",
            "consequence": "Future changes must preserve the reliability boundary.",
        }

    def attention_payload(self, title: str) -> dict[str, object]:
        return {
            "title": title,
            "blocking": False,
            "observation": "A downstream component bypasses the approval contract.",
            "evidence": "The integration route calls execution without approval state.",
            "why_it_matters": "Unauthorized execution could affect production users.",
            "why_no_action_was_taken": "Changing the integration architecture is outside this task.",
            "human_decision_needed": "Authorize an integration contract redesign.",
        }

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def commit_all(self) -> None:
        self.git("init", "-q")
        self.git("config", "user.email", "stage4@example.invalid")
        self.git("config", "user.name", "Stage 4 Test")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "managed baseline")

    def test_runtime_state_classifies_ready_and_recoverable_audit(self) -> None:
        self.init_empty()
        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")
        self.write(
            ".oppen-project-steward/Audit/Runs/build/current/accepted.json", "{}\n"
        )
        residue = self.write(
            ".oppen-project-steward/Audit/Runs/build/failed-interrupted/partial.json",
            "{}\n",
        )
        report = steward.validate_project(self.root)
        self.assertEqual(report.status, "BLOCKED_RECOVERABLE")
        self.assertEqual(report.blockers[0].code, "AUDIT_STAGING_RESIDUE")
        self.assertIn(
            residue.parent.relative_to(self.root).as_posix(), report.blockers[0].paths
        )
        self.assertIn("audit recover", report.blockers[0].recovery)

    def test_failed_stage_without_current_is_recoverable(self) -> None:
        self.init_empty()
        source = self.write(
            ".oppen-project-steward/Audit/Runs/build/failed-before-promotion/partial.json",
            "{}\n",
        ).parent
        self.write(
            ".oppen-project-steward/Audit/Runs/build/failed-before-promotion/report_v2.md",
            "failed\n",
        )
        self.assertEqual(
            steward.validate_project(self.root).status, "BLOCKED_RECOVERABLE"
        )
        steward.recover_audit(self.root, "build")
        self.assertFalse(source.exists())
        self.assertFalse(
            (self.root / ".oppen-project-steward/Audit/Runs/build").exists()
        )
        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")

    def test_runtime_state_classifies_stale_index_as_recoverable(self) -> None:
        self.init_empty()
        steward.raise_attention(
            self.root, self.payload(self.attention_payload("Contract authority needed"))
        )
        index = self.root / ".oppen-project-steward/Attention/index.md"
        index.write_text(
            index.read_text(encoding="utf-8") + "drift\n", encoding="utf-8"
        )
        report = steward.validate_project(self.root)
        self.assertEqual(report.status, "BLOCKED_RECOVERABLE")
        self.assertTrue(
            any(blocker.code == "STALE_GENERATED_INDEX" for blocker in report.blockers)
        )

    def test_runtime_state_classifies_canonical_and_role_conflicts_as_damaged(
        self,
    ) -> None:
        self.init_empty()
        self.write("canonical/one.md", "Status: frozen\n")
        self.write("canonical/two.md", "Status: frozen\n")
        self.write("tests/verify.py", "assert True\n")
        steward.register_canonical(
            self.root,
            "one",
            "canonical/one.md",
            None,
            "tests/verify.py",
            replace=False,
        )
        project_file = self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        text = project_file.read_text(encoding="utf-8")
        entries = steward.parse_canonical_entries(text)
        entries.append(
            steward.CanonicalEntry("two", "canonical/one.md", "", "tests/verify.py")
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
        self.assertEqual(steward.validate_project(self.root).status, "DAMAGED")

        project_file.write_text(text, encoding="utf-8")
        project_file.write_text(
            steward.replace_block(
                text,
                steward.ROLE_START,
                steward.ROLE_END,
                "| Role | Path | Purpose |\n| --- | --- | --- |\n"
                "| Unknown | app | Not a Steward role |",
                "role",
            ),
            encoding="utf-8",
        )
        self.assertEqual(steward.validate_project(self.root).status, "DAMAGED")

    def test_audit_recovery_preserves_current_and_writes_external_manifest(
        self,
    ) -> None:
        self.init_empty()
        current = self.write(
            ".oppen-project-steward/Audit/Runs/build/current/accepted.json",
            '{"pass": true}\n',
        )
        source = self.write(
            ".oppen-project-steward/Audit/Runs/build/failed-interrupted/partial.json",
            '{"pass": false}\n',
        ).parent
        before_current = current.read_bytes()

        destination = steward.recover_audit(self.root, "build")

        self.assertFalse(steward.path_contains(self.root, destination))
        self.assertFalse(source.exists())
        self.assertEqual(current.read_bytes(), before_current)
        recovered = destination / "failed-interrupted/partial.json"
        self.assertEqual(recovered.read_text(encoding="utf-8"), '{"pass": false}\n')
        manifest_path = destination / "recovery-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["stage"], "build")
        self.assertEqual(manifest["file_count"], 1)
        self.assertEqual(manifest["total_size"], len('{"pass": false}\n'))
        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")
        self.assertEqual(
            {path.name for path in current.parent.parent.iterdir()}, {"current"}
        )

    def test_audit_recovery_refuses_ambiguous_artifact(self) -> None:
        self.init_empty()
        self.write(
            ".oppen-project-steward/Audit/Runs/build/current/accepted.json", "{}\n"
        )
        ambiguous = self.write(
            ".oppen-project-steward/Audit/Runs/build/previous/evidence.json", "{}\n"
        ).parent
        with self.assertRaises(steward.RecoverableBlocker) as caught:
            steward.recover_audit(self.root, "build")
        self.assertEqual(caught.exception.code, "AUDIT_RECOVERY_REVIEW_REQUIRED")
        self.assertTrue(ambiguous.exists())
        self.assertEqual(
            steward.validate_project(self.root).status, "BLOCKED_RECOVERABLE"
        )

    def test_audit_recovery_refuses_when_governance_is_damaged(self) -> None:
        self.init_empty()
        self.write(
            ".oppen-project-steward/Audit/Runs/build/current/accepted.json", "{}\n"
        )
        source = self.write(
            ".oppen-project-steward/Audit/Runs/build/failed-interrupted/partial.json",
            "{}\n",
        ).parent
        registry = self.root / steward.STEWARD_NAMESPACE / steward.REGISTRY_NAME
        registry.write_text(
            registry.read_text(encoding="utf-8").replace(steward.CANONICAL_END, ""),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(steward.ProjectError, "DAMAGED"):
            steward.recover_audit(self.root, "build")
        self.assertTrue(source.exists())

    def test_failed_audit_recovery_leaves_source_intact(self) -> None:
        self.init_empty()
        self.write(
            ".oppen-project-steward/Audit/Runs/build/current/accepted.json", "{}\n"
        )
        source_file = self.write(
            ".oppen-project-steward/Audit/Runs/build/failed-copy/partial.json",
            '{"partial": true}\n',
        )
        with mock.patch.object(
            steward.shutil, "copytree", side_effect=OSError("copy failed")
        ):
            with self.assertRaisesRegex(OSError, "copy failed"):
                steward.recover_audit(self.root, "build")
        self.assertEqual(source_file.read_text(encoding="utf-8"), '{"partial": true}\n')

    def test_audit_recovery_verifies_copy_before_source_removal(self) -> None:
        self.init_empty()
        self.write(
            ".oppen-project-steward/Audit/Runs/build/current/accepted.json", "{}\n"
        )
        source_file = self.write(
            ".oppen-project-steward/Audit/Runs/build/failed-verify/partial.json",
            '{"partial": true}\n',
        )
        original_manifest = steward.recovery_content_manifest
        calls = 0

        def mismatched_manifest(
            base: Path, sources: tuple[Path, ...]
        ) -> tuple[tuple[str, str, int, str], ...]:
            nonlocal calls
            calls += 1
            rows = original_manifest(base, sources)
            if calls == 2:
                return (*rows, ("injected", "file", 1, "invalid"))
            return rows

        with mock.patch.object(
            steward, "recovery_content_manifest", side_effect=mismatched_manifest
        ):
            with self.assertRaisesRegex(
                steward.ProjectError, "read-back manifest does not match"
            ):
                steward.recover_audit(self.root, "build")
        self.assertEqual(source_file.read_text(encoding="utf-8"), '{"partial": true}\n')

    def test_memory_add_allows_unrelated_tracked_and_untracked_dirty_work(self) -> None:
        self.init_empty()
        source = self.write("src/app.py", "VALUE = 1\n")
        self.commit_all()
        source.write_text("VALUE = 2\n", encoding="utf-8")
        note = self.write("notes/local-design.md", "Uncommitted design work.\n")
        before_dirty = set(steward.git_dirty_paths(self.root))
        before_source = source.read_bytes()
        before_note = note.read_bytes()

        entry = steward.add_memory(
            self.root, self.payload(self.memory_payload("Adopt bounded concurrency"))
        )

        self.assertTrue(entry.is_file())
        self.assertEqual(source.read_bytes(), before_source)
        self.assertEqual(note.read_bytes(), before_note)
        self.assertTrue(before_dirty.issubset(set(steward.git_dirty_paths(self.root))))

    def test_git_dirty_paths_are_project_relative_inside_parent_repository(
        self,
    ) -> None:
        repository = self.temp_root / "repository"
        self.root = repository / "managed-project"
        self.init_empty()
        subprocess.run(
            ["git", "-C", str(repository), "init", "-q"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.git("config", "user.email", "stage4@example.invalid")
        self.git("config", "user.name", "Stage 4 Test")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "nested managed baseline")
        source = self.write("src/app.py", "VALUE = 1\n")
        self.git("add", "src/app.py")
        self.git("commit", "-q", "-m", "add source")
        source.write_text("VALUE = 2\n", encoding="utf-8")

        self.assertEqual(steward.git_dirty_paths(self.root), (Path("src/app.py"),))

    def test_memory_add_blocks_dirty_managed_index_without_partial_write(self) -> None:
        self.init_empty()
        steward.add_memory(
            self.root, self.payload(self.memory_payload("Initial reliability boundary"))
        )
        self.commit_all()
        index = self.root / ".oppen-project-steward/Memory/index.md"
        index.write_text(
            index.read_text(encoding="utf-8") + "user edit\n", encoding="utf-8"
        )
        before = index.read_bytes()
        payload = self.payload(self.memory_payload("Replacement reliability boundary"))

        with self.assertRaises(steward.RecoverableBlocker) as caught:
            steward.add_memory(self.root, payload)

        self.assertEqual(caught.exception.code, "MANAGED_STATE_CONFLICT")
        self.assertEqual(
            caught.exception.paths, (".oppen-project-steward/Memory/index.md",)
        )
        self.assertEqual(index.read_bytes(), before)
        self.assertFalse(
            (self.root / ".oppen-project-steward/Memory/entries/M-0002.md").exists()
        )
        self.assertTrue(payload.exists())

    def test_index_is_idempotent_with_dirty_but_current_helper_outputs(self) -> None:
        self.init_empty()
        self.commit_all()
        steward.add_memory(
            self.root, self.payload(self.memory_payload("Bound worker concurrency"))
        )
        before = (self.root / ".oppen-project-steward/Memory/index.md").read_bytes()
        steward.refresh_index(self.root)
        self.assertEqual(
            (self.root / ".oppen-project-steward/Memory/index.md").read_bytes(), before
        )

    def test_audit_promotion_ignores_git_dirty_current_stage(self) -> None:
        self.init_empty()
        current = self.write(
            ".oppen-project-steward/Audit/Runs/build/current/accepted.json", "{}\n"
        )
        self.commit_all()
        current.write_text('{"user": "changed"}\n', encoding="utf-8")
        baseline = self.root / steward.STEWARD_NAMESPACE / steward.MANAGED_STATE_NAME
        baseline_before = baseline.read_bytes()
        staging = self.temp_root / "replacement-audit"
        staging.mkdir()
        (staging / "replacement.json").write_text("{}\n", encoding="utf-8")

        promoted = steward.promote_audit(self.root, "build", staging)

        self.assertEqual(promoted, current.parent.resolve())
        self.assertFalse(current.exists())
        self.assertEqual((promoted / "replacement.json").read_text(), "{}\n")
        self.assertEqual(baseline.read_bytes(), baseline_before)
        self.assertFalse(staging.exists())

    def test_runtime_instructions_harden_memory_and_attention_boundaries(self) -> None:
        text = SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "Technical difficulty alone does not justify Decision Memory", text
        )
        self.assertIn("concurrency, reliability, performance policy", text)
        self.assertIn("An incident alone is Audit, logs, or Git", text)
        self.assertIn("Noteworthy does not mean Attention", text)
        self.assertIn("Known pending work is not Attention", text)
        self.assertIn("Attention is not a TODO system", text)

    def test_active_project_end_to_end_recovery_and_dirty_work(self) -> None:
        self.copy_fixture("active-ai-service")
        steward.register_canonical(
            self.root,
            "request-routing",
            "canonical/request-routing.md",
            None,
            "tests/verify_request_routing.py",
            replace=False,
        )
        steward.register_deliverable(
            self.root,
            "operator-guide",
            "Deliverables/operator-guide.md",
            "operator-guide",
            "service-operators",
            "src/router.py",
            replace=False,
        )
        steward.add_memory(
            self.root,
            self.payload(self.memory_payload("Adopt approval-queue routing")),
        )
        steward.raise_attention(
            self.root,
            self.payload(self.attention_payload("External integration bypass")),
        )
        self.commit_all()

        source = self.root / "src/router.py"
        source.write_text(
            source.read_text(encoding="utf-8") + "\n# active user change\n",
            encoding="utf-8",
        )
        note = self.write("notes/current-work.md", "Untracked current design work.\n")
        before_source = source.read_bytes()
        before_note = note.read_bytes()
        current = (
            self.root / ".oppen-project-steward/Audit/Runs/runtime/current/summary.json"
        )
        before_current = current.read_bytes()

        self.assertEqual(
            steward.validate_project(self.root).status, "BLOCKED_RECOVERABLE"
        )
        recovery = steward.recover_audit(self.root, "runtime")
        self.assertTrue((recovery / "recovery-manifest.json").is_file())
        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")

        steward.add_memory(
            self.root,
            self.payload(
                self.memory_payload("Limit retry concurrency after saturation")
            ),
        )
        steward.raise_attention(
            self.root,
            self.payload(self.attention_payload("Deployment approval ambiguity")),
        )
        steward.refresh_index(self.root)
        report = steward.validate_project(self.root)

        self.assertEqual(report.status, "MANAGED_READY")
        self.assertEqual(source.read_bytes(), before_source)
        self.assertEqual(note.read_bytes(), before_note)
        self.assertEqual(current.read_bytes(), before_current)
        self.assertFalse((self.root / ".oppen-project-steward/Audit/failed").exists())
        self.assertFalse(
            (self.root / ".oppen-project-steward/Audit/quarantine").exists()
        )
        self.assertEqual(
            {
                path.name
                for path in (
                    self.root / ".oppen-project-steward/Memory/entries"
                ).iterdir()
            },
            {"M-0001.md", "M-0002.md"},
        )
        self.assertEqual(
            {
                path.name
                for path in (
                    self.root / ".oppen-project-steward/Attention/entries"
                ).iterdir()
            },
            {"A-0001.md", "A-0002.md"},
        )


if __name__ == "__main__":
    unittest.main()
