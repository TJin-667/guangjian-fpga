"""Validated settings and modeled request costs for the offline controller."""
from dataclasses import dataclass, fields
from capture_metrics import FrameInput, FrameMetrics, FrozenDict, source_identity, _freeze


@dataclass(frozen=True)
class Cost:
    attempts: int
    frames: int
    time_ms: int

    def __post_init__(self) -> None:
        for name in ('attempts', 'frames', 'time_ms'):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f'{name} must be a nonnegative integer')


@dataclass(frozen=True)
class ControllerConfig:
    rule_version: str = 'controller-0.1'
    threshold_status: str = 'provisional'
    cost_status: str = 'modeled'
    channel: int = 1
    led: int = 128
    gain16: int = 16
    exposures: tuple[int, ...] = (400, 500, 600, 700)
    initial_exposure_lines: int = 600
    min_area: int = 10000
    min_coverage_bp: int = 9500
    min_effective_bp: int = 9000
    max_dark_bp: int = 1000
    max_near_white_bp: int = 100
    rgb_warn_bp: int = 500
    rgb_review_bp: int = 1000
    confirmations: int = 2
    max_mean_delta_gray: int = 2
    max_effective_delta_bp: int = 200
    max_rgb_delta_bp: int = 50
    max_attempts: int = 8
    max_frames: int = 32
    max_time_ms: int = 40000
    discard_frames_per_request: int = 3
    frame_time_ms: int = 1000
    settle_time_ms: int = 1000
    retry_limit: int = 1

    def __post_init__(self) -> None:
        self.validate()

    @classmethod
    def from_dict(cls, payload: dict) -> 'ControllerConfig':
        if type(payload) is not dict:
            raise ValueError('Configuration must be a JSON object')
        unknown = set(payload) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f'Unknown configuration fields: {sorted(unknown, key=str)}')
        values = dict(payload)
        if 'exposures' in values:
            if type(values['exposures']) not in (list, tuple):
                raise ValueError('exposures must be an array of integer exposure lines')
            values['exposures'] = tuple(values['exposures'])
        return cls(**values)

    def validate(self) -> None:
        fixed = {'rule_version': 'controller-0.1', 'threshold_status': 'provisional',
                 'cost_status': 'modeled', 'channel': 1, 'led': 128, 'gain16': 16,
                 'discard_frames_per_request': 3}
        for name, expected in fixed.items():
            value = getattr(self, name)
            if type(value) is not type(expected) or value != expected:
                raise ValueError(f'{name} must be {expected!r} for controller-0.1')
        if (type(self.exposures) is not tuple
                or any(type(value) is not int for value in self.exposures)
                or self.exposures != (400, 500, 600, 700)):
            raise ValueError('exposures must be (400, 500, 600, 700) lines')
        if type(self.initial_exposure_lines) is not int or self.initial_exposure_lines not in self.exposures:
            raise ValueError('initial_exposure_lines must be an allowed exposure in lines')
        ranges = {
            'min_area': (10000, None), 'min_coverage_bp': (9500, 10000),
            'min_effective_bp': (0, 10000), 'max_dark_bp': (0, 10000),
            'max_near_white_bp': (0, 10000), 'rgb_warn_bp': (0, 10000),
            'rgb_review_bp': (0, 10000), 'confirmations': (2, None),
            'max_mean_delta_gray': (0, 255), 'max_effective_delta_bp': (0, 10000),
            'max_rgb_delta_bp': (0, 10000), 'max_attempts': (1, 8),
            'max_frames': (1, 32), 'max_time_ms': (1, 40000),
            'frame_time_ms': (1, None), 'settle_time_ms': (0, None),
            'retry_limit': (0, 1),
        }
        for name, (minimum, maximum) in ranges.items():
            value = getattr(self, name)
            if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
                raise ValueError(f'{name} must be an integer in [{minimum}, {maximum}]')
        if self.rgb_warn_bp > self.rgb_review_bp:
            raise ValueError('rgb_warn_bp must not exceed rgb_review_bp')

    @property
    def request_cost(self) -> Cost:
        frames = self.discard_frames_per_request + 1
        return Cost(1, frames, self.settle_time_ms + frames * self.frame_time_ms)


@dataclass(frozen=True)
class CaptureEvent:
    kind: str
    context_id: str
    observation_id: str | None
    exposure_lines: int
    metrics: FrameMetrics | None
    error_code: str | None

    def __post_init__(self):
        if self.kind not in ('observation', 'capture_error', 'missing_data'):
            raise ValueError('Unsupported capture event kind.')
        if type(self.context_id) is not str or not self.context_id.strip():
            raise ValueError('context_id must be a nonempty string.')
        if type(self.exposure_lines) is not int or self.exposure_lines not in (400, 500, 600, 700):
            raise ValueError('Unsupported exposure in lines.')
        if self.observation_id is not None and (type(self.observation_id) is not str or not self.observation_id.strip()):
            raise ValueError('observation_id must be nonempty or None.')
        if self.error_code is not None and (type(self.error_code) is not str or not self.error_code.strip()):
            raise ValueError('error_code must be nonempty or None.')
        if self.kind == 'observation':
            if self.observation_id is None or not isinstance(self.metrics, FrameMetrics) or self.error_code is not None:
                raise ValueError('Observation needs identity and metrics, without capture error.')
        elif self.metrics is not None:
            raise ValueError('Non-observation events cannot supply metrics.')


@dataclass(frozen=True)
class Decision:
    status: str
    action_kind: str
    next_exposure_lines: int | None
    reason_codes: tuple[str, ...]
    input_statistics: dict | None
    budget: dict

    def __post_init__(self):
        object.__setattr__(self, 'reason_codes', tuple(self.reason_codes))
        object.__setattr__(self, 'input_statistics', _freeze(self.input_statistics))
        object.__setattr__(self, 'budget', _freeze(self.budget))


@dataclass(frozen=True)
class ControllerSnapshot:
    context_id: str
    status: str
    visited: tuple[int, ...]
    seen_observation_ids: tuple[str, ...]
    seen_source_identities: tuple[str, ...]
    qualified: tuple[dict, ...]
    confirmation_reference: dict | None
    confirmation_count: int
    fallback_used: bool
    retry_count: dict
    pending_request: dict | None
    requested_cost: Cost
    consumed_cost: Cost
    unfulfilled_cost: Cost
    success_observations: int
    risk_seen: bool
    condition_identity: tuple[str, str, str] | None


def _cost_sum(left, right):
    return Cost(left.attempts + right.attempts, left.frames + right.frames,
                left.time_ms + right.time_ms)


def _cost_dict(cost):
    return {field.name: getattr(cost, field.name) for field in fields(Cost)}


def _geometry_evidence(metrics, config):
    """Validate immutable trace and retain unavailable evidence as review reasons."""
    geometry = metrics.geometry
    for name in ('channel', 'led', 'gain16'):
        if name in geometry and (type(geometry[name]) is not int or geometry[name] != getattr(config, name)):
            raise ValueError(f'Unsupported immutable frame {name}.')
    for name in ('available', 'source_identity_available'):
        if name in geometry and type(geometry[name]) is not bool:
            raise ValueError(f'Malformed geometry {name}.')
    source_reasons = geometry.get('reason_codes', ())
    if not isinstance(source_reasons, (tuple, list)) or not all(type(reason) is str and reason.strip()
                                                             for reason in source_reasons):
        raise ValueError('Malformed geometry reason codes.')
    frame_names = tuple(field.name for field in fields(FrameInput))
    if any(name not in geometry for name in frame_names):
        return None, tuple(dict.fromkeys((*source_reasons, 'geometry_unavailable')))
    frame = FrameInput(**{name: geometry[name] for name in frame_names})
    for name in ('channel', 'led', 'gain16'):
        if getattr(frame, name) != getattr(config, name):
            raise ValueError(f'Unsupported immutable frame {name}.')
    if frame.exposure_lines not in config.exposures:
        raise ValueError('Unsupported immutable frame exposure.')
    identity = source_identity(frame)
    record = ({'source_mode': frame.source_mode,
               **{key: frame.source_metadata[key] for key in ('dataset_id', 'capture_id', 'frame_id', 'member')},
               'png_sha256': frame.png_sha256, 'rgb565_sha256': frame.rgb565_sha256}
              if identity else None)
    if geometry.get('source_identity') != identity or geometry.get('source_identity_record') != record:
        raise ValueError('Immutable source identity or source record mismatch.')
    reasons = list(source_reasons)
    if identity is None or geometry.get('source_identity_available') is not True:
        reasons.append('source_identity_unavailable')
    if geometry.get('available') is not True:
        reasons.append('geometry_unavailable')
    required = ('native_area', 'common_area', 'coverage_numerator', 'coverage_denominator',
                'common_mask_sha256', 'evaluation_area_version', 'mask_sources',
                'reason_codes', 'min_area', 'min_coverage_bp')
    if any(name not in geometry for name in required):
        reasons.append('geometry_unavailable')
        return frame, tuple(dict.fromkeys(reasons))
    for name in ('native_area', 'common_area', 'coverage_numerator'):
        if type(geometry[name]) is not int or geometry[name] < 0:
            raise ValueError(f'Malformed geometry {name}.')
    denominator = geometry['coverage_denominator']
    if denominator is not None and (type(denominator) is not int or denominator < 0):
        raise ValueError('Malformed coverage denominator.')
    digest = geometry['common_mask_sha256']
    if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('Malformed common mask SHA256.')
    if (geometry['common_area'] != metrics.n or geometry['coverage_numerator'] != metrics.n
            or denominator != geometry['native_area'] or geometry['native_area'] < metrics.n):
        reasons.append('geometry_inconsistent')
    if not denominator or metrics.n * 10000 < denominator * config.min_coverage_bp:
        reasons.append('insufficient_common_coverage')
    if geometry['evaluation_area_version'] != 'common-evaluation-1':
        reasons.append('geometry_version_unavailable')
    sources = geometry['mask_sources']
    if not isinstance(sources, (list, tuple)) or not all(isinstance(s, dict) for s in sources):
        raise ValueError('Malformed mask source records.')
    matching = [s for s in sources if s.get('observation_id') == frame.observation_id]
    def complete_matching_source(source):
        digest = source.get('native_mask_sha256')
        return (source.get('source_identity') == identity and source.get('roi') == frame.roi
                and type(source.get('needs_manual_review')) is bool
                and type(source.get('mask_source')) is str and bool(source['mask_source'].strip())
                and type(digest) is str and len(digest) == 64
                and all(c in '0123456789abcdef' for c in digest))
    if not matching or not any(complete_matching_source(s) for s in matching):
        reasons.append('geometry_source_mapping_unavailable')
    return frame, tuple(dict.fromkeys(reasons))


def classify(metrics: FrameMetrics, config: ControllerConfig) -> dict:
    """Exact integer rule inputs; geometry availability is offline evidence only."""
    if not isinstance(metrics, FrameMetrics) or not isinstance(config, ControllerConfig):
        raise ValueError('Expected validated metrics and controller configuration.')
    config.validate()
    frame, geometry_reasons = _geometry_evidence(metrics, config)
    n = metrics.n
    reasons = list(geometry_reasons)
    if n < config.min_area:
        reasons.append('insufficient_common_area')
    signal = (not n or metrics.dark_count * 10000 > config.max_dark_bp * n
              or metrics.effective_count * 10000 < config.min_effective_bp * n)
    highlight = (metrics.rgb_max_count * 10000 > config.rgb_warn_bp * n
                 or metrics.near_white_count * 10000 > config.max_near_white_bp * n)
    if metrics.dark_count * 10000 > config.max_dark_bp * n:
        reasons.append('too_dark')
    if not n or metrics.effective_count * 10000 < config.min_effective_bp * n:
        reasons.append('insufficient_effective_area')
    if metrics.rgb_max_count * 10000 > config.rgb_warn_bp * n:
        reasons.append('rgb_risk_warning')
    if metrics.rgb_max_count * 10000 > config.rgb_review_bp * n:
        reasons.append('rgb_high_risk')
    if metrics.near_white_count * 10000 > config.max_near_white_bp * n:
        reasons.append('near_white_risk')
    if signal and highlight:
        reasons.append('dark_and_highlight')
    evidence_available = not geometry_reasons and n >= config.min_area
    return _freeze({**metrics.controller_statistics,
                    'exposure_lines': frame.exposure_lines if frame else None,
                    'source_identity': metrics.geometry.get('source_identity'),
                    'geometry': metrics.geometry,
                    'native_reference_statistics': metrics.native_reference_statistics,
                    'evidence_available': evidence_available,
                    'signal_insufficient': signal, 'highlight_risk': highlight,
                    'qualified': evidence_available and not signal and not highlight,
                    'reason_codes': tuple(dict.fromkeys(reasons))})


def better_setting(left: dict, right: dict) -> bool:
    """Lexicographic exact ranking; candidate counts do not influence quality."""
    if not left.get('qualified'):
        return False
    if not right.get('qualified'):
        return True
    for name, prefer_lower in (('rgb_max_count', True), ('effective_count', False)):
        a, b = left[name] * right['n'], right[name] * left['n']
        if a != b:
            return a < b if prefer_lower else a > b
    a, b = left['background_mean_n'], right['background_mean_n']
    if a is None or b is None:
        if (a is None) != (b is None):
            return a is not None
    else:
        x, y = a['numerator'] * b['denominator'], b['numerator'] * a['denominator']
        if x != y:
            return x < y
    return left['exposure_lines'] < right['exposure_lines']


class Controller:
    """Bounded offline request policy. It performs no camera or hardware writes."""

    def __init__(self, config: ControllerConfig, context_id: str):
        if not isinstance(config, ControllerConfig):
            raise ValueError('Expected ControllerConfig.')
        config.validate()
        if type(context_id) is not str or not context_id.strip():
            raise ValueError('context_id must be a nonempty string.')
        self.config, self.context_id = config, context_id
        self._status = 'READY'
        self._visited, self._seen_observations, self._seen_sources = set(), set(), set()
        self._qualified = []
        self._reference, self._confirmation_count = None, 0
        self._fallback_used, self._risk_seen = False, False
        self._retry_count = {exposure: 0 for exposure in config.exposures}
        self._pending = None
        self._requested = self._consumed = self._unfulfilled = Cost(0, 0, 0)
        self._success_observations = 0
        self._conditions = None

    def snapshot(self) -> ControllerSnapshot:
        return ControllerSnapshot(self.context_id, self._status, tuple(sorted(self._visited)),
                                  tuple(sorted(self._seen_observations)), tuple(sorted(self._seen_sources)),
                                  tuple(self._qualified), self._reference, self._confirmation_count,
                                  self._fallback_used, FrozenDict(self._retry_count), _freeze(self._pending),
                                  self._requested, self._consumed, self._unfulfilled,
                                  self._success_observations, self._risk_seen, self._conditions)

    def _budget(self):
        reserved = self.config.request_cost if self._pending else Cost(0, 0, 0)
        limits = Cost(self.config.max_attempts, self.config.max_frames, self.config.max_time_ms)
        remaining = Cost(limits.attempts - self._requested.attempts,
                         limits.frames - self._requested.frames, limits.time_ms - self._requested.time_ms)
        return {'cost_status': 'modeled', 'requested_cost': _cost_dict(self._requested),
                'consumed_cost': _cost_dict(self._consumed), 'reserved_cost': _cost_dict(reserved),
                'unfulfilled_cost': _cost_dict(self._unfulfilled), 'remaining_cost': _cost_dict(remaining),
                'limits': _cost_dict(limits), 'historical_capture_cost': None,
                'measured_live_control_cost': None}

    def _decision(self, status, action, exposure, reasons, statistics=None):
        self._status = status
        return Decision(status, action, exposure, tuple(reasons), statistics, self._budget())

    def _stop(self, status, reasons, statistics=None):
        return self._decision(status, 'stop', None, reasons, statistics)

    def _request(self, exposure, action, reasons, statistics=None):
        cost = _cost_sum(self._requested, self.config.request_cost)
        if (cost.attempts > self.config.max_attempts or cost.frames > self.config.max_frames
                or cost.time_ms > self.config.max_time_ms):
            return self._stop('NEEDS_REVIEW', (*reasons, 'budget_exhausted'), statistics)
        self._requested = cost
        self._pending = {'exposure_lines': exposure, 'action_kind': action,
                         'cost': _cost_dict(self.config.request_cost)}
        if action == 'set_exposure':
            self._visited.add(exposure)
            self._reset_confirmation()
        return self._decision('CONTINUE_ADJUST', action, exposure, reasons, statistics)

    def start(self) -> Decision:
        if self._status != 'READY':
            raise ValueError('Controller has already started.')
        return self._request(self.config.initial_exposure_lines, 'set_exposure', ('initial_request',))

    def _reset_confirmation(self):
        self._reference, self._confirmation_count = None, 0

    def _stable(self, statistics):
        reference = self._reference
        product = statistics['n'] * reference['n']
        for name, multiplier, maximum in (
                ('gray_sum', 1, self.config.max_mean_delta_gray),
                ('effective_count', 10000, self.config.max_effective_delta_bp),
                ('rgb_max_count', 10000, self.config.max_rgb_delta_bp)):
            difference = abs(statistics[name] * reference['n'] - reference[name] * statistics['n'])
            if difference * multiplier > maximum * product:
                return False
        return True

    def _fallback_or_stop(self, reasons, statistics):
        if self._qualified and not self._fallback_used:
            best = self._qualified[0]
            for setting in self._qualified[1:]:
                if better_setting(setting, best):
                    best = setting
            self._fallback_used = True
            self._reset_confirmation()
            return self._request(best['exposure_lines'], 'fallback_confirm',
                                 (*reasons, 'fresh_fallback_confirmation_required'), statistics)
        status = 'CAPTURE_FAILED' if not self._qualified and not self._risk_seen else 'NEEDS_REVIEW'
        return self._stop(status, (*reasons, 'no_qualified_fallback' if not self._qualified
                                  else 'fallback_exhausted'), statistics)

    def feed(self, event: CaptureEvent) -> Decision:
        if self._status != 'CONTINUE_ADJUST' or self._pending is None:
            raise ValueError('No pending request, or controller is terminal.')
        if not isinstance(event, CaptureEvent):
            raise ValueError('Expected CaptureEvent.')
        if event.context_id != self.context_id:
            raise ValueError('Event context differs from controller context.')
        exposure = self._pending['exposure_lines']
        if event.exposure_lines != exposure:
            raise ValueError('Event exposure differs from pending request.')
        statistics = None
        conditions = None
        if event.kind == 'observation':
            geometry = event.metrics.geometry
            for name, expected in (('context_id', event.context_id), ('observation_id', event.observation_id),
                                   ('exposure_lines', event.exposure_lines)):
                if name in geometry and (type(geometry[name]) is not type(expected) or geometry[name] != expected):
                    raise ValueError(f'Event and immutable geometry disagree on {name}.')
            if event.observation_id in self._seen_observations:
                raise ValueError('Observation identity already consumed.')
            if self._conditions is not None:
                for name, expected in zip(('sample_id', 'pose', 'common_mask_sha256'), self._conditions):
                    if name in geometry and geometry[name] != expected:
                        raise ValueError('Sample, pose or common evaluation area changed.')
            statistics = classify(event.metrics, self.config)
            identity = statistics['source_identity']
            if identity is not None and identity in self._seen_sources:
                raise ValueError('Immutable capture source already consumed.')
            if statistics['evidence_available']:
                conditions = (geometry['sample_id'], geometry['pose'], geometry['common_mask_sha256'])
                if self._conditions is not None and conditions != self._conditions:
                    raise ValueError('Sample, pose or common evaluation area changed.')
        action = self._pending['action_kind']
        self._pending = None
        if event.kind == 'missing_data':
            self._unfulfilled = _cost_sum(self._unfulfilled, self.config.request_cost)
            reason = ('missing_fresh_confirmation' if action in ('confirm_current', 'fallback_confirm')
                      else 'missing_requested_data')
            return self._stop('NEEDS_REVIEW', (reason, 'unfulfilled_modeled_request'))
        self._consumed = _cost_sum(self._consumed, self.config.request_cost)
        if event.kind == 'capture_error':
            self._reset_confirmation()
            if self._retry_count[exposure] < self.config.retry_limit:
                self._retry_count[exposure] += 1
                return self._request(exposure, 'retry_current', ('capture_error', event.error_code or 'unspecified_error'))
            return self._stop('CAPTURE_FAILED', ('capture_error', 'retry_exhausted'))
        self._success_observations += 1
        self._seen_observations.add(event.observation_id)
        if statistics['source_identity'] is not None:
            self._seen_sources.add(statistics['source_identity'])
        if conditions is not None:
            self._conditions = conditions
        reasons = statistics['reason_codes']
        if not statistics['evidence_available']:
            return self._stop('NEEDS_REVIEW', reasons, statistics)
        self._risk_seen |= statistics['highlight_risk']
        if statistics['signal_insufficient'] and statistics['highlight_risk']:
            return self._stop('NEEDS_REVIEW', reasons, statistics)
        if statistics['signal_insufficient'] or statistics['highlight_risk']:
            self._reset_confirmation()
            step = 1 if statistics['signal_insufficient'] else -1
            index = self.config.exposures.index(exposure) + step
            if 0 <= index < len(self.config.exposures):
                next_exposure = self.config.exposures[index]
                if next_exposure not in self._visited:
                    return self._request(next_exposure, 'set_exposure', reasons, statistics)
            return self._fallback_or_stop((*reasons, 'search_exhausted'), statistics)
        self._qualified.append(statistics)
        if self._reference is None:
            self._reference, self._confirmation_count = statistics, 1
        elif self._stable(statistics):
            self._confirmation_count += 1
        else:
            return self._fallback_or_stop(('confirmation_unstable',), statistics)
        if self._confirmation_count >= self.config.confirmations:
            return self._stop('LOCKED', ('offline_policy_locked', 'independent_stable_confirmations'), statistics)
        return self._request(exposure, 'confirm_current', ('fresh_confirmation_required',), statistics)
