"""Independent scalar/common-area and serialized controller oracle for TJ.

No primary controller or detector implementation is imported. Gray/residual
inputs come from the hash-verified external H1/H2 loader in capture_metrics.
Synthetic residual vectors are also accepted and must be tagged synthetic.
All accumulation and decision arithmetic uses unbounded Python integers.

reference_transition accepts complete JSON snapshot/config/event dictionaries.
Bootstrap is the reference-only {'kind': 'start'} event; capture events retain
the public six fields. It returns detached (snapshot, Decision) dictionaries.
Case schema: source_type, snapshot, event, config (optional id/scenario_id and
literal checkpoint). Optional expected_validation_error='ValueError' explicitly
expects programming/identity rejection; result is {'validation_error':'ValueError'}.
Otherwise verification actual schema is state, decision. Export independently
recomputes expected results; it never turns validation rejection into capture failure.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


COUNTS = ('n', 'gray_sum', 'dark_count', 'near_white_count', 'rgb_max_count',
          'effective_count', 'line_center_count', 'line_contrast_sum_n',
          'background_count', 'background_activity_sum_n', 'baseline_candidate_count')
COST_KEYS = ('attempts', 'frames', 'time_ms')
CONFIG_KEYS = ('rule_version', 'threshold_status', 'cost_status', 'channel', 'led',
               'gain16', 'exposures', 'initial_exposure_lines', 'min_area',
               'min_coverage_bp', 'min_effective_bp', 'max_dark_bp', 'max_near_white_bp',
               'rgb_warn_bp', 'rgb_review_bp', 'confirmations', 'max_mean_delta_gray',
               'max_effective_delta_bp', 'max_rgb_delta_bp', 'max_attempts', 'max_frames',
               'max_time_ms', 'discard_frames_per_request', 'frame_time_ms',
               'settle_time_ms', 'retry_limit')
SNAPSHOT_KEYS = ('context_id', 'status', 'visited', 'seen_observation_ids',
                 'seen_source_identities', 'qualified', 'confirmation_reference',
                 'confirmation_count', 'fallback_used', 'retry_count', 'pending_request',
                 'requested_cost', 'consumed_cost', 'unfulfilled_cost',
                 'success_observations', 'risk_seen', 'condition_identity')
FRAME_KEYS = ('context_id', 'observation_id', 'sample_id', 'pose', 'exposure_lines',
              'gain16', 'channel', 'led', 'saved_width', 'saved_height', 'roi',
              'png_sha256', 'rgb565_sha256', 'source_mode', 'source_metadata')
SOURCE_TYPES = ('real_history_replay', 'synthetic_image', 'constructed_statistics')


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value


def _text(value, name):
    if type(value) is not str or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')


def _digest(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _json(value):
    try:
        return json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))
    except (TypeError, ValueError) as error:
        raise ValueError('Input must be finite JSON data') from error


def scalar_metric_reference(gray: np.ndarray, residual_n: np.ndarray,
                            rgb_max: np.ndarray, mask: np.ndarray) -> dict:
    """Visit each pixel/direction explicitly; never call vector line_centers."""
    arrays = (gray, residual_n, rgb_max, mask)
    if any(not isinstance(a, np.ndarray) or a.ndim != 2 for a in arrays):
        raise ValueError('Inputs must be two-dimensional numpy arrays')
    if any(a.shape != gray.shape for a in arrays):
        raise ValueError('Input shapes must match')
    if gray.dtype.kind not in 'iu' or residual_n.dtype.kind not in 'iu':
        raise ValueError('Gray and residual must have integer dtypes')
    if rgb_max.dtype != np.dtype(bool) or mask.dtype != np.dtype(bool):
        raise ValueError('RGB maximum and area inputs must be bool masks')
    if np.any(gray > 255) or np.any(gray < 0) or np.any(residual_n > 20400) or np.any(residual_n < -20400):
        raise ValueError('Gray/residual exceed frozen H1/H2 ranges')
    result = {name: 0 for name in COUNTS if name != 'baseline_candidate_count'}
    height, width = gray.shape
    for row in range(height):
        for column in range(width):
            if not mask[row, column]:
                continue
            value = int(gray[row, column])
            residual = int(residual_n[row, column])
            amplitude = abs(residual)
            result['n'] += 1
            result['gray_sum'] += value
            result['dark_count'] += int(value <= 10)
            result['near_white_count'] += int(value >= 250)
            result['rgb_max_count'] += int(rgb_max[row, column])
            result['effective_count'] += int(value > 10 or amplitude > 648)
            is_center = False
            if amplitude > 648:
                for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
                    points = ((row - dy, column - dx), (row + dy, column + dx))
                    if all(0 <= y < height and 0 <= x < width and mask[y, x] for y, x in points):
                        witnesses = [int(residual_n[y, x]) for y, x in points]
                        if all(abs(v) > 648 and ((v > 0) == (residual > 0)) for v in witnesses):
                            is_center = True
                            break
            if is_center:
                result['line_center_count'] += 1
                result['line_contrast_sum_n'] += amplitude
            else:
                result['background_count'] += 1
                result['background_activity_sum_n'] += amplitude
    return result


def bit_width_contract(max_pixels: int = 1920 * 1080) -> dict:
    """Unsigned maxima/widths; signed residual requires 16 bits.

    Pair products are per comparison operand. Subtraction needs an extra sign
    bit (or unsigned compare/subtract of the larger operand). uint64 covers
    these bounds for full HD; arbitrary future image sizes need recalculation.
    """
    n = _integer(max_pixels, 'max_pixels', 1)
    bounds = dict(pixel_count=n, gray_sum=255*n, residual_absolute_sum=20400*n,
                  basis_point_cross_product=10000*n,
                  stability_gray_cross_product=255*n*n,
                  stability_basis_point_cross_product=10000*n*n,
                  ratio_ranking_cross_product=n*n,
                  background_ranking_cross_product=20400*n*n)
    return {name: {'max': bound, 'bits': bound.bit_length()} for name, bound in bounds.items()}


def _config(config):
    if not isinstance(config, dict) or set(config) != set(CONFIG_KEYS):
        raise ValueError('Unexpected or missing config fields')
    for name in ('rule_version', 'threshold_status', 'cost_status'):
        _text(config[name], name)
    if (config['rule_version'] != 'controller-0.1' or config['threshold_status'] != 'provisional'
            or config['cost_status'] != 'modeled'):
        raise ValueError('Unsupported rule version or configuration status')
    if (not isinstance(config['exposures'], list)
            or any(type(value) is not int for value in config['exposures'])
            or config['exposures'] != [400, 500, 600, 700]):
        raise ValueError('Unsupported exposure set')
    for name in CONFIG_KEYS:
        if name not in ('rule_version', 'threshold_status', 'cost_status', 'exposures'):
            _integer(config[name], name)
    if (config['channel'], config['led'], config['gain16']) != (1, 128, 16):
        raise ValueError('Unsupported fixed parameters')
    if config['discard_frames_per_request'] != 3:
        raise ValueError('controller-0.1 requires three discarded frames per request')
    if config['initial_exposure_lines'] not in config['exposures']:
        raise ValueError('Initial exposure outside allowed set')
    for name in ('min_coverage_bp', 'min_effective_bp', 'max_dark_bp', 'max_near_white_bp',
                 'rgb_warn_bp', 'rgb_review_bp', 'max_effective_delta_bp', 'max_rgb_delta_bp'):
        if config[name] > 10000:
            raise ValueError('Basis points exceed 10000')
    if config['rgb_warn_bp'] > config['rgb_review_bp'] or config['confirmations'] < 2:
        raise ValueError('Invalid risk/confirmation limits')
    for name, upper in (('max_attempts', 8), ('max_frames', 32), ('max_time_ms', 40000), ('retry_limit', 1)):
        if config[name] > upper or (name != 'retry_limit' and config[name] == 0):
            raise ValueError('Global budget/retry limit exceeded')
    if (config['min_area'] < 10000 or config['min_coverage_bp'] < 9500
            or config['frame_time_ms'] < 1 or config['max_mean_delta_gray'] > 255):
        raise ValueError('Invalid area/time/gray limit')


def _cost(attempts=0, frames=0, time_ms=0):
    return dict(attempts=attempts, frames=frames, time_ms=time_ms)


def _add(a, b):
    return {key: a[key] + b[key] for key in COST_KEYS}


def _validate_state(state, config):
    if not isinstance(state, dict) or set(state) != set(SNAPSHOT_KEYS):
        raise ValueError('Incomplete snapshot contract')
    _text(state['context_id'], 'context_id')
    if state['status'] not in ('READY', 'CONTINUE_ADJUST', 'LOCKED', 'NEEDS_REVIEW', 'CAPTURE_FAILED'):
        raise ValueError('Unknown snapshot state')
    for key in ('confirmation_count', 'success_observations'):
        _integer(state[key], key)
    for key in ('fallback_used', 'risk_seen'):
        if type(state[key]) is not bool:
            raise ValueError('State flags must be bool')
    for key in ('requested_cost', 'consumed_cost', 'unfulfilled_cost'):
        if not isinstance(state[key], dict) or set(state[key]) != set(COST_KEYS):
            raise ValueError('Incomplete cost')
        for axis in COST_KEYS:
            _integer(state[key][axis], axis)
    for key in ('visited', 'seen_observation_ids', 'seen_source_identities', 'qualified'):
        if not isinstance(state[key], list):
            raise ValueError('State histories must be arrays')
    if any(type(v) is not int or v not in config['exposures'] for v in state['visited']):
        raise ValueError('Invalid visited setting')
    if not isinstance(state['retry_count'], dict):
        raise ValueError('Invalid retry map')
    for key, value in state['retry_count'].items():
        if key not in ('400', '500', '600', '700'):
            raise ValueError('Invalid retry exposure')
        _integer(value, 'retry_count')
    condition = state['condition_identity']
    if condition is not None:
        if not isinstance(condition, list) or len(condition) != 3 or not _digest(condition[2]):
            raise ValueError('Invalid condition identity')
        _text(condition[0], 'sample_id')
        _text(condition[1], 'pose')
    pending = state['pending_request']
    reserved = _cost()
    if pending is not None:
        if not isinstance(pending, dict) or set(pending) != {'exposure_lines', 'action_kind', 'cost'} or pending['exposure_lines'] not in config['exposures']:
            raise ValueError('Invalid pending request')
        reserved = pending['cost']
        if not isinstance(reserved, dict) or set(reserved) != set(COST_KEYS):
            raise ValueError('Invalid reserved cost')
        for axis in COST_KEYS:
            _integer(reserved[axis], axis)
    for axis in COST_KEYS:
        if state['requested_cost'][axis] != state['consumed_cost'][axis] + state['unfulfilled_cost'][axis] + reserved[axis]:
            raise ValueError('Cost reservation invariant violated')


def _metrics(metric):
    if not isinstance(metric, dict) or set(metric) != set(COUNTS) | {'geometry', 'native_reference_statistics'}:
        raise ValueError('Invalid metric schema')
    for name in COUNTS:
        _integer(metric[name], name)
    n = metric['n']
    for key in ('dark_count', 'near_white_count', 'rgb_max_count', 'effective_count',
                'line_center_count', 'background_count', 'baseline_candidate_count'):
        if metric[key] > n:
            raise ValueError('Metric count exceeds denominator')
    ordinary = n - metric['dark_count'] - metric['near_white_count']
    if ordinary < 0 or metric['effective_count'] < n - metric['dark_count']:
        raise ValueError('Unreachable gray/effective partition')
    low = ordinary*11 + metric['near_white_count']*250
    high = ordinary*249 + metric['dark_count']*10 + metric['near_white_count']*255
    if not low <= metric['gray_sum'] <= high:
        raise ValueError('Unreachable gray sum')
    if metric['background_count'] + metric['line_center_count'] != n:
        raise ValueError('Line/background do not partition area')
    for count, total in (('line_center_count', 'line_contrast_sum_n'),
                         ('background_count', 'background_activity_sum_n')):
        if metric[total] > 20400*metric[count]:
            raise ValueError('Residual sum exceeds H2 range')
    if not isinstance(metric['geometry'], dict) or not isinstance(metric['native_reference_statistics'], dict):
        raise ValueError('Geometry/diagnostics must be objects')


def _provenance(geometry):
    """Rebuild the immutable record; storage paths/observation UUID excluded."""
    metadata = geometry['source_metadata']
    if not isinstance(metadata, dict):
        raise ValueError('Source metadata must be object')
    if any(type(metadata.get(key)) is not str or not metadata[key].strip()
           for key in ('dataset_id', 'capture_id', 'member')):
        return None
    frame_id = metadata.get('frame_id')
    if not ((type(frame_id) is str and frame_id.strip()) or (type(frame_id) is int and frame_id >= 0)):
        return None
    record = {'source_mode': geometry['source_mode'],
              **{key: metadata[key] for key in ('dataset_id', 'capture_id', 'frame_id', 'member')},
              **{key: geometry[key] for key in ('png_sha256', 'rgb565_sha256')}}
    digest = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
    if geometry.get('source_identity') not in (None, digest) or geometry.get('source_identity_record') not in (None, record):
        raise ValueError('Source identity contradicts immutable provenance')
    return digest


def _geometry(metric, config):
    g = metric['geometry']
    if not isinstance(g.get('reason_codes', []), list):
        raise ValueError('Geometry reasons must be an array')
    reasons = list(g.get('reason_codes', []))
    if any(type(reason) is not str for reason in reasons):
        raise ValueError('Invalid geometry reasons')
    for key in ('available', 'source_identity_available'):
        if key in g and type(g[key]) is not bool:
            raise ValueError('Geometry availability flags must be bool')
    for key in ('channel', 'led', 'gain16', 'exposure_lines'):
        if key in g:
            _integer(g[key], key, 1)
            if (key == 'exposure_lines' and g[key] not in config['exposures']) or (key != 'exposure_lines' and g[key] != config[key]):
                raise ValueError('Unsupported frame settings')
    def add(reason):
        if reason not in reasons:
            reasons.append(reason)
    if any(key not in g for key in FRAME_KEYS):
        add('geometry_unavailable')
        return None, None, reasons, False
    for key in ('context_id', 'observation_id', 'sample_id', 'pose', 'source_mode'):
        _text(g[key], key)
    for key in ('exposure_lines', 'gain16', 'channel', 'led'):
        _integer(g[key], key, 1)
    if g['exposure_lines'] not in config['exposures'] or any(g[k] != config[k] for k in ('channel', 'led', 'gain16')):
        raise ValueError('Unsupported frame settings')
    for key in ('saved_width', 'saved_height'):
        _integer(g[key], key, 9)
    if not isinstance(g['roi'], list) or len(g['roi']) != 4:
        raise ValueError('Malformed ROI')
    for value in g['roi']:
        _integer(value, 'roi')
    if g['roi'][2:] != [g['saved_width'], g['saved_height']] or any(not _digest(g[k]) for k in ('png_sha256', 'rgb565_sha256')):
        raise ValueError('ROI/hash mismatch')
    identity = _provenance(g)
    if identity is None or g.get('source_identity_available') is not True:
        add('source_identity_unavailable')
    if g.get('available') is not True:
        add('geometry_unavailable')
    required = ('common_area', 'native_area', 'coverage_numerator', 'coverage_denominator',
                'common_mask_sha256', 'evaluation_area_version', 'mask_sources', 'min_area', 'min_coverage_bp')
    if any(key not in g for key in required):
        add('geometry_unavailable')
        return g['exposure_lines'], identity, reasons, False
    for key in ('common_area', 'native_area', 'coverage_numerator', 'min_area', 'min_coverage_bp'):
        _integer(g[key], key)
    denominator = g['coverage_denominator']
    if denominator is not None:
        _integer(denominator, 'coverage_denominator')
    if not _digest(g['common_mask_sha256']) or not isinstance(g['mask_sources'], list):
        raise ValueError('Invalid mask evidence')
    if (g['common_area'] != metric['n'] or g['coverage_numerator'] != g['common_area']
            or g['coverage_denominator'] != g['native_area'] or g['common_area'] > g['native_area']):
        add('geometry_inconsistent')
    if not denominator or g['coverage_numerator']*10000 < config['min_coverage_bp']*denominator:
        add('insufficient_common_coverage')
    if g['evaluation_area_version'] != 'common-evaluation-1':
        add('geometry_version_unavailable')
    mappings = [source for source in g['mask_sources'] if isinstance(source, dict)
                and source.get('observation_id') == g['observation_id']
                and source.get('source_identity') == identity
                and source.get('roi') == g['roi'] and _digest(source.get('native_mask_sha256'))
                and type(source.get('mask_source')) is str and source['mask_source'].strip()
                and type(source.get('needs_manual_review')) is bool]
    if not mappings:
        add('geometry_source_mapping_unavailable')
    return g['exposure_lines'], identity, list(dict.fromkeys(reasons)), not reasons


def _quality(metric, config):
    _metrics(metric)
    exposure, identity, reasons, evidence = _geometry(metric, config)
    n = metric['n']
    evidence = evidence and n >= config['min_area']
    dark = metric['dark_count']*10000 > config['max_dark_bp']*n
    ineffective = not n or metric['effective_count']*10000 < config['min_effective_bp']*n
    rgb_warn = metric['rgb_max_count']*10000 > config['rgb_warn_bp']*n
    rgb_review = metric['rgb_max_count']*10000 > config['rgb_review_bp']*n
    near_white = metric['near_white_count']*10000 > config['max_near_white_bp']*n
    signal = not n or dark or ineffective
    glare = rgb_warn or near_white
    conditions = [(n < config['min_area'], 'insufficient_common_area'), (dark, 'too_dark'),
                  (ineffective, 'insufficient_effective_area'), (rgb_warn, 'rgb_risk_warning'),
                  (rgb_review, 'rgb_high_risk'), (near_white, 'near_white_risk'),
                  (signal and glare, 'dark_and_highlight')]
    reasons.extend(reason for condition, reason in conditions if condition and reason not in reasons)
    statistics = dict(version='controller-statistics-1', **{key: metric[key] for key in COUNTS},
                      mean_gray={'numerator': metric['gray_sum'], 'denominator': n} if n else None,
                      background_mean_n={'numerator': metric['background_activity_sum_n'],
                                         'denominator': metric['background_count']} if metric['background_count'] else None)
    return dict(**statistics, exposure_lines=exposure,
                source_identity=identity, geometry=metric['geometry'],
                native_reference_statistics=metric['native_reference_statistics'],
                evidence_available=evidence, signal_insufficient=signal,
                highlight_risk=glare, qualified=evidence and n >= config['min_area'] and not signal and not glare,
                reason_codes=reasons)


def _best(records):
    """Independent tournament: exact lexicographic fractional priorities."""
    winner = None
    for record in records:
        if not record['qualified']:
            continue
        if winner is None:
            winner = record
            continue
        a, b = record, winner
        rgb = a['rgb_max_count']*b['n'] - b['rgb_max_count']*a['n']
        effective = a['effective_count']*b['n'] - b['effective_count']*a['n']
        if rgb:
            wins = rgb < 0
        elif effective:
            wins = effective > 0
        elif bool(a['background_count']) != bool(b['background_count']):
            wins = bool(a['background_count'])
        elif a['background_count'] and (a['background_activity_sum_n']*b['background_count'] != b['background_activity_sum_n']*a['background_count']):
            wins = a['background_activity_sum_n']*b['background_count'] < b['background_activity_sum_n']*a['background_count']
        else:
            wins = record['exposure_lines'] < winner['exposure_lines']
        if wins:
            winner = record
    return winner


def _stable(a, b, config):
    product = a['n']*b['n']
    return (abs(a['gray_sum']*b['n'] - b['gray_sum']*a['n']) <= config['max_mean_delta_gray']*product
            and abs(a['effective_count']*b['n'] - b['effective_count']*a['n'])*10000 <= config['max_effective_delta_bp']*product
            and abs(a['rgb_max_count']*b['n'] - b['rgb_max_count']*a['n'])*10000 <= config['max_rgb_delta_bp']*product)


def reference_transition(snapshot: dict, event: dict, config: dict) -> tuple[dict, dict]:
    """Evaluate one specified observation/error/missing request or bootstrap."""
    state, event, config = _json(snapshot), _json(event), _json(config)
    _config(config)
    _validate_state(state, config)
    if not isinstance(event, dict):
        raise ValueError('Event must be an object')
    frame_cost = config['discard_frames_per_request'] + 1
    request_cost = _cost(1, frame_cost, config['settle_time_ms'] + frame_cost*config['frame_time_ms'])
    limits = _cost(config['max_attempts'], config['max_frames'], config['max_time_ms'])
    statistics = None

    def result(status, action, exposure, reasons):
        state['status'] = status
        reserved = state['pending_request']['cost'] if state['pending_request'] else _cost()
        budget = dict(cost_status='modeled', requested_cost=state['requested_cost'],
                      consumed_cost=state['consumed_cost'], reserved_cost=reserved,
                      unfulfilled_cost=state['unfulfilled_cost'],
                      remaining_cost={axis: limits[axis] - state['requested_cost'][axis] for axis in COST_KEYS},
                      limits=limits, historical_capture_cost=None, measured_live_control_cost=None)
        decision = dict(status=status, action_kind=action, next_exposure_lines=exposure,
                        reason_codes=list(dict.fromkeys(reasons)), input_statistics=statistics, budget=budget)
        return _json(state), _json(decision)

    def stop(status, reasons):
        state['pending_request'] = None
        return result(status, 'stop', None, reasons)

    def request(action, exposure, reasons):
        if any(state['requested_cost'][axis] + request_cost[axis] > limits[axis] for axis in COST_KEYS):
            return stop('NEEDS_REVIEW', reasons + ['budget_exhausted'])
        state['requested_cost'] = _add(state['requested_cost'], request_cost)
        state['pending_request'] = dict(exposure_lines=exposure, action_kind=action, cost=request_cost)
        if action == 'set_exposure':
            state['visited'] = sorted(set(state['visited']) | {exposure})
        if action == 'set_exposure':
            state['confirmation_count'], state['confirmation_reference'] = 0, None
        return result('CONTINUE_ADJUST', action, exposure, reasons)

    def fallback(reasons):
        winner = _best(state['qualified'])
        if winner is not None and not state['fallback_used']:
            state['fallback_used'] = True
            # Selecting a fresh fallback ends the old confirmation even when
            # the budget cannot fund that request. Exhausted fallback retains it.
            state['confirmation_count'], state['confirmation_reference'] = 0, None
            return request('fallback_confirm', winner['exposure_lines'], reasons + ['fresh_fallback_confirmation_required'])
        status = 'NEEDS_REVIEW' if winner is not None or state['risk_seen'] else 'CAPTURE_FAILED'
        return stop(status, reasons + ['fallback_exhausted' if winner is not None else 'no_qualified_fallback'])

    if event.get('kind') == 'start':
        if event != {'kind': 'start'} or state['status'] != 'READY' or state['pending_request'] is not None:
            raise ValueError('Bootstrap requires untouched READY snapshot')
        return request('set_exposure', config['initial_exposure_lines'], ['initial_request'])
    if state['status'] != 'CONTINUE_ADJUST' or state['pending_request'] is None:
        raise ValueError('Capture event requires active pending request')
    if set(event) != {'kind', 'context_id', 'observation_id', 'exposure_lines', 'metrics', 'error_code'}:
        raise ValueError('Incomplete event schema')
    if event['kind'] not in ('observation', 'capture_error', 'missing_data'):
        raise ValueError('Unsupported capture event')
    if event['context_id'] != state['context_id'] or type(event['exposure_lines']) is not int or event['exposure_lines'] != state['pending_request']['exposure_lines']:
        raise ValueError('Event context/exposure mismatch')
    for name in ('observation_id', 'error_code'):
        if event[name] is not None:
            _text(event[name], name)
    pending = state['pending_request']
    if event['kind'] == 'observation':
        _text(event['observation_id'], 'observation_id')
        if event['error_code'] is not None:
            raise ValueError('Observation cannot contain capture error')
        statistics = _quality(event['metrics'], config)
        g = statistics['geometry']
        for name in ('context_id', 'observation_id', 'exposure_lines'):
            if name in g and g[name] != event[name]:
                raise ValueError('Frame/event identity mismatch')
        if event['observation_id'] in state['seen_observation_ids'] or (statistics['source_identity'] is not None and statistics['source_identity'] in state['seen_source_identities']):
            raise ValueError('Independent observation identity already consumed')
        if state['condition_identity'] is not None:
            for index, name in enumerate(('sample_id', 'pose', 'common_mask_sha256')):
                if name in g and g[name] != state['condition_identity'][index]:
                    raise ValueError('Frame geometry conditions changed')
        if statistics['evidence_available'] and all(name in g for name in ('sample_id', 'pose', 'common_mask_sha256')):
            condition = [g['sample_id'], g['pose'], g['common_mask_sha256']]
            if state['condition_identity'] is not None and state['condition_identity'] != condition:
                raise ValueError('Frame geometry conditions changed')
            if state['condition_identity'] is None:
                state['condition_identity'] = condition
    elif event['metrics'] is not None:
        raise ValueError('Error/missing event cannot contain metrics')
    state['pending_request'] = None
    if event['kind'] == 'missing_data':
        state['unfulfilled_cost'] = _add(state['unfulfilled_cost'], pending['cost'])
        reason = 'missing_fresh_confirmation' if pending['action_kind'] in ('confirm_current', 'fallback_confirm') else 'missing_requested_data'
        return stop('NEEDS_REVIEW', [reason, 'unfulfilled_modeled_request'])
    state['consumed_cost'] = _add(state['consumed_cost'], pending['cost'])
    if event['kind'] == 'capture_error':
        state['confirmation_count'], state['confirmation_reference'] = 0, None
        key = str(event['exposure_lines'])
        used = state['retry_count'].get(key, 0)
        if used < config['retry_limit']:
            state['retry_count'][key] = used + 1
            return request('retry_current', event['exposure_lines'], ['capture_error', event['error_code'] or 'unspecified_error'])
        # Acquisition retry exhaustion is terminal, regardless of prior quality.
        # The single fallback is reserved for confirmation/search policy.
        return stop('CAPTURE_FAILED', ['capture_error', 'retry_exhausted'])
    state['seen_observation_ids'] = sorted(state['seen_observation_ids'] + [event['observation_id']])
    if statistics['source_identity'] is not None:
        state['seen_source_identities'] = sorted(state['seen_source_identities'] + [statistics['source_identity']])
    state['success_observations'] += 1
    reasons = statistics['reason_codes']
    if statistics['evidence_available']:
        state['risk_seen'] = state['risk_seen'] or statistics['highlight_risk']
    if not statistics['evidence_available'] or statistics['n'] < config['min_area'] or (statistics['signal_insufficient'] and statistics['highlight_risk']):
        return stop('NEEDS_REVIEW', reasons)
    if statistics['qualified']:
        state['qualified'].append(statistics)
        reference = state['confirmation_reference']
        if reference is not None and not _stable(reference, statistics, config):
            return fallback(['confirmation_unstable'])
        if reference is None:
            state['confirmation_reference'] = statistics
        state['confirmation_count'] += 1
        if state['confirmation_count'] >= config['confirmations']:
            return stop('LOCKED', ['offline_policy_locked', 'independent_stable_confirmations'])
        return request('confirm_current', event['exposure_lines'], ['fresh_confirmation_required'])
    state['confirmation_count'], state['confirmation_reference'] = 0, None
    exposures = config['exposures']
    index = exposures.index(event['exposure_lines']) + (-1 if statistics['highlight_risk'] else 1)
    if 0 <= index < len(exposures) and exposures[index] not in state['visited']:
        return request('set_exposure', exposures[index], reasons)
    return fallback(reasons + ['search_exhausted'])


def _case(case):
    if not isinstance(case, dict) or case.get('source_type') not in SOURCE_TYPES:
        raise ValueError('Each case must explicitly identify its source type')
    if not {'snapshot', 'event', 'config'} <= set(case):
        raise ValueError('Case must retain complete state, event and configuration')
    rejection = case.get('expected_validation_error')
    if rejection is not None and rejection != 'ValueError':
        raise ValueError('Only explicit ValueError rejection is supported')
    try:
        state, decision = reference_transition(case['snapshot'], case['event'], case['config'])
    except ValueError:
        if rejection == 'ValueError':
            return {'validation_error': 'ValueError'}
        raise
    if rejection is not None:
        raise ValueError('Expected interface rejection did not occur')
    return dict(state=state, decision=decision)


def _constructed_event(identity, config, exposure=600, **counts):
    """TJ artifact content: fictional capture identities and hand-made counts."""
    geometry = dict(context_id='tj-constructed', observation_id=identity,
                    sample_id='fictional-board', pose='A', exposure_lines=exposure,
                    gain16=16, channel=1, led=128, saved_width=100, saved_height=100,
                    roi=[0, 0, 100, 100], png_sha256='a'*64, rgb565_sha256='b'*64,
                    source_mode='constructed_statistics', source_metadata=dict(
                        dataset_id='tj-artificial-vectors', capture_id=identity,
                        frame_id=identity, member=identity+'.png'))
    identity_hash = _provenance(geometry)
    metadata = geometry['source_metadata']
    geometry.update(source_identity=identity_hash, source_identity_available=True,
                    source_identity_record={'source_mode': geometry['source_mode'],
                                            **metadata, 'png_sha256': 'a'*64,
                                            'rgb565_sha256': 'b'*64},
                    evaluation_area_version='common-evaluation-1', common_mask_sha256='c'*64,
                    native_area=10000, common_area=10000, coverage_numerator=10000,
                    coverage_denominator=10000, min_area=config['min_area'],
                    min_coverage_bp=config['min_coverage_bp'], available=True,
                    reason_codes=[], mask_sources=[dict(observation_id=identity,
                        source_identity=identity_hash, roi=[0, 0, 100, 100],
                        native_mask_sha256='d'*64, mask_source='constructed_statistics',
                        needs_manual_review=True)])
    metric = dict(n=10000, gray_sum=1000000, dark_count=0, near_white_count=0,
                  rgb_max_count=0, effective_count=10000, line_center_count=0,
                  line_contrast_sum_n=0, background_count=10000,
                  background_activity_sum_n=0, baseline_candidate_count=0,
                  geometry=geometry, native_reference_statistics={})
    metric.update(counts)
    return dict(kind='observation', context_id='tj-constructed', observation_id=identity,
                exposure_lines=exposure, metrics=metric, error_code=None)


def constructed_golden_cases(config: dict) -> list[dict]:
    """Reusable default-policy vectors with literal independently chosen checkpoints.

    Return complete replayable transitions, including four explicit rejection
    cases. These are artificial statistics, never historical images or physical
    captures. Custom threshold sensitivity runs should build separate cases.
    """
    config = _json(config)
    _config(config)
    required = dict(initial_exposure_lines=600, min_area=10000, min_coverage_bp=9500,
                    min_effective_bp=9000, max_dark_bp=1000, max_near_white_bp=100,
                    rgb_warn_bp=500, rgb_review_bp=1000, confirmations=2,
                    max_mean_delta_gray=2, max_effective_delta_bp=200, max_rgb_delta_bp=50,
                    max_attempts=8, max_frames=32, max_time_ms=40000,
                    discard_frames_per_request=3, frame_time_ms=1000,
                    settle_time_ms=1000, retry_limit=1)
    if any(config[key] != value for key, value in required.items()):
        raise ValueError('Constructed baseline vectors require default rule/cost limits')
    cases = []
    continue_at = lambda action, exposure: dict(status='CONTINUE_ADJUST', action_kind=action, next_exposure_lines=exposure)
    stopped = lambda status: dict(status=status, action_kind='stop', next_exposure_lines=None)
    def simple(kind, exposure=600):
        return dict(kind=kind, context_id='tj-constructed', observation_id=None,
                    exposure_lines=exposure, metrics=None, error_code=None)
    def scenario(name, events, checkpoints, special_config=None, reject_last=False):
        cfg = config if special_config is None else special_config
        state = dict(context_id='tj-constructed', status='READY', visited=[],
                     seen_observation_ids=[], seen_source_identities=[], qualified=[],
                     confirmation_reference=None, confirmation_count=0, fallback_used=False,
                     retry_count={str(exposure): 0 for exposure in cfg['exposures']},
                     pending_request=None, requested_cost=_cost(),
                     consumed_cost=_cost(), unfulfilled_cost=_cost(), success_observations=0,
                     risk_seen=False, condition_identity=None)
        all_events = [{'kind': 'start'}] + events
        all_checkpoints = [continue_at('set_exposure', 600)] + checkpoints
        for index, (event, checkpoint) in enumerate(zip(all_events, all_checkpoints)):
            case = dict(source_type='constructed_statistics', scenario_id=name,
                        snapshot=_json(state), event=event, config=cfg)
            if reject_last and index == len(all_events)-1:
                case['expected_validation_error'] = 'ValueError'
                _case(case)  # Fail construction if the intended rejection disappeared.
            else:
                case['checkpoint'] = checkpoint
                state, decision = reference_transition(state, event, cfg)
                if any(decision[key] != value for key, value in checkpoint.items()):
                    raise ValueError(f'Independent reference contradicts literal checkpoint: {name}')
            cases.append(case)
    clean = lambda identity, exposure=600, **counts: _constructed_event(identity, config, exposure, **counts)
    dark = dict(dark_count=10000, effective_count=0, gray_sum=0)
    scenario('normal_no_candidates', [clean('normal-1'), clean('normal-2')],
             [continue_at('confirm_current', 600), stopped('LOCKED')])
    scenario('highlight_down', [clean('glare', rgb_max_count=501), simple('missing_data', 500)],
             [continue_at('set_exposure', 500), stopped('NEEDS_REVIEW')])
    scenario('dark_up_and_exhausted', [clean('dark-1', **dark), clean('dark-2', 700, **dark)],
             [continue_at('set_exposure', 700), stopped('CAPTURE_FAILED')])
    scenario('dark_and_highlight', [clean('conflict', **dark, rgb_max_count=501)], [stopped('NEEDS_REVIEW')])
    scenario('strict_equalities', [clean('equal', dark_count=1000, effective_count=9000,
                                       near_white_count=100, rgb_max_count=500, gray_sum=900000)],
             [continue_at('confirm_current', 600)])
    scenario('candidate_growth_does_not_cancel_risk', [clean('candidates', rgb_max_count=501,
                                                           baseline_candidate_count=10000)],
             [continue_at('set_exposure', 500)])
    scenario('budget_exhausted', [clean('budget')], [stopped('NEEDS_REVIEW')], {**config, 'max_attempts': 1})
    scenario('missing_fresh_confirmation', [clean('missing-1'), simple('missing_data')],
             [continue_at('confirm_current', 600), stopped('NEEDS_REVIEW')])
    scenario('capture_error_retry', [simple('capture_error'), simple('capture_error')],
             [continue_at('retry_current', 600), stopped('CAPTURE_FAILED')])
    scenario('fallback_requires_new_frame', [clean('fallback-1'), clean('fallback-2', gray_sum=1030000), simple('missing_data')],
             [continue_at('confirm_current', 600), continue_at('fallback_confirm', 600), stopped('NEEDS_REVIEW')])
    duplicate = clean('duplicate')
    scenario('duplicate_identity', [duplicate, _json(duplicate)], [continue_at('confirm_current', 600), None], reject_last=True)
    wrong_context = clean('wrong-context')
    wrong_context['context_id'] = 'different-context'
    scenario('wrong_context', [wrong_context], [None], reject_last=True)
    scenario('terminal_rejection', [clean('terminal-1'), clean('terminal-2'), clean('terminal-3')],
             [continue_at('confirm_current', 600), stopped('LOCKED'), None], reject_last=True)
    wrong_sample = clean('wrong-sample', 700)
    wrong_sample['metrics']['geometry']['sample_id'] = 'different-fictional-board'
    scenario('different_sample', [clean('sample-first', **dark), wrong_sample],
             [continue_at('set_exposure', 700), None], reject_last=True)
    scenario('risk_history', [clean('risk-first', rgb_max_count=501), clean('risk-dark', 500, **dark)],
             [continue_at('set_exposure', 500), stopped('NEEDS_REVIEW')])
    return _json(cases)


def _differences(expected, actual, path=''):
    if type(expected) is not type(actual):
        return [dict(path=path, expected=expected, actual=actual)]
    if isinstance(expected, dict):
        result = []
        for key in sorted(set(expected) | set(actual)):
            current = f'{path}.{key}' if path else key
            if key not in expected or key not in actual:
                result.append(dict(path=current, expected=expected.get(key), actual=actual.get(key), missing_key=True))
            else:
                result.extend(_differences(expected[key], actual[key], current))
        return result
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [dict(path=path, expected=expected, actual=actual)]
        return [difference for index, (a, b) in enumerate(zip(expected, actual))
                for difference in _differences(a, b, f'{path}[{index}]')]
    return [] if expected == actual else [dict(path=path, expected=expected, actual=actual)]


def verify_reference(cases: list[dict], actual: list[dict]) -> dict:
    """Compare complete state and Decision; report exact changed JSON paths."""
    if not isinstance(cases, list) or not isinstance(actual, list):
        raise ValueError('Cases and actual results must be lists')
    expected = [_case(case) for case in cases]
    mismatches = _differences(expected, _json(actual), 'cases')
    return dict(passed=not mismatches, checked=len(cases), mismatches=mismatches)


def export_golden(cases: list[dict], destination: Path) -> None:
    """Exclusive strict JSON export of input and independently derived expected."""
    if not isinstance(cases, list):
        raise ValueError('Cases must be a list')
    records = [dict(source_type=case.get('source_type'), input=_json(case), expected=_case(case)) for case in cases]
    artifact = dict(reference_version='tj-independent-reference-1', cases=records,
                    bit_widths=bit_width_contract(), offline_verified=True,
                    provisional_thresholds=True, hardware_validation_pending=True)
    text = json.dumps(artifact, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
    with Path(destination).open('x', encoding='utf-8') as stream:
        stream.write(text)
