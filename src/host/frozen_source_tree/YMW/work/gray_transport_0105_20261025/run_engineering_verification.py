"""Verify the new engineering operator on loopback and its offline preparation."""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import engineering_transport_check as check


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, ENGINEERING_CHECK_TEST_OUTPUT=str(out / 'cases'))
    started = time.monotonic()
    with (out / 'unittest.txt').open('w', encoding='utf-8') as log:
        result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-m', 'unittest', '-v',
                                 'test_engineering_transport_check'], cwd=check.HERE, env=env,
                                stdout=log, stderr=subprocess.STDOUT, timeout=180)
    text = (out / 'unittest.txt').read_text(encoding='utf-8')
    match = re.search(r'Ran (\d+) tests?', text)
    tests = int(match[1]) if match else 0
    require = check.require
    require(result.returncode == 0 and tests == 8, 'Engineering operator tests failed; inspect unittest.txt')
    with patch.object(socket, 'socket', side_effect=AssertionError('Offline prepare must not create a socket')):
        plan = check.Runtime().prepare()
        require(plan['maximum_capture_requests'] == 2 and plan['training_data'] is False,
                'Engineering scope changed')
        import operator_host
        production, _, _ = operator_host.Runtime('C:/BX72_0105_LAB').candidate()
        require(production['ready'] is False, 'Production capture gate must remain blocked')
    sources = [Path(check.__file__), check.HERE / 'review_board_handshake.py',
               check.HERE / 'test_engineering_transport_check.py', Path(__file__)]
    receipt = dict(status='PASS', tests=tests, evidence_source='software_udp_peer_only',
                   physical_captures=0, real_board_contacted=False, production_gate_still_blocked=True,
                   no_socket_real_plan_preflight=True, runtime_s=round(time.monotonic()-started,3),
                   source_sha256={p.name:check.sdk.support.sha_file(p) for p in sources},
                   SDK_source_sha256=check.sdk.SOURCE_SNAPSHOT,
                   test_log_sha256=check.sdk.support.sha_file(out / 'unittest.txt'))
    (out / 'verification.json').write_bytes((json.dumps(receipt, indent=2)+'\n').encode('utf-8'))
    print(json.dumps(receipt, indent=2))
