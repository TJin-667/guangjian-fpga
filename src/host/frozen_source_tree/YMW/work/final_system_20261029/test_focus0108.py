"""Real0108 SDK over a loopback-only software camera; no physical CAP."""
import contextlib,hashlib,socket,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import focus0108

NativeSocket=socket.socket
class LocalSocket(NativeSocket):
    def bind(self,address):
        if address[0]!='127.0.0.1':raise AssertionError('Only localhost bind allowed')
        return super().bind(address)
    def sendto(self,data,address):
        if address[0]!='127.0.0.1':raise AssertionError('Only localhost send allowed')
        return super().sendto(data,address)

class FocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0,str(focus0108.HOST));from sdk_loader import load_sdk,load
        cls.sdk=load_sdk();cls.bridge=focus0108.load_bridge(sdk=cls.sdk)
        cls.peer_module=load('_final108_focus_test_peer',focus0108.HOST.parent/'derived_sdk/software_transport_peer_0108.py')
        cls.Peer,cls.engine=cls.peer_module.make_peer()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.token=threading.Event();self.events=[]
        self.net=patch.object(socket,'socket',LocalSocket);self.net.start()
        self.peer=self.Peer(self.engine.root/'ymw');self.peer.__enter__()
        self.runtime=focus0108.Runtime('sample004','A_v1','UNIT_SOFTWARE_PEER',self.token,self.notice)
        self.runtime.sensor_size=(96,32);self.runtime.evidence_source='software_udp_peer';self.runtime.guard=lambda:contextlib.nullcontext()
        self.runtime.focus_plan=lambda:(dict(preview_lines=600,source_contract=dict(board='127.0.0.1',bind='127.0.0.1',port=self.peer.endpoint[1]),candidate=dict(binding={})),NS(roi=[0,0,96,32],mask=bytes([1])*(96*32)),{})
        self.session=self.bridge.FocusSession(self.token,self.notice,max_frames=3,target_fps=4)
    def tearDown(self):self.peer.__exit__(None,None,None);self.net.stop();self.temp.cleanup()
    def notice(self,event,**data):
        self.events.append((event,data))
        if event=='focus_live_frame':self.session.set_roi((10,5,32,20))
    def factory(self,runtime,plan,out):
        self.client=self.bridge.PreviewTransport(board='127.0.0.1',bind='127.0.0.1',port=self.peer.endpoint[1],ymw_root=self.engine.root/'ymw',output_root=out/'sdk_calls',pixel_format=49,evidence_source='software_udp_peer',sensor_size=(96,32),command_timeout=.04,retries=2)
        return self.client
    def run_session(self):return self.session.run(self.root/'focus','sample004',runtime=self.runtime,factory=self.factory)['receipt']
    def test_0108_three_frames_from_real_sdk_are_crc_valid_no_mask_upload(self):
        r=self.run_session();self.assertEqual(r['status'],'FOCUS_BUDGET_REACHED',r.get('error'));self.assertEqual(r['frames'],3);self.assertTrue(r['lights_off']['acknowledged'])
        self.assertFalse(any(c['kind'] in (10,11) for c in self.peer.received));self.assertEqual(sum(c['kind']==4 for c in self.peer.received),1)
        self.assertTrue(all(c['pixel_format']==49 for c in self.peer.captured));self.assertEqual(r['preview_backend'],'qualified0108');self.assertEqual(r['evidence_source'],'software_udp_peer')
    def test_0107_reply_is_still_rejected_before_capture(self):
        self.peer.firmware=263;r=self.run_session();self.assertEqual(r['status'],'FAILED');self.assertEqual(r['frames'],0);self.assertEqual(len(self.peer.captured),0);self.assertIn('0108',r['error']['message']);self.assertTrue(r['lights_off']['acknowledged'])
    def test_bad_payload_is_not_displayed_and_cleanup_runs(self):
        original=self.notice
        def callback(event,**data):
            original(event,**data)
            if event=='focus_live_frame':self.peer.fault='payload_corrupt'
        self.session.notify=callback;r=self.run_session();self.assertEqual(r['status'],'FAILED');self.assertEqual(r['frames'],1);self.assertIn('CRC64',r['error']['message']);self.assertTrue(r['lights_off']['acknowledged'])
    def test_cancel_inflight_preserves_one_frame_and_closes(self):
        original=self.peer._start_capture
        def capture(*args):
            result=original(*args)
            if len(self.peer.captured)==2:self.token.set()
            return result
        self.peer._start_capture=capture;r=self.run_session();self.assertEqual(r['status'],'FOCUS_STOPPED');self.assertEqual(r['frames'],1);self.assertEqual(len(self.peer.captured),2);self.assertTrue(r['lights_off']['acknowledged'])
    def test_pause_resume_rewarms_and_keeps_camera_configuration(self):
        original=self.notice
        def callback(event,**data):
            original(event,**data)
            if event=='focus_live_frame' and data['count']==1:self.session.toggle_pause()
            if event=='focus_paused':self.session.toggle_pause()
        self.session.notify=callback;r=self.run_session();self.assertEqual(r['frames'],3);self.assertEqual([(p['parameters']['settle_frames'],p['parameters']['discard_frames']) for p in self.peer.captured],[(1,3),(1,3),(0,0)])
        self.assertEqual(sum(c['kind']==4 for c in self.peer.received),1)
    def test_bridge_does_not_replace_original_modules_or_source(self):
        import console_workflow,fast_focus
        self.assertIs(console_workflow,focus0108.legacy);self.assertIsNot(self.bridge.PreviewTransport,fast_focus.PreviewTransport)
        self.assertTrue(issubclass(self.bridge.PreviewTransport,self.sdk.TransportExecutor));self.assertFalse(issubclass(fast_focus.PreviewTransport,self.sdk.TransportExecutor))
        self.assertEqual(self.bridge.TARGET_FPS,2.);self.assertEqual(self.bridge.DEFAULT_MAX_FRAMES,1000)

class EntryTests(unittest.TestCase):
    def test_0108_entry_opens_action_page_and_routes_focus_and_capture(self):
        import tkinter as tk
        import app
        root=tk.Tk();root.withdraw()
        with tempfile.TemporaryDirectory() as d,patch.object(socket,'socket',side_effect=AssertionError('Offline UI')):
            ui=app.UnifiedApp(root,result_root=Path(d)/'capture',analysis_root=Path(d)/'analysis',preflight=False,hardware_mode='0108');root.update_idletasks()
            self.assertEqual(ui.tabs.select(),str(ui.engineering_tab));self.assertIn('0108',root.title());self.assertEqual(ui.focus0108_button.cget('text'),'0108实时调焦（2帧/秒，鼠标拖框）')
            with patch.object(ui,'start_focus0108') as focus:ui.start_focus();focus.assert_called_once()
            with patch.object(ui,'start_position0108') as position:ui.start();position.assert_called_once()
            ui.destroy_ui()

if __name__=='__main__':unittest.main(verbosity=2)
