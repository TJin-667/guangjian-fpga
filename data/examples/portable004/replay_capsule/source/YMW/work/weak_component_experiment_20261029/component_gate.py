"""Experimental admission of newly seeded weak components, never old removal.

Inputs are image evidence only. No annotation, sample ID or filesystem access.
Geometry is used to route additions to line supplements or retained review.
The emitted shapes remain actual input pixels; skeletons are diagnostic only.
"""
import heapq,math
import cv2
import numpy as np

PRESETS={
    'size3':dict(min_area=3,min_span=0,min_line_fraction=0,max_median_width=None),
    'line6':dict(min_area=3,min_span=6,min_line_fraction=.50,max_median_width=5),
    'line10':dict(min_area=3,min_span=10,min_line_fraction=.60,max_median_width=5),
    'line14':dict(min_area=3,min_span=14,min_line_fraction=.70,max_median_width=5),
}

def thin(mask):
    """Zhang-Suen two-subiteration thinning; never used as output width."""
    z=np.pad(np.asarray(mask,dtype=bool),1)
    for iteration in range(2*max(z.shape)+2):
        changed=False
        for step in (0,1):
            n=[z[:-2,1:-1],z[:-2,2:],z[1:-1,2:],z[2:,2:],z[2:,1:-1],z[2:,:-2],z[1:-1,:-2],z[:-2,:-2]]
            count=sum(x.astype('uint8') for x in n)
            transitions=sum((~n[i]&n[(i+1)%8]).astype('uint8') for i in range(8))
            if step==0:a=~(n[0]&n[2]&n[4]);b=~(n[2]&n[4]&n[6])
            else:a=~(n[0]&n[2]&n[6]);b=~(n[0]&n[4]&n[6])
            remove=z[1:-1,1:-1]&(count>=2)&(count<=6)&(transitions==1)&a&b
            if remove.any():z[1:-1,1:-1][remove]=False;changed=True
        if not changed:return z[1:-1,1:-1].copy()
    raise RuntimeError('Thinning failed to converge')

def geodesic_span(skeleton):
    """Maximum two-sweep shortest-path span over actual skeleton components.

    Two-sweep span is a descriptor, not exact longest path on a cyclic graph.
    No geometric gap bridging is permitted.
    """
    points=[tuple(v) for v in np.argwhere(skeleton)];remaining=set(points);largest=0.;parts=0
    def distances(start):
        distance={start:0.};queue=[(0.,start)]
        while queue:
            cost,(y,x)=heapq.heappop(queue)
            if cost!=distance[y,x]:continue
            for dy,dx in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
                p=(y+dy,x+dx)
                if 0<=p[0]<skeleton.shape[0] and 0<=p[1]<skeleton.shape[1] and skeleton[p]:
                    candidate=cost+(math.sqrt(2) if dy and dx else 1.)
                    if candidate<distance.get(p,float('inf')):distance[p]=candidate;heapq.heappush(queue,(candidate,p))
        return distance
    while remaining:
        start=min(remaining);first=distances(start);remaining.difference_update(first);parts+=1
        farthest=max(first,key=first.get);largest=max(largest,max(distances(farthest).values()))
    return largest,parts

def geometry(mask):
    a=np.asarray(mask,dtype=bool);skeleton=thin(a);span,parts=geodesic_span(skeleton);s=skeleton.astype('float32')
    yy,xx=np.mgrid[-3:4,-3:4].astype('float32');ones=np.ones((7,7),'float32')
    f=lambda k:cv2.filter2D(s,cv2.CV_32F,k,borderType=cv2.BORDER_CONSTANT)
    count=f(ones);den=np.maximum(count,1);mx,my=f(xx)/den,f(yy)/den
    vx,vy=np.maximum(f(xx*xx)/den-mx*mx,0),np.maximum(f(yy*yy)/den-my*my,0);cov=f(xx*yy)/den-mx*my
    coherence=np.sqrt((vx-vy)**2+4*cov**2)/(vx+vy+1e-6);coherence[count<3]=0
    distance=cv2.distanceTransform(a.astype('uint8'),cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
    widths=np.maximum(1,2*distance[skeleton]-1)
    return dict(area=int(a.sum()),skeleton_pixels=int(skeleton.sum()),skeleton_parts=parts,two_sweep_span_px=float(span),
        line_fraction=float(np.mean(coherence[skeleton]>=.55)) if skeleton.any() else 0.,
        median_width_proxy_px=float(np.median(widths)) if len(widths) else 0.)

def accept(features,preset):
    reasons=[]
    if features['area']<preset['min_area']:reasons.append('too_few_pixels')
    if features.get('board_strong12_pixels',1)==0:reasons.append('no_strong_seed_inside_board_piece')
    if features['two_sweep_span_px']<preset['min_span']:reasons.append('short_geodesic_span')
    if features['line_fraction']<preset['min_line_fraction']:reasons.append('low_local_line_continuity')
    if preset['max_median_width'] is not None and features['median_width_proxy_px']>preset['max_median_width']:reasons.append('broad_component')
    return not reasons,reasons

def partition(protected,loose,strong12,*,residuals=None,valid=None):
    protected=np.asarray(protected);loose=np.asarray(loose);strong12=np.asarray(strong12)
    if protected.dtype!=bool or loose.dtype!=bool or strong12.dtype!=bool or protected.shape!=loose.shape or loose.shape!=strong12.shape or (protected&~loose).any():raise ValueError('Nested boolean native masks required')
    new=loose&~protected;n,labels,stats,_=cv2.connectedComponentsWithStats(new.astype('uint8'),connectivity=8)
    accepted={name:np.zeros_like(new) for name in PRESETS};rows=[]
    for label in range(1,n):
        x,y,w,h,area=map(int,stats[label]);piece=labels[y:y+h,x:x+w]==label;g=geometry(np.pad(piece,1));g.update(component=label,bbox_xywh=[x,y,w,h],board_strong12_pixels=int((strong12[y:y+h,x:x+w]&piece).sum()))
        if residuals is not None:
            r=np.abs(np.asarray(residuals)[:,y:y+h,x:x+w].astype('int32'));v=np.asarray(valid)[:,y:y+h,x:x+w]
            support=((r>486)&v).reshape(4,2,h,w).any(axis=1);direction_count=support.sum(axis=0)
            g['direction_support_pixels']=[int((support[i]&piece).sum()) for i in range(4)];g['multi_direction_fraction']=float(np.mean(direction_count[piece]>=2))
        g['decisions']={}
        for name,preset in PRESETS.items():
            okay,reasons=accept(g,preset);g['decisions'][name]=dict(line_supplement=okay,review_reasons=reasons)
            if okay:accepted[name][y:y+h,x:x+w]|=piece
        rows.append(g)
    result={}
    for name,added in accepted.items():
        review=new&~added;candidate=protected|added
        if (protected&~candidate).any() or (candidate&~loose).any() or (added&review).any() or not np.array_equal(added|review,new):raise AssertionError('Partition contract failed')
        if (added&cv2.dilate(protected.astype('uint8'),np.ones((3,3),'uint8')).astype(bool)).any():raise AssertionError('Fixed weak graph admitted a pixel adjacent to a protected component')
        result[name]=dict(candidate=candidate,line_supplement=added,review=review)
    return result,rows
