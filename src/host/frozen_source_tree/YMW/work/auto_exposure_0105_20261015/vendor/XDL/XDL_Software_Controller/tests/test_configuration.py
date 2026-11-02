"""Configuration and read-only algorithm boundary contracts."""
from pathlib import Path
from dataclasses import asdict, replace
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

try:
    from acquisition_control import ControllerConfig, Cost
except ModuleNotFoundError as error:
    if error.name != 'acquisition_control':
        raise
    ControllerConfig = Cost = None

try:
    from capture_metrics import load_algorithm, preservation_snapshot
except ModuleNotFoundError as error:
    if error.name != 'capture_metrics':
        raise
    load_algorithm = preservation_snapshot = None

ROOT = Path(__file__).resolve().parents[1]
ALGORITHM = ROOT.parent / 'XDL_Algorithm' / 'software'
HISTORY = ROOT.parent / 'XDL_Results' / '2026-10-13_manual_exposure_gain'


class ConfigurationTests(unittest.TestCase):
    def test_default_values_exact(self):
        # A missing configuration interface, wrong fixed settings, or unsupported
        # initial exposure must fail before a request can be constructed.
        self.assertIsNotNone(ControllerConfig, 'ControllerConfig interface not implemented')
        cfg = ControllerConfig()
        cfg.validate()
        self.assertEqual(cfg.exposures, (400, 500, 600, 700))
        self.assertEqual((cfg.initial_exposure_lines, cfg.gain16, cfg.led), (600, 16, 128))
        self.assertEqual(asdict(cfg), {
            'rule_version': 'controller-0.1', 'threshold_status': 'provisional',
            'cost_status': 'modeled', 'channel': 1, 'led': 128, 'gain16': 16,
            'exposures': (400, 500, 600, 700), 'initial_exposure_lines': 600,
            'min_area': 10000, 'min_coverage_bp': 9500, 'min_effective_bp': 9000,
            'max_dark_bp': 1000, 'max_near_white_bp': 100, 'rgb_warn_bp': 500,
            'rgb_review_bp': 1000, 'confirmations': 2, 'max_mean_delta_gray': 2,
            'max_effective_delta_bp': 200, 'max_rgb_delta_bp': 50,
            'max_attempts': 8, 'max_frames': 32, 'max_time_ms': 40000,
            'discard_frames_per_request': 3, 'frame_time_ms': 1000,
            'settle_time_ms': 1000, 'retry_limit': 1,
        })
        self.assertEqual(cfg.request_cost, Cost(1, 4, 5000))
        with self.assertRaises(ValueError):
            ControllerConfig.from_dict({'initial_exposure_lines': 450})

    def test_reject_unknown_key_bool_nan_bad_exposure(self):
        # Malformed values must not silently become valid settings or integers.
        self.assertIsNotNone(ControllerConfig, 'ControllerConfig interface not implemented')
        invalid = [None, [], {'hardware_enabled': False}, {'max_attempts': True},
                   {'min_effective_bp': float('nan')}, {'initial_exposure_lines': 450},
                   {'initial_exposure_lines': 600.0}, {'exposures': [400, 600]},
                   {'exposures': [400, 500, True, 700]}, {'channel': 2}, {'led': 129},
                   {'gain16': 32}, {'min_area': 0}, {'max_dark_bp': -1},
                   {'max_near_white_bp': 10001}, {'rgb_warn_bp': 1200, 'rgb_review_bp': 1000},
                   {'rule_version': ''}, {'threshold_status': 'final'},
                   {'cost_status': 'measured'}, {'confirmations': 1},
                   {'max_attempts': 9}, {'max_frames': 33}, {'max_time_ms': 40001},
                   {'retry_limit': 2}, {'min_area': 9999}, {'min_coverage_bp': 9499},
                   {'frame_time_ms': 0}, {'settle_time_ms': -1}]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                ControllerConfig.from_dict(payload)
        with self.assertRaises(ValueError):
            replace(ControllerConfig(), gain16=True).validate()
        for name in ('min_effective_bp', 'max_dark_bp', 'max_attempts', 'frame_time_ms'):
            for value in (False, 1.0, float('inf'), '1', None):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    ControllerConfig.from_dict({name: value})

    def test_request_cost_exact(self):
        # Cost must include discarded frames and settling, without float math.
        self.assertIsNotNone(ControllerConfig, 'ControllerConfig interface not implemented')
        self.assertEqual(ControllerConfig().request_cost, Cost(1, 4, 5000))
        cfg = ControllerConfig.from_dict({'frame_time_ms': 800, 'settle_time_ms': 600})
        self.assertEqual(cfg.request_cost, Cost(1, 4, 3800))
        self.assertEqual(ControllerConfig.from_dict({'settle_time_ms': 0}).request_cost, Cost(1, 4, 4000))
        for payload in [(True, 4, 5000), (1, -1, 5000), (1, 4, float('nan'))]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                Cost(*payload)

    def test_config_file_round_trip(self):
        # JSON lists should normalize to immutable exposure tuples and validate.
        self.assertIsNotNone(ControllerConfig, 'ControllerConfig interface not implemented')
        self.assertTrue((ROOT / 'config.json').is_file(), 'config.json not implemented')
        payload = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'),
                             parse_constant=lambda value: self.fail(f'nonfinite JSON: {value}'))
        cfg = ControllerConfig.from_dict(payload)
        self.assertEqual(asdict(cfg), asdict(ControllerConfig()))
        self.assertEqual(set(payload), set(asdict(cfg)))
        self.assertEqual(ControllerConfig.from_dict({'initial_exposure_lines': 400}).initial_exposure_lines, 400)

    def test_reject_changed_source(self):
        # A one-byte source change must refuse loading, including on later calls.
        self.assertIsNotNone(load_algorithm, 'load_algorithm interface not implemented')
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            # Short-lived verification fixture; never imported or used as a core.
            shutil.copytree(ALGORITHM / 'light_inspection', fixture / 'light_inspection',
                            ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copy2(ALGORITHM / 'ymw_integer_reference.py', fixture)
            relative_paths = [f'light_inspection/{name}' for name in (
                '__init__.py', 'cli.py', 'core.py', 'image_io.py', 'metadata.py',
                'real_baseline.py', 'reports.py')] + ['ymw_integer_reference.py']
            for relative in relative_paths:
                path = fixture / relative
                original = path.read_bytes()
                path.write_bytes(original + b'\n# changed fixture\n')
                with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, 'SHA256'):
                    load_algorithm(fixture, HISTORY)
                path.write_bytes(original)

    def test_missing_algorithm_has_clear_error(self):
        # Missing files must identify which external algorithm path is required.
        self.assertIsNotNone(load_algorithm, 'load_algorithm interface not implemented')
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'Missing.*light_inspection'):
                load_algorithm(Path(temporary), HISTORY)
            with self.assertRaisesRegex(ValueError, 'Missing.*integrity.json'):
                load_algorithm(ALGORITHM, Path(temporary))

    def test_snapshot_is_read_only(self):
        # Snapshot must hash bytes, preserve source timestamps, and write nothing.
        self.assertIsNotNone(preservation_snapshot, 'preservation_snapshot interface not implemented')
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / 'source.bin'
            fixture.write_bytes(b'abc')
            before = (fixture.read_bytes(), fixture.stat().st_mtime_ns,
                      sorted(path.name for path in fixture.parent.iterdir()))
            self.assertEqual(preservation_snapshot([fixture]), {
                str(fixture.resolve()): 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'})
            after = (fixture.read_bytes(), fixture.stat().st_mtime_ns,
                     sorted(path.name for path in fixture.parent.iterdir()))
            self.assertEqual(before, after)

    def test_load_algorithm_external_functions(self):
        # Bridge must use verified original functions with strict integer thresholds.
        self.assertIsNotNone(load_algorithm, 'load_algorithm interface not implemented')
        import numpy as np
        functions = load_algorithm(ALGORITHM, HISTORY)
        self.assertEqual(set(functions), {'integer_gray', 'integer_h2', 'integer_thresholds',
                                         'board_mask', 'assess_quality', 'hysteresis_connect'})
        weak, strong = functions['integer_thresholds'](np.array([-1621, -1620, 648, 649]))
        self.assertEqual(weak.tolist(), [True, True, False, True])
        self.assertEqual(strong.tolist(), [True, False, False, False])
        gray = functions['integer_gray'](np.array([[[0, 0, 255]]], dtype=np.uint8))
        self.assertEqual(gray.tolist(), [[76]])
        h2 = functions['integer_h2'](np.full((9, 9), 50, dtype=np.uint8))
        self.assertTrue((h2['sum9'] == 4050).all())
        self.assertTrue((h2['residual_n'] == 0).all())
        board = functions['board_mask']((32, 32), [(0, 0), (31, 0), (31, 31), (0, 31)], (0, 0))
        self.assertEqual(int(board.sum()), 576)
        quality = functions['assess_quality'](np.full((16, 16), 50, dtype=np.uint8))
        self.assertEqual(quality['status'], 'valid')
        connected = functions['hysteresis_connect'](np.array([[0, 9, 21]]),
                                                    np.ones((1, 3), dtype=bool), 8, 20)
        self.assertEqual(connected['mask'].tolist(), [[False, True, True]])
        for function in functions.values():
            self.assertTrue(Path(function.__code__.co_filename).resolve().is_relative_to(ALGORITHM.resolve()))

    def test_loading_does_not_modify_sources_or_search_path(self):
        # Explicit loading must not write pycache or depend on PYTHONPATH/cwd.
        self.assertIsNotNone(load_algorithm, 'load_algorithm interface not implemented')
        paths = list((ALGORITHM / 'light_inspection').glob('*.py')) + [ALGORITHM / 'ymw_integer_reference.py']
        before = preservation_snapshot(paths)
        before_tree = {str(path.relative_to(ALGORITHM)): (path.stat().st_size, path.stat().st_mtime_ns)
                       for path in ALGORITHM.rglob('*') if path.is_file()}
        search_path = list(sys.path)
        load_algorithm(ALGORITHM, HISTORY)
        self.assertEqual(sys.path, search_path)
        self.assertEqual(preservation_snapshot(paths), before)
        after_tree = {str(path.relative_to(ALGORITHM)): (path.stat().st_size, path.stat().st_mtime_ns)
                      for path in ALGORITHM.rglob('*') if path.is_file()}
        self.assertEqual(after_tree, before_tree)

    def test_runner_from_unrelated_directory(self):
        # Runner must find the suite without installing or changing PYTHONPATH.
        self.assertTrue((ROOT / 'run_tests.py').is_file(), 'run_tests.py not implemented')
        environment = dict(os.environ, XDL_TEST_RUNNER_CHILD='1')
        environment.pop('PYTHONPATH', None)
        if os.environ.get('XDL_TEST_RUNNER_CHILD'):
            return
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, '-B', str(ROOT / 'run_tests.py'), '--pattern', 'test_configuration.py'],
                                    cwd=temporary, env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('OK', result.stderr)
        self.assertFalse(json.loads(result.stdout.splitlines()[-1])['acceptance_complete'])


if __name__ == '__main__':
    unittest.main()
