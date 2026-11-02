import json
from pathlib import Path
import tempfile
import unittest

from multiobs.contracts import CaptureRequest, Limits, Stop
from multiobs.ports import CaptureFailure
from multiobs.runner import ScriptedPolicy, run
from tests.fixtures import Clock, FakePort, context, identity, reidentify


SCENARIOS = json.loads(Path(__file__).with_name('golden_actions.json').read_bytes())['scenarios']


class GoldenTests(unittest.TestCase):
    pass


def make_test(scenario):
    def test(self):
        def bad(p):
            p.record['camera_readback']['gain16'] = 32
            return p
        behaviors = {'bad_readback': bad, 'timeout': CaptureFailure('IMAGE_TIMEOUT'),
                     'reuse_first': lambda p: reidentify(p, identity(1))}
        clock = Clock()
        port = FakePort(clock, [behaviors[k] for k in scenario['faults']])
        actions = [CaptureRequest('golden_'+str(i), ch, exposure, role, 'injected decision from fixed golden')
                   for i, (ch, exposure, role) in enumerate(scenario['actions'])]
        actions.append(Stop(*scenario['stop']))
        with tempfile.TemporaryDirectory() as temporary:
            report = run(context(), Limits(scenario.get('max_attempts', 12), 60, 20, 1),
                         ScriptedPolicy(actions), lambda: port, Path(temporary) / 'out', clock=clock)
            self.assertEqual([[c['channel'], c['exposure_lines']] for c in port.calls], scenario['expected_requests'])
            self.assertEqual(report['status'], scenario['expected_status'])
            self.assertEqual(len(report['observations']), scenario['expected_accepted'])
            self.assertEqual(report['budget']['reserved_transaction_frames'], scenario['expected_reserved_frames'])
            self.assertTrue(port.off_called and port.closed)
    return test


for scenario in SCENARIOS:
    setattr(GoldenTests, 'test_' + scenario['name'], make_test(scenario))
