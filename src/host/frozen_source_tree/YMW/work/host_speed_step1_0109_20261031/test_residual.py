"""Exact equivalence at reflect borders, repeated/mutated indices and LRU eviction."""
from pathlib import Path
import sys
import time
import numpy as np
import profile_saved as base
from cached_residual import PlannedResidualAccess
from residual_access import ResidualAccess


def run(out):
    base.socket.socket = base.socket.create_connection = base.no_network
    base.verify_tool()
    tools = base.Tools(False)
    rng = np.random.default_rng(1031)
    rows = []
    for h, w in ((9, 9), (63, 65), (129, 137)):
        gray = rng.integers(0, 256, (8, h, w), dtype=np.uint8)
        dense = np.stack([tools.h2(g)['residual_n'] for g in gray])
        old = ResidualAccess(gray, tile_size=16, max_tiles=2)
        new = PlannedResidualAccess(gray, tile_size=16, max_tiles=2)
        for i in range(40):
            yy = rng.integers(0, h, (5, 1))
            xx = rng.integers(0, w, (1, 7))
            if i == 0:
                yy[:, 0] = np.array([0, h - 1, 1, h - 2, h // 2])
                xx[0] = np.array([0, w - 1, 1, w - 2, w // 2, 0, w - 1])
            for repeat in range(2):
                for frame in range(8):
                    actual = new[frame, yy, xx]
                    base.need(np.array_equal(actual, dense[frame, yy, xx]) and np.array_equal(actual, old[frame, yy, xx]), 'Dense/original/optimized residual differs')
                    actual[...] = 123  # Caller cannot corrupt the reusable gather.
                    base.need(np.array_equal(new[frame, yy, xx], dense[frame, yy, xx]), 'Cached output mutated')
            yy[0, 0] = (int(yy[0, 0]) + 1) % h
            base.need(np.array_equal(new[0, yy, xx], dense[0, yy, xx]), 'Mutated coordinate array used stale values')
        for frame in range(8):
            base.need(np.array_equal(new[frame, np.array([], int), np.array([], int)], np.array([], np.int16)), 'Empty gather differs')
            base.need(np.array_equal(new[frame, 0, w - 1], dense[frame, 0, w - 1]), 'Scalar gather differs')
        base.need(len(new.cache) <= 2 and new.computed_tiles > 2, 'Eviction not exercised')
        rows.append(dict(shape=list(gray.shape), status='PASS_DENSE_ORIGINAL_AND_CACHED_EXACT', counters=new.counters()))
    rejected = 0
    for key in ((8, 0, 0), (-1, 0, 0), (0, -1, 0), (0, 0, w), (0, np.array([0.5]), np.array([0])), (0, np.array([True]), np.array([0])), (0, np.array([2**64 - 1], np.uint64), np.array([0], np.uint64))):
        try:
            new[key]
        except IndexError:
            rejected += 1
        else:
            raise AssertionError('Invalid index accepted')
    base.need(rejected == 7, 'Missing negative case')
    # Inherited constructor owns an immutable gray snapshot.
    before = new[0, 0, 0].copy()
    gray[:] = 0
    base.need(np.array_equal(new[0, 0, 0], before), 'Gray alias changed residual')
    out.mkdir(parents=True, exist_ok=False)
    base.write(out / 'SELFTEST.json', dict(status='PASS', array_cases=rows, rejected_invalid_indices=rejected,
                new_CAP=0, hardware_contacted=False, frozen_core_modified=False))
    print('PASS: border/dense/mutation/broadcast/scalar/empty/eviction/invalid cases', flush=True)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=Path, required=True)
    run(p.parse_args().out)
