"""Preserve8/20; replace unconditional6/20 fringes by seeded tip extensions."""
import math,hashlib
import cv2
import numpy as np
from joint_gate import decide
from component_gate import geometry
from fragment_chain import endpoints

def reject_merges(base,piece_mask):
    """Reject entire proposed piece if it joins multiple existing components."""
    _,base_labels=cv2.connectedComponents(base.astype('uint8'),connectivity=8)
    n,labels,stats,_=cv2.connectedComponentsWithStats(piece_mask.astype('uint8'),connectivity=8);accepted=np.zeros_like(base)
    for label in range(1,n):
        x,y,w,h,area=map(int,stats[label]);x0=max(0,x-1);y0=max(0,y-1);x1=min(base.shape[1],x+w+1);y1=min(base.shape[0],y+h+1);piece=labels[y0:y1,x0:x1]==label
        touched=np.unique(base_labels[y0:y1,x0:x1][cv2.dilate(piece.astype('uint8'),np.ones((3,3),'uint8')).astype(bool)]);touched=touched[touched>0]
        if len(touched)<=1:accepted[y0:y1,x0:x1]|=piece
    return accepted

def supplements(cache6,cache_low,config,original):
    a6,_=decide(cache6,config);alo,_=decide(cache_low,config);s6=np.r_[False,a6][cache6['labels']];low=np.r_[False,alo][cache_low['labels']]
    anchor=original|s6;low=reject_merges(anchor,low);base=anchor|low
    return base,anchor,s6,low

def tip_regions(anchor,response,config,reach,half_width,tip_cache=None):
    key=(hashlib.sha256(anchor.tobytes()).digest(),math.floor(81*config['strong']))
    tips=None if tip_cache is None else tip_cache.get(key)
    if tips is None:
        n,labels,stats,_=cv2.connectedComponentsWithStats(anchor.astype('uint8'),connectivity=8);tips=[]
        for label in range(1,n):
            x,y,w,h,area=map(int,stats[label]);piece=labels[y:y+h,x:x+w]==label
            if area<9 or not (response[y:y+h,x:x+w][piece]>81*config['strong']).any():continue
            g=geometry(np.pad(piece,1))
            if g['two_sweep_span_px']<8 or g['line_fraction']<.5:continue
            tips.extend((xy,direction) for xy,direction in endpoints(piece,(x,y)))
        if tip_cache is not None:tip_cache[key]=tips
    allowed=np.zeros_like(anchor)
    for xy,direction in tips:
        x0=max(0,int(math.floor(xy[0]-reach-half_width-1)));x1=min(anchor.shape[1],int(math.ceil(xy[0]+reach+half_width+2)));y0=max(0,int(math.floor(xy[1]-reach-half_width-1)));y1=min(anchor.shape[0],int(math.ceil(xy[1]+reach+half_width+2)))
        yy,xx=np.mgrid[y0:y1,x0:x1];dx=xx-xy[0];dy=yy-xy[1];along=dx*direction[0]+dy*direction[1];lateral=np.abs(-dx*direction[1]+dy*direction[0])
        region=(along>=0)&(along<=reach)&(lateral<=half_width)&(lateral<=1+along*math.tan(math.radians(30)));allowed[y0:y1,x0:x1]|=region
    return allowed,tips

def extend(base,anchor,ordinary,response,config,reach,half_width,tip_cache=None,prepared_base=None):
    allowed,tips=tip_regions(anchor,response,config,reach,half_width,tip_cache);proposed=ordinary&allowed&~base
    if prepared_base is None:
        _,base_labels=cv2.connectedComponents(base.astype('uint8'),connectivity=8);seed_labels=set(np.unique(base_labels[base&(response>81*config['strong'])]).tolist())
    else:base_labels,seed_labels=prepared_base
    n,labels,stats,_=cv2.connectedComponentsWithStats(proposed.astype('uint8'),connectivity=8);extension=np.zeros_like(base)
    for label in range(1,n):
        x,y,w,h,area=map(int,stats[label])
        if area<3 or max(w,h)<2:continue
        x0=max(0,x-1);y0=max(0,y-1);x1=min(base.shape[1],x+w+1);y1=min(base.shape[0],y+h+1);piece=labels[y0:y1,x0:x1]==label
        touched=np.unique(base_labels[y0:y1,x0:x1][cv2.dilate(piece.astype('uint8'),np.ones((3,3),'uint8')).astype(bool)]);touched=touched[touched>0]
        if len(touched)==1 and int(touched[0]) in seed_labels:
            interface=piece&cv2.dilate(base[y0:y1,x0:x1].astype('uint8'),np.ones((3,3),'uint8')).astype(bool);iy,ix=np.nonzero(interface);owned=False
            for xy,direction in tips:
                if base_labels[int(round(xy[1])),int(round(xy[0]))]!=touched[0]:continue
                if len(ix) and np.min((ix+x0-xy[0])**2+(iy+y0-xy[1])**2)<=(half_width+3)**2:owned=True;break
            if owned:extension[y0:y1,x0:x1]|=piece
    candidate=base|extension
    if (candidate&~ordinary).any() or (base&~candidate).any():raise AssertionError('Observed containment failed')
    return dict(candidate=candidate,extension=extension,allowed_tip_regions=allowed,tip_count=len(tips))
