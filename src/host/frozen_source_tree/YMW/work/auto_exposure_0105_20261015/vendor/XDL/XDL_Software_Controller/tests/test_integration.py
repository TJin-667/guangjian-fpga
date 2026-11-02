"""Acceptance catches falsely complete evidence and exercises the real offline CLI."""
import json
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime

import replay


class AcceptanceContractTests(unittest.TestCase):
    def test_numerical_evidence_without_preservation_is_incomplete(self):
        # Removing source/history proof must never retain a full acceptance pass.
        evidence = {key: {'passed': True, 'checked': count} for key, count in {
            'source_integrity': 10, 'scalar_statistics': 10, 'native_reference': 10,
            'decision_reference': 147, 'constructed_actions': 42, 'golden_inventory': 15,
            'repeat_stability': 6, 'sensitivity_actions': 27}.items()}
        evidence['golden_inventory'].update(transitions=42, expected_rejections=4)
        result = replay.verification_status(evidence)
        self.assertFalse(result['offline_verified'])
        self.assertFalse(result['source_unchanged'])
        self.assertFalse(result['historical_results_unchanged'])

    def test_missing_item_evidence_cannot_pass_preservation(self):
        evidence = {'source_preservation': {'passed': True, 'checked': 9},
                    'historical_preservation': {'passed': True, 'checked': 7}}
        result = replay.verification_status(evidence)
        self.assertFalse(result['source_unchanged'])
        self.assertFalse(result['historical_results_unchanged'])

    def test_preservation_detects_changed_deleted_and_added_files(self):
        before = {kind: [{'path': 'fixture', 'bytes': 1, 'sha256': 'a'*64,
                          'expected_sha256': 'a'*64}] for kind in ('source', 'historical', 'input')}
        for change in ('changed', 'deleted', 'added'):
            after = copy.deepcopy(before)
            if change == 'changed': after['source'][0]['sha256'] = 'b'*64
            elif change == 'deleted': after['source'] = []
            else: after['source'].append({'path': 'extra', 'bytes': 1, 'sha256': 'a'*64})
            with self.subTest(change=change):
                self.assertFalse(replay.preservation_checks(before, after)['source_preservation']['passed'])

    def test_modified_trust_anchor_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'baseline.json'
            path.write_text('[]', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'trust anchor'):
                replay.read_trusted_json(path, replay.PRESERVATION_BASELINE_SHA256)


class RealIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Paths are explicitly supplied by run_tests.py; direct discovery can skip,
        # and the acceptance runner reports every skip as incomplete/nonzero.
        text = os.environ.get('XDL_CONTROLLER_ACCEPTANCE_PATHS')
        if not text:
            raise unittest.SkipTest('real acceptance paths were not supplied')
        cls.paths = json.loads(text)
        absent = [str(p) for p in cls.paths.values() if not Path(p).exists()]
        if absent:
            raise unittest.SkipTest('real acceptance material missing: ' + ', '.join(absent))
        result_root = replay.BASE / 'XDL_Results'
        day = datetime.now().strftime('%Y-%m-%d')
        cls.output = next(result_root / f'{day}_software_controller_{n:02d}'
                          for n in range(3, 100) if not (result_root / f'{day}_software_controller_{n:02d}').exists())
        args = [sys.executable, '-B', str(Path(__file__).with_name('offline_probe.py'))]
        for key, value in cls.paths.items():
            args.extend(['--' + key.replace('_', '-'), value])
        args.extend(['--output', str(cls.output)])
        with tempfile.TemporaryDirectory() as folder:
            cls.cli = subprocess.run(args, cwd=folder, capture_output=True, text=True, timeout=240)
        if cls.cli.returncode:
            raise AssertionError(f'full CLI exit {cls.cli.returncode}\n{cls.cli.stdout}\n{cls.cli.stderr}')
        cls.probe = json.loads(cls.cli.stdout.strip().splitlines()[-1])
        cls.verification = cls.load('verification')
        cls.metrics = cls.load('frame_metrics')
        print('REAL_ACCEPTANCE_OUTPUT=' + str(cls.output))
        print(cls.cli.stdout.strip())

    @classmethod
    def load(cls, stem):
        return json.loads((cls.output / (stem + '.json')).read_text(encoding='utf-8'))

    def test_cli_help_and_clean_cwd(self):
        entry = Path(__file__).resolve().parents[1] / 'replay.py'
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, '-B', str(entry), '--help'], cwd=folder,
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('--algorithm-root', result.stdout)
        self.assertIn('--repeat-root', result.stdout)
        self.assertEqual(self.cli.returncode, 0)

    def test_full_scan_reference_counts_match(self):
        rows = [r for r in self.metrics if r['frame']['context_id'] == 'scan_A']
        self.assertEqual([r['frame']['exposure_lines'] for r in rows], [400, 500, 600, 700])
        self.assertEqual([r['metrics']['n'] for r in rows], [602230]*4)
        self.assertEqual([r['metrics']['rgb_max_count'] for r in rows], [25027, 51422, 76027, 98497])
        self.assertTrue(all(r['native_verification']['passed'] and r['scalar_verification']['passed'] for r in rows))
        self.assertTrue(all(len(r['native_verification']['pinned']['comparisons']) == 15 for r in rows))

    def test_repeat_6_frames_completed(self):
        rows = [r for r in self.metrics if r['frame']['context_id'].startswith('repeat_')]
        self.assertEqual(len(rows), 6)
        self.assertEqual([r['metrics']['rgb_max_count'] for r in rows], [62055, 61531, 61640, 41562, 41253, 41250])
        pairs = self.load('repeat_stability')
        self.assertEqual([(r['context_id'], len(r['pairs'])) for r in pairs], [('repeat_001', 3), ('repeat_002', 3)])
        self.assertTrue(all(r['status'] == 'available' for r in pairs))

    def test_preservation_hashes_equal(self):
        self.assertTrue(self.verification['offline_verified'])
        self.assertTrue(self.verification['source_unchanged'])
        self.assertTrue(self.verification['historical_results_unchanged'])
        for kind in ('source', 'historical', 'input'):
            check = self.verification['evidence'][kind + '_preservation']
            self.assertTrue(check['passed'])
            self.assertEqual(check['checked'], len(check['comparisons']))
            self.assertTrue(all(r['unchanged'] for r in check['comparisons']))
            self.assertTrue(all(r['before_sha256'] == r['after_sha256'] for r in check['comparisons']))

    def test_commands_do_not_touch_hardware(self):
        self.assertEqual(self.probe['forbidden_operations'], [])
        self.assertGreater(self.probe['output_write_count'], 0)
        self.assertTrue(all(Path(p).is_relative_to(self.output) for p in self.probe['write_paths']))
        self.assertTrue(self.verification['hardware_validation_pending'])
        self.assertFalse(self.verification['physical_freshness_validation'])
        self.assertIsNone(self.load('provenance')['measured_live_control_cost'])
        self.assertTrue(all(r['measured_live_control_cost'] is None for r in self.load('decisions')))

    def test_every_golden_action_independently_matches(self):
        from fpga_reference import verify_reference
        records = self.load('golden_actions')['cases']
        self.assertEqual(len(records), 147)
        cases = [r['input'] for r in records]
        expected = [r['expected'] for r in records]
        self.assertTrue(verify_reference(cases, expected)['passed'])
        # Corruption of an exported answer must be detected by independent recomputation.
        altered = copy.deepcopy(expected)
        altered[0]['decision']['next_exposure_lines'] = 700
        self.assertFalse(verify_reference(cases, altered)['passed'])
        self.assertEqual(self.verification['evidence']['constructed_actions']['checked'], 42)
        self.assertEqual(self.verification['evidence']['golden_inventory']['expected_rejections'], 4)

    def test_costs_and_real_missing_data_stops(self):
        summaries = self.load('summary')
        self.assertEqual([r['final_decision']['status'] for r in summaries], ['NEEDS_REVIEW']*3)
        self.assertEqual(summaries[0]['final_decision']['reason_codes'],
                         ['missing_fresh_confirmation', 'unfulfilled_modeled_request'])
        self.assertEqual([len(r['consumed_observation_ids']) for r in summaries], [3, 1, 1])
        for row in self.load('decisions'):
            budget = row['decision']['budget']
            for axis in ('attempts', 'frames', 'time_ms'):
                self.assertEqual(budget['requested_cost'][axis], sum(budget[k][axis]
                    for k in ('consumed_cost', 'reserved_cost', 'unfulfilled_cost')))
        for summary, attempts in zip(summaries, (4, 2, 2)):
            self.assertEqual(summary['modeled_control_cost']['requested_cost'],
                             {'attempts': attempts, 'frames': 4*attempts, 'time_ms': 5000*attempts})


if __name__ == '__main__':
    unittest.main()
