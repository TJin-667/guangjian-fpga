"""End-to-end per-run settings through the strict SDK and actual XDL loader."""
import dataclasses
import importlib.util
import json
import socket
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import console_workflow as workflow
from capture_settings import CaptureSettings,for_runtime

HERE=Path(__file__).resolve().parent
ROOT=Path(sys.argv[1]) if len(sys.argv)>1 else Path('E:/GuangjianData/software_tests/r56_config_'+time.strftime('%Y%m%d_%H%M%S'))
spec=importlib.util.spec_from_file_location('r56_prior',HERE/'test_console.py')
prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
prior.ROOT=ROOT/'regression';prior.old.ROOT=prior.ROOT/'inherited'

class SettingsUI(prior.PureAndUI):
    # Only the explicitly named cases below are added to the suite.
    def test_60_validation_and_frozen_settings(self):
        cfg=CaptureSettings.from_text('plate006','B_v0','320','960')
        self.assertEqual(cfg.preview_lines,640)
        with self.assertRaises(dataclasses.FrozenInstanceError):cfg.low=400
        for name in ['', '../bad','CON','a/b','a:b','sample 006','工件006','a'*65]:
            with self.subTest(name=name),self.assertRaises(ValueError):CaptureSettings(name)
        for pair in [(0,800),(400,1117),(800,400),(400,400),(True,800),(1.5,800)]:
            with self.subTest(pair=pair),self.assertRaises(ValueError):CaptureSettings('sample006',low=pair[0],high=pair[1])
    def test_61_GUI_invalid_settings_do_not_dispatch_or_create_files(self):
        root,app=self.make_ui();app.low_lines.set('800');app.high_lines.set('400')
        with patch.object(app,'dispatch',side_effect=AssertionError('Invalid settings dispatched')),patch.object(socket,'socket',side_effect=AssertionError('No sockets')):
            app.start();app.start_focus()
        self.assertIsNone(app.session_root);self.assertIn('设置未通过',app.status.get());root.after_cancel(app.poll_id)
    def test_62_GUI_job_freezes_editable_identity_variant_and_pair(self):
        root,app=self.make_ui();app.sample.set('plate006');app.variant.set('B_v0');app.low_lines.set('320');app.high_lines.set('960')
        jobs=[]
        with patch.object(app,'dispatch',side_effect=jobs.append):app.start()
        self.assertEqual(len(jobs),1)
        app.sample.set('changed');app.variant.set('A_v1');app.low_lines.set('400');app.high_lines.set('800')
        calls=[]
        def capture(*args,**kwargs):calls.append((args,kwargs));return {'receipt':{},'root':str(args[0])}
        with patch.object(workflow,'run_capture',side_effect=capture):jobs[0]()
        frozen=calls[0][1]['settings'];self.assertEqual(frozen,CaptureSettings('plate006','B_v0',320,960))
        app.set_busy(True)
        for field in [app.sample_box,app.variant_box,app.low_spin,app.high_spin]:self.assertEqual(str(field.cget('state')),'disabled')
        app.set_busy(False);self.assertEqual(str(app.sample_box.cget('state')),'normal');root.after_cancel(app.poll_id)
    def test_63_backend_derivation_and_preflight_no_board(self):
        import generate_backend
        self.assertEqual(generate_backend.generate()[0],(HERE/'capture_backend.py').read_bytes())
        cfg=CaptureSettings('sample006','A_v0',250,1050)
        with patch.object(socket,'socket',side_effect=AssertionError('No preflight sockets')):
            runtime=workflow.Runtime(cfg.specimen,cfg.variant,'offline_custom',threading.Event(),lambda *a,**k:None,settings=cfg)
            plan,_,_=workflow.backend.plan_for(runtime,preview=True)
        self.assertEqual((plan['low'],plan['high'],plan['preview_lines']),(250,1050,650))

class ConfiguredLifecycle(prior.Lifecycle):
    @classmethod
    def setUpClass(cls):
        prior.old.ROOT=ROOT/'custom_inherited';super().setUpClass()
    def custom(self):
        cfg=CaptureSettings('plate006','B_v0',320,960)
        self.runtime.specimen=cfg.specimen;self.runtime.variant=cfg.variant;self.runtime.pose='custom_B_v0_320_960'
        self.runtime.capture_settings=cfg
        return cfg
    def test_64_custom_identity_and_pair_through_capture_gallery_and_reexport(self):
        cfg=self.custom()
        result=workflow.run_capture(self.root/'custom',cfg.specimen,self.runtime.cancel_event,self.select,self.runtime.notify,
            automatic_analysis=False,runtime=self.runtime,settings=cfg)
        self.assertEqual(result['receipt']['status'],'P0_PAIR_READY_FOR_LABEL_REVIEW',result)
        self.assertEqual([p['parameters']['exposure_lines'] for p in self.peer.captured],[640]+[320,960]*4)
        pair=self.root/'custom/pair';doc=workflow.read(pair/'XDL_manifest.json');group=doc['groups'][0]
        self.assertEqual((group['specimen_id'],group['board_face'],group['specimen_variant']),('plate006','B','B_v0'))
        self.assertEqual(doc['capture_settings'],cfg.document())
        self.assertEqual([p['exposure_lines'] for p in group['observations']],[320,960]*4)
        summary=workflow.read(pair/'acquisition/operator_summary.json');self.assertEqual((summary['low'],summary['high']),(320,960))
        self.assertEqual(summary['capture_settings'],cfg.document())
        catalogue=workflow.catalog(pair);count=len(self.peer.captured)
        workflow.reexport(catalogue,self.root/'custom_reexport');self.assertEqual(len(self.peer.captured),count)
        again=workflow.read(self.root/'custom_reexport/XDL_manifest.json');self.assertEqual(again['capture_settings'],cfg.document())
        gallery=workflow.read(self.root/'custom/eight_compare/COMPARE_MANIFEST.json')
        self.assertEqual(gallery['specimen_id'],'plate006')
    def test_65_custom_pair_CRC_failure_preserves_four_and_does_not_export(self):
        self.custom();start=self.peer._start_capture
        def corrupt(*args):
            if len(self.peer.captured)==5:self.peer.fault='payload_corrupt'
            return start(*args)
        self.peer._start_capture=corrupt;result=self.run_it()
        self.assertEqual(result['summary']['status'],'FAILED');summary=workflow.read(self.root/'run/acquisition/operator_summary.json')
        self.assertEqual(summary['saved_observations'],4);self.assertEqual((summary['low'],summary['high']),(320,960))
        self.assertTrue(summary['lights_off']['acknowledged']);self.assertFalse((self.root/'run/XDL_manifest.json').exists())
    def test_66_custom_focus_uses_midpoint_and_actual_readback(self):
        cfg=self.custom();events=[];session=None
        def notice(event,**data):
            events.append((event,data))
            if event=='focus_live_frame':session.set_roi((10,5,32,20))
        session=self.fast_session(notice,max_frames=2)
        result=session.run(self.root/'custom_focus',cfg.specimen,self.runtime,self.fast_factory)
        self.assertEqual(result['receipt']['frames'],2)
        self.assertTrue(all(p['parameters']['exposure_lines']==640 for p in self.peer.captured))
        live=[p for e,p in events if e=='focus_live_frame'];self.assertEqual([p['parameters']['exposure_lines'] for p in live],[640,640])

class RegressionLifecycle(prior.Lifecycle):
    @classmethod
    def setUpClass(cls):
        prior.old.ROOT=ROOT/'regression_inherited';super().setUpClass()

def main():
    ROOT.mkdir(parents=True,exist_ok=False);prior.ROOT.mkdir();workflow.verify_bundle()
    preview_spec=importlib.util.spec_from_file_location('r56_preview_tests',HERE/'test_preview_responsiveness.py')
    preview=importlib.util.module_from_spec(preview_spec);preview_spec.loader.exec_module(preview);preview.ROOT=ROOT/'ui';preview.ROOT.mkdir()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(preview.PreviewUI)
    suite.addTests(SettingsUI(name) for name in ['test_60_validation_and_frozen_settings','test_61_GUI_invalid_settings_do_not_dispatch_or_create_files',
        'test_62_GUI_job_freezes_editable_identity_variant_and_pair','test_63_backend_derivation_and_preflight_no_board'])
    suite.addTests(ConfiguredLifecycle(name) for name in ['test_64_custom_identity_and_pair_through_capture_gallery_and_reexport',
        'test_65_custom_pair_CRC_failure_preserves_four_and_does_not_export','test_66_custom_focus_uses_midpoint_and_actual_readback'])
    suite.addTests(RegressionLifecycle(name) for name in ['test_41_fast_gray_three_frames_no_mask_upload_or_perframe_SET',
        'test_42_corrupt_fast_payload_not_displayed_and_OFF','test_43_fast_pause_resume_rewarms_without_reconfiguring_camera',
        'test_44_fast_cancel_inflight_retires_and_preserves_displayed_frames','test_45_fast_changed_session_stops_before_display',
        'test_46_fast_missing_OFF_ack_requires_cleanup','test_26_console_worker_receipt_complete_no_auto_analysis',
        'test_33_nonzero_ROI_real_SDK_export_reader_and_analysis','test_38_ROI_reexport_preserves_original_sensor_and_no_new_CAP',
        'test_11_export_failure_recovery_has_no_new_CAP'])
    started=time.monotonic();source_before={n:workflow.sha(HERE/n) for n in workflow.read(HERE/'BUNDLE.json')['files_sha256']}
    with (ROOT/'tests.txt').open('w',encoding='utf-8') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    source_after={n:workflow.sha(HERE/n) for n in source_before}
    receipt=dict(status='PASS' if result.wasSuccessful() and source_before==source_after else 'FAIL',tests=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),sources_unchanged=source_before==source_after,runtime_sha256=source_after,
        wall_seconds=time.monotonic()-started,hardware_contacted=False,network_scope='127.0.0.1 software peers only',new_physical_CAP=0)
    workflow.write(ROOT/'receipt.json',receipt);print(json.dumps(receipt))
    if receipt['status']!='PASS':print((ROOT/'tests.txt').read_text(encoding='utf-8'))
    return 0 if receipt['status']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
