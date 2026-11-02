from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import math
import re


DIRECTIONS = {1: 'top', 2: 'right', 3: 'bottom', 4: 'left'}
WIDTHS = dict(session=64, request_id=32, config_epoch=32, dvp_sequence=32,
              publish_sequence=32, roi_generation=16, camera_generation=16,
              light_generation=16, frame_id=16)


class ContractError(ValueError):
    def __init__(self, code, message='', *, needs_reset=False):
        super().__init__(message or code)
        self.code, self.needs_reset = code, needs_reset


def require(condition, code):
    if not condition:
        raise ContractError(code)


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value), 'INVALID_ID')


def sha(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Context:
    sample_id: str
    pose_id: str
    roi: tuple[int, int, int, int]
    mask: bytes = field(repr=False)

    def __post_init__(self):
        identifier(self.sample_id)
        identifier(self.pose_id)
        require(type(self.roi) is tuple and len(self.roi) == 4 and all(type(v) is int for v in self.roi), 'INVALID_ROI')
        x, y, w, h = self.roi
        require(x >= 0 and y >= 0 and w >= 9 and h >= 9 and x + w <= 1920 and y + h <= 1080, 'INVALID_ROI')
        require(type(self.mask) is bytes and len(self.mask) == w * h and set(self.mask) <= {0, 1} and 1 in self.mask, 'INVALID_MASK')

    @property
    def mask_sha256(self):
        return sha(self.mask)

    def describe(self):
        return dict(sample_id=self.sample_id, pose_id=self.pose_id, roi=list(self.roi),
                    mask_sha256=self.mask_sha256, board_pixels=sum(self.mask))


@dataclass(frozen=True)
class Profile:
    """Software admission profile; not an assertion of hardware qualification."""
    exposures: tuple[int, ...] = (400, 500, 600, 700, 800)
    gain16: int = 16
    brightness: int = 128
    settle_frames: int = 1
    discard_frames: int = 3

    def __post_init__(self):
        require(type(self.exposures) is tuple and len(set(self.exposures)) == len(self.exposures)
                and self.exposures and all(type(v) is int and v in (400, 500, 600, 700, 800) for v in self.exposures), 'INVALID_PROFILE')
        require(type(self.gain16) is int and self.gain16 == 16
                and type(self.brightness) is int and self.brightness == 128
                and type(self.settle_frames) is int and self.settle_frames == 1
                and type(self.discard_frames) is int and self.discard_frames == 3, 'INVALID_PROFILE')


@dataclass(frozen=True)
class CaptureRequest:
    action_id: str
    channel: int
    exposure_lines: int
    role: str  # base/probe/confirm/supplement are separate cost-bearing observations
    reason: str
    gain16: int = 16

    def parameters(self, profile):
        identifier(self.action_id)
        require(type(self.channel) is int and self.channel in DIRECTIONS, 'INVALID_CHANNEL')
        require(type(self.exposure_lines) is int and self.exposure_lines in profile.exposures, 'EXPOSURE_NOT_ADMITTED')
        require(type(self.gain16) is int and self.gain16 == profile.gain16, 'GAIN_NOT_ADMITTED')
        require(self.role in ('base', 'probe', 'confirm', 'supplement'), 'INVALID_ROLE')
        require(isinstance(self.reason, str) and bool(self.reason.strip()), 'MISSING_REASON')
        return dict(light_mask=1 << (self.channel - 1), brightness=profile.brightness,
                    exposure_lines=self.exposure_lines, gain16=self.gain16,
                    settle_frames=profile.settle_frames, discard_frames=profile.discard_frames)


@dataclass(frozen=True)
class Stop:
    status: str
    reason: str

    def __post_init__(self):
        require(self.status in ('STOP', 'REVIEW'), 'INVALID_STOP')
        require(isinstance(self.reason, str) and bool(self.reason.strip()), 'MISSING_REASON')


def validate_identity(identity):
    require(type(identity) is dict and set(identity) == set(WIDTHS), 'IDENTITY_SCHEMA')
    for key, bits in WIDTHS.items():
        require(type(identity[key]) is int and 0 <= identity[key] < 1 << bits, 'IDENTITY_RANGE_' + key)
    require(all(identity[k] != 0 for k in ('session', 'request_id', 'config_epoch', 'dvp_sequence', 'publish_sequence')), 'IDENTITY_UNCOMMITTED')


def validate_progress(previous, current):
    validate_identity(current)
    if previous is None:
        return
    validate_identity(previous)
    if current['session'] != previous['session']:
        raise ContractError('SESSION_CHANGED', needs_reset=True)
    require(current['roi_generation'] == previous['roi_generation'], 'ROI_GENERATION_CHANGED')
    for key in ('request_id', 'dvp_sequence', 'publish_sequence', 'frame_id'):
        bits = WIDTHS[key]
        require(0 < ((current[key] - previous[key]) & ((1 << bits) - 1)) < 1 << (bits - 1), 'NONFORWARD_' + key)
    # Same-parameter confirmation can legitimately retain configuration generations.
    for key in ('config_epoch', 'camera_generation', 'light_generation'):
        bits = WIDTHS[key]
        require(((current[key] - previous[key]) & ((1 << bits) - 1)) < 1 << (bits - 1), 'BACKWARD_' + key)


@dataclass(frozen=True)
class Observation:
    observation_id: str
    action_id: str
    attempt_id: str
    channel: int
    role: str
    parameters: dict
    identity: dict
    call_id: str
    png_sha256: str
    raw_sha256: str
    source_evidence: str
    execution_mode: str
    files: dict
    statistics: dict = field(default_factory=dict)
    features: dict = field(default_factory=dict)
    camera_readback: dict = field(default_factory=dict)
    analysis: dict = field(default_factory=lambda: {'quality': 'pending_XDL', 'polarity': 'pending_XDL', 'evidence': 'pending_XDL'})

    def describe(self):
        return dict(asdict(self), direction=DIRECTIONS[self.channel])


class ObservationSet:
    """Ordered observations; directions may repeat and each image stays distinct."""
    def __init__(self):
        self._items = []

    @property
    def items(self):
        # Copies prevent a policy from altering the validated acquisition history.
        import copy
        return tuple(copy.deepcopy(self._items))

    def check_request(self, request, max_supplements=2):
        require(request.action_id not in {o.action_id for o in self._items}, 'REUSED_ACTION')
        if request.role == 'base':
            require(request.channel not in {o.channel for o in self._items if o.role == 'base'}, 'DUPLICATE_BASE_DIRECTION')
        if request.role == 'supplement':
            require(any(o.role == 'base' and o.channel == request.channel for o in self._items), 'SUPPLEMENT_WITHOUT_BASE')
            require(sum(o.role == 'supplement' for o in self._items) < max_supplements, 'SUPPLEMENT_BUDGET')

    def append(self, observation):
        import copy
        self.check_observation(observation)
        self._items.append(copy.deepcopy(observation))

    def check_observation(self, observation):
        require(observation.observation_id not in {o.observation_id for o in self._items}, 'REUSED_OBSERVATION')
        require(observation.call_id not in {o.call_id for o in self._items}, 'REUSED_CALL')
        if self._items:
            validate_progress(self._items[-1].identity, observation.identity)
        # Equal image hashes are valid for a static scene with genuinely new identity.

    @property
    def base_complete(self):
        return {o.channel for o in self._items if o.role == 'base'} == set(DIRECTIONS)

    def describe(self):
        return [o.describe() for o in self._items]


@dataclass(frozen=True)
class Limits:
    max_attempts: int
    max_reserved_frames: int
    max_elapsed_s: float
    shutdown_reserve_s: float
    max_supplements: int = 2
    same_setting_retries: int = 1

    def __post_init__(self):
        require(type(self.max_attempts) is int and self.max_attempts > 0
                and type(self.max_reserved_frames) is int and self.max_reserved_frames > 0, 'INVALID_BUDGET')
        require(all(type(v) in (int, float) and math.isfinite(v) for v in (self.max_elapsed_s, self.shutdown_reserve_s))
                and 0 < self.shutdown_reserve_s < self.max_elapsed_s, 'INVALID_BUDGET')
        require(type(self.max_supplements) is int and 0 <= self.max_supplements <= 2
                and type(self.same_setting_retries) is int and 0 <= self.same_setting_retries <= 1, 'INVALID_BUDGET')
