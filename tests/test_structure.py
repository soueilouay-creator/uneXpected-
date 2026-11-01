import csv, json, re, unittest, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REQUIRED=['skill_manifest.json','workflow_profiles/creative-media-studio.md','workflow_profiles/skill-engineering.md','skills/creative-media/WORKFLOW.md','skills/skill-engineering/SKILL.md','unexpected_runtime/skills.py','unexpected_runtime/capabilities.py','unexpected_runtime/approvals.py','tests/test_skills.py','tests/test_capabilities.py','tests/test_approvals.py','agent_manifest.json','AGENT_CATALOG.md','AGENT_CATALOG.csv','AGENT_CATALOG.json','ALL_AGENTS.md','MIGRATION_CROSSWALK_V6_TO_V7.md','MIGRATION_CROSSWALK_V6_TO_V7.csv','MIGRATION_CROSSWALK_V6_TO_V7.json','CORE_ROUTER.md','EXISTING_37_CROSSWALK.md','CAPABILITY_MATRIX.md','SOURCE_MANIFEST.md','GLOBAL_CUSTOM_INSTRUCTION_V7.md','PROJECT_INSTRUCTIONS_V7.md','ARCHITECTURE.md','THREAT_MODEL.md','INSTALL.md','DEPLOY.md','UPGRADE_MIGRATION.md','ROLLBACK_UNINSTALL.md','EVALS.md','TEST_RESULTS.md','PACKAGE_STATUS.md','INSTALL_TESTS_STATUS.md','self_improvement/SKILL.md','self_improvement/EVAL_PROTOCOL.md','tests/scenarios.json','unexpected_runtime/benchmark.py','tests/test_runtime.py','tests/test_structure.py','docs/specs/2026-11-01-trading-intelligence-design.md','docs/plans/2026-11-01-trading-intelligence-implementation-plan.md','skills/trading-ops/WORKFLOW.md','workflow_profiles/trading-ops.md','trading/README.md','trading/UPSTREAM_NOTICES/LICENSE','trading/UPSTREAM_NOTICES/SOURCE_MANIFEST.json','trading/config/paper.example.json','tests/test_trading_package.py','tests/test_trading_engine.py','unexpected_runtime/trading_api.py','trading_engine/__init__.py','trading_engine/models.py','trading_engine/data.py','trading_engine/risk.py','trading_engine/scanner.py','trading_engine/backtest.py','trading_engine/portfolio.py','trading_engine/service.py','docs/specs/2026-11-01-trading-engine-v0.2.0.md','docs/plans/2026-11-01-trading-engine-v0.2.0-implementation-plan.md']
class StructureTests(unittest.TestCase):
 def test_required_files_exist_nonempty(self):
  for rel in REQUIRED:
   p=ROOT/rel; self.assertTrue(p.is_file(),rel); self.assertGreater(p.stat().st_size,0,rel)
 def test_release_version_is_consistent(self):
  d=json.loads((ROOT/'agent_manifest.json').read_text())
  self.assertEqual(d['ecosystem_version'],'7.3.1')
  self.assertIn("__version__ = '7.3.1'",(ROOT/'unexpected_runtime/__init__.py').read_text())
 def test_manifest_ids_and_specs_unique(self):
  d=json.loads((ROOT/'agent_manifest.json').read_text()); agents=d['agents']; ids=[a['id'] for a in agents]
  self.assertEqual(len(agents),38); self.assertEqual(len(ids),len(set(ids)))
  for a in agents:
   p=ROOT/'agents'/f"{a['id']}.md"; self.assertTrue(p.exists(),a['id'])
   self.assertTrue(a['objective'] and a['instruction'] and a['acceptance_tests'],a['id'])
   for key in ('inputs','outputs','allowed_permissions','runtime_capabilities','memory_namespace','handoff_rules','security_limits','provenance'):
    self.assertIn(key,a,a['id'])
 def test_catalog_formats_agree(self):
  d=json.loads((ROOT/'AGENT_CATALOG.json').read_text()); m=json.loads((ROOT/'agent_manifest.json').read_text())['agents']
  self.assertEqual([x['id'] for x in d],[x['id'] for x in m])
  with (ROOT/'AGENT_CATALOG.csv').open() as f: rows=list(csv.DictReader(f))
  self.assertEqual([x['id'] for x in rows],[x['id'] for x in m])
  md=(ROOT/'AGENT_CATALOG.md').read_text()
  for a in m: self.assertIn('`'+a['id']+'`',md)
  cross=json.loads((ROOT/'MIGRATION_CROSSWALK_V6_TO_V7.json').read_text())
  with (ROOT/'MIGRATION_CROSSWALK_V6_TO_V7.csv').open() as f: cross_csv=list(csv.DictReader(f))
  self.assertEqual([x['workflow_id'] for x in cross],[x['workflow_id'] for x in cross_csv])
  cross_md=(ROOT/'MIGRATION_CROSSWALK_V6_TO_V7.md').read_text()
  for item in cross: self.assertIn('`'+item['workflow_id']+'`',cross_md)
 def test_120_v6_workflows_all_mapped(self):
  d=json.loads((ROOT/'MIGRATION_CROSSWALK_V6_TO_V7.json').read_text())
  self.assertEqual(len(d),120); self.assertEqual(len({x['workflow_id'] for x in d}),120); self.assertEqual(len({x['source_path'] for x in d}),120)
  ids=set(json.loads((ROOT/'agent_manifest.json').read_text())['agents'][i]['id'] for i in range(38))
  for w in d:
   self.assertTrue(w['source_url'].startswith('https://github.com/Shubhamsaboo/awesome-llm-apps/tree/'))
   self.assertIn('/tree/6c16b23f1bacd0fdf240bb5141ef45e59e82c306/',w['source_url'])
   self.assertTrue(w['source_url'].endswith('/'+w['source_path']))
   self.assertTrue(w['required_inputs'],w['workflow_id']); self.assertTrue(w['procedure_steps'],w['workflow_id']); self.assertTrue(w['acceptance_checks'],w['workflow_id'])
   self.assertTrue(w['safety_boundary'],w['workflow_id']); self.assertTrue(w['external_dependencies'],w['workflow_id'])
   self.assertIn(w['primary_agent_id'],ids); self.assertEqual(w['disposition'],'merged-as-workflow-capability-not-separate-agent')
 def test_all_37_legacy_profiles_crosswalked(self):
  d=json.loads((ROOT/'EXISTING_37_CROSSWALK.json').read_text()); self.assertEqual(len(d),37)
  self.assertEqual(len({x['legacy_path'] for x in d}),37); self.assertTrue(all(x['disposition']=='kept' for x in d))
 def test_upstream_inventory_is_fresh_and_exact(self):
  s=(ROOT/'SOURCE_MANIFEST.md').read_text()
  for token in ('2026-10-28T16:43:00Z','6c16b23f1bacd0fdf240bb5141ef45e59e82c306','dfa79289f46826b4b63946e3a13540c9a4c3ea12','Apache-2.0','2,541','1,984','557','224','120 linked candidate'):
   self.assertIn(token,s)
 def test_no_false_runtime_activation_claims(self):
  for rel in ('README.md','PACKAGE_STATUS.md','CAPABILITY_MATRIX.md','PROJECT_INSTRUCTIONS_V7.md','GLOBAL_CUSTOM_INSTRUCTION_V7.md'):
   s=(ROOT/rel).read_text().lower()
   self.assertNotIn('all agents are running',s)
   self.assertNotIn('always-on service is active',s)
  cap=(ROOT/'CAPABILITY_MATRIX.md').read_text().lower(); self.assertIn('not configured',cap); self.assertIn('not wired into this runtime',cap)

 def test_workflow_skills_are_hash_pinned_and_do_not_create_roles(self):
  import hashlib
  skills=json.loads((ROOT/'skill_manifest.json').read_text())['skills']
  manifest=json.loads((ROOT/'agent_manifest.json').read_text())['agents']
  ids={a['id'] for a in manifest}
  self.assertEqual(len(ids),38)
  self.assertEqual({s['id'] for s in skills},{'creative-media','skill-engineering','self-improvement','trading-ops'})
  for skill in skills:
   self.assertTrue(set(skill['agent_ids']).issubset(ids),skill['id'])
   path=(ROOT/skill['path']).resolve(); path.relative_to(ROOT.resolve())
   self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),skill['sha256'],skill['id'])
  self.assertFalse((ROOT/'agents/creative-media-studio.md').exists())
  self.assertFalse((ROOT/'agents/skill-engineering.md').exists())
 def test_required_sections_in_every_agent_spec(self):
  required=('Objective','Inputs','Outputs','Procedure','Allowed runtime capabilities','Expected deliverables','Acceptance tests','Handoff / escalation','Security limits','Governed self-development','Provenance')
  for p in (ROOT/'agents').glob('*.md'):
   text=p.read_text()
   for section in required: self.assertIn('## '+section,text,p.name)
 def test_scenarios_and_six_improvement_criteria(self):
  d=json.loads((ROOT/'tests/scenarios.json').read_text()); self.assertEqual(len(d['scenarios']),4); self.assertEqual(len(d['improvement_criteria']),6)
 def test_v6_zip_readable_and_catalog_count_if_supplied(self):
  # The v6 source archive is an optional external migration fixture, not a v7 package dependency.
  # When supplied, validate it; when absent, the v7 crosswalk tests remain authoritative.
  import os
  configured=os.environ.get('UNEXPECTED_V6_FIXTURE')
  candidates=[Path(configured)] if configured else [ROOT.parent/'uneXpected_v6_complete.zip', Path('/mnt/data/uneXpected_v6_complete.zip')]
  v6=next((p for p in candidates if p.is_file()), None)
  if v6 is None:
   self.skipTest('Optional v6 source archive not supplied; v7 crosswalk is tested independently')
  with zipfile.ZipFile(v6) as z:
   self.assertIsNone(z.testzip()); self.assertGreaterEqual(len(z.namelist()),140)
 def test_individual_agent_count_matches_catalog(self):
  self.assertEqual(len(list((ROOT/'agents').glob('*.md'))),38)
 def test_file_inventory_sha256(self):
  import hashlib
  inv=ROOT/'FILE_INVENTORY_SHA256.txt'; self.assertTrue(inv.is_file())
  expected={}
  for line in inv.read_text().splitlines():
   if line.strip() and not line.startswith('#'):
    digest,rel=line.split('  ',1); expected[rel]=digest
  actual={str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and p!=inv and '.git' not in p.parts and '__pycache__' not in p.parts and 'state' not in p.parts and p.suffix not in {'.pyc','.sqlite3'}}
  self.assertEqual(set(expected),actual)
  for rel,digest in expected.items(): self.assertEqual(hashlib.sha256((ROOT/rel).read_bytes()).hexdigest(),digest,rel)
 def test_consolidated_agent_index_covers_all_specs(self):
  manifest=json.loads((ROOT/'agent_manifest.json').read_text())
  index=(ROOT/'ALL_AGENTS.md').read_text()
  for agent in manifest['agents']:
   self.assertIn('`'+agent['id']+'`',index)
   self.assertIn('agents/'+agent['id']+'.md',index)
 def test_v7_package_integrity(self):
  package=Path(__import__('os').environ.get('UNEXPECTED_PACKAGE_ZIP',ROOT.parent/'uneXpected_v7.3.1_governed_runtime.zip'))
  self.assertTrue(package.is_file(),str(package))
  with zipfile.ZipFile(package) as z:
   self.assertIsNone(z.testzip()); names=z.namelist(); self.assertGreater(len(names),70)
   self.assertIn('uneXpected_v7/agent_manifest.json',names); self.assertIn('uneXpected_v7/unexpected_runtime/coordinator.py',names)
if __name__=='__main__': unittest.main(verbosity=2)
