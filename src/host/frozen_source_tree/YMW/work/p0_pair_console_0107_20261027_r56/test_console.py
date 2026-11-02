"""Only loopback SDK peers, socket-forbidden offline work and hidden native Tk."""
from export_paths import legacy_location, data_path, lab_root, network
import ast
import contextlib
import hashlib
import importlib.util
import json
import socket
import sys
import threading
import time
import tkinter as tk
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageFilter
import console_workflow as workflow
import focus_tools
from focus_loop import FocusSession
from console_app import ConsoleApp
import auto_location
import roi_geometry
import xdl_crop_adapter
import fast_focus

HERE=Path(__file__).resolve().parent
ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else legacy_location('E:/GuangjianData/software_tests/r54_console')
sys.path.append(str(HERE.parent/'p0_pair_capture_0107_20261026'))
spec=importlib.util.spec_from_file_location('pinned_tests',HERE.parent/'p0_pair_capture_0107_20261026/test_p0_capture.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
old.app=workflow.backend;old.ROOT=ROOT/'inherited'

class Lifecycle(old.P0Tests):
    def setUp(self):
        super().setUp();self.runtime.cancel_event=threading.Event();self.events=[]
        self.runtime.notify=lambda event,**data:self.events.append((event,data))
    def test_08_stop_between_requests_preserves_committed_and_OFF(self):
        def notify(event,**data):
            self.events.append((event,data))
            if event=='frame' and data['count']==2:self.runtime.cancel_event.set()
        self.runtime.notify=notify;r=self.run_it()
        self.assertEqual(r['summary']['status'],'CANCELLED');self.assertEqual(len(self.peer.captured),3)
        s=workflow.read(self.root/'run/acquisition/operator_summary.json')
        self.assertEqual(s['saved_observations'],2);self.assertTrue(s['lights_off']['acknowledged'])
        self.assertEqual([e[1]['count'] for e in self.events if e[0]=='frame'],[1,2])
    def test_09_cancel_before_preview_has_no_CAP(self):
        self.runtime.cancel_event.set();r=self.run_it()
        self.assertEqual(r['summary']['status'],'CANCELLED');self.assertEqual(len(self.peer.captured),0)
    def test_10_offline_archive_analysis_reexport_no_sockets_raw_unchanged(self):
        result=self.run_it();raw=self.root/'run';before=workflow.sha(result['archive'])
        with patch.object(socket,'socket',side_effect=AssertionError('Offline socket')):
            data=workflow.catalog(raw);self.assertTrue(data['input_ready'])
            recovered=workflow.reexport(data,self.root/'reexport')
            new=workflow.catalog(self.root/'reexport');self.assertTrue(new['input_ready'])
            first=workflow.read(raw/'XDL_manifest.json')['groups'][0]
            second=workflow.read(self.root/'reexport/XDL_manifest.json')['groups'][0]
            self.assertEqual(first['group_id'],second['group_id']);self.assertEqual(recovered['summary']['new_physical_CAP'],0)
            state=workflow.run_analysis(raw/'XDL_manifest.json',self.root/'analysis',threading.Event(),lambda *a,**k:None)
            self.assertEqual(state,'OFFLINE_EVIDENCE_COMPLETE_NOT_DETECTION')
            a=workflow.read(self.root/'analysis/console_analysis.json');self.assertEqual(len(a['views']),3)
            self.assertTrue(a['sockets_forbidden']);self.assertFalse(a['trained_global_or_gate_available'])
            extracted=workflow.extract_zip(result['archive'],self.root/'unzip');self.assertTrue(workflow.catalog(extracted)['input_ready'])
        self.assertEqual(workflow.sha(result['archive']),before);workflow.verify_inventory(raw)
        self.assertEqual(len(self.peer.captured),9)
    def test_11_export_failure_recovery_has_no_new_CAP(self):
        with patch.object(workflow.backend.bridge,'export_batch',side_effect=OSError('Injected export failure')):self.run_it()
        with patch.object(socket,'socket',side_effect=AssertionError('Offline socket')):
            data=workflow.catalog(self.root/'run');self.assertTrue(data['raw_eight_recoverable']);self.assertFalse(data['input_ready'])
            workflow.reexport(data,self.root/'fixed');self.assertTrue(workflow.catalog(self.root/'fixed')['input_ready'])
        self.assertEqual(len(self.peer.captured),9)
    def test_12_offline_corruption_rejected(self):
        self.run_it();path=self.root/'run/acquisition/observations.json';path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'SHA differs'):workflow.catalog(self.root/'run')
    def focus(self,notify,max_frames=3):
        session=FocusSession(self.runtime.cancel_event,notify,max_frames=max_frames)
        return session
    def test_13_focus_real_SDK_full_frames_same_crop_metrics_separate_from_P0(self):
        events=[];session=None
        def notice(event,**data):
            events.append((event,data))
            if event=='focus_overview':session.set_roi((10,5,32,20))
        session=self.focus(notice);r=session.run(self.root/'focus','sample005',self.runtime)
        s=r['receipt'];self.assertEqual(s['status'],'FOCUS_BUDGET_REACHED');self.assertEqual(len(self.peer.captured),3)
        self.assertTrue(s['lights_off']['acknowledged']);self.assertFalse(s['training_data']);self.assertFalse(s['counts_as_P0_group'])
        self.assertEqual(s['recorded_logical_CAP'],3);frames=[data for event,data in events if event=='focus_frame']
        self.assertEqual(len(frames),2)
        for data in frames:
            self.assertEqual(Image.open(data['path']).size,self.runtime.sensor_size);self.assertEqual(data['parameters']['exposure_lines'],600)
            self.assertTrue(data['full_frame'])
            self.assertEqual(data['metric'],focus_tools.measure(Image.open(data['path']),data['roi']))
            record=workflow.read(Path(data['record']));self.assertEqual(record['diagnostic']['roi'],[0,0,*self.runtime.sensor_size])
        self.assertTrue(s['live_full_frame_snapshots']);self.assertTrue(s['focus_ROI_is_host_crop_of_same_frame'])
        workflow.verify_inventory(self.root/'focus')
    def test_40_ROI_changed_in_flight_keeps_full_frame_and_next_ROI_version(self):
        events=[];session=None;original=self.runtime.executor
        def executor(*args):
            device=original(*args);acquire=device.acquire;count=0
            def wrapped(**kw):
                nonlocal count
                result=acquire(**kw);count+=1
                if count==2:session.set_roi((20,7,20,16))
                return result
            device.acquire=wrapped;return device
        self.runtime.executor=executor
        def notice(event,**data):
            events.append((event,data))
            if event=='focus_overview':session.set_roi((10,5,32,20))
        session=self.focus(notice);result=session.run(self.root/'focus','sample004',self.runtime)
        frames=[data for event,data in events if event=='focus_frame']
        self.assertEqual([f['version'] for f in frames],[1,2]);self.assertEqual([f['roi'] for f in frames],[(10,5,32,20),(20,7,20,16)])
        self.assertEqual(len(self.peer.captured),3);self.assertTrue(result['receipt']['lights_off']['acknowledged'])
        for frame in frames:self.assertEqual(frame['metric'],focus_tools.measure(Image.open(frame['path']),frame['roi']))
    def test_14_focus_stop_while_paused_no_new_CAP_OFF(self):
        timer=None;session=None
        def notice(event,**data):
            nonlocal timer
            if event=='focus_overview':session.toggle_pause();session.set_roi((10,5,32,20))
            if event=='focus_paused':
                timer=threading.Timer(.1,self.runtime.cancel_event.set);timer.start()
        session=self.focus(notice);r=session.run(self.root/'focus','sample005',self.runtime)
        if timer:timer.join()
        self.assertEqual(len(self.peer.captured),1);self.assertEqual(r['receipt']['status'],'FOCUS_STOPPED');self.assertTrue(r['receipt']['lights_off']['acknowledged'])
    def test_15_focus_OFF_failure_is_cleanup_required(self):
        session=None
        def notice(event,**data):
            if event=='focus_overview':self.peer.fault='off_ack_lost';self.runtime.cancel_event.set()
        session=self.focus(notice);r=session.run(self.root/'focus','sample005',self.runtime)
        self.assertEqual(r['receipt']['status'],'CLEANUP_REQUIRED');self.assertFalse(r['receipt']['lights_off']['acknowledged'])
    def test_25_cancel_inside_active_SDK_request_OFF_and_archive(self):
        start=self.peer._start_capture
        def cancel_capture(*args):
            result=start(*args)
            if len(self.peer.captured)==2:self.runtime.cancel_event.set()
            return result
        self.peer._start_capture=cancel_capture;r=self.run_it()
        self.assertEqual(r['summary']['status'],'CANCELLED');self.assertLessEqual(len(self.peer.captured),2)
        s=workflow.read(self.root/'run/acquisition/operator_summary.json');self.assertTrue(s['lights_off']['acknowledged'])
        self.assertLess(s['saved_observations'],8);workflow.verify_inventory(self.root/'run')
    def test_26_console_worker_receipt_complete_no_auto_analysis(self):
        result=workflow.run_capture(self.root/'console','sample005',self.runtime.cancel_event,self.select,
            self.runtime.notify,automatic_analysis=False,runtime=self.runtime)
        self.assertEqual(result['receipt']['status'],'P0_PAIR_READY_FOR_LABEL_REVIEW')
        self.assertEqual(result['receipt']['analysis_status'],'NOT_RUN');self.assertEqual(len(self.peer.captured),9)
        self.assertTrue(workflow.catalog(Path(result['root'])/'pair')['input_ready'])
    def roi_selection(self,*args):return dict(points=[[49,4],[75,4],[75,28],[49,28]],margin_px=16)
    def test_33_nonzero_ROI_real_SDK_export_reader_and_analysis(self):
        r=self.run_it(self.roi_selection);self.assertEqual(r['summary']['status'],'P0_PAIR_READY_FOR_LABEL_REVIEW',r['summary']['error'])
        root=self.root/'run';catalogue=workflow.catalog(root);self.assertTrue(catalogue['input_ready'])
        self.assertEqual(len(self.peer.captured),9)
        for row in catalogue['frames']:
            self.assertEqual(row['roi_xywh'],[32,0,64,32]);self.assertEqual(Image.open(row['color']).size,(64,32))
            record=workflow.read(Path(row['record']));self.assertEqual(record['payload_bytes'],64*32*2)
        manifest=workflow.read(root/'XDL_manifest.json');runner=xdl_crop_adapter.load()
        for item in manifest['groups'][0]['observations']:
            observation,_=runner._load_observation(item,root);self.assertEqual(observation.roi_xywh,(32,0,64,32));self.assertEqual(item['source_origin_xy'],[32,0])
        self.assertEqual(workflow.run_analysis(root/'XDL_manifest.json',self.root/'analysis',threading.Event(),lambda *a,**k:None),'OFFLINE_EVIDENCE_COMPLETE_NOT_DETECTION')
        geometry=workflow.read(root/'crop_geometry.json');self.assertFalse(geometry['deskew']);self.assertFalse(geometry['pixels_resampled'])
    def test_38_ROI_reexport_preserves_original_sensor_and_no_new_CAP(self):
        r=self.run_it(self.roi_selection);before=workflow.sha(Path(r['archive']));data=workflow.catalog(self.root/'run')
        with patch.object(socket,'socket',side_effect=AssertionError('No recapture')):
            workflow.reexport(data,self.root/'reexport');new=workflow.catalog(self.root/'reexport')
        self.assertTrue(new['input_ready']);self.assertEqual(new['frames'][0]['roi_xywh'],[32,0,64,32]);self.assertEqual(len(self.peer.captured),9)
        self.assertEqual(workflow.sha(Path(r['archive'])),before)
    def fast_session(self,notice,max_frames=3):
        return fast_focus.FocusSession(self.runtime.cancel_event,notice,max_frames=max_frames,target_fps=4)
    def fast_factory(self,runtime,plan,out):
        self.fast_client=fast_focus.PreviewTransport(board='127.0.0.1',bind='127.0.0.1',port=self.peer.endpoint[1],
            ymw_root=self.engine.root/'ymw',output_root=out/'sdk_calls',pixel_format=49,
            evidence_source='software_udp_peer',sensor_size=(96,32),command_timeout=.04,retries=2)
        return self.fast_client
    def test_41_fast_gray_three_frames_no_mask_upload_or_perframe_SET(self):
        session=None;events=[]
        def notice(event,**data):
            events.append((event,data))
            if event=='focus_live_frame':session.set_roi((10,5,32,20)) if session.get_roi()[0] is None else None
        session=self.fast_session(notice);r=session.run(self.root/'fast','sample004',self.runtime,self.fast_factory)
        self.assertEqual(r['receipt']['status'],'FOCUS_BUDGET_REACHED');self.assertEqual(len(self.peer.captured),3)
        self.assertEqual([p['pixel_format'] for p in self.peer.captured],[49]*3)
        self.assertEqual([(p['parameters']['settle_frames'],p['parameters']['discard_frames']) for p in self.peer.captured],[(1,3),(0,0),(0,0)])
        self.assertEqual(sum(c['kind']==4 for c in self.peer.received),1);self.assertFalse(any(c['kind'] in (10,11) for c in self.peer.received))
        for event,data in events:
            if event=='focus_live_frame':self.assertEqual(data['metric'],focus_tools.measure(data['image'],data['roi']))
        self.assertTrue(r['receipt']['lights_off']['acknowledged']);self.assertFalse(list((self.root/'fast').rglob('*.png')))
        self.assertFalse(r['receipt']['counts_as_P0_group']);workflow.verify_inventory(self.root/'fast')
    def test_42_corrupt_fast_payload_not_displayed_and_OFF(self):
        session=None
        def notice(event,**data):
            if event=='focus_live_frame':session.set_roi((10,5,32,20));self.peer.fault='payload_corrupt'
        session=self.fast_session(notice);r=session.run(self.root/'fast','sample004',self.runtime,self.fast_factory)
        self.assertEqual(r['receipt']['status'],'FAILED');self.assertEqual(r['receipt']['frames'],1)
        self.assertIn('CRC64',r['receipt']['error']['message']);self.assertTrue(r['receipt']['lights_off']['acknowledged'])
    def test_43_fast_pause_resume_rewarms_without_reconfiguring_camera(self):
        session=None
        def notice(event,**data):
            if event=='focus_live_frame' and data['count']==1:session.set_roi((10,5,32,20));session.toggle_pause()
            if event=='focus_paused':session.toggle_pause()
        session=self.fast_session(notice);r=session.run(self.root/'fast','sample004',self.runtime,self.fast_factory)
        self.assertEqual(r['receipt']['status'],'FOCUS_BUDGET_REACHED')
        self.assertEqual([(p['parameters']['settle_frames'],p['parameters']['discard_frames']) for p in self.peer.captured],[(1,3),(1,3),(0,0)])
        self.assertEqual(sum(c['kind']==4 for c in self.peer.received),1);self.assertTrue(r['receipt']['lights_off']['acknowledged'])
    def test_44_fast_cancel_inflight_retires_and_preserves_displayed_frames(self):
        session=None;capture=self.peer._start_capture
        def cancel(*args):
            result=capture(*args)
            if len(self.peer.captured)==2:self.runtime.cancel_event.set()
            return result
        self.peer._start_capture=cancel
        def notice(event,**data):
            if event=='focus_live_frame':session.set_roi((10,5,32,20))
        session=self.fast_session(notice);r=session.run(self.root/'fast','sample004',self.runtime,self.fast_factory)
        self.assertEqual(r['receipt']['status'],'FOCUS_STOPPED');self.assertEqual(r['receipt']['frames'],1)
        self.assertEqual(len(self.peer.captured),2);self.assertTrue(r['receipt']['lights_off']['acknowledged'])
    def test_45_fast_changed_session_stops_before_display(self):
        session=None
        def notice(event,**data):
            if event=='focus_live_frame':session.set_roi((10,5,32,20));self.peer.fault='wrong_session'
        session=self.fast_session(notice);r=session.run(self.root/'fast','sample004',self.runtime,self.fast_factory)
        self.assertEqual(r['receipt']['status'],'FAILED');self.assertEqual(r['receipt']['frames'],1)
    def test_46_fast_missing_OFF_ack_requires_cleanup(self):
        session=None
        def notice(event,**data):
            if event=='focus_live_frame':self.peer.fault='off_ack_lost';self.runtime.cancel_event.set()
        session=self.fast_session(notice);r=session.run(self.root/'fast','sample004',self.runtime,self.fast_factory)
        self.assertEqual(r['receipt']['status'],'CLEANUP_REQUIRED');self.assertFalse(r['receipt']['lights_off']['acknowledged'])

class PureAndUI(unittest.TestCase):
    def test_47_native_CRC64_exact_reference_parity_and_native_load(self):
        crc=fast_focus.NativeCRC();rng=np.random.default_rng(52)
        for size in [0,1,7,8,9,31,256,1380,16384]:
            raw=rng.integers(0,256,size,dtype=np.uint8).tobytes()
            self.assertEqual(crc(raw),workflow.backend.sdk.wire.legacy.crc64_ecma(raw))
        raw=rng.integers(0,256,2332800,dtype=np.uint8).tobytes();begin=time.perf_counter()
        for _ in range(10):value=crc(raw)
        workflow.write(ROOT/'native_CRC_benchmark.json',dict(bytes=len(raw),mean_seconds=(time.perf_counter()-begin)/10,
            crc64=value,hardware_contacted=False,scope='host CRC only, not a sensor FPS test'))
    def test_48_latest_mailbox_never_builds_old_frame_backlog(self):
        mailbox=fast_focus.LatestFrame();signals=[]
        for i in range(100):signals.append(mailbox.put(dict(frame=i)))
        self.assertEqual(sum(signals),1);self.assertEqual(mailbox.take()['frame'],99);self.assertEqual(mailbox.replaced,99)
        self.assertTrue(mailbox.put(dict(frame=100)));self.assertEqual(mailbox.take()['frame'],100);self.assertIsNone(mailbox.take())
    def live_data(self,image,fid,roi=(20,20,100,90),version=0):
        return dict(image=image,frame_id=fid,roi=roi,version=version,metric=focus_tools.measure(image,roi),
            parameters=dict(exposure_lines=600,gain16=16,brightness=128,light_mask=1,settle_frames=0,discard_frames=0),
            count=fid,target_fps=4,actual_fps=4.,received_monotonic=time.monotonic(),record=None)
    def test_49_Tk_live_whole_crop_score_atomic_and_ROI_changed_inflight(self):
        root,app=self.make_ui();app.focus_mode=True;app.focus_session=fast_focus.FocusSession(threading.Event(),lambda *a,**k:None)
        image=Image.fromarray(np.random.default_rng(49).integers(0,256,(480,640),dtype=np.uint8))
        app.notify('focus_live_frame',**self.live_data(image,1));app.poll()
        app.apply_focus_roi((50,50,80,70));app.set_zoom(2)
        blurred=image.filter(ImageFilter.GaussianBlur(3));app.notify('focus_live_frame',**self.live_data(blurred,2));app.poll()
        self.assertEqual(app.focus_image.tobytes(),blurred.crop((50,50,130,120)).convert('RGB').tobytes())
        self.assertEqual(app.source_image.tobytes(),blurred.convert('RGB').tobytes());self.assertEqual(app.focus_tracker.current,focus_tools.measure(blurred,app.focus_roi)['score'])
        self.assertIn('帧2',app.focus_text.get());self.assertIn('同帧2',app.focus_details.get());self.assertEqual(app.zoom,2)
        root.after_cancel(app.poll_id)
    def test_50_1080p_host_display_replay_at_target_four_fps(self):
        root,app=self.make_ui();root.update_idletasks();app.focus_mode=True
        app.focus_session=fast_focus.FocusSession(threading.Event(),lambda *a,**k:None)
        sharp=Image.fromarray(np.random.default_rng(50).integers(0,256,(1080,1920),dtype=np.uint8));blurred=sharp.filter(ImageFilter.GaussianBlur(3))
        started=time.monotonic();times=[];scores=[]
        for index in range(12):
            remaining=started+index*.25-time.monotonic()
            if remaining>0:time.sleep(remaining)
            app.notify('focus_live_frame',**self.live_data(sharp if index%2 else blurred,index+1))
            app.poll();root.update_idletasks();times.append(time.monotonic());scores.append(app.focus_tracker.current)
        fps=(len(times)-1)/(times[-1]-times[0])
        self.assertGreater(fps,3.3);self.assertGreater(max(scores),min(scores));self.assertIn('帧12',app.focus_text.get())
        workflow.write(ROOT/'host_display_replay.json',dict(frames=12,sensor_size=[1920,1080],target_fps=4,actual_host_replay_fps=fps,
            changed_scores=True,hardware_contacted=False,scope='synthetic host display replay excludes FPGA/sensor/network throughput'))
        root.after_cancel(app.poll_id)
    def test_16_focus_exact_old_function_parity_and_blur(self):
        source=HERE/'reference/focus_measure_legacy.py.txt'
        tree=ast.parse(source.read_text(encoding='utf-8'));namespace=dict(Image=Image,ImageFilter=ImageFilter,np=np,WIDTH=1920,HEIGHT=1080)
        exec(compile(tree,str(source),'exec'),namespace)
        image=Image.fromarray(np.random.default_rng(123).integers(0,256,(1080,1920,3),dtype=np.uint8))
        crop,box,score,clipped=namespace['focus_measure'](image,(700,500))
        metric=focus_tools.measure(image,(box[0],box[1],320,240))
        self.assertEqual(metric['score'],score);self.assertEqual(metric['clipped_percent'],clipped)
        self.assertGreater(score,focus_tools.measure(crop.filter(ImageFilter.GaussianBlur(3)))['score'])
    def test_17_ROI_rectangle_and_tracker_conditions(self):
        self.assertEqual(focus_tools.rectangle((50.2,40.8),(-3,2),(100,100)),(0,2,51,39))
        for a,b in [((0,0),(8,8)),((float('nan'),0),(20,20))]:
            with self.assertRaises(ValueError):focus_tools.rectangle(a,b,(100,100))
        tracker=focus_tools.Tracker();self.assertEqual(tracker.accept({'score':7},'A'),7)
        self.assertEqual(tracker.accept({'score':2},'A'),7);self.assertEqual(tracker.accept({'score':2},'B'),2)
        tracker.reset();self.assertIsNone(tracker.best)
    def test_18_zoom_anchor_math_and_boundaries(self):
        left,top=focus_tools.anchored_scroll(1,1.2,300,150,(200,100),(1920,1080),(900,500))
        self.assertAlmostEqual((left+200)/1.2,500);self.assertAlmostEqual((top+100)/1.2,250)
        self.assertEqual(focus_tools.anchored_scroll(1,.05,0,0,(100,100),(1920,1080),(900,500)),(0,0))
    def test_19_zip_paths_validated_before_any_write(self):
        root=ROOT/'zip_safety';root.mkdir()
        for i,names in enumerate([['good.txt','../escape.txt'],['one','ONE'],['C:/escape.txt']]):
            archive=root/(str(i)+'.zip')
            with zipfile.ZipFile(archive,'w') as z:
                for name in names:z.writestr(name,b'test')
            with self.assertRaises(ValueError):workflow.extract_zip(archive,root/str(i))
            self.assertFalse((root/str(i)).exists())
    def test_20_source_guards_and_derivation_no_sockets(self):
        import generate_backend
        self.assertEqual(generate_backend.generate()[0],(HERE/'capture_backend.py').read_bytes())
        with patch.object(socket,'socket',side_effect=AssertionError('No preflight sockets')):
            workflow.verify_bundle();runtime=workflow.Runtime('sample005','A_v1','offline',threading.Event(),lambda *a,**k:None)
            workflow.backend.plan_for(runtime,preview=True)
    def make_ui(self):
        root=tk.Tk();root.withdraw();app=ConsoleApp(root,ROOT/'gui_results',preflight=False)
        self.addCleanup(lambda:root.destroy() if root.winfo_exists() else None)
        return root,app
    def test_21_hidden_Tk_native_ROI_wheel_and_stale_frames(self):
        with patch.object(socket,'socket',side_effect=AssertionError('No GUI sockets')):
            root,app=self.make_ui();root.update_idletasks()
            app.source_image=Image.new('RGB',(1920,1080),(90,100,110));app.set_zoom(1)
            app.canvas.xview_moveto(.2);app.canvas.yview_moveto(.2)
            before=((app.canvas.canvasx(50))/app.scale,(app.canvas.canvasy(50))/app.scale)
            app.wheel(SimpleNamespace(delta=120,num=None,x=50,y=50))
            after=(app.canvas.canvasx(50)/app.scale,app.canvas.canvasy(50)/app.scale)
            self.assertLess(max(abs(a-b) for a,b in zip(before,after)),2)
            app.focus_mode=True;app.focus_session=FocusSession(threading.Event(),lambda *a,**k:None)
            app.apply_focus_roi((20,20,100,90));roi=app.focus_roi;app.set_zoom(2)
            self.assertEqual(app.focus_roi,roi);self.assertEqual(app.focus_session.get_roi()[0],roi)
            app.notify('focus_frame',version=app.focus_version-1,roi=roi,path='DO_NOT_OPEN_STALE_FRAME')
            app.poll();self.assertIsNone(app.focus_image)
            app.focus_tracker.accept({'score':10},'old');app.apply_focus_roi((25,25,100,90));self.assertIsNone(app.focus_tracker.best)
            self.assertTrue(app.canvas.bind('<MouseWheel>'));self.assertTrue(app.canvas.bind('<B2-Motion>'))
            app.notify('error',text='not used') if False else None
            app.events.put(('error','injected'));app.poll();self.assertFalse(app.focus_mode);self.assertIsNone(app.focus_session)
            root.after_cancel(app.poll_id)
    def test_22_selector_close_cancels_worker_before_destroy(self):
        root,app=self.make_ui();answer=[]
        def work():
            try:app.selector('unused.png','sample005','A_v1')
            except InterruptedError:answer.append('cancelled')
        app.dispatch(lambda:('selector',work()));worker=app.worker
        # Discard unneeded display notice; selector still blocks until close.
        deadline=time.monotonic()+1
        while app.events.empty() and time.monotonic()<deadline:time.sleep(.01)
        while not app.events.empty():app.events.get_nowait()
        app.close();self.assertTrue(app.cancel.is_set());self.assertTrue(root.winfo_exists())
        worker.join(2);self.assertFalse(worker.is_alive());self.assertEqual(answer,['cancelled'])
        app.closing=False;root.after_cancel(app.poll_id)
    def test_23_display_exports_block_sealed_directory(self):
        root=ROOT/'display_guard';root.mkdir();(root/'output_manifest.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'sealed'):workflow.new_display_output(root/'display.png')
    def test_24_analysis_cancel_or_failure_preserves_input(self):
        # Use the complete fixture already exercised by test10.
        raw=ROOT/'inherited/10/run';before=workflow.sha(raw/'XDL_manifest.json')
        token=threading.Event();token.set()
        status=workflow.run_analysis(raw/'XDL_manifest.json',ROOT/'cancelled_analysis',token,lambda *a,**k:None)
        self.assertEqual(status,'CANCELLED_RAW_PRESERVED')
        state=workflow.run_analysis(ROOT/'missing_manifest',ROOT/'failed_analysis',threading.Event(),lambda *a,**k:None)
        self.assertEqual(state,'FAILED_RAW_PRESERVED');self.assertEqual(workflow.sha(raw/'XDL_manifest.json'),before)
    def run_focus_counter(self,name,byte_limit=None):
        folder=ROOT/name;token=threading.Event();calls=[];session=None
        class CounterExecutor:
            def acquire(self,**kw):
                calls.append(kw);index=len(calls);call=folder/'sdk_calls'/f'{index:04d}';committed=call/'committed';committed.mkdir(parents=True)
                image=committed/'image.png';record=committed/'result.json';Image.new('RGB',kw['roi'][2:],(90,100,110)).save(image);record.write_text('{}')
                workflow.write(call/'outcome.json',dict(cost=dict(capture_requests=1)))
                return SimpleNamespace(png_path=image,record_path=record,metadata=dict(identity=dict(frame_id=index),actual_parameters=dict(exposure_lines=600),cost=dict(host_elapsed_s=.001)))
            def lights_off(self,**kw):return dict(acknowledged=True)
            def close(self):pass
        runtime=SimpleNamespace(sensor_size=(16,16),cancel_event=token,guard=contextlib.nullcontext,
            executor=lambda *a:CounterExecutor(),archive=lambda out,s:dict(summary=s))
        def notice(event,**data):
            if event=='focus_overview':session.set_roi((1,1,12,12))
        session=FocusSession(token,notice,max_bytes=byte_limit)
        with patch.object(token,'wait',return_value=False),patch.object(workflow.backend,'plan_for',return_value=({},SimpleNamespace(roi=(0,0,16,16),mask=bytes([1])*256),{})),patch.object(workflow.backend.bridge,'load_commit',return_value=None):
            result=session.run(folder,'sample005',runtime)
        return session,result,calls
    def test_27_focus_default_reaches_300_not_120(self):
        with patch.object(socket,'socket',side_effect=AssertionError('Counter fixture forbids sockets')):
            session,result,calls=self.run_focus_counter('counter300')
        self.assertEqual(session.max_frames,300);self.assertIsNone(session.max_bytes)
        self.assertEqual(len(calls),300);self.assertEqual(result['receipt']['frames'],300)
        self.assertEqual(result['receipt']['recorded_logical_CAP'],300);self.assertTrue(result['receipt']['lights_off']['acknowledged'])
        self.assertFalse(result['receipt']['counts_as_P0_group'])
    def test_28_explicit_programmatic_byte_limit_still_works(self):
        session,result,calls=self.run_focus_counter('counterbytes',1)
        self.assertEqual(len(calls),1);self.assertEqual(result['receipt']['status'],'FOCUS_BUDGET_REACHED')
    def test_29_reused_locator_detects_plate_without_capture(self):
        image=np.full((1080,1920,3),15,np.uint8);image[180:950,570:1370]=160
        path=ROOT/'synthetic_plate.png';Image.fromarray(image).save(path)
        with patch.object(socket,'socket',side_effect=AssertionError('Locator must stay offline')):candidate=auto_location.propose(path)
        self.assertEqual(candidate['status'],'auto_candidate_review_required');self.assertEqual(len(candidate['points']),4)
        workflow.backend.polygon_mask(candidate['points'],(1920,1080));self.assertFalse(candidate['ROI_crop_applied_to_formal_P0'])
    def test_30_locator_dark_or_missing_needs_manual(self):
        path=ROOT/'dark.png';Image.new('RGB',(1920,1080)).save(path)
        self.assertEqual(auto_location.propose(path)['points'],[]);self.assertEqual(auto_location.propose(ROOT/'absent.png')['points'],[])
    def test_31_UI_prefills_auto_points_but_waits_for_confirmation(self):
        root,app=self.make_ui();path=ROOT/'manual_UI_plate.png';Image.new('RGB',(100,100)).save(path)
        points=[[10,10],[90,10],[90,90],[10,90]]
        app.notify('selection',png=str(path),specimen='sample005',variant='A_v1',candidate=dict(points=points))
        app.poll();self.assertEqual(app.selected_points,points);self.assertFalse(app.selection_ready.is_set())
        app.confirm_selection();self.assertEqual(app.selection_answer['points'],points);self.assertEqual(app.selection_answer['margin_px'],16);self.assertTrue(app.selection_ready.is_set())
        root.after_cancel(app.poll_id)
    def test_32_locator_source_exact_and_005_raw_unmodified(self):
        proof=workflow.read(HERE/'LOCATOR_SOURCE.json')
        self.assertEqual(workflow.sha(HERE/'plate_locator.py'),proof['sha256']);self.assertEqual(workflow.sha(Path(proof['source'])),proof['sha256'])
    def test_34_geometry_margin_rotation_and_tile_grid_no_pixel_transform(self):
        p=[[582.874,176.116],[1372.046,185.719],[1362.265,976.86],[572.359,966.56]]
        first=roi_geometry.build(p,(1920,1080),16);second=roi_geometry.build(p,(1920,1080),32)
        self.assertEqual(first['roi_xywh'],[544,160,864,864]);self.assertFalse(first['deskew']);self.assertFalse(first['pixels_resampled'])
        for result in [first,second]:
            x,y,w,h=result['roi_xywh'];self.assertEqual((x%32,y%32,w%32,h%32),(0,0,0,0))
            for px,py in p:self.assertTrue(x<=px<x+w and y<=py<y+h)
        self.assertLessEqual(second['roi_xywh'][0],first['roi_xywh'][0]);self.assertGreaterEqual(second['roi_xywh'][2],first['roi_xywh'][2])
    def test_35_invalid_margin_refused_before_capture(self):
        for margin in [0,15,257,True,16.5]:
            with self.assertRaises(ValueError):roi_geometry.build([[20,20],[80,20],[80,80],[20,80]],(100,100),margin)
    def test_36_crop_reader_rejects_wrong_origin_or_hardware_ROI(self):
        root=ROOT/'inherited/33/run';item=workflow.read(root/'XDL_manifest.json')['groups'][0]['observations'][0]
        runner=xdl_crop_adapter.load()
        for change in [dict(source_origin_xy=[0,0]),dict(hardware_capture_roi_xywh=[0,0,64,32]),dict(sensor_size_xy=[32,32])]:
            with self.assertRaises(ValueError):runner._load_observation({**item,**change},root)
    def test_37_source_origin_reader_is_only_documented_derivation(self):
        import generate_xdl_crop_runner
        self.assertEqual(generate_xdl_crop_runner.generate()[0],(HERE/'xdl_crop_runner.py').read_bytes())
    def test_39_fresh_full_view_even_stale_ROI_then_same_frame_crop_and_zoom(self):
        root,app=self.make_ui();root.update_idletasks();app.focus_mode=True
        app.focus_session=FocusSession(threading.Event(),lambda *a,**k:None)
        app.source_image=Image.new('RGB',(1920,1080),(10,20,30));app.set_zoom(2)
        app.apply_focus_roi((20,20,100,90));app.canvas.xview_moveto(.2);app.canvas.yview_moveto(.2)
        before=(app.canvas.xview()[0],app.canvas.yview()[0])
        path=ROOT/'fresh_full.png';image=Image.new('RGB',(1920,1080),(70,80,90));image.paste((130,140,150),(20,20,120,110));image.save(path)
        data=dict(path=str(path),full_frame=True,version=app.focus_version-1,roi=app.focus_roi,frame_id=500,
            metric=focus_tools.measure(image,app.focus_roi),parameters=dict(exposure_lines=600),record='test',count=2)
        app.update_focus_frame(data)
        self.assertEqual(app.source_image.getpixel((0,0)),(70,80,90));self.assertIsNone(app.focus_image)
        self.assertEqual(app.zoom,2);self.assertEqual(app.image_origin,(0,0));self.assertEqual(app.focus_session.get_roi()[0],app.focus_roi)
        self.assertAlmostEqual(before[0],app.canvas.xview()[0],places=4);self.assertAlmostEqual(before[1],app.canvas.yview()[0],places=4)
        app.update_focus_frame({**data,'version':app.focus_version})
        self.assertEqual(app.focus_image.size,(100,90));self.assertEqual(app.focus_image.tobytes(),image.crop((20,20,120,110)).tobytes())
        self.assertNotIn('过暗',app.focus_details.get());self.assertNotIn('过亮',app.focus_details.get());self.assertIn('帧500',app.focus_details.get())
        self.assertEqual(app.focus_tracker.current,data['metric']['score']);root.after_cancel(app.poll_id)

if __name__=='__main__':
    ROOT.mkdir(parents=True,exist_ok=False)
    before={p.name:workflow.sha(p) for p in HERE.glob('*.py')};before['BUNDLE.json']=workflow.sha(HERE/'BUNDLE.json');started=time.monotonic()
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(Lifecycle),unittest.defaultTestLoader.loadTestsFromTestCase(PureAndUI)])
    with (ROOT/'tests.txt').open('w',encoding='utf-8') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    after={p.name:workflow.sha(p) for p in HERE.glob('*.py')};after['BUNDLE.json']=workflow.sha(HERE/'BUNDLE.json')
    receipt=dict(status='PASS' if result.wasSuccessful() and before==after else 'FAIL',tests=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),sources_unchanged=before==after,source_sha256=before,
        wall_seconds=time.monotonic()-started,hardware_contacted=False,network_scope='LocalSocket127.0.0.1 only; offline child forbids sockets',hidden_Tk=True)
    workflow.write(ROOT/'receipt.json',receipt);print(json.dumps(receipt));raise SystemExit(0 if receipt['status']=='PASS' else 2)
