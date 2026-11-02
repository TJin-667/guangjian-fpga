import ast,json,socket,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
import contracts,pipeline

class ContractTests(unittest.TestCase):
    def planes(self):
        return dict(gray=np.zeros((8,12,20),np.uint8),sat1=np.zeros((8,12,20),bool),valid=np.ones((8,12,20),bool),board=np.ones((12,20),bool),residual_n=np.zeros((8,12,20),np.int16))
    def test_eight_native_planes_accepted(self):self.assertEqual(contracts.validate_planes(self.planes()),(8,12,20))
    def test_binary_uint8_sat_from_original_archives_is_supported(self):
        p=self.planes();p['sat1']=p['sat1'].astype('uint8');contracts.validate_planes(p);p['sat1'][0,0,0]=255
        with self.assertRaisesRegex(ValueError,'BINARY_SAT1'):contracts.validate_planes(p)
    def test_fused_response_cannot_replace_eight_evidence_planes(self):
        p=self.planes();p['residual_n']=p['residual_n'][0]
        with self.assertRaisesRegex(ValueError,'SIGNED_RN'):contracts.validate_planes(p)
    def test_unsigned_or_out_of_range_residual_refused(self):
        p=self.planes();p['residual_n']=p['residual_n'].astype('uint16')
        with self.assertRaises(ValueError):contracts.validate_planes(p)
        p=self.planes();p['residual_n'][0,0,0]=20656
        with self.assertRaises(ValueError):contracts.validate_planes(p)
    def test_display_and_sensor_coordinates_are_separate(self):self.assertEqual(contracts.pixel_to_sensor(5,8,[100,200,20,30]),(105,208))
    def test_unqualified_offload_cannot_silently_fallback(self):
        with self.assertRaisesRegex(ValueError,'0108_NOT_QUALIFIED'):contracts.require_backend('offload0108')
    def test_cancel_before_launch_preserves_source_and_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source';source.mkdir();(source/'raw').write_bytes(b'preserve');token=threading.Event();token.set()
            with patch('subprocess.Popen',side_effect=AssertionError('must not spawn')):
                out,status=pipeline.run(source,'capture',Path(d)/'out',cancel=token)
            self.assertEqual(status['status'],'CANCELLED');self.assertEqual((source/'raw').read_bytes(),b'preserve');self.assertFalse((out/'RESULT.json').exists())
    def test_output_cannot_overlap_input(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,'OVERLAPS'):pipeline.run(d,'capture',Path(d)/'out')

class WindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        import app
        self.app_module=app;self.root=tk.Tk();self.root.withdraw();self.temp=tempfile.TemporaryDirectory()
        with patch.object(socket,'socket',side_effect=AssertionError('UI startup must be offline')):
            self.ui=app.UnifiedApp(self.root,result_root=Path(self.temp.name)/'capture',analysis_root=Path(self.temp.name)/'analysis',preflight=False)
            self.root.update_idletasks()
    def tearDown(self):
        try:self.ui.destroy_ui()
        except Exception:pass
        self.temp.cleanup()
    def test_one_window_contains_capture_and_final_result_tabs(self):
        self.assertIn(str(self.ui.image_tab),self.ui.tabs.tabs());self.assertIn(str(self.ui.final_tab),self.ui.tabs.tabs());self.assertEqual(self.ui.low_lines.get(),'400');self.assertEqual(self.ui.high_lines.get(),'800')
    def test_only_successful_complete_capture_hands_off(self):
        self.ui.auto_after_capture=True;called=[]
        with patch.object(self.ui,'start_pipeline',side_effect=lambda *args:called.append(args)):
            self.ui.observe_capture_event('done',('capture',{'receipt':{'status':'FAILED'}},{'input_ready':True,'root':'bad'}));self.root.update_idletasks();self.assertFalse(called)
            self.ui.auto_after_capture=True
            self.ui.observe_capture_event('done',('capture',{'receipt':{'status':'P0_PAIR_READY_FOR_LABEL_REVIEW'}},{'input_ready':True,'root':'good'}));self.root.update_idletasks();self.assertEqual(called,[('good','capture')])
        self.ui.capture_handoff=None
    def test_close_cancels_analysis_instead_of_killing_capture(self):
        self.ui.pipeline_busy=True;self.ui.close();self.assertTrue(self.ui.pipeline_cancel.is_set());self.assertTrue(self.ui.closing);self.ui.pipeline_busy=False
    def test_zoom_pan_render_allocates_visible_crop_only(self):
        v=self.ui.final_view;v.canvas.configure(width=500,height=350);self.root.update_idletasks();v.load(Image.new('RGB',(4000,3000)))
        for i in range(35):v.set_zoom(1.2**(i%12),200,150)
        self.root.update_idletasks();v.redraw();self.assertLess(v.last_render_pixels,2_000_000)
    def test_hidden_result_tab_refits_when_shown_and_manual_zoom_is_retained(self):
        v=self.ui.final_view;v.load(Image.new('RGB',(864,960)));self.assertTrue(v.auto_fit)
        v.set_zoom(2);self.assertFalse(v.auto_fit)
        v.fit();self.assertTrue(v.auto_fit)
    def test_result_tab_folds_capture_controls_and_restores_them(self):
        self.ui.tabs.select(self.ui.final_tab);self.ui.layout_mode();self.assertTrue(self.ui.capture_controls_hidden)
        self.assertTrue(all(not w.winfo_manager() for w in self.ui.capture_bars))
        self.ui.tabs.select(self.ui.image_tab);self.ui.layout_mode();self.assertTrue(all(w.winfo_manager()=='pack' for w in self.ui.capture_bars))
    def test_focus_budget_and_rate_unchanged(self):
        import fast_focus
        self.assertEqual(fast_focus.DEFAULT_MAX_FRAMES,1000)
    def test_transport_choice_does_not_silently_switch_the_default(self):
        self.assertEqual(self.ui.capture_format_code(),50);self.assertFalse(self.ui.full_evidence_audit.get())
        self.ui.capture_format.set('灰度证据候选');self.assertEqual(self.ui.capture_format_code(),49)
        self.assertIn('v1.5',self.root.title())
    def test_capture_queue_observer_does_not_consume_or_mutate_event(self):
        got=[];q=self.app_module.CaptureEvents(lambda *v:got.append(v));event=('done',('off',{'acknowledged':True}));q.put(event);self.assertEqual(q.get_nowait(),event);self.assertEqual(got,[event])

if __name__=='__main__':unittest.main(verbosity=2)
