"""Matched first-use handoff cost plus unchanged full frozen export.

Both branches start after the common capture audit. Offline reconstruction of
that already-existing audit is performed once outside both intervals and is
explicitly labelled. The candidate includes creating/writing/reading/checking
its extra derivative handoff each repetition, not merely a warm cache hit.
"""
import argparse
import gzip
import json
from pathlib import Path
import statistics
import time
import traceback

from intermediates import base, from_replay, seal, restore, bindings, HERE
from reuse_context import build_context
from cached_residual import build_context as step1_context
from performance import Ledger
import numpy as np


def export(tools, value, method, target, group):
    t = time.perf_counter(); cpu_started = time.process_time(); started = time.monotonic(); ledger = Ledger()
    native = value['native']
    if method == 'reuse':
        with ledger.span('new_handoff_creation_write'):
            cache = seal(value, target / 'handoff', tools)
        with ledger.span('new_handoff_read_and_source_checks'):
            handoff = restore(native, cache, tools)
        with ledger.span('PL_R32_context_with_existing_H2_quality'):
            context, _ = build_context(tools, handoff)
    else:
        with ledger.span('step1_context_quality_and_R32'):
            context, _, _ = step1_context(tools, native['gray'], native['sat1'], native['board'], native['words'])
    final = target / 'final'; final.mkdir(parents=True, exist_ok=False)
    rows, scored = tools.algorithm.process(context, group, final / group['group_id'], timing=ledger)
    with ledger.span('finalize_reports_and_freeze_checks'):
        tools.algorithm.finalize(final, group, rows, started)
    ledger.save(target / 'POST_PERFORMANCE.json', method=method, parameter_freeze_id='f09eb5885e1d')
    return dict(seconds=time.perf_counter() - t, process_CPU_seconds=time.process_time() - cpu_started,
                events=ledger.events, final=str(final / group['group_id']),
                handoff_data_bytes=(target / 'handoff/intermediates.npz').stat().st_size if method == 'reuse' else 0,
                cached_array_bytes=int(value['residual_n'].nbytes + value['valid'].nbytes))


def check_final(tools, final, folder):
    final = Path(final)
    with np.load(final / 'formal_arrays.npz', allow_pickle=False) as z:
        arrays = {k: z[k].copy() for k in z.files}
    with gzip.open(final / 'GAP_REVIEWS.json.gz', 'rt', encoding='utf-8') as f:
        evidence = json.load(f)
    scored = base.read(final / 'REVIEW_PRIORITY.json')
    base.check_result(tools, (arrays, evidence, scored), folder)


def run(suite, out, groups, repetitions):
    base.socket.socket = base.socket.create_connection = base.no_network
    suite, out = suite.resolve(), out.resolve()
    base.need(out.is_relative_to(Path('E:/GuangjianData').resolve()) and not out.exists(), 'New E-drive output required')
    base.need(not out.is_relative_to(suite) and not suite.is_relative_to(out) and repetitions > 0, 'Bad output/repetitions')
    base.verify_tool(); base.verify_seal(suite, base.read(suite / 'OUTPUT_MANIFEST.json')['files_sha256'])
    tools = base.Tools(False); bindings(tools)
    out.mkdir(parents=True)
    programs = {p.relative_to(HERE).as_posix(): base.sha(p) for p in HERE.rglob('*.py')}
    base.write(out / 'EXECUTED_SOURCES.json', dict(files_sha256=programs,
               step1_programs=base.read(base.HERE / 'PUBLISH_MANIFEST.json'), reference_bindings=bindings(tools)))
    base.write(out / 'ENVIRONMENT.json', base.environment())
    rows = []; summaries = []
    try:
        for gi, name in enumerate(groups):
            folder = suite / name
            value = from_replay(tools, folder)
            m = base.read(folder / 'MEASUREMENT.json')
            group = dict(group_id=Path(m['final']).name, sample='sample004', low=m['low'], high=m['high'], root=str(folder / 'fusion'))
            group_rows = []
            for repetition in range(1, repetitions + 1):
                order = ('step1', 'reuse') if (gi + repetition) % 2 else ('reuse', 'step1')
                for method in order:
                    target = out / name / f'{method}_r{repetition}'; target.mkdir(parents=True)
                    row = export(tools, value, method, target, group)
                    check_final(tools, row['final'], folder)
                    row.update(group=name, method=method, repetition=repetition, exact_formal_review_and_scores=True,
                               input_manifest_sha256=base.sha(folder / 'OUTPUT_MANIFEST.json'))
                    rows.append(row); group_rows.append(row)
                    base.write(out / 'PROGRESS.json', dict(status='RUNNING', completed=len(rows), expected=len(groups) * repetitions * 2, latest=row))
                    print(f'{name} {method} r{repetition}: {row["seconds"]:.4f}s exact=PASS', flush=True)
                    # This fixed 864-square replay should take seconds, not
                    # minutes. Retain the complete interrupted batch, stop and
                    # qualify it separately; never replace just a slow sample.
                    base.need(row['seconds'] <= 120, 'LONG_WALL_PAUSE: retain this batch; no automatic performance retry')
            a = [r['seconds'] for r in group_rows if r['method'] == 'step1']
            b = [r['seconds'] for r in group_rows if r['method'] == 'reuse']
            am, bm = statistics.median(a), statistics.median(b)
            summaries.append(dict(group=name, step1_seconds=a, reuse_seconds=b, step1_median_seconds=am,
                                  reuse_median_seconds=bm, host_phase_reduction_percent=100 * (am - bm) / am,
                                  host_phase_step1_over_reuse=am / bm))
            base.write(out / 'GROUPS.json', summaries)
        base.need(programs == {p.relative_to(HERE).as_posix(): base.sha(p) for p in HERE.rglob('*.py')}, 'Study source changed')
        bindings(tools); base.verify_seal(suite, base.read(suite / 'OUTPUT_MANIFEST.json')['files_sha256'])
        result = dict(status='PASS_SOURCE_BOUND_HANDOFF_AND_FULL_EXPORT', source=str(suite), groups=summaries, runs=rows,
                      repetitions=repetitions, actual_runs=len(rows), frozen_id='f09eb5885e1d', new_CAP=0,
                      hardware_contacted=False, production_entry_changed=False, system_speedup=None, FPGA_compute_speedup=None,
                      includes_new_handoff_creation_write_read_checks=True,
                      performance_eligible=True, long_wall_pause_limit_seconds=120,
                      common_capture_audit_reconstruction_outside_both_intervals=True,
                      reconstruction_origin='offline_reconstruction_of_existing_capture_audit_not_new_board_data',
                      scope='Same saved PL eight frames/R32. Existing capture-audit arrays to source-bound handoff and full frozen host export; excludes physical capture/PL/FETCH, original native-cache IPC and one-time imports.')
        base.write(out / 'RESULT.json', result)
        base.write(out / 'PROGRESS.json', dict(status=result['status'], completed=len(rows)))
    except BaseException as e:
        base.write(out / 'FAILED.json', dict(type=type(e).__name__, message=str(e), traceback=traceback.format_exc(), completed=rows))
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--suite', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p.add_argument('--groups', nargs='+', required=True); p.add_argument('--repetitions', type=int, default=3)
    a = p.parse_args(); run(a.suite, a.out, a.groups, a.repetitions)
