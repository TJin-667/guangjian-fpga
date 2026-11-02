"""Paired same-input host-only comparison, with unchanged frozen math and exports."""
from export_paths import legacy_location, data_path, lab_root, network
import argparse
from pathlib import Path
import statistics
import time
import traceback

import profile_saved as base
from cached_residual import PlannedResidualAccess, build_context


def run(suite, out, groups, repetitions, export):
    base.socket.socket = base.socket.create_connection = base.no_network
    suite, out = suite.resolve(), out.resolve()
    base.need(out.is_relative_to(legacy_location('E:/GuangjianData').resolve()) and not out.exists(), 'New E-drive study directory required')
    base.need(not out.is_relative_to(suite) and not suite.is_relative_to(out), 'Source/output overlap')
    base.need(repetitions >= 1, 'Positive repetition count required')
    base.verify_tool()
    base.verify_seal(suite, base.read(suite / 'OUTPUT_MANIFEST.json')['files_sha256'])
    tools = base.Tools(False)
    optimized = base.Tools(False)
    last_provider = []
    def optimized_context(gray, sat, board, words):
        result = build_context(tools, gray, sat, board, words)
        last_provider[:] = [result[2]]
        return result
    optimized.hybrid = optimized_context
    out.mkdir(parents=True)
    binding = {p.name: base.sha(p) for p in sorted(base.HERE.glob('*.py'))}
    base.write(out / 'EXECUTED_SOURCES.json', dict(files_sha256=binding,
               unchanged_benchmark_binding_sha256=base.sha(base.BENCHMARK / 'TOOL_BINDING.json'),
               frozen_id='f09eb5885e1d', suite_manifest_sha256=base.sha(suite / 'OUTPUT_MANIFEST.json')))
    base.write(out / 'ENVIRONMENT.json', base.environment())
    rows = []; summaries = []
    try:
        for index, name in enumerate(groups):
            folder = suite / name
            x = base.load_group(tools, folder)
            m = x['measurement']
            record = dict(group_id=Path(m['final']).name, sample='sample004', low=m['low'], high=m['high'], root=str(folder / 'fusion'))
            group_rows = []
            for repetition in range(1, repetitions + 1):
                order = ('original', 'planned') if (index + repetition) % 2 else ('planned', 'original')
                for method in order:
                    active = tools if method == 'original' else optimized
                    if export:
                        target = out / name / f'{method}_r{repetition}'
                        result = active.export(x['gray'], x['sat1'], x['board'], x['words'], 'PL', target, record)
                        seconds = result['seconds']
                        events = result['events']
                        base.need(Path(result['final']).is_dir(), 'Missing full export')
                        # Validate arrays plus full review evidence and score
                        # identity outside the measured interval, from disk.
                        import gzip, json, numpy as np
                        with np.load(Path(result['final']) / 'formal_arrays.npz', allow_pickle=False) as z:
                            arrays = {k: z[k].copy() for k in z.files}
                        with gzip.open(Path(result['final']) / 'GAP_REVIEWS.json.gz', 'rt', encoding='utf-8') as f:
                            evidence = json.load(f)
                        scored = base.read(Path(result['final']) / 'REVIEW_PRIORITY.json')
                        actual = arrays, evidence, scored
                        provider = last_provider[0] if method == 'planned' else None
                    else:
                        t = time.perf_counter()
                        context, _, provider = active.hybrid(x['gray'], x['sat1'], x['board'], x['words'])
                        context_seconds = time.perf_counter() - t
                        tc = time.perf_counter()
                        actual = active.algorithm.frozen_runtime.process(context)
                        compute_seconds = time.perf_counter() - tc
                        seconds = time.perf_counter() - t
                        events = [dict(name='context', seconds=context_seconds), dict(name='frozen_compute', seconds=compute_seconds)]
                    base.check_result(tools, actual, folder)
                    row = dict(group=name, method=method, repetition=repetition, seconds=seconds, events=events,
                               formal_arrays_review_and_scores_equal=True,
                               saved_final=str(Path(m['final'])), input_manifest_sha256=base.sha(folder / 'OUTPUT_MANIFEST.json'))
                    if isinstance(provider, PlannedResidualAccess):
                        row['provider_counters'] = provider.counters()
                    rows.append(row); group_rows.append(row)
                    base.write(out / 'PROGRESS.json', dict(status='RUNNING', completed=len(rows), expected=len(groups) * repetitions * 2, latest=row))
                    print(f'{name} {method} r{repetition}: {seconds:.4f}s exact=PASS', flush=True)
            original = [r['seconds'] for r in group_rows if r['method'] == 'original']
            planned = [r['seconds'] for r in group_rows if r['method'] == 'planned']
            a, b = statistics.median(original), statistics.median(planned)
            summaries.append(dict(group=name, original_seconds=original, planned_seconds=planned,
                                  original_median_seconds=a, planned_median_seconds=b,
                                  host_phase_original_over_planned=a / b, host_phase_reduction_percent=100 * (a - b) / a))
            base.write(out / 'GROUPS.json', summaries)
        base.verify_tool()
        base.need(binding == {p.name: base.sha(p) for p in sorted(base.HERE.glob('*.py'))}, 'Study source changed during execution')
        base.verify_seal(suite, base.read(suite / 'OUTPUT_MANIFEST.json')['files_sha256'])
        result = dict(status='PASS_PAIRED_EXACT_HOST_STUDY', full_export=export, repetitions=repetitions,
                      groups=summaries, runs=rows, comparisons=len(rows), environment=base.environment(),
                      source=str(suite), frozen_id='f09eb5885e1d', new_CAP=0, hardware_contacted=False,
                      bit_or_frozen_algorithm_modified=False, production_entry_changed=False,
                      system_speedup=None, FPGA_compute_speedup=None,
                      scope='Identical saved eight frames and FPGA R32, single-threaded host continuation only. Context and frozen compute' + (' plus unchanged full export.' if export else '; export excluded.'))
        base.write(out / 'RESULT.json', result)
        base.write(out / 'PROGRESS.json', dict(status=result['status'], completed=len(rows)))
        return result
    except BaseException as e:
        base.write(out / 'FAILED.json', dict(type=type(e).__name__, message=str(e), traceback=traceback.format_exc(), completed=rows))
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--suite', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--groups', nargs='+', required=True)
    p.add_argument('--repetitions', type=int, default=3)
    p.add_argument('--export', action='store_true')
    a = p.parse_args()
    run(a.suite, a.out, a.groups, a.repetitions, a.export)
