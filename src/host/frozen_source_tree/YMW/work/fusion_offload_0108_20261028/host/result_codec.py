"""Lossless R32 decode and unchanged host B1 connection; no hardware transport."""
import numpy as np

def decode_words(words,board,hysteresis_connect):
    words=np.asarray(words);board=np.asarray(board)
    if words.ndim!=2 or words.dtype!=np.dtype('<u4') or board.dtype!=np.bool_ or board.shape!=words.shape:
        raise ValueError('Expected little-endian uint32 ROI words and matching boolean board')
    r=(words&65535).astype('<u2').view('<i2')
    source=((words>>16)&15).astype(np.uint8);unknown=source==0
    amplitude=np.abs(r.astype(np.int32))
    weak=((words>>20)&1).astype(bool);strong=((words>>21)&1).astype(bool)
    gray=((words>>22)&255).astype(np.uint8)
    if np.any(words>>30) or np.any(source>8) or np.any(amplitude>20655) or np.any(words[unknown]):
        raise ValueError('Invalid reserved/source/range/unknown encoding')
    if not np.array_equal(weak,(amplitude>648)&~unknown) or not np.array_equal(strong,(amplitude>1620)&~unknown):
        raise ValueError('FPGA threshold flags differ from frozen strict comparisons')
    # Connect over the entire saved ROI. Board masking must happen afterwards.
    connected=hysteresis_connect(amplitude,~unknown,648,1620)
    return dict(residual_n=r,source_frame=source,unknown=unknown,
        source_direction=np.where(source>0,(source.astype(np.int16)-1)//2+1,0).astype(np.uint8),
        source_exposure=np.where(source>0,(source.astype(np.int16)-1)%2+1,0).astype(np.uint8),
        polarity=np.sign(r).astype(np.int8),weak=weak,strong=strong,
        connected_mask=connected['mask'],mask=connected['mask']&board),gray
