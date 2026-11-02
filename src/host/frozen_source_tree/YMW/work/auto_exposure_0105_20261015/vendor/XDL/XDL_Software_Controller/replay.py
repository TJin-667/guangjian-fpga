"""Traceable offline replay. No hardware commands or invented fresh captures."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

from acquisition_control import CaptureEvent, Controller, ControllerConfig
from capture_metrics import (FrameInput, FrameMetrics, build_common_area, compare_repeats,
                             compute_metrics, load_algorithm, source_identity)
from dataset_io import load_scan_inputs, load_repeat_inputs, read_frame, historical_cost
from fpga_reference import (constructed_golden_cases, export_golden, scalar_metric_reference,
                            verify_reference)


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent
AUDIT = BASE / 'XDL_Results/2026-10-13_software_controller_build'
PRESERVATION_BASELINE_SHA256 = '69cb3f1515a7ef1786bd44ea41f195c08e51c9c69b738c9be644156c462f0f4b'
REPEAT_RECEIPT_SHA256 = 'c48282b5e65f063dea6e93e8b321241111a0fbe9077deb8b904daacebe1c5824'
SCENARIOS = frozenset(('normal_no_candidates', 'highlight_down', 'dark_up_and_exhausted',
    'dark_and_highlight', 'strict_equalities', 'candidate_growth_does_not_cancel_risk',
    'budget_exhausted', 'missing_fresh_confirmation', 'capture_error_retry',
    'fallback_requires_new_frame', 'duplicate_identity', 'wrong_context',
    'terminal_rejection', 'different_sample', 'risk_history'))
REJECTIONS = frozenset(('duplicate_identity', 'wrong_context', 'terminal_rejection', 'different_sample'))


def canonical(value):
    """Detached strict JSON representation of the public dataclass interfaces."""
    return json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))


def _source_type(frame):
    if frame.source_mode in ('scan', 'repeat', 'real_history_replay'):
        return 'real_history_replay'
    if frame.source_mode == 'synthetic_image':
        return 'synthetic_image'
    return 'constructed_statistics'


def _validate_inputs(inputs):
    if not inputs or any(not isinstance(f, FrameInput) for f in inputs):
        raise ValueError('A nonempty list of FrameInput is required')
    if len({f.context_id for f in inputs}) != 1:
        raise ValueError('Replay cannot mix contexts')
    if len({(f.sample_id, f.pose, f.channel, f.led, f.gain16) for f in inputs}) != 1:
        raise ValueError('Replay cannot mix samples, positions or illumination')
    identities = [source_identity(f) for f in inputs]
    if len({f.observation_id for f in inputs}) != len(inputs) or len(set(identities)) != len(inputs):
        raise ValueError('Duplicate observation or immutable source identity')


def replay_sequence(inputs: list[FrameInput], config: ControllerConfig, evaluate) -> dict:
    """Only evaluate the first unused frame matching the current pending request."""
    _validate_inputs(inputs)
    started = perf_counter()
    controller = Controller(config, inputs[0].context_id)
    rows, cases, actual, consumed = [], [], [], []
    before = canonical(asdict(controller.snapshot()))
    decision = controller.start()

    def record(snapshot, event, decision, frame=None):
        state, answer = canonical(asdict(controller.snapshot())), canonical(asdict(decision))
        case = dict(source_type=_source_type(frame or inputs[0]), snapshot=snapshot,
                    event=event, config=canonical(asdict(config)))
        cases.append(case)
        actual.append(dict(state=state, decision=answer))
        rows.append(dict(sequence=len(rows), context_id=inputs[0].context_id,
                         source_type=case['source_type'], source_identity=source_identity(frame) if frame else None,
                         input_frame=canonical(asdict(frame)) if frame else None,
                         before_state=snapshot, event=event, state=state, decision=answer,
                         rule_version=config.rule_version, measured_live_control_cost=None))

    record(before, {'kind': 'start'}, decision)
    while decision.status == 'CONTINUE_ADJUST':
        before = canonical(asdict(controller.snapshot()))
        exposure = before['pending_request']['exposure_lines']
        frame = next((f for f in inputs if f.observation_id not in consumed
                      and f.exposure_lines == exposure), None)
        if frame is None:
            event = CaptureEvent('missing_data', inputs[0].context_id, None, exposure, None, None)
        else:
            metrics, _ = evaluate(frame)
            if not isinstance(metrics, FrameMetrics):
                raise ValueError('Evaluator must return FrameMetrics and diagnostics')
            event = CaptureEvent('observation', frame.context_id, frame.observation_id, exposure, metrics, None)
        decision = controller.feed(event)
        if frame is not None:
            consumed.append(frame.observation_id)
        record(before, canonical(asdict(event)), decision, frame)
    verification = verify_reference(cases, actual)
    return dict(context_id=inputs[0].context_id, source_type=_source_type(inputs[0]),
                decisions=rows, final_decision=canonical(asdict(decision)),
                consumed_observation_ids=consumed, unconsumed_observation_ids=[
                    f.observation_id for f in inputs if f.observation_id not in consumed],
                modeled_control_cost=canonical(decision.budget), historical_capture_cost=None,
                measured_live_control_cost=None, compute_walltime_ms=(perf_counter()-started)*1000,
                golden_cases=cases, reference_actual=actual,
                decision_reference_verification=verification, offline_verified=False,
                provisional_thresholds=True, hardware_validation_pending=True,
                physical_freshness_validation=False)


def require_golden_inventory(cases):
    """Protect the complete baseline scenario and rejection inventory at export."""
    baseline = [c for c in cases if c.get('source_type') == 'constructed_statistics' and c.get('scenario_id') in SCENARIOS]
    if (len(baseline) != 42 or {c['scenario_id'] for c in baseline} != SCENARIOS
            or {c['scenario_id'] for c in baseline if c.get('expected_validation_error') == 'ValueError'} != REJECTIONS
            or sum(bool(c.get('expected_validation_error')) for c in baseline) != 4):
        raise ValueError('Incomplete baseline golden scenario/rejection inventory')


def constructed_validation():
    """Run primary transitions separately from independently derived golden answers."""
    cases = constructed_golden_cases(canonical(asdict(ControllerConfig())))
    require_golden_inventory(cases)
    actual, controllers = [], {}
    for case in cases:
        name = case['scenario_id']
        cfg = ControllerConfig.from_dict(case['config'])
        if case['event']['kind'] == 'start':
            controller = Controller(cfg, case['snapshot']['context_id'])
            controllers[name] = controller
        controller = controllers[name]
        if canonical(asdict(controller.snapshot())) != case['snapshot']:
            raise ValueError('Constructed starting snapshot differs from independent reference')
        try:
            if case['event']['kind'] == 'start':
                decision = controller.start()
            else:
                values = dict(case['event'])
                if values['metrics'] is not None:
                    values['metrics'] = FrameMetrics(**values['metrics'])
                decision = controller.feed(CaptureEvent(**values))
            actual.append(dict(state=canonical(asdict(controller.snapshot())), decision=canonical(asdict(decision))))
        except ValueError:
            if case.get('expected_validation_error') != 'ValueError':
                raise
            actual.append({'validation_error': 'ValueError'})
    return cases, actual


def read_trusted_json(path, sha256):
    """Accept relocated audit material only when its immutable original bytes match."""
    content = Path(path).read_bytes()
    if hashlib.sha256(content).hexdigest() != sha256:
        raise ValueError('Preservation trust anchor SHA256 mismatch: ' + str(path))
    return json.loads(content)


def capture_preservation(args):
    """Read-only whole-tree snapshot, grounded by pinned source/history/receipt bytes."""
    baseline = read_trusted_json(args.preservation_baseline, PRESERVATION_BASELINE_SHA256)
    receipt = read_trusted_json(args.repeat_receipt, REPEAT_RECEIPT_SHA256)
    groups = {key: {} for key in ('source', 'historical', 'input')}
    for entry in baseline:
        kind = 'source' if Path(entry['path']).suffix == '.py' else 'historical'
        groups[kind][Path(entry['path']).resolve()] = entry
    for kind, roots in (('historical', (args.expected_results, args.reference_root)),
                        ('input', (args.scan_root, args.repeat_root))):
        for root in roots:
            if not root.is_dir():
                raise ValueError('Missing preservation input root: ' + str(root))
            for path in root.rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts:
                    groups[kind].setdefault(path.resolve(), None)
    for entry in receipt['files']:
        groups['input'][(args.repeat_root / entry['path']).resolve()] = entry
    snapshots = {}
    for kind, files in groups.items():
        rows = []
        for path, expected in sorted(files.items(), key=lambda item: str(item[0])):
            content = path.read_bytes()
            sha = hashlib.sha256(content).hexdigest()
            if expected and (len(content) != expected['bytes'] or sha != expected['sha256']):
                raise ValueError('Protected original SHA256/size mismatch: ' + str(path))
            rows.append(dict(path=str(path), bytes=len(content), sha256=sha,
                             expected_sha256=expected['sha256'] if expected else None))
        snapshots[kind] = rows
    return snapshots


def preservation_checks(before, after):
    """Compare the full inventory as well as every before/after and pinned digest."""
    checks = {}
    for kind in ('source', 'historical', 'input'):
        old, new = ({r['path']: r for r in snapshot.get(kind, [])} for snapshot in (before, after))
        comparisons = []
        for path in sorted(old.keys() | new.keys()):
            left, right = old.get(path), new.get(path)
            expected = (left or right).get('expected_sha256')
            okay = bool(left and right and left == right and
                        (expected is None or left['sha256'] == right['sha256'] == expected))
            comparisons.append(dict(path=path, before_sha256=left['sha256'] if left else None,
                after_sha256=right['sha256'] if right else None,
                before_bytes=left['bytes'] if left else None, after_bytes=right['bytes'] if right else None,
                expected_sha256=expected, unchanged=okay))
        checks[kind + '_preservation'] = dict(passed=bool(comparisons) and all(r['unchanged'] for r in comparisons),
            checked=len(comparisons), pinned_count=sum(r['expected_sha256'] is not None for r in comparisons),
            comparisons=comparisons, scope='before/after complete inventory; trusted pinned originals where available')
    return checks


def _preservation_passed(check, minimum, pinned):
    if not isinstance(check, dict) or check.get('passed') is not True:
        return False
    rows = check.get('comparisons')
    if (type(check.get('checked')) is not int or check['checked'] < minimum
            or not isinstance(rows, list) or len(rows) != check['checked']
            or check.get('pinned_count') != pinned
            or sum(isinstance(r, dict) and r.get('expected_sha256') is not None for r in rows) != pinned
            or len({r.get('path') for r in rows if isinstance(r, dict)}) != len(rows)):
        return False
    return all(isinstance(r, dict) and r.get('unchanged') is True
               and isinstance(r.get('before_sha256'), str) and re.fullmatch('[0-9a-f]{64}', r['before_sha256'])
               and r.get('before_sha256') == r.get('after_sha256')
               and type(r.get('before_bytes')) is int and r['before_bytes'] == r.get('after_bytes')
               and (r.get('expected_sha256') is None or r['expected_sha256'] == r['before_sha256']) for r in rows)


def verification_status(evidence):
    required = ('source_integrity', 'scalar_statistics', 'native_reference',
                'decision_reference', 'constructed_actions', 'golden_inventory', 'repeat_stability', 'sensitivity_actions')
    passed = all(isinstance(evidence.get(k), dict) and evidence[k].get('passed') is True
                 and type(evidence[k].get('checked')) is int and evidence[k]['checked'] > 0 for k in required)
    counts = {'source_integrity': 10, 'scalar_statistics': 10, 'native_reference': 10,
              'constructed_actions': 42, 'golden_inventory': 15, 'repeat_stability': 6, 'sensitivity_actions': 27}
    passed = passed and all(evidence[k]['checked'] == n for k, n in counts.items())
    passed = passed and evidence['decision_reference']['checked'] >= 102
    passed = passed and evidence['golden_inventory'].get('transitions') == 42 and evidence['golden_inventory'].get('expected_rejections') == 4
    source = _preservation_passed(evidence.get('source_preservation'), 9, 9)
    historical = _preservation_passed(evidence.get('historical_preservation'), 7, 7)
    inputs = _preservation_passed(evidence.get('input_preservation'), 20, 20)
    passed = passed and source and historical and inputs
    return dict(offline_verified=passed, provisional_thresholds=True,
                source_unchanged=source, historical_results_unchanged=historical, inputs_unchanged=inputs,
                hardware_validation_pending=True, physical_freshness_validation=False,
                evidence=evidence, scope='offline numerical and policy verification only')


def _native_scalar(arrays):
    """Independent Python-int count/sum of preserved saved/native statistics."""
    gray, rgb, mask = arrays['gray'], arrays['rgb_any_max'], arrays['board_mask']
    saved = dict(pixel_count=gray.size, gray_sum=0, near_black_le5_count=0,
                 near_white_ge250_count=0, rgb_any_max_count=0)
    board = dict(pixel_count=0, gray_sum=0, gray_le10_count=0, gray_ge250_count=0, rgb_any_max_count=0)
    for value, maximum, inside in zip(gray.flat, rgb.flat, mask.flat):
        value = int(value)
        saved['gray_sum'] += value
        saved['near_black_le5_count'] += int(value <= 5)
        saved['near_white_ge250_count'] += int(value >= 250)
        saved['rgb_any_max_count'] += int(maximum)
        if inside:
            board['pixel_count'] += 1
            board['gray_sum'] += value
            board['gray_le10_count'] += int(value <= 10)
            board['gray_ge250_count'] += int(value >= 250)
            board['rgb_any_max_count'] += int(maximum)
    return dict(saved_frame_integer_statistics=saved, board_integer_statistics=board,
                baseline_candidate_count=sum(int(x) for x in arrays['baseline_mask'].flat))


def _pinned_native(frame, metrics, arrays, algorithm):
    if frame.source_mode != 'scan':
        return dict(passed=True, checked=1, scope='independent native count/sum; no historical repeat golden exists')
    reference = Path(algorithm.get('_reference_root', BASE/'XDL_Results/2026-10-13_integer_reference_01'))
    history = Path(algorithm.get('_expected_results', BASE/'XDL_Results/2026-10-13_manual_exposure_gain'))
    manifest = json.loads((reference/'reference_manifest.json').read_text(encoding='utf-8'))
    record = next(r for r in manifest['frames'] if r['group_id'] == frame.source_metadata['group_id'] and r['channel'] == 'CH1')
    archive = reference/record['path']
    content = archive.read_bytes()
    if hashlib.sha256(content).hexdigest() != record['sha256']:
        raise ValueError('Pinned reference archive hash mismatch')
    checks = {}
    with np.load(io.BytesIO(content), allow_pickle=False) as old:
        for key in old.files:
            checks[key] = key in arrays and np.array_equal(arrays[key], old[key])
    golden = json.loads((history/'golden_statistics.json').read_text(encoding='utf-8'))
    if hashlib.sha256((history/'golden_statistics.json').read_bytes()).hexdigest() != manifest['historical_results_sha256']['golden_statistics.json']:
        raise ValueError('Historical native statistics hash mismatch')
    expected = next(r for r in golden['frames'] if r['group_id'] == frame.source_metadata['group_id'] and r['channel'] == 'CH1')
    for key in ('saved_frame_integer_statistics', 'board_integer_statistics'):
        checks[key] = metrics.native_reference_statistics[key] == expected[key]
    return dict(passed=all(checks.values()), checked=len(checks), comparisons=checks,
                reference_archive_sha256=record['sha256'])


def _study_records(inputs, algorithm):
    _validate_inputs(inputs)
    images = [read_frame(f) for f in inputs]
    masks = [algorithm['board_mask'](image.shape[:2], f.source_metadata['analysis_polygon'], f.roi[:2])
             for f, image in zip(inputs, images)]
    area = build_common_area(inputs, masks)
    records = []
    for frame, image, mask in zip(inputs, images, masks):
        metrics, arrays = compute_metrics(image, frame, mask, area, algorithm)
        scalar = scalar_metric_reference(arrays['gray'], arrays['residual_n'], arrays['rgb_any_max'], arrays['common_mask'])
        scalar['baseline_candidate_count'] = sum(int(a) for a, b in zip(arrays['baseline_mask'].flat, arrays['common_mask'].flat) if b)
        comparisons = {k: scalar[k] == getattr(metrics, k) for k in scalar}
        native = _native_scalar(arrays)
        native['quality_status'] = algorithm['assess_quality'](arrays['gray'])['status']
        native_checks = {k: native[k] == metrics.native_reference_statistics[k] for k in native}
        pinned = _pinned_native(frame, metrics, arrays, algorithm)
        records.append(dict(frame=frame, metrics=metrics, arrays=arrays, image=image,
                            scalar_verification=dict(passed=all(comparisons.values()), checked=len(comparisons), comparisons=comparisons),
                            native_verification=dict(passed=all(native_checks.values()) and pinned['passed'],
                                                     checked=len(native_checks)+pinned['checked'], comparisons=native_checks, pinned=pinned)))
    return records, area


def _replay_records(inputs, config, records):
    lookup = {r['frame'].observation_id: r for r in records}
    return replay_sequence(inputs, config, lambda f: (lookup[f.observation_id]['metrics'], lookup[f.observation_id]['arrays']))


def _study(inputs, config, algorithm, repeat):
    started = perf_counter()
    records, area = _study_records(inputs, algorithm)
    result = _replay_records(inputs, config, records)
    result['frame_metrics'] = [dict(frame=canonical(asdict(r['frame'])), metrics=canonical(asdict(r['metrics'])),
                                  scalar_verification=r['scalar_verification'], native_verification=r['native_verification'],
                                  consumed_by_controller=r['frame'].observation_id in result['consumed_observation_ids']) for r in records]
    result['evaluation_area'] = dict(version=area.version, mask_sha256=area.mask_sha256,
                                    common_area=int(area.mask.sum()), coverage=canonical(area.coverage),
                                    sources=canonical(area.sources), available=area.available,
                                    reason_codes=canonical(area.reason_codes),
                                    manual_review_pending=any(s['needs_manual_review'] is True for s in area.sources))
    result['repeat_stability'] = compare_repeats([(r['frame'], r['metrics'], r['arrays']) for r in records], area) if repeat else None
    result['sensitivity'] = _sensitivity_records(inputs, config, records)
    name = re.sub(r'[^A-Za-z0-9_-]', '_', inputs[0].context_id)
    artifacts = {name+'_common_mask.png': area.mask.astype(np.uint8)*255}
    for i, r in enumerate(records):
        overlay = r['image'].copy()
        overlay[r['arrays']['line_centers']] = (0, 255, 255)
        overlay[r['arrays']['baseline_mask']] = (0, 0, 255)
        contours, _ = cv2.findContours(r['arrays']['common_mask'].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(overlay, contours, -1, (0, 255, 0), 2)
        name = re.sub(r'[^A-Za-z0-9_-]', '_', inputs[0].context_id)
        artifacts[f'{name}_{i+1:02d}_native_mask.png'] = r['arrays']['board_mask'].astype(np.uint8)*255
        artifacts[f'{name}_{i+1:02d}_review_overlay.png'] = overlay
    result['_artifacts'] = artifacts
    result['compute_walltime_ms'] = (perf_counter()-started)*1000
    return result


def run_scan(inputs: list[FrameInput], config: ControllerConfig, algorithm: dict) -> dict:
    return _study(inputs, config, algorithm, False)


def run_repeat_study(inputs: list[FrameInput], config: ControllerConfig, algorithm: dict) -> dict:
    if len(inputs) != 3 or any(f.exposure_lines != 600 for f in inputs):
        raise ValueError('Repeat study requires three separate 600-line observations')
    return _study(inputs, config, algorithm, True)


def _sensitivity_records(inputs, config, records):
    baseline = _replay_records(inputs, config, records)
    baseline_config = canonical(asdict(config))
    # Study-only floor keeps all warning variants valid; baseline is untouched.
    suite_review = max(config.rgb_review_bp, 800)
    def signature(result):
        return [[r['decision'][k] for k in ('status', 'action_kind', 'next_exposure_lines', 'reason_codes')] for r in result['decisions']]
    reference_actions = signature(baseline)
    runs = []
    for effective in (8500, 9000, 9500):
        for warn in (300, 500, 800):
            variant = replace(config, min_effective_bp=effective, rgb_warn_bp=warn,
                              rgb_review_bp=suite_review)
            result = _replay_records(inputs, variant, records)
            variant_config = canonical(asdict(variant))
            result.update(config=variant_config, action_dependency=signature(result) != reference_actions,
                          requested_rgb_review_bp=config.rgb_review_bp, sensitivity_rgb_review_bp=suite_review,
                          sensitivity_review_threshold_adjusted=suite_review != config.rgb_review_bp,
                          baseline_config=baseline_config,
                          baseline_comparison=dict(changed_config_fields=[
                              key for key in baseline_config if baseline_config[key] != variant_config[key]],
                              rgb_review_bp_differs=suite_review != config.rgb_review_bp),
                          baseline_actions=reference_actions, actions=signature(result), threshold_selection='none')
            runs.append(result)
    return runs


def sensitivity_runs(inputs: list[FrameInput], config: ControllerConfig, algorithm: dict) -> list[dict]:
    _validate_inputs(inputs)
    records, _ = _study_records(inputs, algorithm)
    return _sensitivity_records(inputs, config, records)


def _output_path(output, roots):
    output = Path(output).resolve()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}_software_controller_\d{2,}', output.name):
        raise ValueError('Output must use YYYY-MM-DD_software_controller_NN')
    if output.exists():
        raise ValueError('Output already exists; refusing overwrite')
    protected = [ROOT, BASE/'YMW', BASE/'XDL_Algorithm'] + [Path(r).resolve() for r in roots]
    protected.extend(p.resolve() for p in (BASE/'XDL_Results').iterdir() if p.is_dir())
    if any(output == root or root in output.parents for root in protected):
        raise ValueError('Output is inside an input, source, controller or existing result directory')
    return output


def _csv_text(rows):
    """Keep nested exact integers, nulls and identity evidence as strict JSON cells."""
    buffer = io.StringIO(newline='')
    columns = sorted({key for row in rows for key in row}) if rows else ['record']
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: json.dumps(v, allow_nan=False, ensure_ascii=False) if isinstance(v, (dict, list, tuple)) or v is None else v for k, v in row.items()})
    return buffer.getvalue()


def write_run(output: Path, payloads: dict) -> None:
    output = _output_path(output, payloads.get('input_roots', []))
    texts, pictures = {}, {}
    for key, value in payloads.items():
        if key in ('input_roots', 'golden_cases', '_artifacts'):
            continue
        if not re.fullmatch(r'[a-z_]+', key):
            raise ValueError('Unsafe artifact name')
        texts[key+'.json'] = json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2)+'\n'
        if key in ('frame_metrics', 'decisions', 'repeat_stability'):
            texts[key+'.csv'] = _csv_text(value)
    cases = payloads.get('golden_cases')
    if cases is not None:
        require_golden_inventory(cases)
        canonical(cases)
        # Validate oracle inputs before creating the directory; no primary answers accepted.
        verify_reference(cases, [])
    for name, value in payloads.get('_artifacts', {}).items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+\.png', name):
            raise ValueError('Unsafe image artifact name')
        okay, encoded = cv2.imencode('.png', value)
        if not okay:
            raise ValueError('Unable to encode review image')
        pictures[name] = encoded.tobytes()
    output.mkdir(parents=False, exist_ok=False)
    for name, text in texts.items():
        with (output/name).open('x', encoding='utf-8', newline='') as stream:
            stream.write(text)
    for name, content in pictures.items():
        with (output/name).open('xb') as stream:
            stream.write(content)
    if cases is not None:
        pending = output/'.golden_actions.pending'
        export_golden(cases, pending)
        golden = json.loads(pending.read_text(encoding='utf-8'))
        golden['reference_vectors_verified'] = True
        golden['offline_verified'] = verification_status(payloads.get('verification', {}).get('evidence', {}))['offline_verified']
        golden['verification_scope'] = 'full offline run status; independent expectations were recomputed by reference exporter'
        with (output/'golden_actions.json').open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(golden, allow_nan=False, ensure_ascii=False, indent=2)+'\n')
        pending.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan-root', type=Path, default=BASE/'YMW/YMW_manual_20261013')
    parser.add_argument('--repeat-root', type=Path, default=BASE/'YMW/ch1_repeat_defect_near_normal_20261013')
    parser.add_argument('--expected-results', type=Path, default=BASE/'XDL_Results/2026-10-13_manual_exposure_gain')
    parser.add_argument('--reference-root', type=Path, default=BASE/'XDL_Results/2026-10-13_integer_reference_01')
    parser.add_argument('--algorithm-root', type=Path, default=BASE/'XDL_Algorithm/software')
    parser.add_argument('--regions', type=Path, default=ROOT/'repeat_regions.json')
    parser.add_argument('--config', type=Path, default=ROOT/'config.json')
    parser.add_argument('--preservation-baseline', type=Path, default=AUDIT/'preservation_before.json')
    parser.add_argument('--repeat-receipt', type=Path, default=AUDIT/'repeat_download_receipt.json')
    parser.add_argument('--output', type=Path)
    try:
        args = parser.parse_args(argv)
        roots = [args.scan_root, args.repeat_root, args.expected_results, args.reference_root, args.algorithm_root]
        output = args.output
        if output is None:
            day = datetime.now().strftime('%Y-%m-%d')
            output = next(BASE/'XDL_Results'/f'{day}_software_controller_{n:02d}' for n in range(1, 100) if not (BASE/'XDL_Results'/f'{day}_software_controller_{n:02d}').exists())
        if output.resolve().parent != (BASE/'XDL_Results').resolve():
            raise ValueError('CLI output must be a direct child of XDL_Results')
        _output_path(output, roots)
        def reject(value):
            raise ValueError('Non-finite JSON number: '+value)
        config = ControllerConfig.from_dict(json.loads(args.config.read_text(encoding='utf-8'), parse_constant=reject))
        preservation_before = capture_preservation(args)
        started = perf_counter()
        algorithm = load_algorithm(args.algorithm_root, args.expected_results)
        algorithm.update(_expected_results=args.expected_results, _reference_root=args.reference_root)
        def logical_context(frame, name):
            return replace(frame, context_id=name, source_metadata={**frame.source_metadata, 'original_adapter_context_id': frame.context_id})
        scan = [logical_context(f, 'scan_A') for f in load_scan_inputs(args.scan_root, args.expected_results)]
        repeats = [logical_context(f, 'repeat_'+f.sample_id[-3:]) for f in load_repeat_inputs(args.repeat_root, args.regions)]
        studies = [run_scan(scan, config, algorithm)]
        studies.extend(run_repeat_study([f for f in repeats if f.context_id == name], config, algorithm)
                       for name in ('repeat_001', 'repeat_002'))
        cost = historical_cost(args.repeat_root)
        cases, actual = constructed_validation()
        baseline_count = len(cases)
        for study in studies:
            cases.extend(study['golden_cases']); actual.extend(study['reference_actual'])
            for variant in study['sensitivity']:
                cases.extend(variant['golden_cases']); actual.extend(variant['reference_actual'])
        decision_check = verify_reference(cases, actual)
        metrics = [row for study in studies for row in study['frame_metrics']]
        evidence = dict(source_integrity=dict(passed=True, checked=len(metrics), scope='adapter reverified original bytes/session/hash/settings'),
                        scalar_statistics=dict(passed=all(r['scalar_verification']['passed'] for r in metrics), checked=len(metrics)),
                        native_reference=dict(passed=all(r['native_verification']['passed'] for r in metrics), checked=len(metrics)),
                        decision_reference=decision_check,
                        constructed_actions=verify_reference(cases[:baseline_count], actual[:baseline_count]),
                        golden_inventory=dict(passed=True, checked=15, transitions=42, expected_rejections=4),
                        repeat_stability=dict(passed=all(s['repeat_stability']['status']=='available' for s in studies[1:]), checked=6),
                        sensitivity_actions=dict(passed=all(r['decision_reference_verification']['passed'] for s in studies for r in s['sensitivity']),
                                                 checked=sum(len(s['sensitivity']) for s in studies)))
        evidence.update(preservation_checks(preservation_before, capture_preservation(args)))
        verification = verification_status(evidence)
        artifacts = {name: image for study in studies for name, image in study.pop('_artifacts').items()}
        # Cost model belongs to each context; the 896 historical receives are one manual study total.
        summaries = []
        for study in studies:
            summaries.append({k: study[k] for k in ('context_id', 'source_type', 'final_decision', 'consumed_observation_ids',
                'unconsumed_observation_ids', 'modeled_control_cost', 'evaluation_area', 'compute_walltime_ms')})
        provenance = dict(version='controller-replay-1', input_frames=[canonical(asdict(f)) for f in scan+repeats],
                          paths={k:str(getattr(args,k).resolve()) for k in ('scan_root','repeat_root','expected_results','reference_root','algorithm_root','regions','config','preservation_baseline','repeat_receipt')},
                          preservation_trust_anchors={'baseline_sha256': PRESERVATION_BASELINE_SHA256,
                                                      'repeat_receipt_sha256': REPEAT_RECEIPT_SHA256},
                          code_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in ROOT.glob('*.py')},
                          algorithm_source_sha256={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in [*args.algorithm_root.joinpath('light_inspection').glob('*.py'), args.algorithm_root/'ymw_integer_reference.py']},
                          config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest(),
                          physical_freshness_validation=False, hardware_validation_pending=True,
                          scan_historical_capture_cost=None, scan_historical_cost_reason='not aggregated by repeat-log adapter',
                          historical_capture_cost=cost['historical_capture_cost'], measured_live_control_cost=None,
                          modeled_control_cost={s['context_id']:s['modeled_control_cost'] for s in studies},
                          compute_walltime_ms=(perf_counter()-started)*1000,
                          overlay_legend={'green':'common region boundary','yellow':'line centers','red':'preserved baseline candidates'},
                          baseline_golden_config=canonical(asdict(ControllerConfig())), real_replay_config=canonical(asdict(config)))
        payloads = dict(config=canonical(asdict(config)), provenance=provenance, verification=verification,
                        frame_metrics=metrics, decisions=[row for s in studies for row in s['decisions']],
                        repeat_stability=[dict(context_id=s['context_id'], **s['repeat_stability']) for s in studies[1:]],
                        sensitivity=[dict(context_id=s['context_id'], runs=s['sensitivity']) for s in studies],
                        summary=summaries, golden_cases=cases, _artifacts=artifacts, input_roots=[str(p) for p in roots])
        write_run(output, payloads)
        print(json.dumps(dict(output=str(output.resolve()), offline_verified=verification['offline_verified'],
                              final_states={s['context_id']:s['final_decision']['status'] for s in studies}), allow_nan=False))
        return 0 if verification['offline_verified'] else 1
    except SystemExit as error:
        return int(error.code)
    except (OSError, ValueError, KeyError, StopIteration) as error:
        print('Replay validation failed: '+str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
