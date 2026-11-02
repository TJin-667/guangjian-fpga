"""Post-process admitted orange windows; scores are evidence indices, not probabilities."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / 'confidence_gap_review_20261029'))
from gap_review import allowed_samples, bilinear, longest_true

TERMS = {
    'joint_coverage': '同帧原片与残差共同支持',
    'raw_continuity': '原片线证据连续程度',
    'response_retention': '略提高复检阈值后的支持保留',
    'endpoint_alignment': '两端走向一致程度',
    'valid_fraction': '有效采样比例',
}

def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def verify_frozen(binding=None, root=REPO):
    binding = binding or json.loads((HERE / 'FROZEN_DEPENDENCIES.json').read_text('utf-8'))
    for relative, digest in binding['files_sha256'].items():
        path = (Path(root) / relative).resolve()
        if not path.is_relative_to(Path(root).resolve()) or file_sha(path) != digest:
            raise ValueError('FROZEN_REVIEW_DEPENDENCY_CHANGED: ' + relative)
    return binding

def measure_gap(gap, gray, valid, board, residual, base_plan, core_plan):
    """Use only the selected real frame/polarity and the largest contiguous missing run."""
    if not gap.get('review'):
        raise ValueError('Only already-admitted frozen review gaps may receive a score')
    if gray.shape != (8, *board.shape) or valid.shape != gray.shape or residual.shape != gray.shape:
        raise ValueError('Native matching eight-frame arrays required')
    q = gap['selected_probe']
    fit = q['best_fit']
    frame = int(fit['frame']) - 1
    polarity = int(fit['polarity'])
    if not 0 <= frame < 8 or polarity not in (-1, 1):
        raise ValueError('Invalid real frame or polarity')
    path = np.asarray(q['path_xy'], dtype='float64')
    if path.ndim != 2 or path.shape[1] != 2 or len(path) < 3 or not np.isfinite(path).all():
        raise ValueError('Invalid native probe path')
    runs = q['visual']['visual_runs']
    if not runs:
        raise ValueError('Admitted window has no visual gap')
    run = max(runs, key=lambda r: (r['length_px'], -r['begin']))
    begin, end = int(run['begin']), int(run['end'])
    if not 0 <= begin <= end < len(path) or run['length_px'] <= core_plan['ignore_gap_at_most_px']:
        raise ValueError('Invalid or ignored visual gap')
    native = np.rint(path).astype(int)
    native[:, 0] = np.clip(native[:, 0], 0, board.shape[1] - 1)
    native[:, 1] = np.clip(native[:, 1], 0, board.shape[0] - 1)
    tangent = np.gradient(path, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1)[:, None], 1e-6)
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    c = base_plan['gap']
    positions = [path + offset * normal for offset in (-.5, 0, .5, c['profile_flank'], -c['profile_flank'])]
    allowed = np.logical_and.reduce([allowed_samples(p, valid[frame], board) for p in positions])
    xx, yy = native.T
    allowed &= valid[frame, yy, xx] & board[yy, xx]
    values = [bilinear(gray[frame], p) for p in positions]
    center = .25 * values[0] + .5 * values[1] + .25 * values[2]
    contrast = np.minimum(polarity * (center - values[3]), polarity * (center - values[4]))
    response = polarity * residual[frame, yy, xx].astype('float64') / 81
    weak = float(q['review_weak_used'])
    stricter = min((float(v) for v in c['thresholds'] if v > weak), default=None)
    if stricter is None:
        raise ValueError('No frozen stricter threshold available for stability measurement')
    sl = slice(begin, end + 1)
    allowed = allowed[sl]
    contrast = contrast[sl]
    response = response[sl]
    raw = allowed & (contrast >= c['raw_contrast'])
    detail = allowed & (response > weak)
    joint = raw & detail
    stricter_joint = raw & (response > stricter)
    n = len(raw)
    raw_empty = longest_true(~raw)
    terms = {
        'joint_coverage': float(joint.mean()),
        'raw_continuity': float(1 - raw_empty / n),
        'response_retention': float(stricter_joint.sum() / joint.sum()) if joint.any() else 0.,
        'endpoint_alignment': float(np.clip(gap['facing_cosine'], 0, 1)),
        'valid_fraction': float(allowed.mean()),
    }
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in terms.values()):
        raise ValueError('Invalid score measurement')
    weakest = min(terms.values())
    # An explicit conservative rule, not a learned weight or probability calibration.
    score = int(5 * math.floor((100 * weakest + 1e-8) / 5))
    limitation = [k for k, value in terms.items() if abs(value - weakest) < 1e-8]
    large = run['length_px'] >= core_plan['large_gap_at_least_px']
    return dict(
        gap_id=gap['id'], evidence_support_score=score, score_scale=[0, 100], score_step=5,
        score_semantics='development_evidence_index_not_probability',
        review_priority='high' if large else 'medium',
        priority_reason='明显大缺口' if large else '中等视觉缺口',
        largest_visual_gap_px=float(run['length_px']),
        largest_run=dict(begin=begin, end=end, samples=n, start_xy=run['start_xy'], end_xy=run['end_xy']),
        source=dict(frame=frame + 1, direction=frame // 2 + 1, exposure=fit['exposure'], polarity=polarity),
        thresholds=dict(review_weak=weak, slightly_stricter=stricter, raw_bilateral_contrast=c['raw_contrast']),
        counts=dict(raw=int(raw.sum()), response=int(detail.sum()), joint=int(joint.sum()),
                    stricter_joint=int(stricter_joint.sum()), valid=int(allowed.sum()),
                    longest_raw_unsupported_samples=int(raw_empty)),
        joint_supported_native_xy=native[sl][joint].tolist(),
        terms=terms, bottleneck_terms=limitation,
        reasons=[('同一原片暗线' if polarity == -1 else '同一原片亮线') + '支持',
                 '两端走向相符',
                 f'最大缺口内{int(joint.sum())}/{n}个位置具有共同支持',
                 '分数短板：' + '、'.join(TERMS[k] for k in limitation)],
        confidence_probability=None, automatic_pass=False,
    )

def attach_scores(evidence, windows, gray, valid, board, residual, base_plan, core_plan):
    """Keep IDs, boxes and admitted gaps exactly; never choose a box using its score."""
    scored = {g['id']: measure_gap(g, gray, valid, board, residual, base_plan, core_plan)
              for g in evidence['gaps'] if g.get('review')}
    output = []
    for window in windows:
        members = [scored[i] for i in window['gap_ids']]
        if not members:
            raise ValueError('A frozen review window must have admitted members')
        # Use the actual largest gap, not a better-supported nearby small gap.
        representative = max(members, key=lambda s: (s['largest_visual_gap_px'], -s['gap_id']))
        row = copy.deepcopy(window)
        row.update(evidence_support_score=representative['evidence_support_score'],
                   review_priority=representative['review_priority'],
                   representative_gap_id=representative['gap_id'],
                   representative_evidence=representative, member_evidence=members,
                   confidence_probability=None, automatic_pass=False)
        output.append(row)
    order = sorted(output, key=lambda r: (r['review_priority'] != 'high', -r['evidence_support_score'],
                                        -r['largest_visual_gap_px'], r['id']))
    for rank, row in enumerate(order, 1):
        row['view_order'] = rank
    return dict(schema='frozen-orange-review-with-evidence-index-v1', windows=output,
                review_window_count=len(output),
                status='MANUAL_REVIEW_SUGGESTED' if output else 'NO_REVIEW_TRIGGER_IN_THIS_ROUTE',
                status_text='发现待人工复检区域' if output else '本通路未触发复检提示',
                confidence_probability=None, automatic_pass=False,
                coverage='gaps_between_existing_fragments_only',
                score_rule='5 * floor(100 * min(component_terms) / 5)',
                priority_order='visible_gap_tier_then_evidence_score_then_gap_length',
                manual_acceptance='PENDING', formal_detector_unchanged=True)
