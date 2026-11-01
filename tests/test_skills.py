import hashlib
import importlib.util
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unexpected_runtime.skills import SkillRegistry, SkillRegistryError
from unexpected_runtime.coordinator import Coordinator
from unexpected_runtime.providers import DeterministicMockProvider

ROOT = Path(__file__).resolve().parents[1]


class SkillRegistryTests(unittest.TestCase):
    def _fixture(self, root: Path, *, relative='skills/demo.md', content='# Verified demo skill\n',
                 sha_override=None):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        digest = sha_override or hashlib.sha256(content.encode()).hexdigest()
        manifest = {
            'schema_version': 1,
            'skills': [{
                'id': 'demo-skill', 'version': '1.0.0', 'path': relative,
                'sha256': digest, 'agent_ids': ['media-producer'],
                'trigger_terms': ['video', 'shorts'], 'source_ref': 'fixture:approved-skill',
                'status': 'active'
            }]
        }
        manifest_path = root / 'skill_manifest.json'
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        return manifest_path

    def test_matching_mapped_role_resolves_and_reads_hash_verified_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = SkillRegistry.load(self._fixture(root), root)
            selected = registry.resolve('media-producer', 'Create a video with captions')
            self.assertIsNotNone(selected)
            self.assertEqual(selected.id, 'demo-skill')
            self.assertIn('Verified demo skill', registry.read_context(selected))

    def test_nonmatching_objective_and_unmapped_role_do_not_attach_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = SkillRegistry.load(self._fixture(root), root)
            self.assertIsNone(registry.resolve('media-producer', 'Prepare a maintenance report'))
            self.assertIsNone(registry.resolve('coding-engineer', 'Create a video'))

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'package'
            root.mkdir()
            with self.assertRaises(SkillRegistryError):
                SkillRegistry.load(self._fixture(root, relative='../escape.md'), root)
            self.assertTrue((Path(tmp) / 'escape.md').is_file())

    def test_unreadable_skill_file_is_wrapped_as_registry_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = SkillRegistry.load(self._fixture(root), root)
            selected = registry.list()[0]
            with patch.object(Path, 'read_bytes', side_effect=OSError('file disappeared')):
                with self.assertRaises(SkillRegistryError):
                    registry.read_context(selected)

    def test_non_utf8_skill_source_is_wrapped_as_registry_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'skills' / 'binary.md'
            target.parent.mkdir(parents=True)
            payload = b'\xff\xfe\xfa'
            target.write_bytes(payload)
            manifest = {
                'schema_version': 1,
                'skills': [{
                    'id': 'binary-skill', 'version': '1.0.0', 'path': 'skills/binary.md',
                    'sha256': hashlib.sha256(payload).hexdigest(), 'agent_ids': ['media-producer'],
                    'trigger_terms': ['video'], 'source_ref': 'fixture:binary', 'status': 'active',
                }],
            }
            path = root / 'skill_manifest.json'
            path.write_text(json.dumps(manifest), encoding='utf-8')
            registry = SkillRegistry.load(path, root)
            with self.assertRaises(SkillRegistryError):
                registry.read_context(registry.list()[0])

    def test_skill_context_reads_verified_bytes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = SkillRegistry.load(self._fixture(root), root)
            selected = registry.list()[0]
            original = Path.read_bytes
            with patch.object(Path, 'read_bytes', autospec=True,
                              side_effect=lambda path: original(path)) as read_bytes:
                value = registry.read_context(selected)
            self.assertIn('Verified demo skill', value)
            self.assertEqual(read_bytes.call_count, 1)

    def test_modified_skill_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(SkillRegistryError):
                SkillRegistry.load(self._fixture(root, sha_override='0' * 64), root)

    def test_missing_skill_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self._fixture(root)
            (root / 'skills/demo.md').unlink()
            with self.assertRaises(SkillRegistryError):
                SkillRegistry.load(manifest, root)

    def test_packaged_manifest_preserves_canonical_role_count(self):
        registry = SkillRegistry.load(ROOT / 'skill_manifest.json', ROOT)
        ids = [entry['id'] for entry in json.loads((ROOT / 'agent_manifest.json').read_text())['agents']]
        self.assertEqual(len(ids), 38)
        self.assertEqual(len(set(ids)), 38)
        self.assertIsNotNone(registry.resolve('voice-agent', 'Produce a voiceover for a video'))
        self.assertIsNotNone(registry.resolve('coding-engineer', 'Create a reusable agent skill'))
        self.assertIsNotNone(registry.resolve('coding-engineer', 'Design a specialist profile'))
        self.assertIsNotNone(registry.resolve('self-improvement-governor', 'Run a benchmark for a self-improvement proposal'))
        self.assertIsNone(registry.resolve('creative-media-studio', 'Create a video'))

    def test_coordinator_exposes_the_skill_manifest_injection_seam(self):
        self.assertIn('skill_manifest_path', inspect.signature(Coordinator).parameters)

    def test_coordinator_attaches_matching_skill_context_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = DeterministicMockProvider()
            coordinator = Coordinator(manifest_path=ROOT / 'agent_manifest.json', state_dir=tmp,
                                       provider=provider, skill_manifest_path=ROOT / 'skill_manifest.json')
            try:
                coordinator.invoke('voice-agent', 'Create a video voiceover with clear narration')
                system_prompt = provider.requests[-1]['system_prompt']
                self.assertIn('Creative Media Studio', system_prompt)
                coordinator.invoke('voice-agent', 'Explain routine maintenance principles')
                system_prompt = provider.requests[-1]['system_prompt']
                self.assertNotIn('Creative Media Studio', system_prompt)
                events = coordinator.store.events(100)
                self.assertIn('skill_context_attached', {e['event_type'] for e in events})
            finally:
                coordinator.close()


    def test_excel_skill_resolves_only_for_mapped_existing_roles(self):
        registry = SkillRegistry.load(ROOT / 'skill_manifest.json', ROOT)
        for role in ('orchestrator', 'data-analyst', 'automation-architect', 'coding-engineer'):
            selected = registry.resolve(role, 'Inspect this Excel workbook and validate spreadsheet formulas')
            self.assertIsNotNone(selected, role)
            self.assertEqual(selected.id, 'excel-engineering')
        self.assertIsNone(registry.resolve('self-improvement-governor', 'Inspect this Excel workbook'))

    def test_coordinator_injects_excel_skill_only_for_excel_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = DeterministicMockProvider()
            coordinator = Coordinator(manifest_path=ROOT / 'agent_manifest.json', state_dir=tmp,
                                       provider=provider, skill_manifest_path=ROOT / 'skill_manifest.json')
            try:
                coordinator.invoke('data-analyst', 'Inspect this Excel workbook and identify data-quality issues')
                self.assertIn('Excel Engineering Skill', provider.requests[-1]['system_prompt'])
                coordinator.invoke('data-analyst', 'Summarize this market research brief')
                self.assertNotIn('Excel Engineering Skill', provider.requests[-1]['system_prompt'])
                events = coordinator.store.events(100)
                self.assertIn('excel-engineering', {json.loads(e['payload_json']).get('skill_id') for e in events if e['event_type'] == 'skill_context_attached'})
            finally:
                coordinator.close()

    def test_skill_module_is_visible_to_runtime(self):
        self.assertIsNotNone(importlib.util.find_spec('unexpected_runtime.skills'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
