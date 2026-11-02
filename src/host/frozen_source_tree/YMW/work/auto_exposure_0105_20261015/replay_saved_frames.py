"""Offline, explicitly counterfactual replay of the two fixed-pose 12-frame pools."""
import argparse,collections,io,json,zipfile
from pathlib import Path
import cv2,numpy as np
import app_core as core

def replay(dataset,out):
    dataset=Path(dataset).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    d=core.load_engine();cm=d.xdl.capture_metrics;ac=d.xdl.acquisition_control
    from closed_loop import plain,canonical
    config=ac.ControllerConfig.from_dict(core.read_json(core.CONTROLLER/'config.json'))
    inputs=core.read_json(dataset/'input_manifest.json');experiments=[]
    for sample in ['sample001','sample002']:
        entry=next(r for r in inputs['archives'] if r['sample_id']==sample and r['role']=='repeat')
        path=dataset/entry['path']
        if core.digest(path)!=entry['sha256']:raise ValueError('Original dataset ZIP hash changed')
        full=next(r for r in inputs['archives'] if r['sample_id']==sample and r['role']=='full')
        if core.digest(dataset/full['path'])!=full['sha256']:raise ValueError('Full-frame geometry source ZIP hash changed')
        with zipfile.ZipFile(dataset/full['path']) as full_zip:geometry=json.loads(full_zip.read('plate_candidate.json'))
        context='saved_replay_'+sample;target=out/sample;target.mkdir()
        with zipfile.ZipFile(path) as z:
            session=json.loads(z.read('session.json'));roi=tuple(session['roi']);w,h=roi[2:]
            saved_native=np.load(io.BytesIO(z.read('plate_mask.npy')),allow_pickle=False).astype(bool)
            native=d.algorithm['board_mask']((h,w),geometry['polygon'],roi[:2])
            if np.any(native & ~saved_native):raise ValueError('Controller mask leaves original saved native mask')
            records={json.loads(z.read(n))['round_id'].rsplit('/',1)[-1]:(n,json.loads(z.read(n)))
                     for n in z.namelist() if n.endswith('/committed/result.json')}
            if len(records)!=12 or session['sample_id']!=sample:raise ValueError('Repeat specimen/count mismatch')
            pool=collections.defaultdict(collections.deque)
            for frame in session['frames']:pool[frame['requested_exposure_lines']].append(frame['name'])
            controller=ac.Controller(config,context);transitions=[];observations=[];consumed=[];area=None;native_rows=[]
            def transition(event=None):
                before=plain(controller.snapshot());decision=controller.start() if event is None else controller.feed(event)
                ev={'kind':'start'} if event is None else plain(event)
                after=plain(controller.snapshot());rs,rd=d.xdl.fpga_reference.reference_transition(before,ev,plain(config))
                if canonical((rs,rd))!=canonical((after,decision)):raise ValueError('Independent action reference mismatch')
                transitions.append(dict(before=before,event=ev,after=after,decision=plain(decision)));return decision
            decision=transition()
            while decision.status=='CONTINUE_ADJUST':
                e=decision.next_exposure_lines
                if not pool[e]:
                    decision=transition(ac.CaptureEvent('missing_data',context,None,e,None,None));break
                name=pool[e].popleft();member,r=records[name];prefix=member.removesuffix('result.json')
                png=z.read(prefix+'image.png');raw=z.read(prefix+'image.rgb565')
                if core.sha(raw)!=r['raw_rgb565_sha256'] or core.sha(png)!=r['png_sha256']:raise ValueError('Image SHA changed')
                actual=dict(exposure_lines=e,gain16=16,light_mask=1,brightness=128,settle_frames=1,discard_frames=3)
                if r['sample_id']!=sample or r['actual_parameters']!=actual:raise ValueError('Frame parameter/sample mismatch')
                oid=core.sha(canonical(r['identity']).encode())
                if oid in consumed:raise ValueError('Consumed saved observation twice')
                consumed.append(oid)
                frame=cm.FrameInput(context,oid,sample,path.stem,e,16,1,128,w,h,roi,r['png_sha256'],r['raw_rgb565_sha256'],
                    'offline_saved_real_image',dict(dataset_id=inputs['dataset_id'],capture_id=r['call_id'],frame_id=canonical(r['identity']),
                        member=prefix+'image.png',complete_identity=r['identity'],mask_source='frozen_xdl_inner_board_mask',board_mask_needs_manual_review=True))
                if area is None:
                    area=cm.build_common_area([frame],[native]);(target/'common_mask.bin').write_bytes(area.mask.tobytes())
                sources=area.sources+(dict(observation_id=oid,source_identity=cm.source_identity(frame),roi=roi,
                    native_mask_sha256=core.sha(native.tobytes()),mask_source='frozen_xdl_inner_board_mask',needs_manual_review=True),)
                coverage=area.coverage+(dict(observation_id=oid,native_area=int(native.sum()),common_area=int(area.mask.sum()),
                    coverage_numerator=int(area.mask.sum()),coverage_denominator=int(native.sum())),)
                view=cm.EvaluationArea(area.mask,sources,area.mask_sha256,coverage,area.available,area.reason_codes)
                image=cv2.imdecode(np.frombuffer(png,np.uint8),cv2.IMREAD_COLOR)
                metric,arrays=cm.compute_metrics(image,frame,native,view,d.algorithm)
                # Independent native device statistics are retained for cross-check.
                h1,h2=d.sdk.acquisition_support.image_metrics(raw,w,h,saved_native.tobytes())
                if list(r['statistics'].values())!=h1 or r['features']!=h2:raise ValueError('Saved native H1/H2 mismatch')
                observations.append(dict(name=name,exposure_lines=e,original_identity=r['identity'],original_record_member=member,
                    image_sha256=r['png_sha256'],native_device_statistics=r['statistics'],common_statistics=plain(metric.controller_statistics),
                    saved_original_native_count=int(saved_native.sum()),controller_mask_count=int(native.sum()),
                    saved_original_native_mask_sha256=core.sha(saved_native.tobytes()),controller_mask_sha256=core.sha(native.tobytes()),
                    geometry=plain(metric.geometry)))
                decision=transition(ac.CaptureEvent('observation',context,oid,e,metric,None))
            core.write_json(target/'decisions.json',transitions);core.write_json(target/'observations.json',observations)
            result=dict(sample_id=sample,controller_status=decision.status,reason_codes=list(decision.reason_codes),
                exposures=[r['exposure_lines'] for r in observations],consumed_observations=len(observations),source_zip_sha256=entry['sha256'],
                locked_exposure_lines=observations[-1]['exposure_lines'] if decision.status=='LOCKED' else None,
                context_mode='offline_counterfactual_saved_frame_replay',physical_live_loop_executed=False,
                normal_ground_truth=False,independent_reference_equal=True,original_capture_costs_not_reinterpreted=True)
            core.write_json(target/'summary.json',result);experiments.append(result)
    report=dict(status='PASS_OFFLINE_REFERENCE_REPLAY',experiments=experiments,source_dataset_id=inputs['dataset_id'],
        controller_mask_profile='xdl-board-mask-15x15-erode-saved-border4-v1',
        physical_board_used=False,real_online_control_verified=False,defect_accuracy_validated=False,controller_rules_modified=False,
        config_sha256=core.digest(core.CONTROLLER/'config.json'),notes=[
            'Only consumed images influence the frozen first-observation common area and controller.',
            'Saved observations are selected from a finite exposure pool without reuse; this is not execution of new settings.',
            'Original captures were 400/500/600/700 in sequence; reordered actions are counterfactual.',
            'Geometry is a candidate mask; LOCKED is a provisional imaging-rule result, not optimal exposure or defect accuracy.'])
    core.write_json(out/'verification.json',report);return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();print(json.dumps(replay(a.dataset,a.out),ensure_ascii=False,indent=2))
