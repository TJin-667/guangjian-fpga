"""Quality-aware helpers for the reproducible real-image baseline.

The functions in this module keep image usability separate from defect
evidence.  A zero response in an invalid region is therefore never treated as
evidence that the surface is normal.
"""
import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from itertools import combinations
import json
from numbers import Real
from pathlib import Path
import platform

import cv2
import numpy as np

from . import __version__
from .core import AnalysisConfig, analyze_image
from .image_io import read_image, write_png


@dataclass(frozen=True)
class QualityConfig:
    """Transparent proxy rules for deciding which image regions may fuse."""

    tile_size: int = 32
    signal_floor: float = 8.0
    local_range_min: float = 6.0
    valid_frame_fraction: float = 0.8
    max_near_white_fraction: float = 0.98

    def validate(self) -> None:
        if type(self.tile_size) is not int or self.tile_size < 2:
            raise ValueError('tile_size must be an integer >= 2.')
        for name in ('signal_floor', 'local_range_min'):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, Real)
                    or not np.isfinite(value) or value < 0 or value > 255):
                raise ValueError(f'{name} must be a finite number from 0 to 255.')
        for name in ('valid_frame_fraction', 'max_near_white_fraction'):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, Real)
                    or not np.isfinite(value) or value < 0 or value > 1):
                raise ValueError(f'{name} must be a finite number from 0 to 1.')

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RealBaselineConfig:
    """Versioned parameters for one reproducible real-image run."""

    background_window: int = 9
    low_threshold: float = 8.0
    high_threshold: float = 20.0
    roi: tuple[int, int, int, int] | None = (880, 480, 400, 260)
    quality: QualityConfig = field(default_factory=QualityConfig)

    def validate(self) -> None:
        AnalysisConfig(self.background_window, self.high_threshold, self.roi).validate()
        if (isinstance(self.low_threshold, bool) or not isinstance(self.low_threshold, Real)
                or not np.isfinite(self.low_threshold) or self.low_threshold < 0
                or self.low_threshold >= self.high_threshold):
            raise ValueError('low_threshold must be finite and satisfy 0 <= low < high.')
        self.quality.validate()

    def to_dict(self) -> dict:
        return {
            'schema_version': 1,
            'background_window': self.background_window,
            'low_threshold': float(self.low_threshold),
            'high_threshold': float(self.high_threshold),
            'roi': list(self.roi) if self.roi is not None else None,
            'quality': self.quality.to_dict(),
        }


def _validate_gray(gray: np.ndarray) -> None:
    if not isinstance(gray, np.ndarray) or gray.ndim != 2 or gray.dtype != np.uint8 or gray.size == 0:
        raise ValueError('gray must be a nonempty uint8 two-dimensional image.')


def assess_quality(gray: np.ndarray, config: QualityConfig | None = None) -> dict:
    """Return a tile validity mask plus a three-state frame assessment.

    ``valid`` means most tiles contain usable encoded signal,
    ``locally_valid`` means only some tiles may contribute, and ``review``
    means no tile is trusted for fusion.  These are data-quality states, not
    defect decisions.
    """
    _validate_gray(gray)
    config = config or QualityConfig()
    config.validate()
    height, width = gray.shape
    valid_mask = np.zeros_like(gray, dtype=bool)
    tile_rows = []
    usable_tiles = 0
    total_tiles = 0

    for y in range(0, height, config.tile_size):
        for x in range(0, width, config.tile_size):
            tile = gray[y:min(y + config.tile_size, height),
                        x:min(x + config.tile_size, width)]
            p01, p50, p99 = np.percentile(tile, [1, 50, 99])
            near_white_fraction = float(np.mean(tile >= 250))
            ordinary_signal = p50 >= config.signal_floor
            local_dark_field_detail = (
                p99 >= config.signal_floor and p99 - p01 >= config.local_range_min
            )
            usable = bool((ordinary_signal or local_dark_field_detail)
                          and near_white_fraction < config.max_near_white_fraction)
            if usable:
                valid_mask[y:min(y + config.tile_size, height),
                           x:min(x + config.tile_size, width)] = True
                usable_tiles += 1
            total_tiles += 1
            tile_rows.append({
                'x': x, 'y': y, 'width': int(tile.shape[1]), 'height': int(tile.shape[0]),
                'gray_p01': float(p01), 'gray_p50': float(p50), 'gray_p99': float(p99),
                'near_white_fraction': near_white_fraction, 'usable': usable,
            })

    usable_fraction = usable_tiles / total_tiles
    if usable_fraction >= config.valid_frame_fraction:
        status = 'valid'
    elif usable_tiles:
        status = 'locally_valid'
    else:
        status = 'review'

    frame_p01, frame_p50, frame_p99 = np.percentile(gray, [1, 50, 99])
    reasons = []
    if usable_tiles == 0:
        reasons.append('no_usable_tiles')
    if frame_p99 < config.signal_floor:
        reasons.append('near_black_quantized')
    if float(np.mean(gray >= 250)) >= config.max_near_white_fraction:
        reasons.append('near_white_clipped_proxy')
    if status == 'locally_valid':
        reasons.append('partial_spatial_support')

    return {
        'status': status,
        'reason_codes': reasons,
        'valid_mask': valid_mask,
        'usable_tile_fraction': float(usable_fraction),
        'gray_p01': float(frame_p01),
        'gray_p50': float(frame_p50),
        'gray_p99': float(frame_p99),
        'near_black_fraction': float(np.mean(gray <= 5)),
        'near_white_fraction': float(np.mean(gray >= 250)),
        'tiles': tile_rows,
    }


def hysteresis_connect(response: np.ndarray, valid_mask: np.ndarray,
                       low: float, high: float) -> dict:
    """Keep weak 8-connected response components containing a strong seed."""
    response = np.asarray(response)
    valid_mask = np.asarray(valid_mask)
    if response.ndim != 2 or response.size == 0 or not np.issubdtype(response.dtype, np.number):
        raise ValueError('response must be a nonempty numeric two-dimensional array.')
    if valid_mask.shape != response.shape or valid_mask.dtype != np.bool_:
        raise ValueError('valid_mask must be boolean and match response shape.')
    if (isinstance(low, bool) or isinstance(high, bool)
            or not isinstance(low, Real) or not isinstance(high, Real)
            or not np.isfinite(low) or not np.isfinite(high) or low < 0 or high <= low):
        raise ValueError('thresholds must be finite and satisfy 0 <= low < high.')
    if not np.isfinite(response).all():
        raise ValueError('response must contain only finite values.')

    weak = (response > low) & valid_mask
    strong = (response > high) & valid_mask
    if not strong.any():
        connected = np.zeros_like(strong)
    else:
        _, labels = cv2.connectedComponents(weak.astype(np.uint8), connectivity=8)
        keep = np.unique(labels[strong])
        keep = keep[keep != 0]
        connected = np.isin(labels, keep)
    return {'weak_mask': weak, 'strong_mask': strong, 'mask': connected}


COMPONENT_FIELDS = [
    'component_id', 'area', 'x', 'y', 'width', 'height',
    'principal_length', 'transverse_width', 'orientation_degrees', 'elongation',
    'mean_response', 'max_response',
]


def describe_components(mask: np.ndarray, response: np.ndarray) -> list[dict]:
    """Describe connected candidates without using the descriptors as a gate."""
    mask = np.asarray(mask)
    response = np.asarray(response)
    if mask.ndim != 2 or mask.dtype != np.bool_ or mask.size == 0:
        raise ValueError('mask must be a nonempty boolean two-dimensional array.')
    if response.shape != mask.shape or not np.issubdtype(response.dtype, np.number):
        raise ValueError('response must be numeric and match mask shape.')
    if not np.isfinite(response).all():
        raise ValueError('response must contain only finite values.')

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    rows = []
    for label in range(1, count):
        ys, xs = np.nonzero(labels == label)
        points = np.column_stack((xs, ys)).astype(np.float64)
        if len(points) == 1:
            principal_length = transverse_width = 1.0
            orientation = 0.0
        else:
            centered = points - points.mean(axis=0)
            covariance = centered.T @ centered / len(points)
            _, vectors = np.linalg.eigh(covariance)
            principal = vectors[:, -1]
            transverse = vectors[:, 0]
            principal_length = float(np.ptp(centered @ principal) + 1.0)
            transverse_width = float(np.ptp(centered @ transverse) + 1.0)
            orientation = float(np.degrees(np.arctan2(principal[1], principal[0])))
            if orientation >= 90:
                orientation -= 180
            elif orientation < -90:
                orientation += 180
        values = response[labels == label]
        rows.append({
            'component_id': int(label),
            'area': int(stats[label, cv2.CC_STAT_AREA]),
            'x': int(stats[label, cv2.CC_STAT_LEFT]),
            'y': int(stats[label, cv2.CC_STAT_TOP]),
            'width': int(stats[label, cv2.CC_STAT_WIDTH]),
            'height': int(stats[label, cv2.CC_STAT_HEIGHT]),
            'principal_length': principal_length,
            'transverse_width': transverse_width,
            'orientation_degrees': orientation,
            'elongation': float(principal_length / max(transverse_width, 1.0)),
            'mean_response': float(values.mean()),
            'max_response': float(values.max()),
        })
    return sorted(rows, key=lambda row: (-row['area'], row['component_id']))


def fuse_channel_evidence(evidence: dict[str, dict]) -> dict:
    """Fuse valid channel responses while preserving source and polarity."""
    if not evidence:
        raise ValueError('At least one channel is required for fusion.')
    channels = list(evidence)
    required = {'response', 'residual', 'mask', 'valid_mask'}
    shape = None
    for channel, values in evidence.items():
        if set(values) < required:
            raise ValueError(f'{channel} is missing required evidence arrays.')
        arrays = [np.asarray(values[key]) for key in required]
        if any(array.ndim != 2 for array in arrays):
            raise ValueError('All evidence arrays must be two-dimensional.')
        if len({array.shape for array in arrays}) != 1:
            raise ValueError(f'{channel} evidence arrays have different shapes.')
        if shape is None:
            shape = arrays[0].shape
        elif arrays[0].shape != shape:
            raise ValueError('All channels must have the same shape.')

    responses = np.stack([np.asarray(evidence[ch]['response'], dtype=np.float32) for ch in channels])
    residuals = np.stack([np.asarray(evidence[ch]['residual'], dtype=np.float32) for ch in channels])
    valid = np.stack([np.asarray(evidence[ch]['valid_mask'], dtype=bool) for ch in channels])
    masks = np.stack([np.asarray(evidence[ch]['mask'], dtype=bool) & valid[index]
                      for index, ch in enumerate(channels)])
    if not np.isfinite(responses).all() or not np.isfinite(residuals).all():
        raise ValueError('Fusion inputs must be finite.')

    valid_count = valid.sum(axis=0).astype(np.uint8)
    unknown = valid_count == 0
    selectable = np.where(valid, responses, -np.inf)
    source_zero = np.argmax(selectable, axis=0)
    rows, cols = np.indices(shape)
    fused_response = selectable[source_zero, rows, cols]
    fused_residual = residuals[source_zero, rows, cols]
    fused_response[unknown] = 0
    fused_residual[unknown] = 0
    source_channel = (source_zero + 1).astype(np.uint8)
    source_channel[unknown] = 0
    polarity = np.sign(fused_residual).astype(np.int8)
    polarity[unknown] = 0

    return {
        'channels': channels,
        'response': fused_response.astype(np.float32),
        'residual': fused_residual.astype(np.float32),
        'mask': np.any(masks, axis=0) & ~unknown,
        'source_channel': source_channel,
        'polarity': polarity,
        'valid_count': valid_count,
        'unknown': unknown,
    }


def enumerate_channel_subsets(channels: list[str] | tuple[str, ...]) -> list[tuple[str, ...]]:
    if not channels or len(set(channels)) != len(channels):
        raise ValueError('channels must be a nonempty sequence of unique names.')
    return [subset for size in range(1, len(channels) + 1)
            for subset in combinations(channels, size)]


def summarize_subsets(channel_masks: dict[str, np.ndarray]) -> list[dict]:
    """Compare every nonempty channel subset with the full-set mask.

    The full-set mask is an internal reference, not ground truth.  The metrics
    therefore describe evidence retention only and must not be labelled recall.
    """
    if not channel_masks:
        raise ValueError('At least one channel mask is required.')
    channels = list(channel_masks)
    masks = {channel: np.asarray(mask, dtype=bool) for channel, mask in channel_masks.items()}
    shapes = {mask.shape for mask in masks.values()}
    if len(shapes) != 1 or next(iter(shapes), ()) == ():
        raise ValueError('All channel masks must be nonempty and have the same shape.')
    full = np.logical_or.reduce([masks[channel] for channel in channels])
    full_pixels = int(full.sum())
    rows = []
    for subset in enumerate_channel_subsets(channels):
        combined = np.logical_or.reduce([masks[channel] for channel in subset])
        retained = int((combined & full).sum())
        lost = int((full & ~combined).sum())
        rows.append({
            'subset_size': len(subset),
            'channels': '+'.join(subset),
            'candidate_pixels': int(combined.sum()),
            'full_reference_pixels': full_pixels,
            'retained_from_full_fraction': float(retained / full_pixels) if full_pixels else None,
            'lost_from_full_pixels': lost,
            'interpretation': ('evidence_retention_not_recall' if full_pixels
                               else 'no_valid_full_reference'),
        })
    return rows


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f'Cannot write an empty table: {path.name}')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_components(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=COMPONENT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime_record() -> dict:
    source = Path(__file__).resolve().parent
    return {
        'tool_version': __version__,
        'python': platform.python_version(),
        'numpy': np.__version__,
        'opencv': cv2.__version__,
        'source_sha256': {
            path.name: _sha256(path) for path in sorted(source.glob('*.py'))
        },
    }


def _read_dataset_index(dataset_root: Path) -> list[dict]:
    manifest = dataset_root / 'dataset_index.csv'
    try:
        with manifest.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
    except OSError as exc:
        raise ValueError(f'Cannot read dataset_index.csv: {exc}') from exc
    required = {
        'sample_id', 'group_id', 'capture_id', 'channel', 'brightness_command',
        'image_path', 'frame_status', 'source_type',
    }
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        missing = sorted(required - set(reader.fieldnames or ()))
        raise ValueError(f'dataset_index.csv is missing columns: {missing}')
    if not rows:
        raise ValueError('dataset_index.csv contains no frames.')
    seen = set()
    for line, row in enumerate(rows, 2):
        key = (row['group_id'].strip(), row['channel'].strip())
        if not all(key) or key in seen:
            raise ValueError(f'Invalid or duplicate group/channel at CSV line {line}: {key}')
        seen.add(key)
        if row['frame_status'].strip().lower() != 'complete':
            raise ValueError(f'Frame is not complete at CSV line {line}.')
        if row['source_type'].strip().lower() != 'real':
            raise ValueError(f'Real baseline requires source_type=real at CSV line {line}.')
        try:
            row['brightness_command'] = int(row['brightness_command'])
        except ValueError as exc:
            raise ValueError(f'Invalid brightness_command at CSV line {line}.') from exc
        image = (dataset_root / row['image_path']).resolve()
        try:
            image.relative_to(dataset_root.resolve())
        except ValueError as exc:
            raise ValueError(f'Image path leaves the dataset directory at CSV line {line}.') from exc
        if not image.is_file():
            raise ValueError(f'Image is missing at CSV line {line}: {image}')
        row['image_abspath'] = str(image)
    return rows


def _channel_sort_key(channel: str) -> tuple:
    suffix = channel[2:] if channel.upper().startswith('CH') else ''
    return (0, int(suffix)) if suffix.isdigit() else (1, channel)


def _quality_for_json(quality: dict) -> dict:
    return {key: value for key, value in quality.items() if key != 'valid_mask'}


def _scale_response(response: np.ndarray) -> np.ndarray:
    maximum = float(np.percentile(response, 99.8)) if response.size else 0.0
    if maximum <= 0:
        return np.zeros(response.shape, np.uint8)
    return np.clip(response * (255.0 / maximum), 0, 255).astype(np.uint8)


def _export_frame(frame_dir: Path, result: dict, quality: dict,
                  continuity: dict, components: list[dict], frame_summary: dict) -> None:
    frame_dir.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(
        frame_dir / 'arrays.npz',
        gray=result['gray'], background=result['background'], residual=result['residual'],
        bright=result['bright'], dark=result['dark'],
        raw_high_mask=result['mask'], weak_mask=continuity['weak_mask'],
        strong_mask=continuity['strong_mask'], continuity_mask=continuity['mask'],
        quality_valid_mask=quality['valid_mask'],
    )
    write_png(frame_dir / 'gray.png', result['gray'])
    write_png(frame_dir / 'background.png', np.clip(result['background'], 0, 255).astype(np.uint8))
    write_png(frame_dir / 'bright.png', np.clip(result['bright'], 0, 255).astype(np.uint8))
    write_png(frame_dir / 'dark.png', np.clip(result['dark'], 0, 255).astype(np.uint8))
    write_png(frame_dir / 'raw_high_mask.png', result['mask'].astype(np.uint8) * 255)
    write_png(frame_dir / 'continuity_mask.png', continuity['mask'].astype(np.uint8) * 255)
    write_png(frame_dir / 'quality_valid_mask.png', quality['valid_mask'].astype(np.uint8) * 255)
    _write_components(frame_dir / 'components.csv', components)
    _write_json(frame_dir / 'summary.json', frame_summary)


def _export_fusion(group_dir: Path, fused: dict) -> None:
    np.savez_compressed(
        group_dir / 'fusion_arrays.npz',
        response=fused['response'], residual=fused['residual'], mask=fused['mask'],
        source_channel=fused['source_channel'], polarity=fused['polarity'],
        valid_count=fused['valid_count'], unknown=fused['unknown'],
    )
    write_png(group_dir / 'fusion_response.png', _scale_response(fused['response']))
    write_png(group_dir / 'fusion_mask.png', fused['mask'].astype(np.uint8) * 255)
    write_png(group_dir / 'source_channel.png', fused['source_channel'].astype(np.uint8) * 50)
    write_png(group_dir / 'polarity.png', ((fused['polarity'].astype(np.int16) + 1) * 127).astype(np.uint8))
    write_png(group_dir / 'valid_count.png', fused['valid_count'].astype(np.uint8) * 60)
    write_png(group_dir / 'unknown.png', fused['unknown'].astype(np.uint8) * 255)


def _write_fpga_interface(output: Path, config: RealBaselineConfig) -> None:
    _write_json(output / 'fpga_reference' / 'interface_spec.json', {
        'schema_version': 1,
        'purpose': 'software_reference_not_rtl_bit_exact_yet',
        'config': config.to_dict(),
        'channel_order': 'numeric CH order; source_channel is 1-based, 0 means unknown',
        'arrays': {
            'gray': 'uint8 ROI after OpenCV BGR2GRAY',
            'background': 'float32 local mean; BORDER_REFLECT_101; full frame before ROI crop',
            'residual': 'float32 gray-background; signed',
            'weak_mask': 'bool abs(residual)>low_threshold and quality-valid',
            'strong_mask': 'bool abs(residual)>high_threshold and quality-valid',
            'continuity_mask': 'bool weak component containing at least one strong seed',
            'quality_valid_mask': 'bool tile proxy; false does not mean normal',
            'fusion_source_channel': 'uint8 1..N or 0 unknown',
            'fusion_polarity': 'int8 -1 dark, 0 neutral/unknown, +1 bright',
        },
        'fixed_point_status': 'pending_TJ_coefficient_rounding_and_border_agreement',
    })


def run_real_baseline(dataset_root: str | Path, output: str | Path,
                      config: RealBaselineConfig | None = None) -> dict:
    """Run the quality-aware baseline over a package ``dataset_index.csv``."""
    dataset_root = Path(dataset_root).resolve()
    output = Path(output).resolve()
    config = config or RealBaselineConfig()
    config.validate()
    rows = _read_dataset_index(dataset_root)
    if output.exists():
        raise ValueError(f'Output directory already exists; choose a new path: {output}')
    output.mkdir(parents=True, exist_ok=False)
    _write_json(output / 'config.json', config.to_dict())
    _write_fpga_interface(output, config)

    grouped = {}
    for row in rows:
        grouped.setdefault(row['group_id'], []).append(row)
    frame_table = []
    subset_table = []
    group_summaries = {}
    quality_counts = {'valid': 0, 'locally_valid': 0, 'review': 0}

    for group_id in sorted(grouped):
        group_rows = sorted(grouped[group_id], key=lambda row: _channel_sort_key(row['channel']))
        group_dir = output / 'groups' / group_id
        group_dir.mkdir(parents=True, exist_ok=False)
        evidence = {}
        channel_status = {}

        for row in group_rows:
            channel = row['channel']
            image_path = Path(row['image_abspath'])
            result = analyze_image(
                read_image(image_path),
                AnalysisConfig(config.background_window, config.high_threshold, config.roi),
            )
            quality = assess_quality(result['gray'], config.quality)
            continuity = hysteresis_connect(
                np.abs(result['residual']), quality['valid_mask'],
                config.low_threshold, config.high_threshold,
            )
            components = describe_components(continuity['mask'], np.abs(result['residual']))
            evidence[channel] = {
                'response': np.abs(result['residual']),
                'residual': result['residual'],
                'mask': continuity['mask'],
                'valid_mask': quality['valid_mask'],
            }
            quality_counts[quality['status']] += 1
            channel_status[channel] = quality['status']
            frame_summary = {
                'sample_id': row['sample_id'], 'group_id': group_id,
                'capture_id': row['capture_id'], 'channel': channel,
                'brightness_command': row['brightness_command'],
                'input': {'path': str(image_path), 'sha256': _sha256(image_path)},
                'quality': _quality_for_json(quality),
                'candidate_pixels': int(continuity['mask'].sum()),
                'strong_pixels': int(continuity['strong_mask'].sum()),
                'weak_pixels': int(continuity['weak_mask'].sum()),
                'component_count': len(components),
                'interpretation': 'exploratory_evidence_not_defect_verdict',
            }
            _export_frame(group_dir / channel, result, quality, continuity, components, frame_summary)
            fpga_dir = output / 'fpga_reference' / group_id
            fpga_dir.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                fpga_dir / f'{channel}.npz',
                gray=result['gray'], background=result['background'], residual=result['residual'],
                weak_mask=continuity['weak_mask'], strong_mask=continuity['strong_mask'],
                continuity_mask=continuity['mask'], quality_valid_mask=quality['valid_mask'],
            )
            frame_table.append({
                'group_id': group_id, 'brightness_command': row['brightness_command'],
                'channel': channel, 'quality_status': quality['status'],
                'quality_reasons': '|'.join(quality['reason_codes']),
                'usable_tile_fraction': quality['usable_tile_fraction'],
                'gray_p01': quality['gray_p01'], 'gray_p50': quality['gray_p50'],
                'gray_p99': quality['gray_p99'],
                'strong_pixels': int(continuity['strong_mask'].sum()),
                'continuity_pixels': int(continuity['mask'].sum()),
                'input_sha256': frame_summary['input']['sha256'],
            })

        fused = fuse_channel_evidence(evidence)
        _export_fusion(group_dir, fused)
        rows_for_group = summarize_subsets({ch: values['mask'] for ch, values in evidence.items()})
        for subset_row in rows_for_group:
            subset_table.append({
                'group_id': group_id,
                'brightness_command': group_rows[0]['brightness_command'],
                **subset_row,
            })
        group_summary = {
            'brightness_command': group_rows[0]['brightness_command'],
            'channels': list(evidence), 'quality_status': channel_status,
            'subset_count': len(rows_for_group),
            'fusion_candidate_pixels': int(fused['mask'].sum()),
            'unknown_pixels': int(fused['unknown'].sum()),
            'interpretation': 'full_channel_fusion_is_reference_not_ground_truth',
        }
        _write_json(group_dir / 'summary.json', group_summary)
        group_summaries[group_id] = group_summary

    _write_csv(output / 'frame_quality.csv', frame_table)
    _write_csv(output / 'subset_comparison.csv', subset_table)
    summary = {
        'schema_version': 1,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'dataset_root': str(dataset_root),
        'dataset_index_sha256': _sha256(dataset_root / 'dataset_index.csv'),
        'runtime': _runtime_record(),
        'frame_count': len(rows), 'group_count': len(grouped),
        'quality_counts': quality_counts, 'groups': group_summaries,
        'claims': {
            'accuracy_reported': False,
            'best_brightness_reported': False,
            'subset_metrics_are_recall': False,
            'auto_exposure_gain_were_locked': False,
        },
        'notes': [
            'Quality status controls fusion participation and is not a normal/defect label.',
            'Subset retention is measured against the same sample full-channel result, not ground truth.',
            'The FPGA package is a floating-point software reference until TJ freezes fixed-point rules.',
        ],
    }
    _write_json(output / 'summary.json', summary)
    return summary
