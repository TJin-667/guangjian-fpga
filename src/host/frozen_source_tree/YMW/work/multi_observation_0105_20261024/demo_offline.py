"""Create a reviewable software_fake archive; cannot select a hardware port."""
import argparse
import json
from pathlib import Path
import socket
from unittest.mock import patch

from multiobs.contracts import CaptureRequest, Limits, Stop
from multiobs.ports import CaptureFailure
from multiobs.runner import ScriptedPolicy, run
from tests.fixtures import Clock, FakePort, context, identity, reidentify


if __name__ == '__main__':
    scenarios = json.loads((Path(__file__).parent / 'tests/golden_actions.json').read_bytes())['scenarios']
    choices = {s['name']: s for s in scenarios}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=choices, default='weak_segment_local_supplements')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    scenario = choices[args.scenario]
    def bad_readback(p):
        p.record['camera_readback']['gain16'] = 32
        return p
    behaviors = {'bad_readback': bad_readback, 'timeout': CaptureFailure('IMAGE_TIMEOUT'),
                 'reuse_first': lambda p: reidentify(p, identity(1))}
    clock = Clock()
    port = FakePort(clock, [behaviors[k] for k in scenario['faults']])
    actions = [CaptureRequest('golden_'+str(i), ch, exposure, role, 'injected offline decision')
               for i, (ch, exposure, role) in enumerate(scenario['actions'])]
    actions.append(Stop(*scenario['stop']))
    with patch.object(socket, 'socket', side_effect=AssertionError('Offline demonstration forbids sockets')):
        report = run(context(), Limits(scenario.get('max_attempts', 12), 60, 20, 1),
                     ScriptedPolicy(actions), lambda: port, args.out, clock=clock)
    print(json.dumps(dict(status=report['status'], execution_mode=report['execution_mode'],
                          observations=len(report['observations']), budget=report['budget'],
                          timing='injected fake clock, not measured hardware throughput'), indent=2))
