"""Bound sideways growth by6/20, preserve original8/20 and prevent new merges."""
import cv2
import numpy as np
from joint_gate import geometry

def prepare(original,guide,response):
    n,labels,stats,_=cv2.connectedComponentsWithStats(original.astype('uint8'),connectivity=8);reliable=np.zeros(n,bool)
    for label in range(1,n):
        x,y,w,h,area=map(int,stats[label]);piece=labels[y:y+h,x:x+w]==label
        if area<9:continue
        g=geometry(np.pad(piece,1))
        reliable[label]=g['two_sweep_span_px']>=8 and g['line_fraction']>=.5
    # Pixel labels map nearest-zero pixels back to connected original structures.
    inverse=(~original).astype('uint8');distance=cv2.distanceTransform(inverse,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
    _,pixel_labels=cv2.distanceTransformWithLabels(inverse,cv2.DIST_L2,5,labelType=cv2.DIST_LABEL_PIXEL)
    lookup=np.zeros(int(pixel_labels.max())+1,np.int32);lookup[pixel_labels[original]]=labels[original];owner=lookup[pixel_labels]
    return dict(original=original,guide=guide,response=response,distance=distance,owner=owner,original_labels=labels,reliable=reliable)

def apply(base,prepared,radius,strong):
    original=prepared['original'];guide=prepared['guide'];owner=prepared['owner'];reliable=prepared['reliable']
    if radius==0:return dict(candidate=base.copy(),side_addition=np.zeros_like(base),side_envelope=np.zeros_like(base))
    side_envelope=guide&~original&(prepared['distance']<=radius)&reliable[owner]
    _,base_labels=cv2.connectedComponents(base.astype('uint8'),connectivity=8);mapping=np.zeros(len(reliable),np.int32);ol=prepared['original_labels'];mapping[ol[original]]=base_labels[original]
    proposals=side_envelope&~base;colors=base_labels.copy();colors[proposals]=mapping[owner[proposals]];padded=np.pad(colors,1);conflict=np.zeros_like(base)
    for dy,dx in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
        neighbor=padded[1+dy:1+dy+base.shape[0],1+dx:1+dx+base.shape[1]];conflict|=proposals&(neighbor>0)&(neighbor!=colors)
    proposals&=~conflict;n,labels,stats,_=cv2.connectedComponentsWithStats(proposals.astype('uint8'),connectivity=8);added=np.zeros_like(base)
    seeded=set(np.unique(base_labels[base&(prepared['response']>81*strong)]).tolist())
    for label in range(1,n):
        x,y,w,h,area=map(int,stats[label]);x0=max(0,x-1);y0=max(0,y-1);x1=min(base.shape[1],x+w+1);y1=min(base.shape[0],y+h+1);piece=labels[y0:y1,x0:x1]==label
        neighbors=cv2.dilate(piece.astype('uint8'),np.ones((3,3),'uint8')).astype(bool);touched=np.unique(base_labels[y0:y1,x0:x1][neighbors]);touched=touched[touched>0]
        if len(touched)==1 and int(touched[0]) in seeded:added[y0:y1,x0:x1]|=piece
    if (added&~guide).any() or (original&~(base|added)).any():raise AssertionError('Side envelope / original protection failed')
    return dict(candidate=base|added,side_addition=added,side_envelope=side_envelope)
