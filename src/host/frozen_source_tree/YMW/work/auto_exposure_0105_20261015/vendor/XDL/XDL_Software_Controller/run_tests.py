"""Run the complete local suite from any working directory, without installation."""
from pathlib import Path
import argparse
import json
import os
import sys
import unittest


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parent
    base = root.parent
    audit = base / 'XDL_Results/2026-10-13_software_controller_build'
    parser = argparse.ArgumentParser(description=__doc__)
    defaults = {'algorithm_root': base/'XDL_Algorithm/software',
                'scan_root': base/'YMW/YMW_manual_20261013',
                'expected_results': base/'XDL_Results/2026-10-13_manual_exposure_gain',
                'reference_root': base/'XDL_Results/2026-10-13_integer_reference_01',
                'repeat_root': base/'YMW/ch1_repeat_defect_near_normal_20261013',
                'regions': root/'repeat_regions.json', 'config': root/'config.json',
                'preservation_baseline': audit/'preservation_before.json',
                'repeat_receipt': audit/'repeat_download_receipt.json'}
    for key, value in defaults.items():
        parser.add_argument('--' + key.replace('_', '-'), type=Path, default=value)
    parser.add_argument('--pattern', default='test*.py', help='focused diagnostic discovery; not full acceptance')
    args = parser.parse_args()
    os.environ['XDL_CONTROLLER_ACCEPTANCE_PATHS'] = json.dumps({key: str(getattr(args, key).resolve()) for key in defaults})
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern=args.pattern)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    complete = result.wasSuccessful() and not result.skipped and args.pattern == 'test*.py'
    print(json.dumps({'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
                      'skipped': [{'test': str(test), 'reason': reason} for test, reason in result.skipped],
                      'acceptance_complete': complete, 'scope': 'full' if args.pattern == 'test*.py' else 'focused diagnostic'},
                     ensure_ascii=False, allow_nan=False))
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
