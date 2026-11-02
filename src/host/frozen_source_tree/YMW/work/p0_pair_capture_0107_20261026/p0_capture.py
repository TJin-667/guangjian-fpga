"""Isolated P0 RGB acquisition on existing0107; original09 and gates unchanged."""
import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'acceptance_0107_resume_20261026'))
import resume_acceptance as shared
import cv2
import numpy as np

original, host, sdk, bridge = shared.original, shared.original.host, shared.sdk, shared.bridge
read, sha, need, write, say = shared.read, shared.sha, shared.require, shared.write, shared.say
XDL_COMMIT = '0cb2c6e25878016cb8813169e514f155ab0cc574'


def polygon_mask(points, sensor_size):
    width, height = sensor_size
    pts = np.asarray(points, dtype=np.float64)
    need(pts.shape == (4, 2) and np.isfinite(pts).all(), 'Select exactly four board corners')
    need((pts >= 0).all() and (pts[:, 0] < width).all() and (pts[:, 1] < height).all(), 'Board corner outside image')
    pts = np.rint(pts).astype(np.int32)
    need(cv2.isContourConvex(pts) and abs(cv2.contourArea(pts)) >= 81, 'Corners must follow a non-crossing board boundary')
    mask = np.zeros((height, width), np.uint8)
    cv2.fillConvexPoly(mask, pts, 1)
    # Keep the 9x9 support away from the physical board edge.
    mask = cv2.erode(mask, np.ones((9, 9), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)
    need(mask.sum() >= 81, 'Selected board interior is too small')
    return mask


def select_board(png, specimen, variant):
    import tkinter as tk
    from tkinter import messagebox
    from PIL import Image, ImageTk, ImageOps
    image = Image.open(png).convert('RGB')
    width, height = image.size
    scale = min(960 / width, 540 / height, 1)
    shown = ImageOps.autocontrast(image).resize((round(width * scale), round(height * scale)))
    root = tk.Tk(); root.title('P0 ' + specimen + ' ' + variant)
    tk.Label(root, text=specimen + ' ' + variant + '：确认实物板号；沿板面内缘依次点4个角', font=('Microsoft YaHei', 13)).pack()
    tk.Label(root, text='包含要研究的全部划痕。只选板面，不描划痕；显示已提亮，原图不变。右键撤销。').pack()
    photo = ImageTk.PhotoImage(shown)
    canvas = tk.Canvas(root, width=shown.width, height=shown.height); canvas.pack()
    canvas.create_image(0, 0, anchor='nw', image=photo)
    points = []; answer = []
    def redraw():
        canvas.delete('selection')
        values = [(x * scale, y * scale) for x, y in points]
        for x, y in values: canvas.create_oval(x-4, y-4, x+4, y+4, fill='yellow', tags='selection')
        if len(values) > 1: canvas.create_line(*[v for pair in values for v in pair], fill='yellow', width=2, tags='selection')
        if len(values) == 4: canvas.create_line(*values[-1], *values[0], fill='yellow', width=2, tags='selection')
    def click(event):
        if len(points) < 4:
            points.append((min(width-1, max(0, event.x/scale)), min(height-1, max(0, event.y/scale))))
            redraw()
    def undo(event=None):
        if points: points.pop(); redraw()
    def accept():
        try: polygon_mask(points, (width, height))
        except ValueError as exc: messagebox.showerror('请重新选板面', str(exc), parent=root); return
        answer.extend(points); root.destroy()
    def clear(): points.clear(); redraw()
    buttons = tk.Frame(root); buttons.pack()
    tk.Button(buttons, text='清空重选', command=clear).pack(side='left')
    tk.Button(buttons, text='取消并保留已有结果', command=root.destroy).pack(side='left')
    tk.Button(buttons, text='确认板号/板面未移动，开始8张', command=accept).pack(side='left')
    canvas.bind('<Button-1>', click); canvas.bind('<Button-3>', undo)
    root.bind('<Escape>', lambda event: root.destroy()); root.protocol('WM_DELETE_WINDOW', root.destroy)
    root.mainloop()
    need(len(answer) == 4, 'Operator cancelled; no formal group captured')
    return answer


class Runtime(original.Runtime):
    evidence_source = 'real_board'
    sensor_size = (1920, 1080)
    bridge_sensor_size = (1920, 1080)

    def __init__(self, specimen, variant, pose):
        super().__init__()
        need(specimen in ('sample005', 'sample004') and variant == 'A_v1', 'P0 only supports the requested completed A_v1 surfaces')
        self.specimen, self.variant, self.pose = specimen, variant, pose
        self.mask_path = self.preview_record = self.preview_png = None

    def context(self, mask):
        width, height = self.sensor_size
        return host.legacy.backend.Context(self.specimen, self.pose, (0, 0, width, height), mask)

    def archive(self, out, summary):
        summary.update(training_data=False, labels='UNLABELED', optical_quality_evaluated=False,
                       release_ready=False, external_IO_qualified=False, production09_switched=False)
        return self.core.finalize_output(out, summary)


def plan_for(runtime, preview=False):
    candidate, proofs, sources = runtime.candidate()
    need(candidate['ready'], 'Existing0107 candidate binding not ready')
    width, height = runtime.sensor_size
    if preview:
        mask = bytes([1]) * (width * height)
        source_files = {}
    else:
        mask = runtime.mask_path.read_bytes()
        need(len(mask) == width*height and set(mask) <= {0, 1} and any(mask), 'Invalid physical board mask')
        source_files = {'source_preview.png':runtime.preview_png.read_bytes(),
                        'source_preview_record.json':runtime.preview_record.read_bytes(), 'source_board_mask.bin':mask,
                        'P0_CONTEXT.json':json.dumps(dict(specimen=runtime.specimen, variant=runtime.variant, pose=runtime.pose,
                            source='new0107_P0_preview', board_mask_operator_confirmed=True,
                            mask_is_geometric_board_interior_not_scratch_label=True, XDL_request_commit=XDL_COMMIT), sort_keys=True).encode()}
        sources.update({str(p):sha(p) for p in (runtime.mask_path, runtime.preview_record, runtime.preview_png)})
    source_files.update(proofs)
    sources.update(sdk.SOURCE_SNAPSHOT)
    sources[str(HERE/'p0_capture.py')] = sha(HERE/'p0_capture.py')
    plan = dict(schema='p0-paired-0107-source-plan-v1', pixel_format=1, low=400, high=800,
        gain16=16, brightness=128, settle_frames=1, discard_frames=3, physical_specimen_id=runtime.specimen,
        pose_id=runtime.pose, specimen_variant=runtime.variant, pair_status='development_trial',
        source_contract=dict(source='new0107_P0_preview' if not preview else 'P0_initialization_only',
            board='192.168.0.2', bind='192.168.0.3', port=5000),
        candidate=candidate, runtime_sha256=sources, implementation_sha256={},
        source_snapshot_sha256={k:sdk.support.sha_bytes(v) for k,v in source_files.items()},
        board_mask_sha256=sdk.support.sha_bytes(mask), XDL_request_commit=XDL_COMMIT,
        same_pose_operator_confirmation_required=True, release_ready=False)
    return plan, runtime.context(mask), source_files


def capture_preview(runtime, out):
    out.mkdir(); result = None; off = None; error = None
    plan, context, _ = plan_for(runtime, preview=True)
    try:
        with runtime.guard():
            executor = runtime.executor(plan, out)
            try:
                result = executor.acquire(light_channel=1, brightness=128, exposure_lines=600, gain16=16,
                    roi=context.roi, board_mask=context.mask, settle_frames=1, discard_frames=3,
                    timeout_s=300, sample_id=runtime.specimen, round_id='P0_INITIALIZATION_ONLY')
                bridge.load_commit(result.record_path, sensor_size=runtime.sensor_size)
            finally:
                try: off = executor.lights_off(timeout_s=3)
                finally: executor.close()
    except BaseException as exc: error = str(exc)
    receipt = runtime.archive(out, dict(status='PREVIEW_READY' if result and off and off['acknowledged'] and not error else 'FAILED',
        error=error, initialization_only=True, formal_images=0, lights_off=off,
        record=result.record_path.relative_to(out).as_posix() if result else None, evidence_source=runtime.evidence_source))
    need(receipt['summary']['status'] == 'PREVIEW_READY', 'Preview failed; results preserved: ' +
         str(error or (off or {}).get('error') or 'Lights OFF was not acknowledged'))
    return result


def capture_eight(runtime, out, plan, context, files):
    out.mkdir(); entries = []; validated = []; failure = None; off = {'acknowledged':False}; executor = None
    started = time.monotonic()
    try:
        with runtime.guard():
            need(plan_for(runtime)[0] == plan, 'Source/mask/bit changed while waiting for shared lock')
            for name, data in files.items():
                path = out/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            write(out/'approved_plan.json', plan)
            executor = runtime.executor(plan, out)
            try:
                for channel in range(1, 5):
                    for role in ('low', 'high'):
                        need(not host.check_hashes(plan), 'Changed source/build/mask during batch')
                        need(time.monotonic()-started < 900, 'P0 batch deadline reached')
                        say(f'Capturing {runtime.specimen} CH{channel} {role} {plan[role]}lines; completed {len(entries)}/8')
                        result = executor.acquire(light_channel=channel, brightness=128, exposure_lines=plan[role], gain16=16,
                            roi=context.roi, board_mask=context.mask, settle_frames=1, discard_frames=3,
                            timeout_s=300, sample_id=runtime.specimen, round_id=runtime.pose)
                        row = host.audit_result(result, plan, context, out, channel, role, validated[-1] if validated else None)
                        bridge.load_commit(result.record_path, sensor_size=runtime.sensor_size)
                        validated.append(row)
                        entries.append(dict(observation_id=f'CH{channel}_{role}', physical_specimen_id=runtime.specimen,
                            sample_id=runtime.specimen, pose_id=runtime.pose, channel=channel, role=role,
                            record=result.record_path.relative_to(out).as_posix(), identity=row['validated']['metadata']['identity'],
                            payload_sha256=row['validated']['payload_sha256']))
                        write(out/'observations.json', entries)
                dataset = host.fixed_eight.validate_eight(validated, sample_id=runtime.specimen, pose_id=runtime.pose,
                    low=400, high=800, roi=list(context.roi), board=np.frombuffer(context.mask,np.uint8).reshape(runtime.sensor_size[::-1]).astype(bool))
                write(out/'fixed_eight_dataset.json', dataset)
            finally:
                try: off = executor.lights_off(timeout_s=3)
                finally: executor.close()
    except BaseException as exc: failure = dict(type=type(exc).__name__, message=str(exc))
    changed = host.check_hashes(plan)
    status = 'ACQUIRED_EIGHT_REVIEW_REQUIRED' if len(entries)==8 and failure is None and not changed and off['acknowledged'] else 'FAILED'
    return runtime.archive(out, dict(schema='fixed-pair-operator-0107-v1', status=status, error=failure,
        evidence_source=runtime.evidence_source, physical_specimen_id=runtime.specimen, sample_id=runtime.specimen,
        pose_id=runtime.pose, specimen_variant=runtime.variant, low=400, high=800, saved_observations=len(entries),
        lights_off=off, changed_source_or_build_files=changed, pixel_format=1,
        operator_same_specimen_and_pose_confirmed=True, full_source_RGB_retained=True,
        mask_is_physical_board_interior=True, initial_preview_is_not_formal_frame=True,
        maximum_formal_CAP=8, automatic_recapture=False, elapsed_s=time.monotonic()-started))


def export_xdl(root, runtime):
    bridge.export_batch(root/'acquisition', root/'model_inputs', sensor_size=runtime.sensor_size)
    group = read(root/'model_inputs/group.json'); observations=[]
    runner = bridge.xdl_reference.load('run')
    for entry in group['entries']:
        frame_root = root/'model_inputs'/entry['frame_root']
        frame, manifest = bridge.load_frame(frame_root)
        prefix = frame_root.relative_to(root).as_posix()
        fields = dict(manifest['xdl_fields'])
        for key in ('gray8_path', 'sat1_path', 'valid_mask_path'): fields[key] = prefix+'/'+fields[key]
        fields.update(source_path=prefix+'/capture/image.png', source_sha256=sha(frame_root/'capture/image.png'),
            frame_payload_sha256=None, observation_id=entry['slot'], specimen_id=runtime.specimen,
            pose_id=runtime.pose, direction='CH'+str(entry['channel']), exposure_role=entry['role'],
            exposure_lines=frame.metadata['parameters']['exposure_lines'], gain16=16, led=128,
            valid_mask_id=frame.record['mask_sha256'])
        runner._load_observation(fields, root)
        observations.append(fields)
    document=dict(manifest_schema='exposure_fusion_group_v1', dataset_revision=runtime.pose,
        exposure_pair_status='DEVELOPMENT_CANDIDATE_400_800_NOT_OPTIMAL',
        labels='UNLABELED_PENDING_HUMAN_REVIEW', groups=[dict(group_id=runtime.pose, specimen_id=runtime.specimen,
            specimen_variant=runtime.variant, board_face='A', pose_id=runtime.pose, capture_round=runtime.pose,
            repeat_id='r01', observations=observations)])
    write(root/'XDL_manifest.json', document)
    return document


def run(out, runtime, selector=select_board):
    out=Path(out).resolve(); out.mkdir(parents=True, exist_ok=False)
    status='FAILED'; phase='preflight'; error=None; results={}
    say('STARTED: P0 development capture. Existing0107 RGB; no bit programming. Keep board and camera fixed.')
    try:
        plan_for(runtime, preview=True)
        phase='preview'; say('One600line positioning preview; not a training/pair frame. Progress every5seconds.')
        with shared.Progress(out, interval=5): preview=capture_preview(runtime, out/'preview')
        phase='select_board'; say('Preview ready; lights OFF acknowledged. Select four inner board corners in the window, then confirm the specimen.')
        points=selector(preview.png_path, runtime.specimen, runtime.variant)
        mask=polygon_mask(points, runtime.sensor_size)
        runtime.preview_record=preview.record_path; runtime.preview_png=preview.png_path
        runtime.mask_path=out/'selected_board_mask.bin'; runtime.mask_path.write_bytes(mask.tobytes())
        write(out/'board_selection.json', dict(points_xy=points, inset_pixels=4, board=runtime.specimen,
            variant=runtime.variant, pose_id=runtime.pose, operator_confirmed=True, preview_sha256=sha(preview.png_path),
            labels='NONE; geometric valid mask only', input_dimensions=list(runtime.sensor_size)))
        plan,context,files=plan_for(runtime)
        phase='capture_eight'; say('Confirmed: capturing8 full RGB frames with same-frame gray/SAT and the selected physical board mask.')
        with shared.Progress(out, interval=5): results['acquisition']=capture_eight(runtime,out/'acquisition',plan,context,files)
        need(results['acquisition']['summary']['status']=='ACQUIRED_EIGHT_REVIEW_REQUIRED', 'Eight-request capture failed; preserve results and stop')
        phase='export'; say('8/8 verified; lights OFF acknowledged. Exporting and checking XDL input, please keep the window open.')
        results['XDL_manifest']='XDL_manifest.json'; export_xdl(out,runtime)
        status='P0_PAIR_READY_FOR_LABEL_REVIEW'; phase='complete'
    except BaseException as exc:
        error=dict(type=type(exc).__name__, message=str(exc)); say('STOPPED: '+str(exc)+'. Results preserved; do not repeat blindly.')
    return runtime.archive(out,dict(status=status,phase=phase,error=error,results=results,
        physical_specimen_id=runtime.specimen,specimen_variant=runtime.variant,pose_id=runtime.pose,
        evidence_source=runtime.evidence_source,formal_observations=8 if status=='P0_PAIR_READY_FOR_LABEL_REVIEW' else None,
        maximum_new_CAP=9, positioning_preview_CAP=1, source_RGB_retained=True, XDL_request_commit=XDL_COMMIT,
        paired_raw_usable_pending_human_review=status=='P0_PAIR_READY_FOR_LABEL_REVIEW',
        no_key_reset_required=True,no_bit_programmed=True,exposure_optimum_verified=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specimen',choices=['sample005','sample004'],required=True)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(); pose=args.specimen+'_A_v1_'+time.strftime('%Y%m%d_%H%M%S')
    runtime=Runtime(args.specimen,'A_v1',pose)
    if args.check_only:
        plan_for(runtime,preview=True)
        print(json.dumps(dict(status='OFFLINE_READY',specimen=args.specimen,hardware_contacted=False,bit_download_required=False)));raise SystemExit(0)
    need(args.out is not None,'New output directory required')
    result=run(args.out,runtime); print(json.dumps(dict(status=result['summary']['status'],result=result['archive'],directory=str(args.out)),indent=2))
    raise SystemExit(0 if result['summary']['status']=='P0_PAIR_READY_FOR_LABEL_REVIEW' else 2)
