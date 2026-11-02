"""Export numerical evidence and fixed-scale diagnostic figures."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile

os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'light-inspection-mpl'))
import matplotlib
matplotlib.use('Agg')
from matplotlib import font_manager
import matplotlib.pyplot as plt
import numpy as np
import cv2

from . import __version__
from .core import AnalysisConfig, analyze_image
from .image_io import read_image, write_png

try:
    font_manager.findfont('Microsoft YaHei', fallback_to_default=False)
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'DejaVu Sans']
except ValueError:
    pass
plt.rcParams['axes.unicode_minus'] = False
DIRECTIONS = ('E', 'S', 'W', 'N')


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def provenance(path: Path) -> dict:
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def runtime_record() -> dict:
    source = Path(__file__).resolve().parent
    return {
        'tool_version': __version__, 'python': platform.python_version(),
        'platform': platform.platform(), 'numpy': np.__version__,
        'opencv': cv2.__version__, 'matplotlib': matplotlib.__version__,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(source.glob('*.py'))},
    }


def new_output(path: Path) -> None:
    if path.exists():
        raise ValueError(f'Output directory already exists; choose a new run directory: {path}')
    path.mkdir(parents=True, exist_ok=False)


def export_arrays(output: Path, result: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output / 'arrays.npz', **{key: result[key] for key in
                        ('gray', 'background', 'residual', 'bright', 'dark', 'mask', 'histogram')})
    write_png(output / 'gray.png', result['gray'])
    write_png(output / 'bright.png', np.clip(result['bright'], 0, 255).astype(np.uint8))
    write_png(output / 'dark.png', np.clip(result['dark'], 0, 255).astype(np.uint8))
    write_png(output / 'mask.png', result['mask'].astype(np.uint8) * 255)
    with (output / 'histogram.csv').open('x', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['gray_level', 'pixel_count'])
        writer.writerows(enumerate(result['histogram'].tolist()))


def base_summary(config: AnalysisConfig, source_type: str) -> dict:
    return {
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_type': source_type, 'origin_verification': 'declared_not_independently_verified',
        'real_experiment_evidence': False,
        'interpretation': 'exploratory_candidates_only',
        'config': config.to_dict(), 'runtime': runtime_record(),
        'algorithm': {
            'gray': 'OpenCV BGR2GRAY or unchanged GRAY8',
            'background': 'float32 local mean on full image, then ROI crop',
            'border': 'BORDER_REFLECT_101', 'residual': 'gray - background',
            'candidate': 'abs(residual) > threshold', 'morphology': 'disabled',
            'component_filtering': 'disabled',
        },
        'diagnostic_notes': [
            'near_black means gray <= 5; near_white means gray >= 250; neither is an invalid-frame rule.',
            'gray_std and laplacian_variance are not calibrated noise or defocus estimates.',
            'A candidate mask is not ground truth, a defect count, or a pass/fail decision.',
            'PNG response previews truncate fractions; arrays.npz preserves float32 numerical responses.',
            'Image-file decoding cannot verify original network-frame completeness.',
        ],
    }


def analyze_file(input_path: Path, output: Path, config: AnalysisConfig, source_type: str) -> dict:
    result = analyze_image(read_image(input_path), config)
    summary = base_summary(config, source_type)
    summary['input'] = provenance(input_path)
    summary['metrics'] = result['metrics']
    scale = max(1.0, float(config.threshold), float(np.abs(result['residual']).max()))
    summary['display'] = {'gray_range': [0, 255], 'response_range': [0, scale],
                          'signed_range': [-scale, scale]}
    new_output(output)
    export_arrays(output, result)
    save_json(output / 'config.json', config.to_dict())
    fig, axes = plt.subplots(2, 3, figsize=(13, 8), layout='constrained')
    panels = [
        ('Gray ROI', result['gray'], 'gray', 0, 255),
        ('Local background', result['background'], 'gray', 0, 255),
        ('Signed response', result['residual'], 'coolwarm', -scale, scale),
        ('Bright response', result['bright'], 'magma', 0, scale),
        ('Dark response', result['dark'], 'magma', 0, scale),
        (f'Candidates |R| > {config.threshold:g}', result['mask'], 'gray', 0, 1),
    ]
    for ax, (title, data, cmap, low, high) in zip(axes.flat, panels):
        shown = ax.imshow(data, cmap=cmap, vmin=low, vmax=high, interpolation='nearest')
        ax.set_title(title)
        ax.set_axis_off()
        if 'response' in title.lower():
            fig.colorbar(shown, ax=ax, shrink=.7)
    label = 'SYNTHETIC / SOFTWARE CHECK ONLY' if source_type == 'synthetic' else 'REAL INPUT / EXPLORATORY CANDIDATES'
    fig.suptitle(f'{label}\nwindow={config.background_window}, threshold={config.threshold:g}')
    fig.savefig(output / 'overview.png', dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 4), layout='constrained')
    ax.bar(np.arange(256), result['histogram'], width=1)
    ax.set(xlabel='Gray level', ylabel='Pixel count', xlim=(0, 255), title=label)
    fig.savefig(output / 'histogram.png', dpi=130)
    plt.close(fig)
    # Summary is written last: its existence marks a completed export.
    save_json(output / 'summary.json', summary)
    return summary


def compare_frames(rows: list[dict], output: Path, config: AnalysisConfig,
                   warnings: list[str], manifest: Path) -> dict:
    if not rows:
        raise ValueError('No frames match this sample_id and repeat_id.')
    sources = {row['source_type'] for row in rows}
    if len(sources) != 1:
        raise ValueError('Cannot compare mixed real and synthetic sources.')
    decoded = {row['direction']: read_image(row['image_abspath']) for row in rows}
    if len({im.shape[:2] for im in decoded.values()}) != 1:
        raise ValueError('Comparison requires identical full-image dimensions; no automatic resizing.')
    results = {direction: analyze_image(im, config) for direction, im in decoded.items()}
    scale = max(1.0, float(config.threshold),
                *(float(np.abs(r['residual']).max()) for r in results.values()))
    summary = base_summary(config, next(iter(sources)))
    summary.update({
        'sample_id': rows[0]['sample_id'], 'repeat_id': rows[0]['repeat_id'],
        'manifest': provenance(manifest), 'warnings': warnings,
        'missing_directions': [d for d in DIRECTIONS if d not in results],
        'complete_four_directions': len(results) == 4,
        'display': {'gray_range': [0, 255], 'response_range': [0, scale],
                    'response_scale_policy': 'one_shared_scale_for_all_directions'},
        'frames': {},
    })
    by_direction = {row['direction']: row for row in rows}
    new_output(output)
    save_json(output / 'config.json', config.to_dict())
    fig, axes = plt.subplots(4, 4, figsize=(15, 12), layout='constrained')
    for col, direction in enumerate(DIRECTIONS):
        if direction not in results:
            for ax in axes[:, col]:
                ax.set_axis_off()
                ax.text(.5, .5, f'{direction}\nMISSING', ha='center', va='center', color='firebrick',
                        transform=ax.transAxes, fontsize=16)
            continue
        result = results[direction]
        row = by_direction[direction]
        export_arrays(output / direction, result)
        summary['frames'][direction] = {'capture': row, 'input': provenance(Path(row['image_abspath'])),
                                        'metrics': result['metrics']}
        for index, (key, cmap, maximum) in enumerate([
                ('gray', 'gray', 255), ('bright', 'magma', scale),
                ('dark', 'magma', scale), ('mask', 'gray', 1)]):
            ax = axes[index, col]
            ax.imshow(result[key], cmap=cmap, vmin=0, vmax=maximum, interpolation='nearest')
            title = f'{direction} / {key}'
            if index == 0:
                title += f"\nexp={row['exposure_us']} us, gain={row['gain']}\nlight={row['light_level']}"
            ax.set_title(title, fontsize=10)
            ax.set_axis_off()
    label = 'SYNTHETIC / SOFTWARE CHECK ONLY' if summary['source_type'] == 'synthetic' else 'REAL INPUT / VISUAL COMPARISON'
    fig.suptitle(f"{label}\nsample={summary['sample_id']}, repeat={summary['repeat_id']}; "
                 f"gray 0..255, responses 0..{scale:.2f}, threshold={config.threshold:g}\n"
                 'Check settings and alignment before interpreting direction differences.', fontsize=12)
    fig.savefig(output / 'comparison.png', dpi=150)
    plt.close(fig)
    save_json(output / 'summary.json', summary)
    return summary
