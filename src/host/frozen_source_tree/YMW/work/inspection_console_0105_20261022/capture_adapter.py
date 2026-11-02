"""09 acquisition adapter derived from frozen 08; 01--08 are not edited."""
import hashlib
import importlib.util
import re
import secrets
import sys
import threading
import time
from pathlib import Path
import numpy as np
from common import digest, read_json, require, verify_inventory, seal_folder

LEGACY_SHA = 'd0a537d7cf0a336bb93a8b1d6f4270430e0032d326c77ca699c79dbdecb2fd6d'
CHANNELS = ((1, 'top'), (2, 'right'), (3, 'bottom'), (4, 'left'))


def legacy(lab):
    path = Path(lab).resolve() / 'fourlight_fixed_v1/fourlight_capture.py'
    require(digest(path) == LEGACY_SHA, 'Installed 08 changed; review its version before using 09')
    name = '_inspection_legacy_' + hashlib.sha256(str(path).encode()).hexdigest()[:12]
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def prepare_plan(lab, source=None, locked_report=None):
    original = legacy(lab)
    plan, snapshot, confirmation = original.prepare_plan(lab, source)
    plan.update(schema=2, mode='inspection_fourlight_fixed600', adapter_source_sha256=digest(__file__),
                legacy_08_sha256=LEGACY_SHA, exposure_binding=None)
    if locked_report is not None:
        folder = Path(locked_report).resolve()
        verify_inventory(folder)
        summary, auto_plan = read_json(folder/'operator_summary.json'), read_json(folder/'plan.json')
        require(summary['status'] == 'LOCKED' and summary['independent_audit']['status'] == 'PASS'
                and summary['evidence_source'] == 'real_board' and summary['operator_same_pose_confirmed'] is True
                and summary['lights_off']['acknowledged'] is True, 'Auto stage must lock, audit and acknowledge OFF before four-light capture')
        require(summary['sample_id'] == plan['sample_id'] and
                summary['source_full_png_sha256'] == plan['source_full_png_sha256'] and
                summary['uploaded_native_mask_sha256'] == plan['native_mask_sha256'] and
                auto_plan['source'] == plan['source'] and auto_plan['roi'] == plan['roi'] and
                auto_plan['source_session_sha256'] == plan['source_session_sha256'] and
                summary['core_source_sha256'] == plan['frozen_core_sha256'], 'Auto result is not bound to this source/mask/sample')
        exposure = summary['locked_exposure_lines']
        require(type(exposure) is int and exposure in (400, 500, 600, 700), 'Unsupported locked exposure')
        plan.update(mode='inspection_fourlight_fresh_auto', exposure_lines=exposure,
                    exposure_binding=dict(folder=str(folder), summary_sha256=digest(folder/'operator_summary.json'),
                                          manifest_sha256=digest(folder/'output_manifest.json')))
    return plan, snapshot, confirmation


def executor_class(core, engine, notify):
    return core.progress_executor_class(engine, notify)


def run_capture(plan, out, *, confirmed_same_pose=False, cancel=None, notify=lambda *a, **k: None):
    """Fresh four-frame capture into a NEW inner folder; sealed before analysis."""
    require(confirmed_same_pose is True, 'Explicit same-pose confirmation is required before acquisition')
    original = legacy(plan['lab_root'])
    core = original.load_core(plan['lab_root'])
    binding = plan.get('exposure_binding')
    fresh, source, confirmation = prepare_plan(plan['lab_root'], plan['source'], binding['folder'] if binding else None)
    require(fresh == plan, 'Source or plan changed; reload and confirm before acquisition')
    cancel = cancel or threading.Event()
    require(not cancel.is_set(), 'Cancelled before acquisition; no command sent')
    started = time.monotonic_ns()
    lab, out = Path(plan['lab_root']), Path(out)
    engine = core.load_engine()
    with core.operator_lock(lab):
        out.mkdir(parents=True, exist_ok=False)
        core.write_json(out/'plan.json', plan)
        x, y, w, h = plan['roi']
        common = np.zeros((1080, 1920), np.uint8)
        common[y:y+h, x:x+w] = source['controller_native_mask']
        for name, data in [('source_full.png', source['full_png_bytes']), ('source_geometry.json', source['geometry_bytes']),
                           ('source_mask.npy', source['mask_npy_bytes']), ('source_session.json', source['session_bytes']),
                           ('source_result.json', source['result_bytes']), ('source_roi_session.json', confirmation['session_bytes']),
                           ('source_roi_result.json', confirmation['result_bytes']),
                           ('native_mask.bin', source['controller_native_mask'].tobytes()), ('common_mask.bin', common.tobytes())]:
            (out/name).write_bytes(data)
        summary = dict(status='STARTED', schema=2, sample_id=plan['sample_id'], frames=[], captures_complete=False,
                       evidence_source='not_started', operator_confirmation_supplied=True, operator_same_pose_confirmed=False,
                       operator_started_monotonic_ns=started, observed_at=core.local_now().isoformat(),
                       geometry_mask_profile=plan['mask_profile'], native_mask_pixels=plan['mask_pixels'],
                       source_frames_are_initialization_only=True, source_frames_counted_as_fourlight_observations=False,
                       physical_freshness_verified=False, settling_calibrated=False, external_io_qualified=False,
                       detector_or_fusion_accuracy_validated=False, lights_off=dict(requested=False, acknowledged=False),
                       source_02_03_sdk_elapsed_ms=sum(core.parse_json(b)['cost']['host_elapsed_s'] for b in
                                                   [source['result_bytes'], confirmation['result_bytes']])*1000,
                       workflow_complete_end_to_end_measured=False)
        core.write_json(out/'operator_summary.json', summary)
        stage = time.monotonic()
        deadline = stage + plan['sequence_timeout_s']
        try:
            Executor = executor_class(core, engine, notify)
            with Executor(board=plan['board'], port=plan['port'], bind=plan['bind'], ymw_root=engine.root/'ymw',
                          output_root=out/'captures', mode='strict', evidence_source='real_board', command_timeout=1.5, retries=3) as executor:
                summary['evidence_source'] = executor.evidence_source
                summary['operator_same_pose_confirmed'] = executor.evidence_source == 'real_board'
                try:
                    for channel, direction in CHANNELS:
                        if cancel.is_set():
                            raise InterruptedError('Cancelled between directions')
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError('Four-direction budget exhausted')
                        notify('step', channel=channel, direction=direction)
                        result = executor.acquire(light_channel=channel, brightness=plan['brightness'], exposure_lines=plan['exposure_lines'],
                                                  gain16=plan['gain16'], roi=tuple(plan['roi']), board_mask=source['controller_native_mask'].tobytes(),
                                                  settle_frames=plan['settle_frames'], discard_frames=plan['discard_frames'],
                                                  timeout_s=min(plan['single_timeout_s'], remaining), cancel=cancel,
                                                  sample_id=plan['sample_id'], round_id=out.name+'/CH'+str(channel))
                        r = original.validate_frame(result, plan, channel, summary['frames'][-1] if summary['frames'] else None)
                        require(r['evidence_source'] == executor.evidence_source, 'Evidence source mismatch')
                        target = out/'images'
                        target.mkdir(exist_ok=True)
                        stem = 'CH'+str(channel)+'_'+direction
                        (target/(stem+'.png')).write_bytes(result.png_path.read_bytes())
                        (target/(stem+'.rgb565')).write_bytes((result.record_path.parent/'image.rgb565').read_bytes())
                        frame = dict(channel=channel, direction=direction, call_id=r['call_id'], identity=r['identity'],
                                     actual_parameters=r['actual_parameters'], camera_readback=r['camera_readback'],
                                     png='images/'+stem+'.png', raw='images/'+stem+'.rgb565', png_sha256=r['png_sha256'],
                                     raw_sha256=r['raw_rgb565_sha256'], result_json=result.record_path.relative_to(out).as_posix(),
                                     statistics=r['statistics'], features=r['features'], cost=r['cost'], evidence_source=r['evidence_source'],
                                     device_reported_settle_frames=r['device_reported_settle_frames'],
                                     device_reported_discard_frames=r['device_reported_discard_frames'])
                        summary['frames'].append(frame)
                        core.write_json(out/'operator_summary.json', summary)
                        notify('frame_saved', channel=channel, png=str(target/(stem+'.png')),
                               exposure_lines=plan['exposure_lines'])
                finally:
                    notify('progress', text='正在关灯并保存采集记录')
                    summary['lights_off'] = core.request_lights_off(executor)
            summary['captures_complete'] = len(summary['frames']) == 4
            summary['status'] = 'CAPTURED_FOUR_LIGHT_REVIEW_REQUIRED' if summary['lights_off']['acknowledged'] else 'CAPTURED_OFF_UNCONFIRMED'
        except BaseException as exc:
            summary.update(status='CANCELLED' if isinstance(exc, (KeyboardInterrupt, InterruptedError)) or getattr(exc, 'code', '') == 'CANCELLED' else 'FAILED',
                           error=dict(type=type(exc).__name__, code=getattr(exc, 'code', ''), message=str(exc)))
        summary['capture_stage_host_ms'] = (time.monotonic()-stage)*1000
        outcomes = [core.read_json(p) for p in sorted((out/'captures').glob('*/outcome.json'))]
        summary.update(capture_attempts=len(outcomes), saved_images=len(summary['frames']),
                       known_completed_transaction_frames=sum(1+f['device_reported_settle_frames']+f['device_reported_discard_frames'] for f in summary['frames']),
                       attempt_costs=[dict(call_id=r.get('call_id'), status=r.get('status'), cost=r.get('cost'), error=r.get('error')) for r in outcomes],
                       cancel_requested=cancel.is_set(), host_elapsed_ms_before_archive=(time.monotonic_ns()-started)/1e6)
        summary.update(mask_uploads=0, mask_reuses=0)
        for path in sorted((out/'captures').glob('*/frame_trace.jsonl')):
            events = [core.parse_json(line) for line in path.read_text(encoding='utf-8').splitlines() if line]
            summary['mask_uploads'] += sum(e['event'] == 'mask_upload_start' for e in events)
            summary['mask_reuses'] += sum(e['event'] == 'mask_reused' for e in events)
        core.write_json(out/'frames.json', summary['frames'])
        core.write_json(out/'operator_summary.json', summary)
        seal_folder(out)
        return dict(summary=summary, output=str(out))
