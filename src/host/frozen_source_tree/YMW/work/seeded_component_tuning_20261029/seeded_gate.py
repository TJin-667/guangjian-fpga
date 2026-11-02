"""Offline seeded component admission. Inference has no label or sample input.

The fixed weak graph determines all output pixels. Geometry and raw profiles
admit whole existing pieces only; no dilation, painted links or new weak pixels.
Unseeded lines cannot enter the supplement, regardless of their raw appearance.
"""
import math
import sys
from pathlib import Path
import cv2
import numpy as np

PARENT = Path(__file__).resolve().parent.parent / 'weak_component_experiment_20261029'
sys.path.insert(0, str(PARENT))
from component_gate import geometry
from fragment_chain import endpoints, gap_support

CHAIN = {
    'off': None,
    'tight': dict(distance=4., angle=25., raw_fraction=.75),
    'previous': dict(distance=8., angle=35., raw_fraction=.60),
}

def profiles(centers, gray, valid, board, length=13, flank=3.):
    """All 8x8x2 fits, batched over components; never only a prior best fit.

    Means and fractions refer to one actual observation, one orientation and
    one polarity. All four interpolation neighbors must be valid and on board.
    """
    n=len(centers);fraction=np.zeros((n,8,8,2),np.float32);mean=np.full_like(fraction,-1e6)
    if not n:return fraction,mean
    if length<3 or length%2!=1:raise ValueError('Odd profile length >=3 required')
    h,w=board.shape;gray=gray.astype('float32',copy=False)
    for orientation in range(8):
        theta=orientation*math.pi/8;t=np.array([math.cos(theta),math.sin(theta)]);normal=np.array([-t[1],t[0]])
        base=np.asarray(centers)[:,None,:]+np.arange(-(length//2),length//2+1)[None,:,None]*t
        paths=[base+offset*normal for offset in (-.5,0,.5,flank,-flank)]
        maps=[(p[:,:,0].astype('float32'),p[:,:,1].astype('float32')) for p in paths]
        indices=[];inside=np.ones(n,bool)
        for p in paths:
            x=np.floor(p[:,:,0]).astype(int);y=np.floor(p[:,:,1]).astype(int)
            inside&=((x>=0)&(y>=0)&(x+1<w)&(y+1<h)).all(axis=1)
            indices.append((np.clip(y,0,h-2),np.clip(x,0,w-2)))
        for frame in range(8):
            allowed=inside.copy()
            for y,x in indices:
                for dy,dx in ((0,0),(0,1),(1,0),(1,1)):
                    allowed&=(valid[frame,y+dy,x+dx]&board[y+dy,x+dx]).all(axis=1)
            values=[cv2.remap(gray[frame],x,y,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT) for x,y in maps]
            c=.25*values[0]+.5*values[1]+.25*values[2];p,m=values[3:]
            for polarity,contrast in enumerate((np.minimum(c-p,c-m),np.minimum(p-c,m-c))):
                fraction[:,orientation,frame,polarity]=np.where(allowed,(contrast>=1.).mean(axis=1),0)
                mean[:,orientation,frame,polarity]=np.where(allowed,contrast.mean(axis=1),-1e6)
    return fraction,mean

def build(response, valid_fused, board, protected, loose, gray, valid_frames, *, profile_variants=((13,3.),)):
    if response.shape!=board.shape or gray.shape!=(8,*board.shape) or valid_frames.shape!=gray.shape:raise ValueError('Eight native gray/valid planes required')
    if (protected&~loose).any():raise ValueError('Protected must be subset of loose')
    new=loose&~protected
    n,labels,stats,centers=cv2.connectedComponentsWithStats(new.astype('uint8'),connectivity=8)
    rows=[];tips=[]
    for label in range(1,n):
        x,y,w,h,area=map(int,stats[label]);piece=labels[y:y+h,x:x+w]==label
        g=geometry(np.pad(piece,1));peak=int(response[y:y+h,x:x+w][piece&valid_fused[y:y+h,x:x+w]].max(initial=0))
        rows.append(dict(label=label,bbox_xywh=[x,y,w,h],centroid_xy=centers[label].tolist(),peak_n=peak,**g))
        if area>=3 and g['two_sweep_span_px']>=2 and g['line_fraction']>=.35 and g['median_width_proxy_px']<=5:
            tips.extend((label-1,xy,direction) for xy,direction in endpoints(piece,(x,y)))
    # Include protected anchors in the relation graph, never alter their pixels.
    core_n,core_labels,core_stats,_=cv2.connectedComponentsWithStats(protected.astype('uint8'),connectivity=8)
    for core_label in range(1,core_n):
        x,y,w,h,area=map(int,core_stats[core_label])
        if area<3:continue
        piece=core_labels[y:y+h,x:x+w]==core_label
        tips.extend((-core_label,xy,direction) for xy,direction in endpoints(piece,(x,y)))
    edges=[];positions=np.asarray([t[1] for t in tips]);gray=gray.astype('float32',copy=False)
    for j,(a,pa,da) in enumerate(tips):
        distances=np.linalg.norm(positions-pa,axis=1)
        for k in np.flatnonzero((distances>0)&(distances<=8)):
            if k<=j:continue
            b,pb,db=tips[k]
            if a==b or (a<0 and b<0):continue
            u=(pb-pa)/distances[k];facing=min(float(da@u),float(db@-u))
            if facing<math.cos(math.radians(35)):continue
            photo=gap_support(pa,pb,gray,valid_frames,board)
            edges.append(dict(a=a,b=b,distance=float(distances[k]),facing=facing,raw_fraction=photo['fraction']))
    fits={}
    for length,flank in profile_variants:fits[f'{length}/{flank:g}']=profiles(centers[1:],gray,valid_frames,board,length,flank)
    return dict(labels=labels,rows=rows,edges=edges,profiles=fits,protected=protected,loose=loose,board=board)

def choose(cache,config):
    rows=cache['rows'];n=len(rows)
    if not n:return np.zeros(0,bool),dict(geometry=0,raw=0,chain=0)
    area=np.array([r['area'] for r in rows]);span=np.array([r['two_sweep_span_px'] for r in rows]);line=np.array([r['line_fraction'] for r in rows]);width=np.array([r['median_width_proxy_px'] for r in rows]);peak=np.array([r['peak_n'] for r in rows])
    # This check is shared by ALL formal admission routes, including raw-only.
    seeded=peak>81*config['strong'];base=seeded&(area>=config['min_area'])&(width<=config['width'])
    geometry_ok=base&(span>=config['span'])&(line>=config['line'])
    key=f"{config['length']}/{config['flank']:g}";fraction,mean=cache['profiles'][key]
    raw_ok=base&((fraction>=config['raw_fraction'])&(mean>=config['raw_mean'])).any(axis=(1,2,3))
    admitted=geometry_ok.copy();chain_config=CHAIN[config['chain']]
    if chain_config is not None:
        eligible=base&(span>=2)&(line>=.35);links={i:set() for i in range(n)};frontier=set(np.flatnonzero(geometry_ok).tolist())
        for edge in cache['edges']:
            a,b=edge['a'],edge['b']
            if edge['distance']>chain_config['distance'] or edge['facing']<math.cos(math.radians(chain_config['angle'])) or edge['raw_fraction']<chain_config['raw_fraction']:continue
            if a>=0 and not eligible[a] or b>=0 and not eligible[b]:continue
            if a<0:frontier.add(b)
            elif b<0:frontier.add(a)
            else:links[a].add(b);links[b].add(a)
        # Only reachability from a protected/geometry anchor; no independent chains.
        reached=set(frontier);queue=list(frontier)
        while queue:
            for b in links[queue.pop()]-reached:reached.add(b);queue.append(b)
        if reached:admitted[list(reached)]=True
    chained=admitted&~geometry_ok;admitted|=raw_ok
    if (admitted&~seeded).any():raise AssertionError('Unseeded component entered formal supplement')
    return admitted,dict(geometry=int(geometry_ok.sum()),raw=int(raw_ok.sum()),chain=int(chained.sum()))

def masks(cache,config):
    admitted,routes=choose(cache,config);lookup=np.r_[False,admitted];added=lookup[cache['labels']]
    candidate=cache['protected']|added;review=cache['loose']&~candidate
    if (candidate&~cache['loose']).any() or (cache['protected']&~candidate).any():raise AssertionError('Mask containment failed')
    if (added&cv2.dilate(cache['protected'].astype('uint8'),np.ones((3,3),'uint8')).astype(bool)).any():raise AssertionError('Addition touches protected block')
    return dict(candidate=candidate,supplement=added,review=review),routes
