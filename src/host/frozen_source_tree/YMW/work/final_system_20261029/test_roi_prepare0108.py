"""Model the actual0108 latched capture ROI at the real SDK boundary."""
import hashlib,json,socket,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from archive0108 import HOST
from roi_prepare0108 import executor_class
import numpy as np

NativeSocket=socket.socket
class LocalSocket(NativeSocket):
    def bind(self,address):
        if address[0]!='127.0.0.1':raise AssertionError('Only localhost bind')
        return super().bind(address)
    def sendto(self,data,address):
        if address[0]!='127.0.0.1':raise AssertionError('Only localhost send')
        return super().sendto(data,address)

class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(HOST));from sdk_loader import load
        cls.implementation=load('_final_roi_test_engineering',HOST/'engineering_executor.py')
        peer_module=load('_final_roi_test_peer',HOST/'software_offload_peer.py');Base,cls.engine=peer_module.make_peer()
        class LatchedPeer(Base):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs);self.executed_domain=(*self.sensor_size,0);self.begin_rejected_for_old_roi=0
            def _start_capture(self,peer,args):
                self.executed_domain=(*self.roi[2:],self.roi_generation) if args[0]==3 else (*self.sensor_size,0)
                return super()._start_capture(peer,args)
            def _handle(self,data,peer):
                # Matches source_roi_* and camera_crop_enable being latched by CAP,
                # plus fusion_net_service BEGIN's !mask_matches rejection.
                if len(data)==20 and data[5]==17 and self.mask_domain!=self.executed_domain:
                    saved=self.mask_valid;self.mask_valid=False;self.begin_rejected_for_old_roi+=1
                    try:return super()._handle(data,peer)
                    finally:self.mask_valid=saved
                return super()._handle(data,peer)
        cls.Peer=LatchedPeer
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.token=threading.Event()
        self.net=patch.object(socket,'socket',LocalSocket);self.net.start();self.peer=self.Peer(self.engine.root/'ymw');self.peer.__enter__();self.roi=[7,9,19,13];self.board=np.ones((13,19),bool);self.client=None
    def tearDown(self):
        if self.client:
            try:self.client.lights_off(timeout_s=.5)
            finally:self.client.close()
        self.peer.__exit__(None,None,None);self.net.stop();self.temp.cleanup()
    def create(self,kind):
        self.client=kind(group_id=0x10899,group_digest=b'ROI_PREP_TEST_01',group_roi=self.roi,group_board=self.board,result_directory=self.root/'fusion',board='127.0.0.1',port=self.peer.endpoint[1],bind='127.0.0.1',ymw_root=self.engine.root/'ymw',output_root=self.root/'captures',pixel_format=50,mode='strict',evidence_source='software_udp_peer',sensor_size=(96,32),command_timeout=.08,retries=2)
        return self.client
    def args(self,slot):return dict(light_channel=(slot-1)//2+1,brightness=128,exposure_lines=400 if slot%2 else 800,gain16=16,roi=self.roi,board_mask=self.board.astype(np.uint8).tobytes(),settle_frames=1,discard_frames=3,timeout_s=15,sample_id='UNIT_SOFTWARE_PEER',round_id='TEST_NOT_HARDWARE',cancel=self.token)
    def test_original_executor_reproduces_begin3_before_any_capture(self):
        client=self.create(self.implementation.EngineeringExecutor)
        with self.assertRaisesRegex(Exception,'BEGIN status 3'):client.acquire(**self.args(1))
        self.assertEqual(len(self.peer.captured),0);self.assertEqual(self.peer.begin_rejected_for_old_roi,1)
    def test_preparation_then_eight_real_sdk_frames_and_lossless_reference(self):
        client=self.create(executor_class(self.implementation));pre=client.acquire_roi_preparation(**self.args(1))
        self.assertEqual(client._off_slot,0);self.assertFalse(client._off_group_live);self.assertFalse((self.root/'fusion').exists())
        frames=[client.acquire(**self.args(slot)) for slot in range(1,9)]
        r=json.loads((self.root/'fusion/RESULT.json').read_text('utf-8'));self.assertEqual(r['status'],'SAME_INPUT_EQUAL');self.assertFalse(any(r['differences'].values()));self.assertEqual(len(r['frames']),8)
        self.assertNotIn(str(pre.record_path),[row['record'] for row in r['frames']]);self.assertEqual(len(self.peer.captured),9);self.assertEqual(self.peer.begin_rejected_for_old_roi,0)
        self.assertEqual([f.metadata['identity']['request_id'] for f in frames],list(range(2,10)));self.assertFalse(self.peer.off_live)
    def test_failed_preparation_never_begins_fusion_group(self):
        self.peer.fault='payload_corrupt';client=self.create(executor_class(self.implementation))
        with self.assertRaises(Exception):client.acquire_roi_preparation(**self.args(1))
        self.assertEqual(client._off_slot,0);self.assertFalse(client._off_group_live);self.assertEqual(self.peer.off_execution.get(17,0),0)

if __name__=='__main__':unittest.main(verbosity=2)
