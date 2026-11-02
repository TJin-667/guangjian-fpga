"""Run only synthetic/fake-executor checks, with all socket creation prohibited."""
import argparse
import io
import json
from pathlib import Path
import socket
import sys
import time
import unittest
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    output = io.StringIO()
    started = time.monotonic()
    with patch.object(socket, 'socket', side_effect=AssertionError('Offline suite forbids all socket creation')):
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent / 'tests'), top_level_dir=str(Path(__file__).parent))
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    (args.out / 'unittest.txt').write_text(output.getvalue(), encoding='utf-8')
    report = dict(scope='software_fake only; no sockets, board commands, captures or hardware acceptance',
                  tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                  successful=result.wasSuccessful(), elapsed_s=time.monotonic()-started,
                  network_creation_forbidden=True, sdk_live_executed=False)
    (args.out / 'offline_tests.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(output.getvalue())
    print(json.dumps(report, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
