from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "oppen_project_steward.py"
SPEC = importlib.util.spec_from_file_location(
    "oppen_project_steward_stage4_2", SCRIPT_PATH
)
assert SPEC and SPEC.loader
steward = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = steward
SPEC.loader.exec_module(steward)


class Stage42AdoptionNamespaceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temporary.name)
        self.root = self.temp_root / "existing-project"
        self.root.mkdir()
        self.root = self.root.resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def payload(
        self,
        *,
        roles: dict[str, str] | None = None,
        canonical: list[dict[str, object]] | None = None,
        deliverables: list[dict[str, str]] | None = None,
        name: str = "adoption.json",
    ) -> Path:
        path = self.temp_root / name
        path.write_text(
            json.dumps(
                {
                    "role_mappings": roles or {},
                    "initial_canonical_registrations": canonical or [],
                    "initial_deliverable_registrations": deliverables or [],
                }
            ),
            encoding="utf-8",
        )
        return path

    def realistic_project(self) -> dict[str, bytes]:
        self.write("project.md", "# Product Contract\n\nThe editor preserves drafts.\n")
        self.write("src/editor.ts", "export const state = 'draft';\n")
        self.write("docs/architecture.md", "# Architecture\n")
        self.write("tests/verify_contract.py", "assert True\n")
        self.write("package.json", '{"name":"existing-product"}\n')
        self.write("README.md", "# Existing Product\n")
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_preflight_is_read_only_and_unmanaged_is_adoption_required(self) -> None:
        before = self.realistic_project()
        result = steward.adoption_preflight(self.root)

        self.assertEqual(result["status"], "ADOPTION_REQUIRED")
        self.assertEqual(result["steward_namespace"], ".oppen-project-steward/")
        self.assertEqual(result["adoption_write_set"], ".oppen-project-steward/**")
        self.assertEqual(result["full_project_materialization"], "NO")
        self.assertFalse((self.root / steward.STEWARD_NAMESPACE).exists())
        self.assertEqual(
            before,
            {
                path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob("*")
                if path.is_file()
            },
        )
        self.assertEqual(
            steward.validate_project(self.root).status, "ADOPTION_REQUIRED"
        )

    def test_adoption_preserves_dirty_project_and_registers_root_document(self) -> None:
        before = self.realistic_project()
        self.git("init", "-q")
        self.git("config", "user.email", "stage42@example.invalid")
        self.git("config", "user.name", "Stage 4.2 Test")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "existing project")
        self.write("src/editor.ts", "export const state = 'review';\n")
        self.write("project.md", "# Product Contract\n\nLocal contract revision.\n")
        self.write("new-notes.md", "Untracked notes.\n")
        before = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file() and ".git" not in path.parts
        }
        dirty_before = set(steward.git_dirty_paths(self.root))
        payload = self.payload(
            roles={"source": "src"},
            canonical=[
                {
                    "topic": "product-contract",
                    "path": "project.md",
                    "section": None,
                    "status": "frozen",
                    "verification": "tests/verify_contract.py",
                }
            ],
        )

        registry, action = steward.apply_adoption(self.root, payload)

        self.assertEqual(action, "ADOPTED")
        self.assertFalse(payload.exists())
        for relative, content in before.items():
            self.assertEqual((self.root / relative).read_bytes(), content)
        self.assertTrue(dirty_before.issubset(set(steward.git_dirty_paths(self.root))))
        registry_text = registry.read_text(encoding="utf-8")
        self.assertIn("| product-contract | project.md |", registry_text)
        self.assertNotIn(steward.SCHEMA_MARKER, (self.root / "project.md").read_text())
        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")

    def test_no_role_adoption_and_apply_are_idempotent(self) -> None:
        self.write("README.md", "# Tiny utility\n")
        payload = self.payload()
        registry, action = steward.apply_adoption(self.root, payload)
        before = {
            path.relative_to(
                self.root / steward.STEWARD_NAMESPACE
            ).as_posix(): path.read_bytes()
            for path in (self.root / steward.STEWARD_NAMESPACE).rglob("*")
            if path.is_file()
        }
        repeat = self.payload(name="repeat.json")

        same_registry, repeat_action = steward.apply_adoption(self.root, repeat)

        self.assertEqual(action, "ADOPTED")
        self.assertEqual(repeat_action, "ALREADY_MANAGED")
        self.assertEqual(registry, same_registry)
        self.assertFalse(repeat.exists())
        self.assertEqual(
            before,
            {
                path.relative_to(
                    self.root / steward.STEWARD_NAMESPACE
                ).as_posix(): path.read_bytes()
                for path in (self.root / steward.STEWARD_NAMESPACE).rglob("*")
                if path.is_file()
            },
        )
        self.assertFalse(
            any((self.root / name).exists() for name in ("Data", "Deliverables", "src"))
        )

    def test_namespace_conflict_blocks_without_mutation(self) -> None:
        conflict = self.write(
            ".oppen-project-steward/user-settings.json", '{"owner":"user"}\n'
        )
        before = conflict.read_bytes()
        result = steward.adoption_preflight(self.root)

        self.assertEqual(result["status"], "ADOPTION_BLOCKED")
        self.assertTrue(result["namespace_conflict"])
        self.assertEqual(result["blockers"][0]["code"], "NAMESPACE_CONFLICT")
        with self.assertRaisesRegex(steward.ProjectError, "NAMESPACE_CONFLICT"):
            steward.apply_adoption(self.root, self.payload())
        self.assertEqual(conflict.read_bytes(), before)

    def test_namespace_appearing_during_promotion_is_never_deleted(self) -> None:
        payload = self.payload()
        original_rename = Path.rename

        def conflict_before_rename(candidate: Path, target: Path) -> Path:
            target.mkdir()
            (target / "concurrent-user-file.txt").write_text(
                "concurrent user content\n", encoding="utf-8"
            )
            return original_rename(candidate, target)

        with mock.patch.object(Path, "rename", conflict_before_rename):
            with self.assertRaises(steward.ProjectError):
                steward.apply_adoption(self.root, payload)

        concurrent = self.root / steward.STEWARD_NAMESPACE / "concurrent-user-file.txt"
        self.assertEqual(
            concurrent.read_text(encoding="utf-8"), "concurrent user content\n"
        )
        self.assertTrue(payload.exists())

    def test_large_unrelated_artifact_is_not_scanned_or_materialized(self) -> None:
        huge = self.root / "models/huge-model.bin"
        huge.parent.mkdir()
        with huge.open("wb") as handle:
            handle.truncate(5 * 1024**4)
        before = huge.stat()

        with (
            mock.patch.object(steward.os, "link", wraps=steward.os.link) as link_spy,
            mock.patch.object(
                steward.shutil, "copytree", wraps=shutil.copytree
            ) as tree_spy,
        ):
            steward.apply_adoption(self.root, self.payload())

        link_spy.assert_not_called()
        tree_spy.assert_not_called()
        self.assertEqual(huge.stat().st_size, before.st_size)
        self.assertEqual(huge.stat().st_mtime_ns, before.st_mtime_ns)

    def test_cli_init_adopt_check_and_canonical_status(self) -> None:
        self.write("README.md", "# Existing\n")
        output = io.StringIO()
        with self.assertRaisesRegex(steward.ProjectError, "ADOPTION_REQUIRED"):
            steward.main(["init", str(self.root)])
        with contextlib.redirect_stdout(output):
            self.assertEqual(steward.main(["adopt", str(self.root), "--check"]), 0)
        self.assertIn('"status": "ADOPTION_REQUIRED"', output.getvalue())

        payload = self.payload()
        self.assertEqual(
            steward.main(["adopt", str(self.root), "--apply", "--input", str(payload)]),
            0,
        )
        self.write("contract.md", "# Contract without injected status\n")
        self.write("verify.py", "assert True\n")
        self.assertEqual(
            steward.main(
                [
                    "canonical",
                    str(self.root),
                    "--topic",
                    "contract",
                    "--path",
                    "contract.md",
                    "--status",
                    "frozen",
                    "--verification",
                    "verify.py",
                ]
            ),
            0,
        )
        self.assertNotIn("Status:", (self.root / "contract.md").read_text())

    def make_legacy_layout(self) -> dict[str, bytes]:
        self.write("src/app.py", "VALUE = 1\n")
        self.write("canonical/contract.md", "Status: frozen\n")
        self.write("tests/verify.py", "assert True\n")
        steward.ensure_v3_project(self.root, create=True)
        steward.refresh_index(self.root)
        steward.register_canonical(
            self.root,
            "contract",
            "canonical/contract.md",
            None,
            "tests/verify.py",
            replace=False,
        )
        namespace = self.root / steward.STEWARD_NAMESPACE
        registry_text = (namespace / steward.REGISTRY_NAME).read_text(encoding="utf-8")
        roles = steward.parse_role_mappings(self.root, registry_text)
        roles["Audit"] = self.root / "Audit"
        legacy_role_table = steward.markdown_table(
            ("Role", "Path", "Purpose"),
            [
                (
                    role,
                    path.relative_to(self.root).as_posix(),
                    steward.ROLE_DESCRIPTIONS.get(
                        role, "Machine verification evidence"
                    ),
                )
                for role, path in roles.items()
            ],
        )
        registry_text = steward.replace_block(
            registry_text,
            steward.ROLE_START,
            steward.ROLE_END,
            legacy_role_table,
            "role",
        )
        (self.root / "project.md").write_text(registry_text, encoding="utf-8")
        for name in ("Memory", "Attention", "Audit"):
            shutil.copytree(namespace / name, self.root / name)
        shutil.rmtree(namespace)
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in (self.root / "src").rglob("*")
            if path.is_file()
        }

    def test_proven_legacy_layout_upgrades_and_preserves_user_content(self) -> None:
        user_content = self.make_legacy_layout()
        report = steward.validate_project(self.root)
        self.assertEqual(report.status, "BLOCKED_RECOVERABLE")
        self.assertEqual(report.blockers[0].code, "LEGACY_STEWARD_LAYOUT")
        self.assertEqual(
            steward.legacy_layout_preflight(self.root)["status"],
            "LEGACY_STEWARD_LAYOUT",
        )

        registry, action = steward.apply_layout_upgrade(self.root)

        self.assertEqual(action, "UPGRADED")
        self.assertTrue(registry.is_file())
        self.assertFalse((self.root / "project.md").exists())
        self.assertFalse(
            any(
                (self.root / name).exists() for name in ("Memory", "Attention", "Audit")
            )
        )
        for relative, content in user_content.items():
            self.assertEqual((self.root / relative).read_bytes(), content)
        self.assertEqual(steward.validate_project(self.root).status, "MANAGED_READY")

    def test_legacy_upgrade_rolls_back_after_finalization_failure(self) -> None:
        self.make_legacy_layout()
        with mock.patch.object(
            steward,
            "refresh_index",
            side_effect=OSError("injected finalization failure"),
        ):
            with self.assertRaisesRegex(OSError, "injected finalization failure"):
                steward.apply_layout_upgrade(self.root)

        self.assertFalse((self.root / steward.STEWARD_NAMESPACE).exists())
        self.assertTrue((self.root / "project.md").is_file())
        self.assertTrue((self.root / "Memory/index.md").is_file())
        self.assertTrue((self.root / "Attention/index.md").is_file())
        self.assertTrue((self.root / "Audit/Runs").is_dir())

    def test_user_owned_root_names_are_not_mistaken_for_legacy(self) -> None:
        project = self.write(
            "project.md",
            "# User Contract\n\n<!-- oppen-project-steward:v3 -->\n",
        )
        for name in ("Memory", "Attention", "Audit"):
            self.write(f"{name}/user.txt", f"user-owned {name}\n")
        before = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file()
        }

        self.assertEqual(
            steward.validate_project(self.root).status, "ADOPTION_REQUIRED"
        )
        with self.assertRaisesRegex(steward.ProjectError, "not detected"):
            steward.legacy_layout_preflight(self.root)
        self.assertEqual(project.read_bytes(), before["project.md"])
        self.assertEqual(
            before,
            {
                path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob("*")
                if path.is_file()
            },
        )


if __name__ == "__main__":
    unittest.main()
