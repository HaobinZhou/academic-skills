from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "oppen_project_steward.py"
SPEC = importlib.util.spec_from_file_location(
    "oppen_project_steward_stage2", SCRIPT_PATH
)
assert SPEC and SPEC.loader
steward = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = steward
SPEC.loader.exec_module(steward)


class Stage2AttentionMemoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temp_dir.name)
        self.root = self.temp_root / "project"
        steward.ensure_v3_project(self.root, create=True)
        steward.refresh_index(self.root)
        self.payload_number = 0

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def payload(self, data: dict[str, object]) -> Path:
        self.payload_number += 1
        path = self.temp_root / f"payload-{self.payload_number}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def attention_payload(
        self, title: str = "Unresolved permission boundary"
    ) -> dict[str, object]:
        return {
            "title": title,
            "blocking": False,
            "observation": "The fallback path bypasses the documented permission boundary.",
            "evidence": "src/permissions.py:42 permits the fallback without an identity check.",
            "why_it_matters": "A future release decision could expose unauthorized data.",
            "why_no_action_was_taken": "Changing authorization behavior is outside this task.",
            "human_decision_needed": "Decide whether fallback access should be removed.",
        }

    def memory_payload(
        self,
        title: str = "Keep explicit permission checks",
        *,
        related_topics: list[str] | None = None,
        supersedes: list[str] | None = None,
        invalidates: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "title": title,
            "related_topics": [] if related_topics is None else related_topics,
            "supersedes": [] if supersedes is None else supersedes,
            "invalidates": [] if invalidates is None else invalidates,
            "before": "The project favored implicit permission inheritance.",
            "trigger": "Production behavior showed inherited access was ambiguous.",
            "decision": "Require explicit permission checks at every boundary.",
            "why": "Explicit checks make authorization behavior inspectable and stable.",
            "rejected_or_prior_approach": "Implicit inheritance was rejected after the observed ambiguity.",
            "consequence": "New boundaries must declare and test their permission behavior.",
        }

    def add_memory(self, **kwargs: object) -> Path:
        payload = self.memory_payload(**kwargs)
        return steward.add_memory(self.root, self.payload(payload))

    def test_attention_first_and_sequential_id_allocation(self) -> None:
        first = steward.raise_attention(
            self.root, self.payload(self.attention_payload("First issue"))
        )
        second = steward.raise_attention(
            self.root, self.payload(self.attention_payload("Second issue"))
        )
        self.assertEqual(first.name, "A-0001.md")
        self.assertEqual(second.name, "A-0002.md")
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_attention_resolution_preserves_high_water_and_regenerates_index(
        self,
    ) -> None:
        first = steward.raise_attention(
            self.root, self.payload(self.attention_payload("Issue to resolve"))
        )
        steward.resolve_attention(self.root, "A-0001")
        self.assertFalse(first.exists())
        steward.refresh_index(self.root)
        index = (self.root / ".oppen-project-steward/Attention/index.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("Issue to resolve", index)
        self.assertIn("attention-high-water:0001", index)

        second = steward.raise_attention(
            self.root, self.payload(self.attention_payload("Later issue"))
        )
        self.assertEqual(second.name, "A-0002.md")
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_attention_creation_consumes_payload_and_uses_fixed_schema(self) -> None:
        payload = self.payload(self.attention_payload())
        entry = steward.raise_attention(self.root, payload)
        self.assertFalse(payload.exists())
        metadata, body = steward.parse_structured_frontmatter(entry)
        self.assertEqual(tuple(metadata), steward.ATTENTION_METADATA_FIELDS)
        for section in steward.ATTENTION_SECTIONS:
            self.assertIn(f"## {section}", body)
        self.assertIn(
            "| A-0001 | Unresolved permission boundary | false |",
            (self.root / ".oppen-project-steward/Attention/index.md").read_text(
                encoding="utf-8"
            ),
        )

    def test_attention_rejects_invalid_schema_and_blocking_value(self) -> None:
        incomplete = self.attention_payload()
        incomplete.pop("evidence")
        with self.assertRaisesRegex(steward.ProjectError, "payload schema"):
            steward.raise_attention(self.root, self.payload(incomplete))

        invalid = self.attention_payload()
        invalid["blocking"] = "false"
        with self.assertRaisesRegex(steward.ProjectError, "JSON boolean"):
            steward.raise_attention(self.root, self.payload(invalid))

    def test_attention_rejects_obvious_active_duplicate(self) -> None:
        steward.raise_attention(
            self.root, self.payload(self.attention_payload("Permission boundary"))
        )
        with self.assertRaisesRegex(steward.ProjectError, "same normalized title"):
            steward.raise_attention(
                self.root,
                self.payload(self.attention_payload("  permission   BOUNDARY ")),
            )

    def test_attention_invalid_alternative_topology_fails_validation(self) -> None:
        steward.raise_attention(self.root, self.payload(self.attention_payload()))
        (self.root / ".oppen-project-steward/Attention/resolved").mkdir()
        report = steward.validate_project(self.root)
        self.assertTrue(any("alternative topology" in error for error in report.errors))

    def test_attention_index_drift_is_detected_and_index_repairs_it(self) -> None:
        steward.raise_attention(self.root, self.payload(self.attention_payload()))
        index_path = self.root / ".oppen-project-steward/Attention/index.md"
        index_path.write_text("# stale\n", encoding="utf-8")
        report = steward.validate_project(self.root)
        self.assertTrue(any("Attention/index.md" in error for error in report.errors))
        index_path.write_text(steward.render_attention_index([], 1), encoding="utf-8")
        steward.refresh_index(self.root)
        self.assertIn("A-0001", index_path.read_text(encoding="utf-8"))
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_concurrent_attention_allocation_never_reuses_id(self) -> None:
        payloads = [
            self.payload(self.attention_payload("Concurrent issue one")),
            self.payload(self.attention_payload("Concurrent issue two")),
        ]
        with ThreadPoolExecutor(max_workers=2) as executor:
            paths = list(
                executor.map(
                    lambda path: steward.raise_attention(self.root, path), payloads
                )
            )
        self.assertEqual({path.name for path in paths}, {"A-0001.md", "A-0002.md"})
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_memory_first_sequential_ids_and_empty_related_topics(self) -> None:
        first = self.add_memory(title="First decision")
        second = self.add_memory(title="Second decision")
        self.assertEqual(first.name, "M-0001.md")
        self.assertEqual(second.name, "M-0002.md")
        first_entry = steward.parse_memory_entry(first)
        self.assertEqual(first_entry.related_topics, ())
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_memory_creation_consumes_payload_and_does_not_require_canonical(
        self,
    ) -> None:
        payload = self.payload(
            self.memory_payload(related_topics=["authentication-contract"])
        )
        entry_path = steward.add_memory(self.root, payload)
        self.assertFalse(payload.exists())
        entry = steward.parse_memory_entry(entry_path)
        self.assertEqual(entry.related_topics, ("authentication-contract",))
        self.assertEqual(entry.status, "active")
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_memory_supersedes_updates_status_and_reverse_link(self) -> None:
        first = self.add_memory(title="Use inherited permissions")
        second = self.add_memory(
            title="Use explicit permissions", supersedes=["M-0001"]
        )
        prior = steward.parse_memory_entry(first)
        current = steward.parse_memory_entry(second)
        self.assertEqual(prior.status, "superseded")
        self.assertEqual(prior.superseded_by, ("M-0002",))
        self.assertEqual(current.supersedes, ("M-0001",))
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_memory_invalidates_updates_status_and_reverse_link(self) -> None:
        first = self.add_memory(title="Assume stable provider identifiers")
        second = self.add_memory(
            title="Provider identifiers are unstable", invalidates=["M-0001"]
        )
        prior = steward.parse_memory_entry(first)
        current = steward.parse_memory_entry(second)
        self.assertEqual(prior.status, "invalidated")
        self.assertEqual(prior.invalidated_by, ("M-0002",))
        self.assertEqual(current.invalidates, ("M-0001",))
        self.assertTrue(steward.validate_project(self.root).ok)

    def test_memory_rejects_invalid_or_broken_relationship_ids(self) -> None:
        with self.assertRaisesRegex(steward.ProjectError, "invalid ID"):
            self.add_memory(supersedes=["M-12"])
        with self.assertRaisesRegex(steward.ProjectError, "missing ID"):
            self.add_memory(supersedes=["M-0009"])

    def test_memory_rejects_relationship_to_inactive_entry(self) -> None:
        self.add_memory(title="First direction")
        self.add_memory(title="Second direction", supersedes=["M-0001"])
        with self.assertRaisesRegex(steward.ProjectError, "active entries only"):
            self.add_memory(title="Third direction", invalidates=["M-0001"])

    def test_memory_invalid_status_and_schema_fail_validation(self) -> None:
        entry_path = self.add_memory()
        entry = steward.parse_memory_entry(entry_path)
        metadata = steward.memory_metadata(entry)
        metadata["status"] = "retired"
        steward.replace_structured_frontmatter(entry_path, metadata)
        report = steward.validate_project(self.root)
        self.assertTrue(any("invalid status" in error for error in report.errors))

        metadata["status"] = "active"
        metadata["unresolved_risk"] = "must not exist"
        steward.replace_structured_frontmatter(entry_path, metadata)
        report = steward.validate_project(self.root)
        self.assertTrue(any("invalid fixed schema" in error for error in report.errors))

    def test_memory_broken_reverse_reference_fails_validation(self) -> None:
        first = self.add_memory(title="Prior direction")
        self.add_memory(title="Current direction", supersedes=["M-0001"])
        prior = steward.parse_memory_entry(first)
        metadata = steward.memory_metadata(prior)
        metadata["superseded_by"] = []
        steward.replace_structured_frontmatter(first, metadata)
        steward.refresh_memory_index_unlocked(self.root)
        report = steward.validate_project(self.root)
        self.assertTrue(any("not mirrored" in error for error in report.errors))
        self.assertTrue(
            any("inconsistent reverse links" in error for error in report.errors)
        )

    def test_memory_index_regeneration_and_alternative_topology(self) -> None:
        self.add_memory(title="Indexed decision")
        index_path = self.root / ".oppen-project-steward/Memory/index.md"
        index_path.write_text(steward.render_memory_index([], 1), encoding="utf-8")
        report = steward.validate_project(self.root)
        self.assertTrue(
            any("does not exactly match" in error for error in report.errors)
        )
        steward.refresh_index(self.root)
        self.assertIn("Indexed decision", index_path.read_text(encoding="utf-8"))

        (self.root / ".oppen-project-steward/Memory/decisions.md").write_text(
            "# alternate\n", encoding="utf-8"
        )
        report = steward.validate_project(self.root)
        self.assertTrue(any("alternative topology" in error for error in report.errors))

    def test_memory_body_schema_validation(self) -> None:
        entry_path = self.add_memory()
        content = entry_path.read_text(encoding="utf-8")
        entry_path.write_text(
            content.replace("## Consequence", "## Outcome"), encoding="utf-8"
        )
        report = steward.validate_project(self.root)
        self.assertTrue(
            any("exactly these sections" in error for error in report.errors)
        )


if __name__ == "__main__":
    unittest.main()
