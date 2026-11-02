"""Exact native residual access with one reusable coordinate plan.

The frozen reviewer probes the same native coordinates in eight frames and two
polarities. Reuse only integer indexing and the immediately repeated gather;
all tile arithmetic, reflect101 borders and the 256-tile LRU are inherited.
No detector/review decision, threshold or evidence is cached or changed.
"""
import numpy as np
from residual_access import ResidualAccess


class PlannedResidualAccess(ResidualAccess):
    def __init__(self, gray, *, tile_size=64, max_tiles=256):
        super().__init__(gray, tile_size=tile_size, max_tiles=max_tiles)
        self._plan = None
        self._values = {}
        self.plan_builds = self.plan_hits = self.gather_hits = self.requests = 0
        self.peak_plan_bytes = 0

    def __getitem__(self, key):
        if not isinstance(key, tuple) or len(key) != 3:
            raise IndexError('Use real frame,y,x native indices')
        frame, yy, xx = key
        if not isinstance(frame, (int, np.integer)) or not 0 <= frame < 8:
            raise IndexError('Invalid real frame')
        yy, xx = np.broadcast_arrays(np.asarray(yy), np.asarray(xx))
        if yy.dtype.kind not in 'iu' or xx.dtype.kind not in 'iu':
            raise IndexError('Native coordinates must be integers')
        shape = yy.shape
        y, x = yy.ravel(), xx.ravel()
        self.requests += 1
        plan = self._plan
        # Compare copied coordinates, never object IDs: callers may mutate an
        # index array between queries. Every cached plan was bounds-validated.
        if plan is not None and plan['shape'] == shape and np.array_equal(y, plan['y']) and np.array_equal(x, plan['x']):
            self.plan_hits += 1
            if int(frame) in self._values:
                self.gather_hits += 1
                # Preserve the original fresh, writable return-array contract.
                return self._values[int(frame)].copy()
        else:
            if np.any(y < 0) or np.any(x < 0) or np.any(y >= self.shape[1]) or np.any(x >= self.shape[2]):
                raise IndexError('Native coordinates outside savedROI')
            tx, ty = x // self.tile_size, y // self.tile_size
            keys = ty * ((self.shape[2] + self.tile_size - 1) // self.tile_size) + tx
            groups = []
            for encoded in np.unique(keys):
                ids = np.flatnonzero(keys == encoded)
                row, column = int(ty[ids[0]]), int(tx[ids[0]])
                groups.append((row, column, ids, y[ids] - row * self.tile_size, x[ids] - column * self.tile_size))
            plan = dict(shape=shape, y=y.copy(), x=x.copy(), groups=groups)
            self._plan = plan
            self._values = {}
            self.plan_builds += 1
        out = np.empty(y.size, 'int16')
        for row, column, ids, local_y, local_x in plan['groups']:
            out[ids] = self.tile(int(frame), row, column)[local_y, local_x]
        result = out.reshape(shape)
        self._values[int(frame)] = result.copy()
        self.peak_plan_bytes = max(self.peak_plan_bytes, self.plan_bytes())
        return result

    def plan_bytes(self):
        if self._plan is None:
            return 0
        p = self._plan
        return (p['y'].nbytes + p['x'].nbytes + sum(a.nbytes for g in p['groups'] for a in g[2:])
                + sum(v.nbytes for v in self._values.values()))

    def counters(self):
        return dict(requests=self.requests, plan_builds=self.plan_builds, plan_hits=self.plan_hits,
                    gather_hits=self.gather_hits, computed_tiles=self.computed_tiles,
                    peak_tile_cache_bytes=self.peak_cache_bytes, peak_plan_array_bytes=self.peak_plan_bytes,
                    gray_copy_bytes=self.gray.nbytes, max_tiles=self.max_tiles, tile_size=self.tile_size)


def build_context(tools, gray, sat, board, words):
    """Keep every original R32/quality/gray-source validation and frozen core."""
    context, fused, _ = tools.hybrid(gray, sat, board, words)
    provider = PlannedResidualAccess(gray)
    context['planes']['residual_n'] = provider
    return context, fused, provider
