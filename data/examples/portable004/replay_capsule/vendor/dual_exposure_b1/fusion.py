"""Ordered valid MaxAbs selection, followed by unchanged B1 hysteresis.

Frame order is CH1_low, CH1_high, ..., CH4_low, CH4_high.
The direction candidates are diagnostic outputs, never inputs to final fusion.
"""
import numpy as np

from .frozen_reference.fourlight_fusion.fusion import single_features
from light_inspection.real_baseline import hysteresis_connect


FRAME_ORDER = tuple(f'CH{i}_{role}' for i in range(1, 5) for role in ('low', 'high'))


def maxabs_connect(residuals, valid, *, source_ids=None, source_maps=None, board=None):
    r, v = np.asarray(residuals), np.asarray(valid)
    if (r.ndim != 3 or not 1 <= r.shape[0] <= 8 or min(r.shape[1:], default=0) < 1
            or not np.issubdtype(r.dtype, np.signedinteger)
            or v.dtype != np.bool_ or v.shape != r.shape
            or np.any((r < -20655) | (r > 20655))):
        raise ValueError('Expected 1..8 signed H2 residual planes and matching boolean validity')
    if board is not None:
        board = np.asarray(board)
        if board.dtype != np.bool_ or board.shape != r.shape[1:]:
            raise ValueError('Board must be a matching boolean plane')
    if source_ids is not None and source_maps is not None:
        raise ValueError('Specify source IDs or source maps, not both')
    if source_maps is not None:
        sources = np.asarray(source_maps)
        if (sources.shape != r.shape or not np.issubdtype(sources.dtype, np.integer)
                or np.any((sources < 0) | (sources > 8)) or np.any(v & (sources == 0))):
            raise ValueError('Source maps must identify each valid response by frame ID 1..8')
    else:
        sources = np.arange(1, len(r) + 1) if source_ids is None else np.asarray(source_ids)
        if (sources.shape != (len(r),) or not np.issubdtype(sources.dtype, np.integer)
                or np.any((sources < 1) | (sources > 8)) or len(set(sources.tolist())) != len(r)):
            raise ValueError('Source IDs must be distinct integers in 1..8')
    values = r.astype(np.int32)
    chosen = np.argmax(np.where(v, np.abs(values), -1), axis=0)
    yy, xx = np.indices(r.shape[1:])
    unknown = ~v.any(axis=0)
    selected = values[chosen, yy, xx].copy()
    source = (sources[chosen, yy, xx] if source_maps is not None else sources[chosen]).astype(np.uint8)
    selected[unknown], source[unknown] = 0, 0
    connected = hysteresis_connect(np.abs(selected), ~unknown, 648, 1620)
    mask = connected['mask'] if board is None else connected['mask'] & board
    return {'residual_n': selected.astype('<i2'), 'source_frame': source,
            'source_direction': np.where(source > 0, (source.astype(np.int16) - 1) // 2 + 1, 0).astype(np.uint8),
            'source_exposure': np.where(source > 0, (source.astype(np.int16) - 1) % 2 + 1, 0).astype(np.uint8),
            'polarity': np.sign(selected).astype(np.int8), 'unknown': unknown,
            'weak': connected['weak_mask'], 'strong': connected['strong_mask'],
            'connected_mask': connected['mask'], 'mask': mask}


def fuse_two_stage(residuals, valid, *, board=None):
    r, v = np.asarray(residuals), np.asarray(valid)
    if r.ndim != 3 or r.shape[0] != 8 or v.shape != r.shape:
        raise ValueError('Exactly eight ordered planes are required')
    directions = tuple(maxabs_connect(r[2*i:2*i+2], v[2*i:2*i+2],
                                     source_ids=np.array([2*i+1, 2*i+2]), board=board)
                       for i in range(4))
    # Crucially use raw selected residuals and validity, including unseeded weak
    # responses; directions[i]['mask'] is never read in this stage.
    final = maxabs_connect(np.stack([d['residual_n'] for d in directions]),
                           np.stack([~d['unknown'] for d in directions]),
                           source_maps=np.stack([d['source_frame'] for d in directions]), board=board)
    return {'directions': directions, 'final': final}
