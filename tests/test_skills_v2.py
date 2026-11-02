import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from unexpected_runtime.skills import SkillRegistry, SkillRegistryError


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AdvancedSkillBundleTests(unittest.TestCase):
    def _write_skill(self, root: Path, skill_id: str, body: str, *,
                     invocation_mode: str = "automatic", trigger_terms=None,
                     allowed_tools=None, resources=None):
        directory = root / "skills" / skill_id
        directory.mkdir(parents=True, exist_ok=True)
        main_path = directory / "SKILL.md"
        main_path.write_text(body, encoding="utf-8")
        entry = {
            "id": skill_id,
            "version": "1.0.0",
            "path": main_path.relative_to(root).as_posix(),
            "sha256": digest(body),
            "agent_ids": ["maintenance-engineer"],
            "trigger_terms": list(trigger_terms or []),
            "source_ref": f"fixture:{skill_id}",
            "status": "active",
            "invocation_mode": invocation_mode,
            "description": f"Reviewed {skill_id} workflow",
            "allowed_tools": list(allowed_tools or []),
            "resources": [],
        }
        for kind, relative, payload in resources or []:
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")
            entry["resources"].append({
                "path": target.relative_to(root).as_posix(),
                "sha256": digest(payload),
                "kind": kind,
            })
        return entry

    def _manifest(self, root: Path, entries):
        path = root / "skill_manifest.json"
        path.write_text(json.dumps({"schema_version": 2, "skills": entries}), encoding="utf-8")
        return path

    def test_v2_modes_resolve_always_automatic_and_explicit_manual_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            always = self._write_skill(root, "always-skill", "# Always\n",
                                       invocation_mode="always_apply")
            automatic = self._write_skill(root, "auto-skill", "# Automatic\n",
                                          trigger_terms=["machine uptime"])
            manual = self._write_skill(root, "manual-skill", "# Manual\n",
                                       invocation_mode="user_invocable")
            registry = SkillRegistry.load(self._manifest(root, [always, automatic, manual]), root)

            resolved = registry.resolve_all("maintenance-engineer", "Improve machine uptime")
            self.assertEqual([item.id for item in resolved], ["always-skill", "auto-skill"])

            explicit = registry.resolve_all(
                "maintenance-engineer", "Improve machine uptime",
                requested_skill_ids=("manual-skill",),
            )
            self.assertEqual([item.id for item in explicit],
                             ["always-skill", "auto-skill", "manual-skill"])

    def test_manual_selection_cannot_bypass_role_scope_or_invocation_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            automatic = self._write_skill(root, "auto-skill", "# Auto\n",
                                          trigger_terms=["uptime"])
            registry = SkillRegistry.load(self._manifest(root, [automatic]), root)
            with self.assertRaises(SkillRegistryError):
                registry.resolve_all("maintenance-engineer", "uptime",
                                     requested_skill_ids=("auto-skill",))
            with self.assertRaises(SkillRegistryError):
                registry.resolve_all("coding-engineer", "uptime",
                                     requested_skill_ids=("auto-skill",))

    def test_bundle_loads_only_hash_verified_reference_text_and_never_scripts_or_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry = self._write_skill(
                root, "bundle-skill", "# Maintenance workflow\nUse the checklist.",
                invocation_mode="user_invocable",
                allowed_tools=["maintenance.read"],
                resources=[
                    ("reference", "references/checklist.md", "# Checklist\nCheck isolation."),
                    ("script", "scripts/verify.py", "raise RuntimeError('must never execute')"),
                    ("asset", "assets/diagram.svg", "<svg>asset bytes</svg>"),
                ],
            )
            registry = SkillRegistry.load(self._manifest(root, [entry]), root)
            skill = registry.resolve_all(
                "maintenance-engineer", "review",
                requested_skill_ids=("bundle-skill",),
            )[0]
            context = registry.read_context(skill)

            self.assertIn("Maintenance workflow", context)
            self.assertIn("Check isolation", context)
            self.assertNotIn("must never execute", context)
            self.assertNotIn("asset bytes", context)
            self.assertEqual(skill.allowed_tools, ("maintenance.read",))
            self.assertEqual({resource.kind for resource in skill.resources},
                             {"reference", "script", "asset"})

    def test_modified_reference_fails_closed_when_context_is_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry = self._write_skill(
                root, "bundle-skill", "# Main\n",
                resources=[("reference", "references/ref.md", "# Original\n")],
            )
            registry = SkillRegistry.load(self._manifest(root, [entry]), root)
            selected = registry.resolve_all("maintenance-engineer", "nothing")[0]
            ref_path = root / "skills/bundle-skill/references/ref.md"
            ref_path.write_text("# Tampered\n", encoding="utf-8")
            with self.assertRaises(SkillRegistryError):
                registry.read_context(selected)

    def test_resource_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry = self._write_skill(
                root, "bundle-skill", "# Main\n",
                resources=[("reference", "../../outside.md", "# Outside\n")],
            )
            manifest = self._manifest(root, [entry])
            with self.assertRaises(SkillRegistryError):
                SkillRegistry.load(manifest, root)

    def test_invalid_invocation_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entry = self._write_skill(root, "bad-skill", "# Main\n",
                                      invocation_mode="autonomous")
            with self.assertRaises(SkillRegistryError):
                SkillRegistry.load(self._manifest(root, [entry]), root)

    def test_legacy_v1_manifest_remains_automatic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            body = "# Legacy skill\n"
            target = root / "skills/legacy.md"
            target.parent.mkdir(parents=True)
            target.write_text(body, encoding="utf-8")
            manifest = root / "skill_manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 1,
                "skills": [{
                    "id": "legacy", "version": "1.0.0", "path": "skills/legacy.md",
                    "sha256": digest(body), "agent_ids": ["maintenance-engineer"],
                    "trigger_terms": ["uptime"], "source_ref": "fixture:legacy", "status": "active",
                }],
            }), encoding="utf-8")
            registry = SkillRegistry.load(manifest, root)
            self.assertEqual(registry.resolve_all("maintenance-engineer", "uptime")[0].invocation_mode,
                             "automatic")


if __name__ == "__main__":
    unittest.main(verbosity=2)
