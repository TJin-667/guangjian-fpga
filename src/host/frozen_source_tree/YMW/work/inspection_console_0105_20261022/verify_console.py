"""Offline/guarded localhost integration checks. Never contact 192.168.0.2."""
import argparse
import copy
import hashlib
import io
import shutil
import socket
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import capture_adapter as capture
import workflow
from common import ROOT, digest, read_json, write_json, verify_vendor, verify_inventory, extract_zip, seal_folder


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lab-root', type=Path, default=Path('C:/BX72_0105_LAB'))
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--golden-root', type=Path, default=Path('D:/BX72_inspection_verify_20261022/golden'))
    p.add_argument('--b1-root', type=Path, default=Path('D:/BX72_s2_line_pilot_20261022/inputs'))
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    old = capture.legacy(a.lab_root)
    core = old.load_core(a.lab_root)
    plan, source, confirmation = capture.prepare_plan(a.lab_root)
    protected = read_json(ROOT/'protected_before.json')
    original = socket.socket
    class LocalSocket(original):
        def sendto(self, data, *args):
            if args[-1][0] != '127.0.0.1':
                raise AssertionError('Physical endpoint prohibited in tests')
            return super().sendto(data, *args)
        def connect(self, address):
            if address[0] != '127.0.0.1':
                raise AssertionError('Physical endpoint prohibited in tests')
            return super().connect(address)
    engine = core.load_engine(include_peer=True)
    from software_peer import make_peer_class
    Peer = make_peer_class(engine)
    success, parity, gui = {}, [], {}

    def clone_lab(name):
        lab = a.out/name
        lab.mkdir()
        for dirname in ['auto_exposure_r3', 'fourlight_fixed_v1']:
            shutil.copytree(a.lab_root/dirname, lab/dirname)
        for rel in ['runtime_provenance.json', 'bx72_0105_lab.bit']+['runtime/software/'+n for n in ['acquisition_executor.py','acquisition_support.py','identity_diag.py']]:
            target=lab/rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(a.lab_root/rel,target)
        for folder in [source['source'], confirmation['folder']]:
            shutil.copytree(folder, lab/'results'/folder.name)
        return lab

    def run_peer(name, exposure=600, fault=None, cancel=None, notify=lambda *a, **k: None):
        lab = clone_lab(name)
        planned, snap, conf = capture.prepare_plan(lab)
        # An explicit injected exposure tests transport propagation, not controller correctness.
        # Every resulting frame remains labelled software_udp_peer.
        planned['exposure_lines'] = exposure
        cls = core.progress_executor_class(engine, lambda *a, **k: None)
        with Peer(sensor_size=(1920,1080), fault_plan=fault) as peer:
            def factory(*unused):
                def build(**kw):
                    kw.update(board='127.0.0.1', bind='127.0.0.1', port=peer.endpoint[1], evidence_source='software_udp_peer')
                    return cls(**kw)
                return build
            with patch.object(capture, 'executor_class', side_effect=factory), \
                 patch.object(capture, 'prepare_plan', return_value=(planned, snap, conf)):
                result = capture.run_capture(planned, lab/'capture_test', confirmed_same_pose=True, cancel=cancel, notify=notify)
            return result, list(peer.captured), planned

    class Checks(unittest.TestCase):
        def test_01_vendor_matches_original_frozen_hashes(self):
            manifest = verify_vendor()
            frozen = read_json(ROOT/'vendor/fourlight_fusion/freeze.json')
            for name, sha in frozen['files'].items():
                path = ROOT/'vendor/fourlight_fusion'/name
                if path.exists():
                    self.assertEqual(digest(path), sha)
            for name, sha in frozen['external_dependencies'].items():
                self.assertEqual(digest(ROOT/'vendor/fourlight_fusion'/name), sha)
            self.assertEqual(len(manifest['files']), 9)

        def test_02_preflight_opens_no_socket(self):
            with patch.object(socket, 'socket', side_effect=AssertionError('No planning socket')):
                self.assertEqual(capture.prepare_plan(a.lab_root)[0], plan)

        def test_03_confirmation_required(self):
            with patch.object(socket, 'socket', side_effect=AssertionError('No socket')):
                with self.assertRaisesRegex(ValueError, 'Explicit'):
                    capture.run_capture(plan, a.out/'never', confirmed_same_pose=False)
                with self.assertRaises(ValueError):
                    workflow.execute(plan)

        def test_04_mutated_plan_rejected(self):
            changed=copy.deepcopy(plan)
            changed['exposure_lines']=500
            with patch.object(socket, 'socket', side_effect=AssertionError('No socket')):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    capture.run_capture(changed,a.out/'never',confirmed_same_pose=True)

        def test_05_cancel_before_commands(self):
            event=threading.Event()
            event.set()
            with patch.object(socket, 'socket', side_effect=AssertionError('No socket')):
                with self.assertRaisesRegex(ValueError, 'Cancelled'):
                    capture.run_capture(plan,a.out/'never',confirmed_same_pose=True,cancel=event)

        def test_06_localhost_500_lines_four_new_frames(self):
            result, frames, selected = run_peer('peer500', exposure=500)
            success.update(result=result, plan=selected)
            s=result['summary']
            self.assertTrue(s['captures_complete'])
            self.assertEqual(s['evidence_source'],'software_udp_peer')
            self.assertFalse(s['operator_same_pose_confirmed'])
            self.assertTrue(s['lights_off']['acknowledged'])
            self.assertEqual(len(frames),4)
            self.assertEqual([f['actual_parameters']['exposure_lines'] for f in s['frames']],[500]*4)
            self.assertEqual([f['actual_parameters']['light_mask'] for f in s['frames']],[1,2,4,8])
            self.assertEqual([f['camera_readback']['exposure_raw'] for f in s['frames']],[8000]*4)
            self.assertEqual(len({f['identity']['request_id'] for f in s['frames']}),4)
            self.assertEqual(s['known_completed_transaction_frames'],20)
            verify_inventory(result['output'])

        def test_07_peer_analysis_explicit_and_not_hardware(self):
            # Worker rejects software fixtures unless an explicit test-only flag is supplied.
            with self.assertRaises(ValueError):
                workflow.run_analysis(success['result']['output'],a.out/'peer_analysis_forbidden')
            r=workflow.run_analysis(success['result']['output'],a.out/'peer_analysis',allow_peer=True)
            self.assertEqual(r['evidence_source'],'software_udp_peer')
            self.assertEqual(r['exposure_lines'],500)
            self.assertFalse(r['physical_scratch_count_available'])

        def test_08_failure_keeps_first_frame_and_turns_off(self):
            result, frames, _=run_peer('peer_failed',fault={2:'truncated_image'})
            s=result['summary']
            self.assertEqual(s['status'],'FAILED')
            self.assertFalse(s['captures_complete'])
            self.assertEqual(s['saved_images'],1)
            self.assertEqual(s['capture_attempts'],2)
            self.assertTrue(s['lights_off']['acknowledged'])
            verify_inventory(result['output'])

        def test_09_cancel_keeps_partial_and_turns_off(self):
            event=threading.Event()
            def notify(kind,**kw):
                if kind=='step' and kw['channel']==2:
                    event.set()
            result,frames,_=run_peer('peer_cancel',cancel=event,notify=notify)
            self.assertEqual(result['summary']['status'],'CANCELLED')
            self.assertEqual(result['summary']['saved_images'],1)
            self.assertTrue(result['summary']['lights_off']['acknowledged'])
            self.assertEqual(len(frames),1)

        def test_10_latest_failed_roi_never_falls_back(self):
            lab=clone_lab('bad03')
            bad=lab/'results/single_roi_20991231_failed'
            bad.mkdir()
            write_json(bad/'session.json',dict(status='FAILED'))
            with self.assertRaisesRegex(ValueError,'Newest 03'):
                capture.prepare_plan(lab)

        def test_11_zip_rejects_unsafe_paths_and_duplicates(self):
            for i, names in enumerate([['../escape'],['C:/escape'],['x\\escape'],['CON.txt'],['a.txt','A.txt']]):
                zip_path=a.out/('unsafe%d.zip'%i)
                with zipfile.ZipFile(zip_path,'w') as z:
                    for n in names:
                        z.writestr(n,b'never extract')
                # Windows ZipInfo normalizes backslashes when writing; restore that unsafe wire name.
                if any('\\' in n for n in names):
                    zip_path.write_bytes(zip_path.read_bytes().replace(b'x/escape',b'x\\escape'))
                with self.assertRaises(ValueError):
                    extract_zip(zip_path,a.out/('bad_extract%d'%i))
                self.assertFalse((a.out/('bad_extract%d'%i)).exists())

        def test_12_content_tamper_stops_analysis(self):
            source_path=Path(success['result']['output'])
            target=a.out/'tampered'
            shutil.copytree(source_path,target)
            f=read_json(target/'frames.json')[0]
            raw=target/f['raw']
            raw.write_bytes(raw.read_bytes()[:-2])
            with self.assertRaisesRegex(ValueError,'hash'):
                verify_inventory(target)

        def test_13_resealed_wrong_direction_still_rejected(self):
            target=a.out/'wrong_direction'
            shutil.copytree(success['result']['output'],target)
            frames=read_json(target/'frames.json')
            frames[0]['channel']=3
            summary=read_json(target/'operator_summary.json')
            summary['frames']=frames
            write_json(target/'frames.json',frames)
            write_json(target/'operator_summary.json',summary)
            (target/'output_manifest.json').unlink()
            seal_folder(target)
            # CPU child independently validates the sealed input's internal binding.
            with self.assertRaises(ValueError):
                workflow.run_analysis(target,a.out/'wrong_direction_analysis',allow_peer=True)

        def test_14_console_lock_prevents_concurrent_workflow(self):
            with workflow.console_lock(a.lab_root):
                with self.assertRaisesRegex(ValueError,'另一个09'):
                    with workflow.console_lock(a.lab_root):
                        pass

        def test_15_existing_two_boards_pixel_parity_all_published_arrays(self):
            sources=['fourlight_sample001_20261020_232625_5fceb2','fourlight_sample002_20261021_002054_e2f679']
            for sample,folder in zip(['sample001','sample002'],sources):
                target=a.out/('offline_'+sample)
                summary=workflow.run_analysis(a.lab_root/'results'/folder,target)
                self.assertFalse(summary['reference_annotations_used'])
                for mode in ['B1','M1']:
                    gold=(a.b1_root/sample/'B1/arrays.npz') if mode=='B1' else a.golden_root/sample/'M1/arrays.npz'
                    with np.load(gold) as g,np.load(target/(mode+'_arrays.npz')) as n:
                        self.assertEqual(set(g.files),set(n.files))
                        for key in g.files:
                            self.assertEqual(g[key].dtype,n[key].dtype,key)
                            self.assertTrue(np.array_equal(g[key],n[key]),sample+'/'+mode+'/'+key)
                    parity.append(dict(sample=sample,mode=mode,golden_sha256=digest(gold),all_18_arrays_exact=True,
                                       result=summary['modes'][mode]))

        def test_16_import_zip_is_readonly_and_creates_verified_bundle(self):
            src=a.lab_root/'results/fourlight_sample001_20261020_232625_5fceb2.zip'
            sha=digest(src)
            result=workflow.import_existing(a.lab_root,src)
            success['import']=result
            self.assertEqual(digest(src),sha)
            self.assertEqual(result['summary']['status'],'OFFLINE_ANALYZED_REVIEW_REQUIRED')
            self.assertFalse(result['summary']['physical_board_contacted_by_this_run'])
            verify_inventory(result['output'])
            with zipfile.ZipFile(result['archive']) as z:
                self.assertIsNone(z.testzip())
                self.assertIn('analysis/B1_arrays.npz',z.namelist())
            self.assertEqual(read_json(result['archive_receipt'])['archive_sha256'],digest(result['archive']))

        def test_17_auto_report_wrong_source_is_rejected_before_commands(self):
            reports=sorted(a.lab_root.glob('results/auto_exposure_sample001_20261016_164500_91354a'))
            self.assertEqual(len(reports),1)
            with patch.object(socket,'socket',side_effect=AssertionError('No socket')):
                with self.assertRaisesRegex(ValueError,'bound'):
                    capture.prepare_plan(a.lab_root,locked_report=reports[0])

        def test_18_gui_preflight_offline_render_and_clear_old_success(self):
            import tkinter as tk
            from inspection_app import InspectionApp
            root=tk.Tk()
            root.withdraw()
            errors=[]
            root.report_callback_exception=lambda *exc:errors.append(str(exc))
            app=InspectionApp(root,a.lab_root)
            try:
                deadline=time.monotonic()+25
                while (app.plan is None or app.busy()) and time.monotonic()<deadline:
                    root.update()
                    time.sleep(.02)
                self.assertIsNotNone(app.plan)
                self.assertFalse(errors,errors)
                self.assertFalse(app.confirm.get())
                app.display_result(success['import'])
                root.update()
                self.assertTrue(app.result_path)
                self.assertIn('未作合格判定',app.status.get())
                self.assertEqual(len(app.original_tab.winfo_children()),2)
                app.full_image(app.result_path/'analysis/B1_overlay.png').withdraw()
                root.update()
                app.clear_result()
                self.assertIsNone(app.result_path)
                self.assertEqual(len(app.b1_tab.winfo_children()),0)
                gui.update(preflight_rendered=True,results_rendered=True,original_pixel_view=True,stale_success_cleared=True,
                           hidden_tk_window=True,physical_board_used=False)
            finally:
                root.destroy()

        def test_19_original_bits_entries_and_07_08_unchanged(self):
            self.assertEqual({p:digest(p) for p in protected},protected)
            core.verify_vendor()

        def test_20_complete_workflow_over_localhost_is_explicitly_peer(self):
            lab=clone_lab('whole_peer')
            selected,_,_=capture.prepare_plan(lab)
            cls=core.progress_executor_class(engine,lambda *a,**k:None)
            analyze=workflow.run_analysis
            with Peer(sensor_size=(1920,1080)) as peer:
                def factory(*unused):
                    def build(**kw):
                        kw.update(board='127.0.0.1',bind='127.0.0.1',port=peer.endpoint[1],evidence_source='software_udp_peer')
                        return cls(**kw)
                    return build
                def peer_analysis(source,out,cancel=None,notify=lambda *a,**k:None):
                    return analyze(source,out,cancel,notify,allow_peer=True)
                with patch.object(capture,'executor_class',side_effect=factory),patch.object(workflow,'run_analysis',side_effect=peer_analysis):
                    result=workflow.execute(selected,confirmed_same_pose=True)
            self.assertEqual(result['summary']['status'],'ANALYZED_REVIEW_REQUIRED')
            self.assertEqual(result['summary']['evidence_source'],'software_udp_peer')
            self.assertFalse(result['summary']['operator_same_pose_confirmed'])
            self.assertEqual(result['summary']['analysis']['evidence_source'],'software_udp_peer')
            verify_inventory(result['output'])
            verify_inventory(Path(result['output'])/'acquisition')
            self.assertEqual(read_json(result['archive_receipt'])['archive_sha256'],digest(result['archive']))

        def test_21_missing_auto_confirmation_never_contacts_board(self):
            with patch.object(socket,'socket',side_effect=AssertionError('No socket')):
                with self.assertRaises(ValueError):
                    workflow.execute(plan,automatic=True,confirmed_same_pose=False)

        def test_22_pre_cancelled_analysis_has_no_output(self):
            event=threading.Event()
            event.set()
            target=a.out/'never_analysis'
            with self.assertRaises(InterruptedError):
                workflow.run_analysis(a.lab_root/'results',target,cancel=event)
            self.assertFalse(target.exists())

    with patch.object(socket,'socket',LocalSocket):
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    write_json(a.out/'verification.json',dict(status='PASS' if result.wasSuccessful() else 'FAIL',tests=result.testsRun,
               failures=len(result.failures),errors=len(result.errors),physical_board_used=False,
               socket_scope='guarded localhost only; planning has sockets disabled',
               exposure500_scope='Explicit injected 500-line transport test, not automatic-controller selection',
               parity=parity,gui=gui,protected_files_unchanged={p:digest(p) for p in protected}==protected,
               original_input_used_readonly=True,source_code_sha256={p.name:digest(p) for p in ROOT.glob('*.py')}))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    raise SystemExit(main())
