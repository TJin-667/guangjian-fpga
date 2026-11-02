"""Positioning/lifecycle tests use a labelled fake executor; no physical IO."""
from export_paths import legacy_location, data_path, lab_root, network
import contextlib,json,socket,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from PIL import Image
import engineering0108,location0108

QA=legacy_location('E:/GuangjianData/reviews/final_system_20261029/positioning_unit');QA.mkdir(exist_ok=True,parents=True)

class LocationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=QA);self.root=Path(self.temp.name);self.calls=[];self.off=False;self.closed=False;self.fail=False
        sys.path.insert(0,str(location0108.HOST));import sdk_loader
        case=self
        class Fake:
            def __init__(self,**kwargs):case.output=kwargs['output_root'];self.v1=NS(save_png=lambda p,*a:Image.new('RGB',(1920,1080)).save(p))
            def acquire(self,**kwargs):
                case.calls.append(kwargs);assert kwargs['cancel'] is case.token
                if case.fail:raise RuntimeError('UNIT_FIXTURE_CAPTURE_FAILURE')
                folder=case.output/'fixture';folder.mkdir(parents=True);record=folder/'result.json'
                record.write_text(json.dumps(dict(status='COMMITTED',strict_verified=True,firmware=264,roi=[0,0,1920,1080],evidence_source='UNIT_TEST_FAKE_EXECUTOR')),'utf-8')
                (folder/'same_frame.rgb565').write_bytes(b'unit_fixture_only')
                return NS(record_path=record)
            def lights_off(self,**kwargs):case.off=True;return dict(acknowledged=True)
            def close(self):case.closed=True
        peer=NS(load_engine=lambda:NS(root=self.root),operator_lock=lambda p:contextlib.nullcontext())
        sdk=NS(TransportExecutor=Fake,wire=NS(pinned_module=lambda *a:peer))
        self.sdk_patch=patch.object(sdk_loader,'load_sdk',return_value=sdk);self.sdk_patch.start();self.socket_patch=patch.object(socket,'socket',side_effect=AssertionError('No hardware sockets in unit tests'));self.socket_patch.start();self.token=threading.Event()
    def tearDown(self):self.socket_patch.stop();self.sdk_patch.stop();self.temp.cleanup()
    def test_one_positioning_capture_forwards_cancel_and_cleans_up(self):
        receipt=location0108.capture_preview(self.root/'location','sample004','test',self.token)
        r=json.loads(receipt.read_text('utf-8'));self.assertEqual(r['formal_observations'],0);self.assertEqual(len(self.calls),1);self.assertTrue(self.off and self.closed)
        self.assertEqual(self.calls[0]['roi'],[0,0,1920,1080]);self.assertEqual(self.calls[0]['exposure_lines'],600)
    def test_capture_failure_still_attempts_off_and_close(self):
        self.fail=True
        with self.assertRaises(RuntimeError):location0108.capture_preview(self.root/'location','sample004','test',self.token)
        self.assertTrue(self.off and self.closed);self.assertEqual(len(self.calls),1)
        self.assertEqual(json.loads((self.root/'location/POSITIONING.json').read_text('utf-8'))['status'],'FAILED')
    def test_cancel_before_positioning_does_not_construct(self):
        self.token.set()
        with self.assertRaises(InterruptedError):location0108.capture_preview(self.root/'location','sample004','test',self.token)
        self.assertFalse(self.calls);self.assertFalse((self.root/'location').exists())
    def test_confirming_new_roi_prepares_plan_without_eight_more_captures(self):
        receipt=location0108.capture_preview(self.root/'location','sample004','test',self.token)
        plan=location0108.prepare_selection(receipt,[[600,150],[1400,150],[1400,950],[600,950]],16)
        r=json.loads(plan.read_text('utf-8'));self.assertEqual(r['sample'],'sample004');self.assertEqual(r['roi'],[576,128,864,864]);self.assertEqual(len(self.calls),1)
        self.assertFalse((plan.parent/'run').exists());self.assertEqual((plan.parent.parent/'selected_board_mask.bin').stat().st_size,864*864)

class GroupLifecycleTests(unittest.TestCase):
    def test_native_sdk_cancellation_forwarded_and_off_on_failure(self):
        # Exercise the new wrapper boundary; the real SDK owns _check(allow_cancel).
        sys.path.insert(0,str(location0108.HERE.parent/'p0_pair_console_0107_20261027_r56'))
        import console_workflow
        catalogue=console_workflow.catalog(str(legacy_location('E:/GuangjianData/P0Pairs/GUI_sample004_20261028_220937_1024af/pair')),full_verify=False)
        with tempfile.TemporaryDirectory(dir=QA) as d:
            plan=engineering0108.prepare(catalogue,Path(d)/'plan');token=threading.Event();calls=[];state={}
            class Fake:
                def __init__(self,**kwargs):state['created']=True
                def acquire_roi_preparation(self,**kwargs):
                    assert kwargs['cancel'] is token;state['preparation']=True;return NS(record_path=Path(d)/'UNIT_PREPARATION_NOT_FORMAL')
                def acquire(self,**kwargs):
                    calls.append(kwargs);assert kwargs['cancel'] is token
                    if len(calls)==3:raise RuntimeError('UNIT_FIXTURE_FAILURE')
                    return NS(record_path=Path(d)/('fixture'+str(len(calls))))
                def lights_off(self,**kwargs):state['off']=True;return dict(acknowledged=True)
                def close(self):state['closed']=True
            peer=NS(load_engine=lambda:NS(root=Path(d)),operator_lock=lambda p:contextlib.nullcontext())
            sdk=NS(wire=NS(pinned_module=lambda *a:peer));original=engineering0108.module
            def load(name,path,**kwargs):return NS(EngineeringExecutor=Fake,sdk=sdk) if name=='_final0108_executor' else original(name,path,**kwargs)
            with patch.object(engineering0108,'module',side_effect=load),patch('roi_prepare0108.executor_class',return_value=Fake),patch.object(socket,'socket',side_effect=AssertionError('No real IO')):
                with self.assertRaises(RuntimeError):engineering0108.capture(plan,token)
            self.assertTrue(state['off'] and state['closed'] and state['preparation']);self.assertEqual(len(calls),3)
            summary=json.loads((plan.parent/'run/SUMMARY.json').read_text('utf-8'));self.assertEqual(summary['status'],'FAILED');self.assertEqual(len(summary['records']),2)

if __name__=='__main__':unittest.main(verbosity=2)
