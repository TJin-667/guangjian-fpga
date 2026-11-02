import json,os,socket,unittest
from pathlib import Path
from unittest.mock import patch
import gray_acquisition_workflow as workflow
import operator_host as host
import board_probe
from test_operator_host import FixtureRuntime
from test_sdk_transport import LocalSocket
from software_transport_peer import make_peer

class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.Peer,cls.engine=make_peer();cls.core=board_probe.core_module()
    def setUp(self):
        self.root=Path(os.environ['GRAY_WORKFLOW_TEST_OUTPUT'])/('case'+self._testMethodName.split('_')[1]);self.root.mkdir()
        self.patcher=patch.object(socket,'socket',LocalSocket);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.peer=self.Peer(self.engine.root/'ymw');self.peer.__enter__();self.addCleanup(lambda:self.peer.__exit__(None,None,None))
        self.runtime=FixtureRuntime(self.root,self.core,self.peer,self.engine);self.runtime.bridge_sensor_size=(96,32)
        self.plan=host.build_plan(self.runtime,low=400,high=800,physical_specimen_id='software_plate',pose_id='software_pose',
            pair_status='development_trial',pair_reference='software only, no actual exposure choice')[0]
    def run_workflow(self,**kw):
        return workflow.execute(self.plan,out=self.root/'workflow',confirmed_same_pose=True,
            _runtime=self.runtime,single_timeout_s=3,**kw)
    def test_01_capture_to_export_complete(self):
        result=self.run_workflow()
        self.assertEqual(result['status'],'GRAY_INPUTS_READY_FOR_REVIEW');self.assertEqual(len(self.peer.captured),8)
        self.assertTrue((self.root/'workflow/acquisition.zip').is_file())
        self.assertTrue((self.root/'workflow/model_inputs/group.json').is_file())
        self.assertTrue(result['acquisition_result']['summary']['lights_off']['acknowledged'])
        self.assertFalse(result['automatic_recapture']);self.assertFalse(result['release_ready'])
    def test_02_fifth_capture_failure_never_exports(self):
        start=self.peer._start_capture
        def fail(*args):
            if len(self.peer.captured)==4:self.peer.fault='payload_corrupt'
            return start(*args)
        self.peer._start_capture=fail
        result=self.run_workflow();self.assertEqual(result['status'],'CAPTURE_INCOMPLETE_NO_EXPORT')
        self.assertEqual(len(self.peer.captured),5);self.assertFalse((self.root/'workflow/model_inputs').exists())
        self.assertEqual(result['acquisition_result']['summary']['saved_observations'],4)
    def test_03_export_error_preserves_eight_and_does_not_recapture(self):
        def fail(*args,**kwargs):raise OSError('injected export failure')
        result=self.run_workflow(_exporter=fail)
        self.assertEqual(result['status'],'EXPORT_FAILED_CAPTURE_PRESERVED');self.assertEqual(len(self.peer.captured),8)
        self.assertTrue((self.root/'workflow/acquisition.zip').is_file())
        self.assertTrue(result['acquisition_result']['summary']['lights_off']['acknowledged'])
    def test_04_current_production_gate_blocks_before_socket(self):
        # Use the actual candidate gate with an explicit software pose fixture.
        # This isolates release policy from unrelated historical02/03 freshness.
        self.runtime.candidate=lambda:host.Runtime.candidate(self.runtime)
        with patch.object(socket,'socket',side_effect=AssertionError('No real socket')):
            plan=host.build_plan(self.runtime,low=400,high=800,physical_specimen_id='software_plate',pose_id='software_pose',
                pair_status='development_trial',pair_reference='offline candidate gate test, explicit software pose')[0]
            result=workflow.execute(plan,out=self.root/'blocked',confirmed_same_pose=True,_runtime=self.runtime)
        self.assertEqual(result['status'],'BLOCKED_OR_FAILED');self.assertEqual(result['phase'],'preflight')
        self.assertFalse((self.root/'blocked/acquisition').exists())
