import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

from .core import load_config
from .metadata import validate_manifest


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description='Week-one local-background exploration. No automated defect verdict.')
    sub = cli.add_subparsers(dest='command', required=True)
    analyze = sub.add_parser('analyze', help='Analyze one 8-bit image and preserve numerical responses.')
    analyze.add_argument('--input', type=Path, required=True)
    analyze.add_argument('--source-type', choices=['real', 'synthetic'], required=True)
    compare = sub.add_parser('compare', help='Compare one sample and repeat across E/S/W/N.')
    compare.add_argument('--manifest', type=Path, required=True)
    compare.add_argument('--sample-id', required=True)
    compare.add_argument('--repeat-id', required=True)
    for item in (analyze, compare):
        item.add_argument('--output', type=Path, required=True, help='New run directory; never overwritten.')
        item.add_argument('--config', type=Path)
        item.add_argument('--window', type=int)
        item.add_argument('--threshold', type=float)
        item.add_argument('--roi', type=int, nargs=4, metavar=('X', 'Y', 'W', 'H'))
    validate = sub.add_parser('validate-metadata', help='Validate CSV schema, image contents and grouping.')
    validate.add_argument('--manifest', type=Path, required=True)
    validate.add_argument('--output', type=Path, help='Optional NEW JSON report file.')
    real = sub.add_parser(
        'real-baseline',
        help='Run quality-aware continuity, traceable fusion and channel-subset analysis.',
    )
    real.add_argument('--dataset-root', type=Path, required=True,
                      help='Package directory containing dataset_index.csv.')
    real.add_argument('--output', type=Path, required=True, help='New result directory.')
    real.add_argument('--window', type=int, default=9)
    real.add_argument('--low-threshold', type=float, default=8)
    real.add_argument('--high-threshold', type=float, default=20)
    real.add_argument('--roi', type=int, nargs=4, metavar=('X', 'Y', 'W', 'H'),
                      default=(880, 480, 400, 260))
    real.add_argument('--tile-size', type=int, default=32)
    return cli


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == 'real-baseline':
            from .real_baseline import QualityConfig, RealBaselineConfig, run_real_baseline
            config = RealBaselineConfig(
                background_window=args.window,
                low_threshold=args.low_threshold,
                high_threshold=args.high_threshold,
                roi=tuple(args.roi) if args.roi is not None else None,
                quality=QualityConfig(tile_size=args.tile_size),
            )
            summary = run_real_baseline(args.dataset_root, args.output, config)
            print(json.dumps({
                'output': str(args.output.resolve()),
                'frame_count': summary['frame_count'],
                'group_count': summary['group_count'],
                'quality_counts': summary['quality_counts'],
                'interpretation': 'exploratory_evidence_not_accuracy',
            }, ensure_ascii=False, indent=2))
            return 0
        if args.command == 'validate-metadata':
            report = validate_manifest(args.manifest)
            if args.output:
                from .reports import save_json
                save_json(args.output, report)
            print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
            return 2 if report['errors'] else 0
        config = load_config(args.config)
        overrides = {}
        if args.window is not None:
            overrides['background_window'] = args.window
        if args.threshold is not None:
            overrides['threshold'] = args.threshold
        if args.roi is not None:
            overrides['roi'] = tuple(args.roi)
        config = replace(config, **overrides)
        config.validate()
        from .reports import analyze_file, compare_frames
        if args.command == 'analyze':
            summary = analyze_file(args.input, args.output, config, args.source_type)
            notices = []
        else:
            report = validate_manifest(args.manifest)
            if report['errors']:
                raise ValueError('Metadata validation failed:\n' + '\n'.join(report['errors']))
            selected = [row for row in report['rows'] if row['sample_id'] == args.sample_id
                        and row['repeat_id'] == args.repeat_id]
            summary = compare_frames(selected, args.output, config, report['warnings'], args.manifest)
            notices = summary['warnings']
        print(json.dumps({'output': str(args.output.resolve()), 'source_type': summary['source_type'],
                          'interpretation': summary['interpretation'], 'warnings': notices},
                         ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
