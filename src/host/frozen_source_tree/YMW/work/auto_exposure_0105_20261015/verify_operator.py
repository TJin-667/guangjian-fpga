"""CPU/hidden-Tk/localhost verification only. Never opens a physical-board socket."""
import argparse,contextlib,hashlib,io,json,shutil,socket,sys,tempfile,threading,time,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import app_core as core

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',type=Path,default=Path('C:/BX72_0105_LAB'))
    p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    plan=core.make_plan(args.lab_root)
    fixture=Path(plan['source'])
    def clone_source(target):
        target.mkdir(parents=True)
        for name in ['session.json','plate_candidate.json','first_full.png','first_full.rgb565','plate_mask_CANDIDATE_NOT_REVIEWED.npy']:
            shutil.copy2(fixture/name,target/name)
        for record in (fixture/'calls').glob('*/committed/result.json'):
            destination=target/record.parent.relative_to(fixture);destination.mkdir(parents=True)
            for name in ['result.json','image.png','image.rgb565']:shutil.copy2(record.parent/name,destination/name)
        return target
    class OperatorTests(unittest.TestCase):
        def test_01_plan_is_offline_and_timeout_is_explicit(self):
            with patch.object(socket,'socket',side_effect=AssertionError('No sockets permitted for planning')):
                actual=core.make_plan(args.lab_root)
            self.assertEqual(actual['single_timeout_s'],30.0)
            self.assertEqual(actual['controller_config']['max_time_ms'],40000)
            self.assertEqual(actual['transaction_frames'],5)
            self.assertEqual(actual['controller_modeled_transaction_frames'],4)
            self.assertFalse(actual['board_bit_sha_readback_verified'])
        def test_02_mask_conversion_matches_original_array(self):
            data=core.load_source(fixture);m=data['mask'];w,h=data['roi'][2:]
            self.assertEqual(m.nbytes,w*h);self.assertEqual(set(np.unique(m)),{0,1})
            self.assertEqual(core.sha(m.tobytes()),plan['source_mask_raw_sha256'])
            self.assertFalse(m.flags.writeable)
        def test_03_source_image_change_rejected(self):
            source=clone_source(args.out/'bad_image');(source/'first_full.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'SHA'):core.load_source(source)
        def test_04_mask_nonbinary_rejected(self):
            source=clone_source(args.out/'bad_mask');m=np.load(source/'plate_mask_CANDIDATE_NOT_REVIEWED.npy');m[20,20]=2
            np.save(source/'plate_mask_CANDIDATE_NOT_REVIEWED.npy',m)
            with self.assertRaisesRegex(ValueError,'mask'):core.load_source(source)
        def test_05_mask_shape_rejected(self):
            source=clone_source(args.out/'bad_shape');np.save(source/'plate_mask_CANDIDATE_NOT_REVIEWED.npy',np.ones((20,20),np.uint8))
            with self.assertRaisesRegex(ValueError,'mask'):core.load_source(source)
        def test_06_newest_failed_source_has_no_stale_fallback(self):
            lab=args.out/'failed_latest';clone_source(lab/'results/single_full_20261015_100000_good')
            bad=lab/'results/single_full_20261015_110000_failed';bad.mkdir();core.write_json(bad/'session.json',{'status':'FAILED'})
            core.write_json(bad/'plate_candidate.json',{'status':'FAILED'})
            self.assertEqual(core.latest_source(lab),bad)
            with self.assertRaises(ValueError):core.load_source(core.latest_source(lab))
        def test_07_same_pose_confirmation_required_before_sockets(self):
            with patch.object(socket,'socket',side_effect=AssertionError('No board access')):
                with self.assertRaises(ValueError):core.run_real(plan,confirmed_same_pose=False)
        def test_08_source_change_after_confirmation_rejected(self):
            source=clone_source(args.out/'changed_after_plan');before=core.make_plan(args.lab_root,source)
            m=np.load(source/'plate_mask_CANDIDATE_NOT_REVIEWED.npy');m[20,20]=1-m[20,20]
            np.save(source/'plate_mask_CANDIDATE_NOT_REVIEWED.npy',m)
            with patch.object(socket,'socket',side_effect=AssertionError('No board access')):
                with self.assertRaises(ValueError):core.run_real(before,confirmed_same_pose=True)
        def test_09_double_program_lock_rejected(self):
            target=args.out/'mutex';target.mkdir()
            with core.operator_lock(target):
                with self.assertRaises(RuntimeError):
                    with core.operator_lock(target):pass
            with core.operator_lock(target):pass
        def test_10_peer_two_independent_confirmations_and_archive(self):
            events=[];result=core.run_peer(args.out/'peer_lock',notify=lambda kind,**d:events.append((kind,d)))
            s=result['summary'];self.assertEqual(s['status'],'LOCKED');self.assertEqual(s['attempts'],2)
            self.assertTrue(s['lights_off']['acknowledged']);self.assertFalse(s['physical_board_used'])
            images=[d for k,d in events if k=='image'];self.assertEqual(len(images),2)
            self.assertNotEqual(images[0]['identity'],images[1]['identity'])
            with zipfile.ZipFile(result['archive']) as z:
                self.assertIsNone(z.testzip());inventory=json.loads(z.read('output_manifest.json'))['files']
                for name,digest in inventory.items():self.assertEqual(core.sha(z.read(name)),digest)
        def test_11_peer_capture_error_retains_failure_and_off(self):
            result=core.run_peer(args.out/'peer_failure',fault_plan={1:'missing_packet',2:'missing_packet'})
            s=result['summary'];self.assertEqual(s['status'],'CAPTURE_FAILED');self.assertEqual(s['accepted_observations'],0)
            self.assertTrue(s['lights_off']['acknowledged']);self.assertEqual(s['independent_audit']['status'],'PASS')
        def test_12_peer_cancel_retains_no_success_and_off(self):
            cancel=threading.Event()
            def notify(event,**d):
                if event=='capture':cancel.set()
            result=core.run_peer(args.out/'peer_cancel',notify=notify,cancel=cancel)
            self.assertNotEqual(result['summary']['status'],'LOCKED');self.assertTrue(result['summary']['lights_off']['acknowledged'])
        def test_13_hidden_gui_worker_progress_and_responsiveness(self):
            import tkinter as tk
            from auto_exposure_app import App
            root=tk.Tk();root.withdraw();beats=[];pulse_job=[None]
            def pulse():
                beats.append(time.monotonic());pulse_job[0]=root.after(20,pulse)
            def runner(plan,*,notify,cancel,**kw):return core.run_peer(args.out/'gui_peer',notify=notify,cancel=cancel)
            app=App(root,args.lab_root,runner=runner,autoload=False);app.accept_plan(plan)
            self.assertIn('disabled',app.start_button.state());app.confirm.set(True)
            self.assertNotIn('disabled',app.start_button.state());app.start();pulse();deadline=time.monotonic()+20
            try:
                while app.state!='idle' and time.monotonic()<deadline:root.update();time.sleep(.005)
                self.assertEqual(app.state,'idle');self.assertIsNotNone(app.last_result)
                self.assertEqual(app.last_result['summary']['status'],'LOCKED');self.assertFalse(app.confirm.get())
                self.assertIn('600',app.quality.get());self.assertTrue(app.photo is not None)
                gap=max((b-a for a,b in zip(beats,beats[1:])),default=0);self.assertLess(gap,.75)
                core.write_json(args.out/'gui_heartbeat.json',dict(max_gap_s=gap,beats=len(beats),hidden_tk=True,physical_board_used=False))
            finally:
                if pulse_job[0] is not None:root.after_cancel(pulse_job[0])
                app.destroy()
        def test_14_hidden_gui_cancel_button(self):
            import tkinter as tk
            from auto_exposure_app import App
            root=tk.Tk();root.withdraw()
            def runner(plan,*,notify,cancel,**kw):return core.run_peer(args.out/'gui_cancel',notify=notify,cancel=cancel,fault_plan={1:'slow_capture'})
            app=App(root,args.lab_root,runner=runner,autoload=False);app.accept_plan(plan);app.confirm.set(True);app.start()
            root.after(80,app.stop);deadline=time.monotonic()+20
            try:
                while app.state!='idle' and time.monotonic()<deadline:root.update();time.sleep(.005)
                self.assertEqual(app.state,'idle');self.assertTrue(app.cancel.is_set());self.assertIsNotNone(app.last_result)
                self.assertNotEqual(app.last_result['summary']['status'],'LOCKED');self.assertTrue(app.last_result['summary']['lights_off']['acknowledged'])
            finally:app.destroy()
        def test_15_frozen_vendor_unchanged(self):core.verify_vendor()
        def test_16_full_operator_path_through_localhost_only(self):
            # Exercise the production orchestration (including OS lock, source
            # snapshots, full-size ROI, audit, OFF and ZIP) against an explicitly
            # software-labelled peer. No physical endpoint can reach socket().
            lab=args.out/'full_backend_lab';lab.mkdir()
            for rel in ['runtime_provenance.json','bx72_0105_lab.bit']+['runtime/software/'+n for n in ['acquisition_executor.py','acquisition_support.py','identity_diag.py']]:
                target=lab/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(args.lab_root/rel,target)
            engine=core.load_engine(include_peer=True)
            from software_peer import make_peer_class
            Peer=make_peer_class(engine);factory=core.progress_executor_class
            with Peer(sensor_size=(1920,1080)) as peer:
                def peer_factory(d,notify):
                    cls=factory(d,notify)
                    def constructor(**kw):
                        kw.update(board='127.0.0.1',port=peer.endpoint[1],bind='127.0.0.1',evidence_source='software_udp_peer')
                        return cls(**kw)
                    return constructor
                with patch.object(core,'load_engine',return_value=engine),patch.object(core,'progress_executor_class',side_effect=peer_factory):
                    planned=core.make_plan(lab,fixture)
                    result=core.run_real(planned,confirmed_same_pose=True)
            s=result['summary'];self.assertEqual(s['status'],'LOCKED');self.assertEqual(s['locked_exposure_lines'],600)
            self.assertEqual(s['evidence_source'],'software_udp_peer');self.assertFalse(s['operator_same_pose_confirmed'])
            self.assertTrue(s['lights_off']['acknowledged']);self.assertEqual(s['independent_audit']['status'],'PASS')
            self.assertEqual(s['transport_cost']['known_frames'],10);self.assertEqual(len(peer.captured),2)
            observations=core.read_json(Path(result['output'])/'loop/observations.json')
            self.assertEqual(s['uploaded_native_mask_pixels'],602441);self.assertEqual(s['original_source_mask_pixels'],624533)
            self.assertTrue(all(o['native_device_statistics']['board_count']==602441 and o['common_statistics']['n']==602441 for o in observations))
            self.assertEqual(core.digest(Path(result['output'])/'native_mask.bin'),planned['controller_native_mask_sha256'])
            original_mask=np.load(Path(result['output'])/'source_mask.npy',allow_pickle=False)
            self.assertEqual(int(original_mask.sum()),624533)
            self.assertEqual(core.digest(Path(result['output'])/'source_full.png'),planned['source_full_png_sha256'])
            self.assertEqual(core.digest(Path(result['output'])/'source_result.json'),planned['source_result_sha256'])
            receipt=core.read_json(result['archive_receipt'])
            self.assertGreater(s['host_elapsed_ms_before_archive'],s['preflight_and_source_snapshot_host_ms'])
            self.assertGreater(receipt['host_elapsed_ms_through_archive'],s['host_elapsed_ms_before_archive'])
            self.assertGreaterEqual(s['independent_audit_host_ms'],0);self.assertGreaterEqual(s['lights_off_host_ms'],0)
        def test_17_committed_source_identity_mismatch_rejected(self):
            source=clone_source(args.out/'bad_committed_identity');record=next((source/'calls').glob('*/committed/result.json'))
            data=core.read_json(record);data['identity']['frame_id']+=1;core.write_json(record,data)
            with self.assertRaisesRegex(ValueError,'身份'):core.load_source(source)
        def test_18_source_wrong_specimen_or_parameters_rejected(self):
            source=clone_source(args.out/'bad_committed_specimen');record=next((source/'calls').glob('*/committed/result.json'))
            data=core.read_json(record);original=data.copy()
            for field,value in [('sample_id','some_other_plate'),('actual_parameters',dict(exposure_lines=700)),('strict_verified',False),('evidence_source','software_udp_peer')]:
                with self.subTest(field=field):
                    changed=dict(original);changed[field]=value;core.write_json(record,changed)
                    with self.assertRaises(ValueError):core.load_source(source)
        def test_19_source_missing_record_or_raw_mismatch_rejected(self):
            source=clone_source(args.out/'bad_raw');raw=source/'first_full.rgb565';original=raw.read_bytes()
            raw.write_bytes(bytes([original[0]^1])+original[1:])
            with self.assertRaisesRegex(ValueError,'SHA'):core.load_source(source)
            raw.write_bytes(original);next((source/'calls').glob('*/committed/result.json')).unlink()
            with self.assertRaisesRegex(ValueError,'唯一'):core.load_source(source)
        def test_20_source_preview_rebuilt_without_old_overlay(self):
            import cv2
            source=clone_source(args.out/'no_old_overlay');snapshot=core.load_source(source)
            self.assertFalse((source/'plate_candidate_overlay.png').exists())
            rebuilt=core.source_preview(snapshot);image=cv2.imdecode(np.frombuffer(rebuilt,np.uint8),cv2.IMREAD_COLOR)
            self.assertEqual(image.shape,(1080,1920,3));self.assertNotEqual(core.sha(rebuilt),snapshot['full_png_sha256'])
            self.assertEqual(core.digest(source/'first_full.png'),snapshot['full_png_sha256'])
        def test_21_plan_rejects_changed_source_record_before_socket(self):
            source=clone_source(args.out/'changed_record');before=core.make_plan(args.lab_root,source)
            record=next((source/'calls').glob('*/committed/result.json'));data=core.read_json(record)
            data['review_annotation']='Changed after approval';core.write_json(record,data)
            with patch.object(socket,'socket',side_effect=AssertionError('No board access')):
                with self.assertRaisesRegex(ValueError,'变化'):core.run_real(before,confirmed_same_pose=True)
        def test_22_source_snapshot_survives_later_file_changes(self):
            source=clone_source(args.out/'immutable_snapshot');snapshot=core.load_source(source);preview=core.source_preview(snapshot)
            for name in ['first_full.png','plate_candidate.json','session.json','plate_mask_CANDIDATE_NOT_REVIEWED.npy']:
                (source/name).write_bytes(b'replaced after snapshot')
            self.assertEqual(core.source_preview(snapshot),preview)
            self.assertEqual(core.sha(snapshot['full_png_bytes']),snapshot['full_png_sha256'])
            self.assertEqual(core.sha(snapshot['geometry_bytes']),snapshot['geometry_sha256'])
            self.assertFalse(snapshot['mask'].flags.writeable)
        def test_23_hidden_gui_new_source_clears_old_results(self):
            import tkinter as tk
            from auto_exposure_app import App
            root=tk.Tk();root.withdraw();app=App(root,args.lab_root,autoload=False)
            try:
                app.accept_plan(plan);app.quality.set('Old specimen metrics');app.result_text.set('Old LOCKED700')
                app.last_result={'output':'old'};app.confirm.set(True);app.accept_plan(plan)
                self.assertNotIn('Old',app.quality.get());self.assertNotIn('Old',app.result_text.get())
                self.assertIsNone(app.last_result);self.assertFalse(app.confirm.get());self.assertTrue(app.preview_ready)
                self.assertIn('disabled',app.start_button.state());self.assertIn('disabled',app.open_button.state())
            finally:app.destroy()
        def test_24_hidden_gui_invalid_preview_blocks_start(self):
            import tkinter as tk
            from auto_exposure_app import App
            root=tk.Tk();root.withdraw();called=[];app=App(root,args.lab_root,runner=lambda *a,**k:called.append(True),autoload=False)
            try:
                app.accept_plan(plan,preview_png=b'invalid PNG');app.confirm.set(True);app.start()
                self.assertFalse(app.preview_ready);self.assertIsNone(app.photo);self.assertEqual(app.state,'idle')
                self.assertIn('disabled',app.start_button.state());self.assertFalse(called)
            finally:app.destroy()
        def test_25_archive_write_failure_does_not_publish_zip(self):
            out=args.out/'archive_write_fault';out.mkdir();(out/'raw.bin').write_bytes(b'original')
            with patch.object(zipfile.ZipFile,'write',side_effect=OSError('Injected disk write failure')):
                with self.assertRaises(core.ArchiveError) as raised:core.finalize_output(out,{'status':'NEED_REVIEW'})
            self.assertEqual(raised.exception.output,str(out));self.assertFalse(Path(str(out)+'.zip').exists())
            self.assertFalse(list(args.out.glob('archive_write_fault.zip.*.part')))
            self.assertEqual((out/'raw.bin').read_bytes(),b'original')
            self.assertFalse(core.read_json(out/'archive_error.json')['published_zip'])
        def test_26_archive_verification_failure_does_not_publish_zip(self):
            out=args.out/'archive_verify_fault';out.mkdir();(out/'raw.bin').write_bytes(b'original')
            original_hash=core.hash_stream
            def corrupted(stream):
                if isinstance(stream,zipfile.ZipExtFile):return '0'*64
                return original_hash(stream)
            with patch.object(core,'hash_stream',side_effect=corrupted):
                with self.assertRaises(core.ArchiveError):core.finalize_output(out,{'status':'NEED_REVIEW'})
            self.assertFalse(Path(str(out)+'.zip').exists());self.assertTrue((out/'raw.bin').exists())
        def test_27_archive_never_overwrites_existing_target(self):
            out=args.out/'archive_existing';out.mkdir();target=Path(str(out)+'.zip');target.write_bytes(b'previous valid data')
            with self.assertRaises(core.ArchiveError):core.finalize_output(out,{'status':'NEED_REVIEW'})
            self.assertEqual(target.read_bytes(),b'previous valid data')
        def test_28_archive_preserves_dotted_specimen_name_and_receipt(self):
            out=args.out/'auto_exposure_plate.002_20261015_unique';out.mkdir();(out/'raw.bin').write_bytes(b'original')
            result=core.finalize_output(out,{'status':'NEED_REVIEW'});archive=Path(result['archive'])
            self.assertEqual(archive.name,out.name+'.zip');receipt=core.read_json(result['archive_receipt'])
            self.assertEqual(receipt['archive_sha256'],core.digest(archive));self.assertGreater(receipt['inventory_compression_verification_ms'],0)
        def test_29_hidden_gui_poll_recovers_from_bad_display_event(self):
            import tkinter as tk
            from auto_exposure_app import App
            root=tk.Tk();root.withdraw();app=App(root,args.lab_root,autoload=False)
            try:
                app.accept_plan(plan);root.after_cancel(app.poll_job);app.poll_job=None
                app.notify('decision',decision=None);app.poll()
                self.assertIsNotNone(app.poll_job);self.assertFalse(app.preview_ready)
                app.notify('run_error',message='Injected compression failure',trace='test only',output=str(args.out))
                root.after_cancel(app.poll_job);app.poll_job=None;app.poll()
                self.assertEqual(app.last_result['output'],str(args.out));self.assertNotIn('disabled',app.open_button.state())
            finally:app.destroy()
        def test_30_both_current_physical_source_records_accepted(self):
            # Read-only validation of the two already captured full-frame sources.
            roots=[args.lab_root/'results'/name for name in ['single_full_20261015_172014_e719d0','single_full_20261015_173726_d6b0ef']]
            for source in roots:
                with self.subTest(source=source.name):
                    snapshot=core.load_source(source);self.assertIn(snapshot['sample_id'],['sample001','sample002'])
                    self.assertGreater(snapshot['mask_pixels'],600000)
        def test_31_controller_mask_matches_frozen_xdl_profile(self):
            counts={'single_full_20261015_172014_e719d0':(624567,602405),'single_full_20261015_173726_d6b0ef':(624533,602441)}
            for name,(original,inner) in counts.items():
                with self.subTest(sample=name):
                    planned,snapshot=core.prepare_plan(args.lab_root,args.lab_root/'results'/name)
                    self.assertEqual(planned['schema'],3);self.assertEqual(planned['source_mask_pixels'],original)
                    self.assertEqual(planned['mask_pixels'],inner);self.assertFalse(snapshot['controller_native_mask'].flags.writeable)
                    self.assertFalse(np.any(snapshot['controller_native_mask'] & ~snapshot['mask'].astype(bool)))
                    self.assertEqual(core.sha(snapshot['controller_native_mask'].tobytes()),planned['controller_native_mask_sha256'])
        def test_32_old_or_tampered_mask_plan_requires_new_approval(self):
            for altered in [dict(plan,schema=2),dict(plan,controller_native_mask_sha256='0'*64)]:
                with self.subTest(schema=altered['schema']):
                    with patch.object(socket,'socket',side_effect=AssertionError('No board access')):
                        with self.assertRaisesRegex(ValueError,'变化'):core.run_real(altered,confirmed_same_pose=True)
    buffer=io.StringIO();suite=unittest.defaultTestLoader.loadTestsFromTestCase(OperatorTests)
    result=unittest.TextTestRunner(stream=buffer,verbosity=2).run(suite)
    (args.out/'test_log.txt').write_text(buffer.getvalue(),encoding='utf-8')
    report=dict(status='PASS' if result.wasSuccessful() and result.testsRun==32 and not result.skipped else 'FAIL',tests=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),physical_board_used=False,
        source_sha256={p.name:core.digest(p) for p in [core.PACKAGE/'app_core.py',core.PACKAGE/'auto_exposure_app.py',Path(__file__)]})
    core.write_json(args.out/'verification.json',report);print(buffer.getvalue());print(json.dumps(report,indent=2))
    return 0 if report['status']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
