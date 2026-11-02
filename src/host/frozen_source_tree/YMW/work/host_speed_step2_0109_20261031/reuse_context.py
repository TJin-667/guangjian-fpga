"""Resume frozen processing from PL R32 and source-bound audit intermediates."""
import numpy as np
from intermediates import base, native_check


def build_context(tools, handoff):
    native = handoff['native']
    gray, sat, board, words = (native[k] for k in ('gray', 'sat1', 'board', 'words'))
    valid, residual = handoff['valid'], handoff['residual_n']
    base.need(gray.dtype == np.uint8 and gray.shape == (8, *board.shape) and board.dtype == bool, 'Native gray/board mismatch')
    base.need(sat.dtype == bool and sat.shape == gray.shape and valid.dtype == bool and valid.shape == gray.shape
              and residual.dtype == np.int16 and residual.shape == gray.shape, 'Native evidence shapes differ')
    # Continue to read the actual PL result. This does not run PC fusion instead.
    fused, selected_gray = tools.decode(words, board, tools.connect)
    source = fused['source_frame']; yy, xx = np.indices(board.shape); index = np.maximum(source.astype(int) - 1, 0)
    base.need(not np.any((source > 0) & ~valid[index, yy, xx]), 'PL selected an invalid observation')
    expected = gray[index, yy, xx].copy(); expected[source == 0] = 0
    base.need(np.array_equal(selected_gray, expected), 'Selected-source gray differs')
    selected_r = residual[index, yy, xx].copy(); selected_r[source == 0] = 0
    base.need(np.array_equal(fused['residual_n'], selected_r), 'Selected-source residual differs')
    unknown = ~valid.any(0)
    base.need(np.array_equal(fused['unknown'], unknown), 'PL unknown differs from cached exact validity')
    amplitude = np.abs(fused['residual_n'].astype(np.int32)); visible = ~unknown
    guide = tools.connect(amplitude, visible, 486, 1620)['mask'] & board
    context = dict(planes=dict(gray=gray, sat1=sat, board=board, valid=valid, residual_n=residual),
                   r=amplitude, v=visible, board=board, original=fused['mask'], guide=guide,
                   hysteresis=tools.connect, sleeve=tools.sleeve(fused['mask'], guide, amplitude), caches={}, tip_cache={}, original_differences={})
    return context, fused
