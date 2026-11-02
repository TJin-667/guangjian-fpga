"""Joint weak/strong thresholds with fixed or moving protected structures.

No annotation, specimen ID, model weight, network or file input in inference.
The fixed policy rejects whole new board pieces touching the6/20 reference;
it does not trim a connector and then admit disconnected unseeded remnants.
"""
import math,sys
from pathlib import Path
import cv2
import numpy as np

LIB=Path(__file__).resolve().parent.parent/'seeded_component_tuning_20261029'
sys.path.insert(0,str(LIB))
from seeded_gate import profiles,choose
from component_gate import geometry,thin

def cutoff(weak):
    value=float(weak)
    if not math.isfinite(value) or value<0:raise ValueError('Finite nonnegative threshold required')
    return math.floor(81*value)

def build_cache(response,valid,board,reference,weak_protected,ordinary14,gray,valid_frames,*,policy):
    if gray.shape!=(8,*board.shape) or valid_frames.shape!=gray.shape:raise ValueError('Eight actual observations required')
    core=weak_protected if policy=='same_weak20' else reference if policy=='fixed6_20_isolated_supplements' else None
    if core is None:raise ValueError('Unknown protection policy')
    if (core&~ordinary14).any() or (reference&~core).any():raise ValueError('Non-nested thresholds')
    delta=ordinary14&~core;n,labels,stats,centers=cv2.connectedComponentsWithStats(delta.astype('uint8'),connectivity=8)
    touches=np.zeros(n,bool);near=cv2.dilate(reference.astype('uint8'),np.ones((3,3),'uint8')).astype(bool)
    touches[np.unique(labels[near&delta])]=True;touches[0]=False
    excluded=touches[labels]&delta if policy=='fixed6_20_isolated_supplements' else np.zeros_like(board)
    eligible=delta&~excluded;n,labels,stats,centers=cv2.connectedComponentsWithStats(eligible.astype('uint8'),connectivity=8)
    rows=[]
    for label in range(1,n):
        x,y,w,h,area=map(int,stats[label]);piece=labels[y:y+h,x:x+w]==label;padded=np.pad(piece,1);g=geometry(padded);sk=thin(padded)
        ring=[sk[:-2,1:-1],sk[:-2,2:],sk[1:-1,2:],sk[2:,2:],sk[2:,1:-1],sk[2:,:-2],sk[1:-1,:-2],sk[:-2,:-2]]
        transitions=sum((~ring[i]&ring[(i+1)%8]).astype('uint8') for i in range(8));junction=sk[1:-1,1:-1]&(transitions>=3)
        branches=int(cv2.connectedComponents(junction.astype('uint8'),connectivity=8)[0]-1)
        peak=int(response[y:y+h,x:x+w][piece&valid[y:y+h,x:x+w]].max(initial=0))
        rows.append(dict(label=label,bbox_xywh=[x,y,w,h],centroid_xy=centers[label].tolist(),peak_n=peak,branch_clusters=branches,**g))
    fraction,mean=profiles(centers[1:],gray,valid_frames,board,13,2.5)
    return dict(labels=labels,rows=rows,edges=[],profiles={'13/2.5':(fraction,mean)},protected=core,reference=reference,ordinary14=ordinary14,loose=core|eligible,board=board,policy=policy,rejected_attached=excluded)

def decide(cache,config):
    # Existing geometry/profile code is retained unchanged; chain stays disabled.
    admitted,routes=choose(cache,{**config,'chain':'off','length':13,'flank':2.5});return admitted,routes

def output(cache,config):
    admitted,routes=decide(cache,config);extra=np.r_[False,admitted][cache['labels']];mask=cache['protected']|extra
    if (cache['reference']&~mask).any() or (mask&~cache['ordinary14']).any():raise AssertionError('Containment failed')
    if cache['policy']=='fixed6_20_isolated_supplements' and (extra&cv2.dilate(cache['reference'].astype('uint8'),np.ones((3,3),'uint8')).astype(bool)).any():raise AssertionError('Attached supplement slipped through')
    peak=np.array([0]+[r['peak_n'] for r in cache['rows']]);need_seed=extra&~(peak[cache['labels']]>81*config['strong'])
    if need_seed.any():raise AssertionError('Actual strict seed absent')
    review=cache['ordinary14']&~mask
    return dict(candidate=mask,supplement=mask&~cache['reference'],filtered_supplement=extra,review=review,rejected_attached=cache['rejected_attached']),routes
