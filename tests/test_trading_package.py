import hashlib
import json
import unittest
import tempfile
from pathlib import Path

from unexpected_runtime.skills import SkillRegistry
from unexpected_runtime.coordinator import Coordinator
from unexpected_runtime.providers import DeterministicMockProvider

ROOT = Path(__file__).resolve().parents[1]


class TradingPackageTests(unittest.TestCase):
    def setUp(self):
        self.trading_root = ROOT / 'trading'
        self.source_manifest_path = self.trading_root / 'UPSTREAM_NOTICES' / 'SOURCE_MANIFEST.json'
        self.source_manifest = json.loads(self.source_manifest_path.read_text(encoding='utf-8'))

    def test_upstream_source_is_pinned_and_all_eleven_capabilities_are_inventoried(self):
        manifest = self.source_manifest
        self.assertEqual(manifest['upstream_repository'], 'https://github.com/Jakeschincariol/day-trader-skill')
        self.assertEqual(manifest['upstream_version'], '2.0.0')
        self.assertEqual(manifest['upstream_commit'], '3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd')
        self.assertEqual(manifest['license'], 'MIT')
        self.assertEqual(len(manifest['entries']), 11)
        names = [item['capability'] for item in manifest['entries']]
        self.assertEqual(len(names), len(set(names)))
        for item in manifest['entries']:
            self.assertRegex(item['skill_git_blob_sha'], r'^[0-9a-f]{40}$')
            self.assertRegex(item['tool_git_blob_sha'], r'^[0-9a-f]{40}$')
            self.assertTrue(item['skill_path'].endswith('/SKILL.md'))
            self.assertTrue(item['tool_path'].endswith('.py'))
            self.assertIs(item['copied_into_this_release'], False)

    def test_mit_license_notice_is_present(self):
        license_path = self.trading_root / 'UPSTREAM_NOTICES' / 'LICENSE'
        license_text = license_path.read_text(encoding='utf-8')
        self.assertIn('MIT License', license_text)
        self.assertIn('Copyright (c) 2026 Jake Schincariol', license_text)
        self.assertIn('Permission is hereby granted, free of charge', license_text)
        self.assertIn('THE SOFTWARE IS PROVIDED "AS IS"', license_text)

    def test_paper_config_fixes_non_execution_and_requires_user_risk_inputs(self):
        config = json.loads((self.trading_root / 'config' / 'paper.example.json').read_text(encoding='utf-8'))
        self.assertEqual(config['mode'], 'paper')
        self.assertIs(config['broker_connection'], False)
        self.assertIs(config['live_order_execution'], False)
        self.assertIs(config['paper_order_simulation'], True)
        self.assertIs(config['background_polling'], False)
        for key in ('allow_options', 'allow_crypto', 'allow_margin', 'allow_leverage', 'allow_short'):
            self.assertIs(config[key], False, key)
        for key in ('account_budget_usd', 'max_loss_per_trade_usd', 'max_daily_loss_usd',
                    'max_position_pct', 'max_trades_per_day'):
            self.assertIsNone(config[key], key)
        self.assertEqual(config['market_data_provider'], 'fixture')
        self.assertIs(config['journal_writes_enabled_by_default'], False)
        self.assertEqual(config['storage_mode_default'], 'ephemeral')

    def test_readme_does_not_claim_the_upstream_tools_are_installed_or_executable(self):
        readme = (self.trading_root / 'README.md').read_text(encoding='utf-8').lower()
        self.assertIn('not copied, installed, executed or exposed as tools', readme)
        self.assertIn('not a python execution engine', readme)
        self.assertIn('no live or paper broker connector', readme)

    def test_workflow_content_hash_matches_registry_record(self):
        manifest = json.loads((ROOT / 'skill_manifest.json').read_text(encoding='utf-8'))
        skill = next(item for item in manifest['skills'] if item['id'] == 'trading-ops')
        content = (ROOT / skill['path']).read_bytes()
        self.assertEqual(hashlib.sha256(content).hexdigest(), skill['sha256'])
        self.assertEqual(skill['version'], '0.2.0')
        self.assertEqual(set(skill['agent_ids']), {'orchestrator', 'investment-research', 'data-analyst'})
        self.assertNotIn('permissions', skill)

    def test_workflow_explicitly_states_safety_and_all_eleven_capabilities(self):
        workflow = (ROOT / 'skills' / 'trading-ops' / 'WORKFLOW.md').read_text(encoding='utf-8').lower()
        for phrase in ('never place, modify, cancel or close an order',
                       'no options, crypto, margin, leverage or short selling',
                       'no unattended trading', 'paper_proposal', 'simulated_fill', 'simulated_pnl',
                       'market scanner', 'news and filings monitor', 'entry analysis', 'exit planning',
                       'historical simulation', 'risk review', 'position sizing', 'price and level alerts',
                       'company and earnings research', 'public disclosure tracker', 'paper journal'):
            self.assertIn(phrase, workflow)

    def test_workflow_profile_does_not_create_a_canonical_agent_or_grant_trade_permission(self):
        profile = (ROOT / 'workflow_profiles' / 'trading-ops.md').read_text(encoding='utf-8').lower()
        self.assertIn('not a new canonical agent', profile)
        self.assertIn('cannot authorize or invoke `trade`', profile)
        self.assertIn('no new role ids', profile)


class TradingSkillIntegrationTests(unittest.TestCase):
    def test_trading_skill_resolves_only_for_intended_roles_and_triggers(self):
        registry = SkillRegistry.load(ROOT / 'skill_manifest.json', ROOT)
        cases = (
            ('investment-research', 'Scan the US stock market for paper trading setups'),
            ('data-analyst', 'Calculate trading position sizing and run a backtest'),
            ('orchestrator', 'Prepare a paper trade journal'),
        )
        for agent_id, objective in cases:
            selected = registry.resolve(agent_id, objective)
            self.assertIsNotNone(selected, (agent_id, objective))
            self.assertEqual(selected.id, 'trading-ops')
            self.assertIn('PAPER_ONLY', registry.read_context(selected))
        overlap = registry.resolve('orchestrator', 'Benchmark a trading strategy using a historical backtest')
        self.assertIsNotNone(overlap)
        self.assertEqual(overlap.id, 'trading-ops')
        self.assertIsNone(registry.resolve('maintenance-engineer', 'Scan the stock market for a trading setup'))
        self.assertIsNone(registry.resolve('investment-research', 'Prepare a routine maintenance report'))
        self.assertIsNone(registry.resolve('data-analyst', 'Create a short video thumbnail'))

    def test_coordinator_attaches_verified_trading_context_only_for_matching_objectives(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = DeterministicMockProvider()
            coordinator = Coordinator(manifest_path=ROOT / 'agent_manifest.json', state_dir=tmp,
                                       provider=provider, skill_manifest_path=ROOT / 'skill_manifest.json')
            try:
                coordinator.invoke('investment-research', 'Scan the US stock market for paper trading setups')
                attached = provider.requests[-1]['system_prompt']
                self.assertIn('uneXpected Trading Operations', attached)
                self.assertIn('PAPER_ONLY', attached)
                coordinator.invoke('investment-research', 'Prepare a routine maintenance report')
                unrelated = provider.requests[-1]['system_prompt']
                self.assertNotIn('uneXpected Trading Operations', unrelated)
            finally:
                coordinator.close()

    def test_trading_skill_maps_only_to_existing_canonical_roles(self):
        registry = SkillRegistry.load(ROOT / 'skill_manifest.json', ROOT)
        spec = next(skill for skill in registry.list() if skill.id == 'trading-ops')
        agent_manifest = json.loads((ROOT / 'agent_manifest.json').read_text(encoding='utf-8'))
        canonical_ids = {agent['id'] for agent in agent_manifest['agents']}
        self.assertLessEqual(set(spec.agent_ids), canonical_ids)
        self.assertEqual(set(spec.agent_ids), {'orchestrator', 'investment-research', 'data-analyst'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
