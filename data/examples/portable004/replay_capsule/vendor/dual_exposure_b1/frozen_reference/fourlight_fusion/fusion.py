"""fourlight-fusion-1: observed integer evidence only; no bridge drawing."""
from pathlib import Path
import sys
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'software'))
from ymw_integer_reference import integer_gray,integer_h2
from light_inspection.real_baseline import assess_quality,hysteresis_connect


def single_features(bgr):
    gray=integer_gray(bgr);h2=integer_h2(gray);quality=assess_quality(gray)
    result=hysteresis_connect(np.abs(h2['residual_n'].astype(np.int32)),quality['valid_mask'],648,1620)
    return dict(gray=gray,**h2,valid=quality['valid_mask'],weak=result['weak_mask'],
                strong=result['strong_mask'],mask=result['mask'])


def tile_quality(bgr,board,tile_size=32,rgb_penalty=4,dark_penalty=4):
    if (not isinstance(bgr,np.ndarray) or bgr.dtype!=np.uint8 or bgr.ndim!=3 or bgr.shape[2]!=3
            or board.shape!=bgr.shape[:2] or board.dtype!=np.bool_ or not board.any()):
        raise ValueError('Expected BGR uint8 and nonempty boolean geometric board')
    if type(tile_size)!=int or tile_size<2 or any(type(p)!=int or p<0 for p in (rgb_penalty,dark_penalty)):
        raise ValueError('Invalid quality parameters')
    gray=integer_gray(bgr);maximum=(bgr==255).any(axis=2)
    q=np.zeros(gray.shape,np.uint16);rows=[]
    for y in range(0,gray.shape[0],tile_size):
        for x in range(0,gray.shape[1],tile_size):
            sl=np.s_[y:y+tile_size,x:x+tile_size];m=board[sl];n=int(m.sum())
            clipped=int((maximum[sl]&m).sum());dark=int(((gray[sl]<=10)&m).sum())
            # Integer floor Q8 ranking only; never multiply the detection residual.
            weight=(256*n//(n+rgb_penalty*clipped+dark_penalty*dark)) if n else 0
            q[sl]=weight
            rows.append(dict(x=x,y=y,width=m.shape[1],height=m.shape[0],board_pixels=n,
                rgb_max_pixels=clipped,dark_pixels=dark,rgb_max_fraction=clipped/n if n else None,
                dark_fraction=dark/n if n else None,quality_q8=weight))
    return dict(quality_q8=q,tiles=rows)


def fuse(residuals,valid,mode='B1',quality=None):
    r=np.asarray(residuals);v=np.asarray(valid)
    if (r.ndim!=3 or r.shape[0]!=4 or min(r.shape[1:],default=0)<1
            or not np.issubdtype(r.dtype,np.signedinteger) or v.dtype!=np.bool_ or v.shape!=r.shape
            or ((r< -20655)|(r>20655)).any()):
        raise ValueError('Expected four signed H2 residual arrays and boolean validity')
    if mode not in ('B1','M1'):raise ValueError('Unknown fusion mode')
    r=r.astype(np.int32);v=v.copy();q=np.full(r.shape,256,np.int32)
    if mode=='M1':
        q=np.asarray(quality)
        if (q.shape!=r.shape or not np.issubdtype(q.dtype,np.integer) or (q<0).any() or (q>256).any()):
            raise ValueError('Expected Q8 quality from 0 to 256')
        q=q.astype(np.int32);v&=q>0
    yy,xx=np.indices(r.shape[1:]);bits=(1<<np.arange(4,dtype=np.uint8))[:,None,None]
    rawweak=(np.abs(r)>648)&v;rawstrong=(np.abs(r)>1620)&v
    weakbits=np.bitwise_or.reduce(np.where(rawweak,bits,0).astype(np.uint8),axis=0)
    strongbits=np.bitwise_or.reduce(np.where(rawstrong,bits,0).astype(np.uint8),axis=0)
    unknown=~v.any(axis=0)
    if mode=='B1':
        scores=np.where(v,np.abs(r),-1);idx=np.argmax(scores,axis=0)
        selected=r[idx,yy,xx].copy();selected[unknown]=0
        source=(idx+1).astype(np.uint8);source[unknown]=0
        bright=np.maximum(selected,0);dark=np.maximum(-selected,0)
        sb=np.where(bright>0,source,0).astype(np.uint8);sd=np.where(dark>0,source,0).astype(np.uint8)
    else:
        values=[];sources=[]
        for sign in (1,-1):
            magnitude=np.maximum(r*sign,0);eligible=v&(magnitude>0)
            scores=np.where(eligible,magnitude*q,-1);idx=np.argmax(scores,axis=0)
            mag=magnitude[idx,yy,xx].copy();absent=~eligible.any(axis=0);mag[absent]=0
            src=(idx+1).astype(np.uint8);src[absent]=0;values.append(mag);sources.append(src)
        bright,dark=values;sb,sd=sources
        choose_bright=(bright>dark)|((bright==dark)&((sb<sd)|(sd==0)))
        selected=np.where(choose_bright,bright,-dark);source=np.where(choose_bright,sb,sd).astype(np.uint8)
    amplitude=np.maximum(bright,dark)
    connected=hysteresis_connect(amplitude,~unknown,648,1620)
    selected_bits=np.where(bright>648,np.left_shift(1,np.maximum(sb.astype(np.int16)-1,0)),0).astype(np.uint8)
    selected_bits|=np.where(dark>648,np.left_shift(1,np.maximum(sd.astype(np.int16)-1,0)),0).astype(np.uint8)
    return dict(residual_n=selected.astype('<i2'),source_channel=source,polarity=np.sign(selected).astype(np.int8),
        bright_n=bright.astype('<u2'),dark_n=dark.astype('<u2'),source_bright=sb,source_dark=sd,
        weak=connected['weak_mask'],strong=connected['strong_mask'],mask=connected['mask'],unknown=unknown,
        valid_count=v.sum(axis=0).astype(np.uint8),weak_source_bits=weakbits,strong_source_bits=strongbits,
        selected_weak_source_bits=selected_bits)
