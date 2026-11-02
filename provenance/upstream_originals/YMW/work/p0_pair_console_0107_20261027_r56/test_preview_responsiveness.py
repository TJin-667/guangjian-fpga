"""Hidden native Tk and localhost-only regressions; never contact the board."""
import contextlib
import hashlib
import importlib.util
import io
import json
import socket
import sys
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image,ImageFilter,ImageTk
import console_workflow as workflow
import fast_focus
import focus_tools
from console_app import ConsoleApp

HERE=Path(__file__).resolve().parent
ROOT=Path(sys.argv[1]) if len(sys.argv)>1 else Path('E:/GuangjianData/software_tests/r55_preview_'+time.strftime('%Y%m%d_%H%M%S'))

class PreviewUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sharp=Image.fromarray(np.random.default_rng(55).integers(0,256,(1080,1920),dtype=np.uint8))
        cls.soft=cls.sharp.filter(ImageFilter.GaussianBlur(3))
    def setUp(self):
        self.root=tk.Tk();self.root.withdraw();self.app=ConsoleApp(self.root,ROOT/'gui',preflight=False)
        self.errors=[];self.root.report_callback_exception=lambda *args:self.errors.append(repr(args))
        self.root.update_idletasks()
        # A real native Tk canvas and PhotoImage, with an explicit desktop-sized
        # viewport even though the test window stays hidden from the user.
        self.app.canvas.winfo_width=lambda:1024;self.app.canvas.winfo_height=lambda:576
    def tearDown(self):
        self.app.worker=None
        if self.root.winfo_exists():
            for callback in self.root.tk.call('after','info'):self.root.after_cancel(callback)
            self.app.destroy_ui()
        self.assertEqual(self.errors,[])
    def pump(self,seconds=.08):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.root.update();time.sleep(.002)
    def live(self,image,fid,roi=None):
        roi=roi or self.app.focus_roi or (700,420,320,240)
        return dict(image=image,frame_id=fid,roi=roi,version=self.app.focus_version,
            metric=focus_tools.measure(image,roi),parameters=dict(exposure_lines=600,gain16=16,brightness=128,light_mask=1),
            count=fid,target_fps=2.,actual_fps=2.,received_monotonic=time.monotonic(),record=None)
    def focus(self):
        self.app.focus_mode=True;self.app.focus_session=fast_focus.FocusSession(threading.Event(),lambda *a,**k:None)
        self.app.update_live_focus(self.live(self.sharp,1));self.pump()
    def test_01_400_percent_allocates_only_visible_pixels(self):
        self.app.source_image=self.sharp.convert('RGB');self.app.set_zoom(4);self.pump()
        self.assertEqual(self.app.view_geometry,(7680,4320))
        self.assertLessEqual(self.app.photo.width(),1025);self.assertLessEqual(self.app.photo.height(),577)
        self.assertEqual(len(self.app.canvas.find_withtag('viewport_image')),1)
        workflow.write(ROOT/'viewport_bound.json',dict(old_zoomed_raster=[7680,4320],new_raster=self.app.render_stats,
            pixel_reduction_ratio=7680*4320/(self.app.photo.width()*self.app.photo.height()),hardware_contacted=False))
    def test_02_wheel_burst_is_coalesced_and_cursor_anchor_preserved(self):
        self.app.source_image=self.sharp.convert('RGB');self.app.set_zoom(1);self.pump()
        self.app.canvas.xview_moveto(.2);self.app.canvas.yview_moveto(.2)
        before=(self.app.canvas.canvasx(300)/self.app.scale,self.app.canvas.canvasy(200)/self.app.scale)
        event=SimpleNamespace(delta=120,num=None,x=300,y=200)
        self.app.wheel(event)
        after=(self.app.canvas.canvasx(300)/self.app.scale,self.app.canvas.canvasy(200)/self.app.scale)
        self.assertLess(max(abs(a-b) for a,b in zip(before,after)),2)
        count=self.app.render_count
        for i in range(240):self.app.wheel(SimpleNamespace(delta=120 if i%2 else -120,num=None,x=300,y=200))
        self.assertEqual(self.app.render_count,count,'Mouse handlers must not render full images synchronously')
        self.pump();self.assertLessEqual(self.app.render_count-count,3)
    def test_03_pan_scrollbars_and_resize_paint_current_source_region(self):
        self.app.source_image=self.sharp.convert('RGB');self.app.set_zoom(4);self.pump()
        original=self.app.render_stats['source_box']
        self.app.canvas.scan_mark(300,200);self.app.pan(SimpleNamespace(x=100,y=60));self.pump()
        panned=self.app.render_stats['source_box'];self.assertNotEqual(original,panned)
        self.app.scroll_x('moveto',.35);self.app.scroll_y('moveto',.4);self.pump()
        self.assertGreater(self.app.render_stats['source_box'][0],panned[0])
        for _ in range(100):self.app.render()
        self.pump();self.assertLessEqual(self.app.photo.width(),1025)
    def test_04_live_frame_crop_score_and_overview_remain_same_frame(self):
        self.focus();self.app.set_zoom(4);self.app.canvas.xview_moveto(.3);self.app.canvas.yview_moveto(.2);self.pump()
        self.app.apply_focus_roi((800,440,200,180));old=self.live(self.soft,2,roi=(700,420,320,240));old['version']=-1
        self.app.update_live_focus(old)
        self.assertEqual(self.app.focus_tracker.current,focus_tools.measure(self.soft,(800,440,200,180))['score'])
        self.assertEqual(self.app.focus_image.tobytes(),self.soft.crop((800,440,1000,620)).convert('RGB').tobytes())
        self.assertEqual(self.app.source_image.tobytes(),self.soft.convert('RGB').tobytes())
        self.assertIn('帧2',self.app.focus_text.get());self.assertIn('同帧2',self.app.focus_details.get())
        self.assertEqual(self.app.zoom,4);self.assertLessEqual(self.app.photo.width(),1025)
    def test_05_drag_box_survives_new_frame_and_preserves_native_coordinates(self):
        self.focus();self.app.set_zoom(2);self.pump()
        self.app.click(SimpleNamespace(x=100,y=100));self.app.focus_drag(SimpleNamespace(x=400,y=300))
        self.assertTrue(self.app.canvas.find_withtag('focus_drag'))
        self.app.update_live_focus(self.live(self.soft,2))
        self.assertTrue(self.app.canvas.find_withtag('focus_drag'))
        self.app.finish_focus_drag(SimpleNamespace(x=400,y=300))
        self.assertEqual(self.app.focus_roi,(50,50,150,100));self.assertFalse(self.app.canvas.find_withtag('focus_drag'))
    def test_06_1080p_live_interaction_keeps_event_loop_responsive(self):
        self.focus();self.app.set_zoom(4);self.pump()
        beats=[];frames=[];started=time.monotonic();active=[True]
        def beat():
            if active[0]:beats.append(time.monotonic());self.root.after(10,beat)
        def frame(i):
            self.app.notify('focus_live_frame',**self.live(self.soft if i%2 else self.sharp,i+2));frames.append(i)
        def interact(i):
            self.app.wheel(SimpleNamespace(delta=120 if i%2 else -120,num=None,x=300,y=200))
            self.app.canvas.scan_mark(400,250);self.app.pan(SimpleNamespace(x=390,y=245))
            if i%7==0:self.app.apply_focus_roi((600+i,350,320,240))
        beat()
        for i in range(5):self.root.after(i*500,lambda i=i:frame(i))
        for i in range(70):self.root.after(i*32,lambda i=i:interact(i))
        self.pump(2.45);active[0]=False
        gaps=[b-a for a,b in zip(beats,beats[1:])]
        self.assertEqual(len(frames),5);self.assertGreater(len(beats),70)
        self.assertLess(max(gaps),.5,'Tk heartbeat stalled during zoom/pan/reframe')
        self.assertEqual(self.app.events.qsize(),0);self.assertIn('帧6',self.app.focus_text.get())
        workflow.write(ROOT/'interaction_replay.json',dict(status='PASS',frames=len(frames),target_fps=2,
            interactions=70,heartbeat_count=len(beats),max_heartbeat_gap_ms=max(gaps)*1000,
            p95_heartbeat_gap_ms=float(np.percentile(gaps,95))*1000,render_count=self.app.render_count,
            final_raster=self.app.render_stats,elapsed_s=time.monotonic()-started,
            scope='synthetic host UI; excludes real camera/network FPS',hardware_contacted=False))
    def test_07_poll_yields_with_heavy_notice_queue(self):
        for _ in range(100):self.app.events.put(('notice',('focus_paused',{'waiting_for_roi':False})))
        self.app.poll();self.assertGreater(self.app.events.qsize(),0)
        self.pump(.15);self.assertEqual(self.app.events.qsize(),0)
    def test_08_close_cancels_pending_render_and_late_frame_is_ignored(self):
        self.app.source_image=self.sharp.convert('RGB');self.app.render();self.assertIsNotNone(self.app.render_id)
        self.app.update_live_focus(self.live(self.soft,3));self.assertIsNone(self.app.focus_image)
        self.app.destroy_ui();self.assertIsNone(self.app.render_id)
        # tearDown must not try to call into a destroyed Tcl interpreter.
        self.root=SimpleNamespace(winfo_exists=lambda:False)
    def test_09_preview_defaults_limit_and_data_root(self):
        self.assertEqual(fast_focus.TARGET_FPS,2.);self.assertEqual(fast_focus.DEFAULT_MAX_FRAMES,1000)
        self.assertEqual(fast_focus.FocusSession(threading.Event(),lambda *a,**k:None).target_fps,2.)
        self.assertEqual(workflow.default_result_root(),Path('E:/GuangjianData/P0Pairs'))
        with patch.object(self.app,'dispatch',side_effect=lambda job:None):self.app.start_focus()
        self.assertEqual(self.app.session_root.parents[1],self.app.result_root)
        self.assertEqual(self.app.session_root.parent.name,'focus')
    def test_10_100_percent_visible_pixels_are_unmodified(self):
        self.app.source_image=self.sharp.convert('RGB');self.app.set_zoom(1)
        self.app.canvas.xview_moveto(.12);self.app.canvas.yview_moveto(.15);self.pump()
        shown=ImageTk.getimage(self.app.photo).convert('RGB')
        box=self.app.render_stats['source_box'];self.assertTrue(all(v==int(v) for v in box))
        self.assertEqual(shown.tobytes(),self.app.source_image.crop(tuple(map(int,box))).tobytes())

def main():
    ROOT.mkdir(parents=True,exist_ok=False)
    workflow.verify_bundle()
    # Include the real SDK over a localhost peer: CRC rejection, identity,
    # pause/resume/OFF, formal ROI export and eight-frame gallery recovery.
    spec=importlib.util.spec_from_file_location('r55_existing_tests',HERE/'test_console.py')
    prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
    prior.ROOT=ROOT/'regression';prior.old.ROOT=prior.ROOT/'inherited';prior.ROOT.mkdir()
    names=['test_41_fast_gray_three_frames_no_mask_upload_or_perframe_SET',
        'test_42_corrupt_fast_payload_not_displayed_and_OFF',
        'test_43_fast_pause_resume_rewarms_without_reconfiguring_camera',
        'test_44_fast_cancel_inflight_retires_and_preserves_displayed_frames',
        'test_45_fast_changed_session_stops_before_display',
        'test_46_fast_missing_OFF_ack_requires_cleanup',
        'test_26_console_worker_receipt_complete_no_auto_analysis',
        'test_33_nonzero_ROI_real_SDK_export_reader_and_analysis',
        'test_38_ROI_reexport_preserves_original_sensor_and_no_new_CAP',
        'test_11_export_failure_recovery_has_no_new_CAP']
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(PreviewUI)
    suite.addTests(prior.Lifecycle(name) for name in names)
    began=time.monotonic()
    with (ROOT/'tests.txt').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    receipt=dict(status='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),wall_seconds=time.monotonic()-began,
        hardware_contacted=False,network_scope='127.0.0.1 software peers only',new_physical_CAP=0)
    workflow.write(ROOT/'receipt.json',receipt);print(json.dumps(receipt))
    if not result.wasSuccessful():print((ROOT/'tests.txt').read_text(encoding='utf-8'))
    return 0 if result.wasSuccessful() else 2

if __name__=='__main__':raise SystemExit(main())
