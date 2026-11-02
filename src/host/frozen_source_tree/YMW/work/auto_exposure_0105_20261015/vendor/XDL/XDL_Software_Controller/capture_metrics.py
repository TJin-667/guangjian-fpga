"""Read-only bridge to the unchanged detector and exact integer primitives."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import uuid
from dataclasses import dataclass, fields
from itertools import combinations
import math

import numpy as np


class FrozenDict(dict):
    """JSON-compatible detached mapping with recursively immutable values."""

    def _immutable(self, *args, **kwargs):
        raise TypeError('Metadata is immutable.')

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable


def _freeze(value):
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ValueError('Metadata keys must be strings.')
        return FrozenDict({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError('Metadata must contain finite JSON values only.')


def _integer(name, value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be a Python integer >= {minimum}.')


@dataclass(frozen=True)
class FrameInput:
    context_id: str
    observation_id: str
    sample_id: str
    pose: str
    exposure_lines: int
    gain16: int
    channel: int
    led: int
    saved_width: int
    saved_height: int
    roi: tuple[int, int, int, int]
    png_sha256: str
    rgb565_sha256: str
    source_mode: str
    source_metadata: dict

    def __post_init__(self):
        for name in ('context_id', 'observation_id', 'sample_id', 'pose', 'source_mode'):
            if type(getattr(self, name)) is not str or not getattr(self, name).strip():
                raise ValueError(f'{name} must be a nonempty string.')
        for name in ('exposure_lines', 'gain16', 'channel', 'led'):
            _integer(name, getattr(self, name), 1)
        for name in ('saved_width', 'saved_height'):
            _integer(name, getattr(self, name), 9)
        if type(self.roi) is not tuple or len(self.roi) != 4:
            raise ValueError('roi must be an (x,y,width,height) integer tuple.')
        for value in self.roi:
            _integer('roi', value)
        if self.roi[2:] != (self.saved_width, self.saved_height):
            raise ValueError('ROI dimensions must match saved image dimensions.')
        for name in ('png_sha256', 'rgb565_sha256'):
            digest = getattr(self, name)
            if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError(f'{name} must be a lowercase SHA256 digest.')
        if not isinstance(self.source_metadata, dict):
            raise ValueError('source_metadata must be a dict.')
        object.__setattr__(self, 'source_metadata', _freeze(self.source_metadata))


def _source_identity_record(frame):
    metadata = frame.source_metadata
    for name in ('dataset_id', 'capture_id', 'member'):
        if type(metadata.get(name)) is not str or not metadata[name].strip():
            return None
    frame_id = metadata.get('frame_id')
    if not ((type(frame_id) is str and frame_id.strip()) or (type(frame_id) is int and frame_id >= 0)):
        return None
    return _freeze({'source_mode': frame.source_mode,
                    **{key: metadata[key] for key in ('dataset_id', 'capture_id', 'frame_id', 'member')},
                    'png_sha256': frame.png_sha256, 'rgb565_sha256': frame.rgb565_sha256})


def source_identity(frame: FrameInput) -> str | None:
    """Canonical immutable capture identity; absolute storage paths never participate.

    A caller-supplied source_identity cannot replace required provenance. Distinct
    proven captures may have identical pixel hashes, so capture keys are required.
    """
    if not isinstance(frame, FrameInput):
        raise ValueError('Expected FrameInput.')
    record = _source_identity_record(frame)
    if record is None:
        return None
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _immutable_mask(mask):
    return np.frombuffer(mask.tobytes(order='C'), dtype=np.bool_).reshape(mask.shape)


def _bool_mask(mask, shape):
    if not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ or mask.shape != shape:
        raise ValueError('Expected a bool mask matching saved image dimensions.')


@dataclass(frozen=True)
class EvaluationArea:
    mask: np.ndarray
    sources: tuple[dict, ...]
    mask_sha256: str
    coverage: tuple[dict, ...]
    available: bool
    reason_codes: tuple[str, ...]
    version: str = 'common-evaluation-1'
    min_area: int = 10000
    min_coverage_bp: int = 9500

    def __post_init__(self):
        if not isinstance(self.mask, np.ndarray) or self.mask.ndim != 2 or self.mask.dtype != np.bool_:
            raise ValueError('Evaluation mask must be a two-dimensional bool array.')
        immutable = _immutable_mask(self.mask)
        if hashlib.sha256(immutable.tobytes()).hexdigest() != self.mask_sha256:
            raise ValueError('Evaluation mask hash mismatch.')
        object.__setattr__(self, 'mask', immutable)
        object.__setattr__(self, 'sources', tuple(_freeze(item) for item in self.sources))
        object.__setattr__(self, 'coverage', tuple(_freeze(item) for item in self.coverage))
        object.__setattr__(self, 'reason_codes', tuple(self.reason_codes))


@dataclass(frozen=True)
class FrameMetrics:
    n: int
    gray_sum: int
    dark_count: int
    near_white_count: int
    rgb_max_count: int
    effective_count: int
    line_center_count: int
    line_contrast_sum_n: int
    background_count: int
    background_activity_sum_n: int
    baseline_candidate_count: int
    native_reference_statistics: dict
    geometry: dict

    @property
    def controller_statistics(self) -> dict:
        """Common-area counts and exact display ratios, separated from native H1."""
        counts = {field.name: getattr(self, field.name) for field in fields(self)
                  if field.name not in ('native_reference_statistics', 'geometry')}
        return _freeze({'version': 'controller-statistics-1', **counts,
                        'mean_gray': {'numerator': self.gray_sum, 'denominator': self.n} if self.n else None,
                        'background_mean_n': {'numerator': self.background_activity_sum_n,
                                              'denominator': self.background_count}
                        if self.background_count else None})

    def __post_init__(self):
        for field in fields(self):
            if field.name not in ('native_reference_statistics', 'geometry'):
                _integer(field.name, getattr(self, field.name))
        for name in ('dark_count', 'near_white_count', 'rgb_max_count', 'effective_count',
                     'line_center_count', 'background_count', 'baseline_candidate_count'):
            if getattr(self, name) > self.n:
                raise ValueError(f'{name} exceeds its denominator.')
        ordinary = self.n - self.dark_count - self.near_white_count
        if ordinary < 0 or self.effective_count < self.n - self.dark_count:
            raise ValueError('Impossible gray partition or effective area.')
        lower = 11 * ordinary + 250 * self.near_white_count
        upper = 10 * self.dark_count + 249 * ordinary + 255 * self.near_white_count
        if not lower <= self.gray_sum <= upper:
            raise ValueError('gray_sum is unreachable for the supplied gray partitions.')
        if self.background_count + self.line_center_count != self.n:
            raise ValueError('Line and background pixels must partition the area.')
        if (self.line_contrast_sum_n > 20400 * self.line_center_count
                or self.background_activity_sum_n > 20400 * self.background_count):
            raise ValueError('Residual sum exceeds its integer range.')
        for name in ('native_reference_statistics', 'geometry'):
            if not isinstance(getattr(self, name), dict):
                raise ValueError(f'{name} must be a dict.')
            object.__setattr__(self, name, _freeze(getattr(self, name)))


def build_common_area(frames: list[FrameInput], native_masks: list[np.ndarray],
                      sensor_shape=(1080, 1920)) -> EvaluationArea:
    """Intersect native masks in full coordinates without resizing or changing filters."""
    if not frames or len(frames) != len(native_masks):
        raise ValueError('Nonempty frames and native_masks must have equal lengths.')
    if type(sensor_shape) is not tuple or len(sensor_shape) != 2:
        raise ValueError('sensor_shape must be a (height,width) tuple.')
    for value in sensor_shape:
        _integer('sensor_shape', value, 1)
    if not all(isinstance(frame, FrameInput) for frame in frames):
        raise ValueError('Expected FrameInput records.')
    conditions = {(f.context_id, f.sample_id, f.pose, f.gain16, f.channel, f.led) for f in frames}
    if len(conditions) != 1:
        raise ValueError('Common area requires one sample, pose, context and fixed illumination.')
    common = np.ones(sensor_shape, bool)
    sources, native_areas = [], []
    for frame, mask in zip(frames, native_masks):
        _bool_mask(mask, (frame.saved_height, frame.saved_width))
        x, y, width, height = frame.roi
        if x + width > sensor_shape[1] or y + height > sensor_shape[0]:
            raise ValueError('ROI leaves the sensor coordinate bounds.')
        full = np.zeros(sensor_shape, bool)
        full[y:y + height, x:x + width] = mask
        common &= full
        native_areas.append(int(np.count_nonzero(mask)))
        sources.append({'observation_id': frame.observation_id,
                        'source_identity': source_identity(frame), 'roi': frame.roi,
                        'native_mask_sha256': hashlib.sha256(mask.tobytes()).hexdigest(),
                        'mask_source': frame.source_metadata.get('mask_source'),
                        'needs_manual_review': frame.source_metadata.get('board_mask_needs_manual_review')})
    n = int(np.count_nonzero(common))
    coverage = tuple({'observation_id': f.observation_id, 'native_area': native,
                      'common_area': n, 'coverage_numerator': n,
                      'coverage_denominator': native if native else None}
                     for f, native in zip(frames, native_areas))
    reasons = []
    if n < 10000:
        reasons.append('insufficient_common_area')
    if any(native == 0 or n * 10000 < native * 9500 for native in native_areas):
        reasons.append('insufficient_native_coverage')
    return EvaluationArea(common, tuple(sources), hashlib.sha256(common.tobytes()).hexdigest(),
                          coverage, not reasons, tuple(reasons))


def line_centers(residual_n: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Centers with three same-sign strict weak witnesses in four directions."""
    if (not isinstance(residual_n, np.ndarray) or residual_n.ndim != 2
            or not np.issubdtype(residual_n.dtype, np.signedinteger)
            or np.any(residual_n < -20400) or np.any(residual_n > 20400)):
        raise ValueError('residual_n must be a signed integer array in [-20400,20400].')
    _bool_mask(mask, residual_n.shape)
    height, width = residual_n.shape
    result = np.zeros(residual_n.shape, bool)
    # Boolean sign classes avoid abs(int16 minimum) overflow.
    for sign in (residual_n > 648, residual_n < -648):
        witness = sign & mask
        for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
            y0, y1 = abs(dy), height - abs(dy)
            x0, x1 = abs(dx), width - abs(dx)
            if y1 <= y0 or x1 <= x0:
                continue
            center = (slice(y0, y1), slice(x0, x1))
            before = (slice(y0 - dy, y1 - dy), slice(x0 - dx, x1 - dx))
            after = (slice(y0 + dy, y1 + dy), slice(x0 + dx, x1 + dx))
            result[center] |= witness[center] & witness[before] & witness[after]
    return result


def _local_mask(frame, area):
    x, y, width, height = frame.roi
    if x + width > area.mask.shape[1] or y + height > area.mask.shape[0]:
        raise ValueError('Frame ROI leaves common mask coordinates.')
    return area.mask[y:y + height, x:x + width]


def _sum(values):
    return int(np.sum(values, dtype=np.uint64))


def compute_metrics(image_bgr: np.ndarray, frame: FrameInput, native_mask: np.ndarray,
                    area: EvaluationArea, algorithm: dict) -> tuple[FrameMetrics, dict[str, np.ndarray]]:
    """Preserve saved-image reference arrays; count controller evidence on common area."""
    if not isinstance(frame, FrameInput) or not isinstance(area, EvaluationArea):
        raise ValueError('Expected FrameInput and EvaluationArea.')
    shape = (frame.saved_height, frame.saved_width)
    if (not isinstance(image_bgr, np.ndarray) or image_bgr.dtype != np.uint8
            or image_bgr.shape != (*shape, 3)):
        raise ValueError('Expected uint8 BGR matching the saved frame dimensions.')
    _bool_mask(native_mask, shape)
    matching = [s for s in area.sources if s['observation_id'] == frame.observation_id
                and s['source_identity'] == source_identity(frame) and s['roi'] == frame.roi]
    if not matching or matching[0]['native_mask_sha256'] != hashlib.sha256(native_mask.tobytes()).hexdigest():
        raise ValueError('Frame/native mask is not a verified source of this common area.')
    common = _local_mask(frame, area)
    if np.any(common & ~native_mask):
        raise ValueError('Common evaluation mask leaves native board mask.')
    gray = algorithm['integer_gray'](image_bgr)
    h2 = algorithm['integer_h2'](gray)
    weak, strong = algorithm['integer_thresholds'](h2['residual_n'])
    absolute = np.abs(h2['residual_n'].astype(np.int32))
    quality = algorithm['assess_quality'](gray)
    continuity = algorithm['hysteresis_connect'](absolute, quality['valid_mask'], 648, 1620)
    baseline = continuity['mask'] & native_mask
    lines = line_centers(h2['residual_n'], common)
    background = common & ~lines
    rgb_max = np.any(image_bgr == 255, axis=2)
    n, native_n = int(common.sum()), int(native_mask.sum())
    saved_stats = {'pixel_count': gray.size, 'gray_sum': _sum(gray),
                   'near_black_le5_count': int((gray <= 5).sum()),
                   'near_white_ge250_count': int((gray >= 250).sum()),
                   'rgb_any_max_count': int(rgb_max.sum())}
    board_stats = {'pixel_count': native_n, 'gray_sum': _sum(gray[native_mask]),
                   'gray_le10_count': int(((gray <= 10) & native_mask).sum()),
                   'gray_ge250_count': int(((gray >= 250) & native_mask).sum()),
                   'rgb_any_max_count': int((rgb_max & native_mask).sum())}
    background_n = int(background.sum())
    background_sum = _sum(absolute[background])
    native_stats = {'saved_frame_integer_statistics': saved_stats,
                    'board_integer_statistics': board_stats,
                    'baseline_candidate_count': int(baseline.sum()),
                    'quality_status': quality['status']}
    identity = source_identity(frame)
    reasons = list(area.reason_codes)
    if identity is None:
        reasons.append('source_identity_unavailable')
    coverage = next(c for c in area.coverage if c['observation_id'] == frame.observation_id)
    geometry = {field.name: getattr(frame, field.name) for field in fields(frame)}
    geometry.update({'source_identity': identity, 'source_identity_record': _source_identity_record(frame),
                     'source_identity_available': identity is not None,
                     'evaluation_area_version': area.version, 'common_mask_sha256': area.mask_sha256,
                     **coverage, 'min_area': area.min_area, 'min_coverage_bp': area.min_coverage_bp,
                     'available': area.available and identity is not None,
                     'reason_codes': reasons, 'mask_sources': area.sources})
    metrics = FrameMetrics(n, _sum(gray[common]), int(((gray <= 10) & common).sum()),
                           int(((gray >= 250) & common).sum()), int((rgb_max & common).sum()),
                           int(((gray > 10) | weak)[common].sum()), int(lines.sum()),
                           _sum(absolute[lines]), background_n, background_sum,
                           int((baseline & common).sum()), native_stats, geometry)
    arrays = {'gray': gray, **h2, 'board_mask': native_mask.copy(), 'rgb_any_max': rgb_max,
              'quality_valid_mask': quality['valid_mask'],
              'valid_board_mask': quality['valid_mask'] & native_mask,
              'weak_raw': weak, 'strong_raw': strong,
              'weak_quality': continuity['weak_mask'], 'strong_quality': continuity['strong_mask'],
              'continuity_before_board': continuity['mask'], 'baseline_mask': baseline,
              'common_mask': common.copy(), 'line_centers': lines, 'background_mask': background}
    return metrics, arrays


def _mapped(array, frame, shape):
    if not isinstance(array, np.ndarray) or array.shape != (frame.saved_height, frame.saved_width):
        raise ValueError('Repeat arrays must match their frame coordinates.')
    result = np.zeros(shape, array.dtype)
    x, y, width, height = frame.roi
    result[y:y + height, x:x + width] = array
    return result


def compare_repeats(records: list[tuple[FrameInput, FrameMetrics, dict]], area: EvaluationArea) -> dict:
    """Exact pairwise same-condition repeat evidence, with null for zero union."""
    result = {'version': 'common-repeat-1', 'status': 'unavailable', 'reason_codes': [],
              'common_mask_sha256': area.mask_sha256, 'pairs': []}
    if len(records) < 2:
        result['reason_codes'].append('insufficient_repeat_records')
        return result
    conditions = {(f.context_id, f.sample_id, f.pose, f.exposure_lines, f.gain16, f.channel, f.led)
                  for f, _, _ in records}
    if len(conditions) != 1:
        result['reason_codes'].append('not_same_condition_repeat')
        return result
    if not area.available:
        result['reason_codes'].extend(area.reason_codes)
        return result
    identities = [source_identity(f) for f, _, _ in records]
    if None in identities or len(set(identities)) != len(identities):
        result['reason_codes'].append('missing_or_duplicate_source_identity')
        return result
    if len({f.observation_id for f, _, _ in records}) != len(records):
        result['reason_codes'].append('duplicate_observation_id')
        return result
    n = int(area.mask.sum())
    # Capture identity excludes labels/coordinates, so bind those independently
    # to the immutable metric trace and the area's recorded source association.
    trace_fields = tuple(field.name for field in fields(FrameInput)
                         if field.name != 'source_metadata')
    for frame, metrics, arrays in records:
        trace_matches = all(name in metrics.geometry
                            and type(metrics.geometry[name]) is type(getattr(frame, name))
                            and metrics.geometry[name] == getattr(frame, name)
                            for name in trace_fields)
        matching_sources = [source for source in area.sources
                            if source.get('observation_id') == frame.observation_id
                            and source.get('source_identity') == source_identity(frame)
                            and source.get('roi') == frame.roi]
        association_matches = (len(matching_sources) == 1
                               and matching_sources[0] in metrics.geometry.get('mask_sources', ()))
        if (not trace_matches or not association_matches
                or metrics.geometry.get('source_identity') != source_identity(frame)
                or metrics.geometry.get('source_identity_record') != _source_identity_record(frame)
                or metrics.geometry.get('common_mask_sha256') != area.mask_sha256
                or metrics.n != n or not metrics.geometry.get('available')):
            result['reason_codes'].append('repeat_geometry_mismatch')
            return result
    # Validate every record before remapping even the first evidence array.
    mapped = []
    for frame, metrics, arrays in records:
        required = ('gray', 'line_centers', 'baseline_mask')
        if any(key not in arrays for key in required):
            raise ValueError('Repeat evidence arrays missing.')
        mapped.append({key: _mapped(arrays[key], frame, area.mask.shape) for key in required})
    for (i, (first, a, _)), (j, (second, b, _)) in combinations(enumerate(records), 2):
        pair = {'first_observation_id': first.observation_id, 'second_observation_id': second.observation_id,
                'n': n, 'gray_abs_diff_sum': _sum(np.abs(mapped[i]['gray'].astype(np.int16)
                                                        - mapped[j]['gray'].astype(np.int16))[area.mask]),
                'mean_gray_delta': {'numerator': abs(a.gray_sum * b.n - b.gray_sum * a.n),
                                    'denominator': a.n * b.n},
                'effective_delta_bp': {'numerator': abs(a.effective_count * b.n - b.effective_count * a.n) * 10000,
                                        'denominator': a.n * b.n},
                'rgb_delta_bp': {'numerator': abs(a.rgb_max_count * b.n - b.rgb_max_count * a.n) * 10000,
                                  'denominator': a.n * b.n}}
        for key, prefix in (('line_centers', 'line'), ('baseline_mask', 'baseline')):
            left, right = mapped[i][key] & area.mask, mapped[j][key] & area.mask
            intersection, union = int((left & right).sum()), int((left | right).sum())
            pair.update({prefix + '_intersection': intersection, prefix + '_union': union,
                         prefix + '_iou': {'numerator': intersection, 'denominator': union} if union else None})
        result['pairs'].append(pair)
    result['status'] = 'available'
    return result


_DETECTOR_SHA256 = {
    '__init__.py': '7cd2e26b25c7748c87aeeac27749a0032762dec277e31d7b335baec9df3d609f',
    'cli.py': '0247fe273122685b9cdaad77043aee63f3b421ef836b1481ed48774b73ef9e2b',
    'core.py': '47585c9a081351f8a44dbca40b803907a9975291dfb615e713d4c969e9cf92d0',
    'image_io.py': '74d2bda791ac2d9a45a45341c5cf1f221fd1b3336f2fdb98d79a02b1fff834e5',
    'metadata.py': 'b3b271b256c6648bc50f2bf823634fbbbe57e5c0ca5b91caf70a3d3bf4005c1f',
    'real_baseline.py': '3d796a28d155b7a9d74562e24ff77c712bd17fb23377bf4d5def558311919c1a',
    'reports.py': '191f856e7f5dad24e76e17aa54aba052fbe802b04731eefd4e8195d846b2f19e',
}
_INTEGER_SHA256 = 'caefc8519c355cc7670cf7fb95986f0cc4fd2885ffb618061dc9899ba84186de'


def preservation_snapshot(paths: list[Path]) -> dict[str, str]:
    """Return absolute path/SHA256 records without writing source or cache files."""
    records = {}
    for path in paths:
        absolute = Path(path).resolve()
        with absolute.open('rb') as stream:
            records[str(absolute)] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return records


def _reject_json_constant(value: str):
    raise ValueError(f'Nonfinite JSON value in integrity manifest: {value}')


def load_algorithm(algorithm_root: Path, expected_results: Path) -> dict:
    """Verify pinned sources before executing any external algorithm code.

    algorithm_root is the external software directory; expected_results is the
    historical result directory containing integrity.json. Sources are compiled
    directly from verified bytes, so no pycache or PYTHONPATH change is needed.
    Returned functions retain the original signatures and file identities.
    """
    root = Path(algorithm_root).resolve()
    manifest_path = Path(expected_results).resolve() / 'integrity.json'
    if not manifest_path.is_file():
        raise ValueError(f'Missing historical integrity.json: {manifest_path}')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'),
                              parse_constant=_reject_json_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f'Invalid historical integrity.json: {manifest_path}') from error
    if not isinstance(manifest, dict) or manifest.get('source_algorithm_sha256') != _DETECTOR_SHA256:
        raise ValueError(f'Historical detector SHA256 identity mismatch: {manifest_path}')

    expected = {root / 'light_inspection' / name: digest for name, digest in _DETECTOR_SHA256.items()}
    expected[root / 'ymw_integer_reference.py'] = _INTEGER_SHA256
    verified = {}
    for path, digest in expected.items():
        if not path.is_file():
            raise ValueError(f'Missing external algorithm source: {path}')
        try:
            source = path.read_bytes()
        except OSError as error:
            raise ValueError(f'Cannot read external algorithm source: {path}') from error
        if hashlib.sha256(source).hexdigest() != digest:
            raise ValueError(f'Algorithm SHA256 mismatch: {path}')
        verified[path] = source

    namespace = '_xdl_verified_' + uuid.uuid4().hex
    loaded = []

    def execute(name: str, path: Path, package: bool = False):
        specification = importlib.util.spec_from_file_location(
            name, path, submodule_search_locations=[str(path.parent)] if package else None)
        module = importlib.util.module_from_spec(specification)
        sys.modules[name] = module
        loaded.append(name)
        exec(compile(verified[path], str(path), 'exec'), module.__dict__)
        return module

    try:
        execute(namespace, root / 'light_inspection' / '__init__.py', package=True)
        execute(namespace + '.image_io', root / 'light_inspection' / 'image_io.py')
        execute(namespace + '.core', root / 'light_inspection' / 'core.py')
        baseline = execute(namespace + '.real_baseline', root / 'light_inspection' / 'real_baseline.py')
        integer = execute(namespace + '.integer', root / 'ymw_integer_reference.py')
        return {name: getattr(integer, name) for name in (
                    'integer_gray', 'integer_h2', 'integer_thresholds', 'board_mask')} | {
                    'assess_quality': baseline.assess_quality,
                    'hysteresis_connect': baseline.hysteresis_connect}
    finally:
        for name in reversed(loaded):
            sys.modules.pop(name, None)
