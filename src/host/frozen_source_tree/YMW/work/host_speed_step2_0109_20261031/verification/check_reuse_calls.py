"""Outside timing: ensure restoring/constructing the context does not rerun H2/quality."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intermediates import base, from_replay, restore
from reuse_context import build_context
from residual_access import ResidualAccess


def run(suite, study, out):
    base.socket.socket = base.socket.create_connection = base.no_network
    tools = base.Tools(False)
    group = '03_PL_cold_r1'
    value = from_replay(tools, suite / group)
    names = {tools.h2.__code__: 'integer_H2', tools.quality.__code__: 'quality', ResidualAccess.tile.__code__: 'residual_tile'}
    counts = {name: 0 for name in names.values()}
    def observe(frame, event, arg):
        if event == 'call' and frame.f_code in names:
            counts[names[frame.f_code]] += 1
    previous = sys.getprofile()
    sys.setprofile(observe)
    try:
        handoff = restore(value['native'], study / group / 'reuse_r1/handoff', tools)
        context, _ = build_context(tools, handoff)
    finally:
        sys.setprofile(previous)
    base.need(not any(counts.values()), 'Reuse unexpectedly recomputed H2/quality/tiles')
    out.mkdir(parents=True, exist_ok=False)
    base.write(out / 'CALL_AUDIT.json', dict(status='PASS_NO_H2_QUALITY_OR_TILE_RECOMPUTE', observed_calls=counts,
               group=group, source=str(suite), cache=str(study / group / 'reuse_r1/handoff'),
               scope='Restore and context only; prior offline reconstruction excluded. Not a timing measurement.',
               hardware_contacted=False, new_CAP=0))
    print('PASS: restore/context recomputation calls', counts, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--suite', type=Path, required=True)
    p.add_argument('--study', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); run(a.suite, a.study, a.out)
