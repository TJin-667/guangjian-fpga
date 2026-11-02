"""Connect evidence about existing fragments; never draw gap pixels into mask."""
import math
import cv2
import numpy as np
from component_gate import thin,geometry

CONFIG=dict(max_endpoint_distance_px=8,outward_angle_degrees=35,tangent_trace_pixels=5,
    raw_flank_offset_px=2.5,raw_two_sided_contrast_min=1.,raw_same_frame_support_fraction=.60,
    min_fragment_area=3,min_fragment_span_px=2,min_local_line_fraction=.35,max_median_width_proxy_px=5,
    independent_chain_min_fragments=3,independent_chain_min_observed_span_px=12,
    gap_pixels_added=False)

def endpoints(mask,origin):
    sk=thin(np.pad(mask,1));coordinates=np.argwhere(sk);answer=[]
    def neighbors(p):
        y,x=p
        return [(y+dy,x+dx) for dy,dx in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)) if 0<=y+dy<sk.shape[0] and 0<=x+dx<sk.shape[1] and sk[y+dy,x+dx]]
    for a in map(tuple,coordinates):
        n=neighbors(a)
        if len(n)!=1:continue
        previous=a;current=n[0];trace=[current]
        for _ in range(CONFIG['tangent_trace_pixels']-1):
            n=[p for p in neighbors(current) if p!=previous]
            if len(n)!=1:break
            previous,current=current,n[0];trace.append(current)
        outward=np.asarray(a,dtype=float)-np.asarray(trace,dtype=float).mean(axis=0);length=np.linalg.norm(outward)
        if length>0:
            xy=np.asarray([a[1]-1+origin[0],a[0]-1+origin[1]],dtype=float);direction=np.asarray([outward[1],outward[0]])/length
            answer.append((xy,direction))
    return answer

def gap_support(a,b,gray,valid,board):
    delta=b-a;distance=np.linalg.norm(delta);normal=np.array([-delta[1],delta[0]])/distance
    t=np.linspace(0,1,max(3,int(math.ceil(distance))+1));center=a[None,:]+t[:,None]*delta
    positions=[center,center+CONFIG['raw_flank_offset_px']*normal,center-CONFIG['raw_flank_offset_px']*normal]
    best=dict(fraction=0.,frame=0,polarity=0,sample_positions=len(t))
    h,w=board.shape
    for i,image in enumerate(gray):
        allowed=True
        for points in positions:
            x=np.floor(points[:,0]).astype(int);y=np.floor(points[:,1]).astype(int)
            if (x<0).any() or (y<0).any() or (x+1>=w).any() or (y+1>=h).any():allowed=False;break
            for dy,dx in ((0,0),(0,1),(1,0),(1,1)):
                if not np.all(valid[i,y+dy,x+dx]&board[y+dy,x+dx]):allowed=False;break
            if not allowed:break
        if not allowed:continue
        samples=[cv2.remap(image.astype('float32',copy=False),points[:,0].astype('float32')[None,:],points[:,1].astype('float32')[None,:],cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT).ravel() for points in positions]
        c,p,m=samples;bright=np.minimum(c-p,c-m);dark=np.minimum(p-c,m-c)
        for sign,v in ((1,bright),(-1,dark)):
            fraction=float(np.mean(v>=CONFIG['raw_two_sided_contrast_min']))
            if fraction>best['fraction']:best=dict(fraction=fraction,frame=i+1,polarity=sign,sample_positions=len(t))
    return best

def chain(protected,loose,base_supplement,gray,valid,board):
    if gray.shape!=(8,*board.shape) or valid.shape!=gray.shape:raise ValueError('Actual eight gray/valid planes required')
    gray=gray.astype('float32',copy=False)
    n,labels,stats,_=cv2.connectedComponentsWithStats(loose.astype('uint8'),connectivity=8)
    nodes=[];tips=[]
    for label in range(1,n):
        x,y,w,h,area=map(int,stats[label]);piece=labels[y:y+h,x:x+w]==label;core=bool((protected[y:y+h,x:x+w]&piece).any());primary=core or bool((base_supplement[y:y+h,x:x+w]&piece).any())
        g=geometry(np.pad(piece,1));eligible=core or (area>=CONFIG['min_fragment_area'] and g['two_sweep_span_px']>=CONFIG['min_fragment_span_px'] and g['line_fraction']>=CONFIG['min_local_line_fraction'] and g['median_width_proxy_px']<=CONFIG['max_median_width_proxy_px'])
        nodes.append(dict(label=label,core=core,primary=primary,eligible=eligible,**g))
        if eligible:
            for xy,direction in endpoints(piece,(x,y)):tips.append((label,xy,direction))
    cosine=math.cos(math.radians(CONFIG['outward_angle_degrees']));edges=[];positions=np.asarray([t[1] for t in tips]);maximum=CONFIG['max_endpoint_distance_px']
    for j,(la,a,out_a) in enumerate(tips):
        distance=np.linalg.norm(positions-a,axis=1)
        for k in np.flatnonzero((distance>0)&(distance<=maximum)):
            if k<=j:continue
            lb,b,out_b=tips[k]
            if la==lb or (nodes[la-1]['core'] and nodes[lb-1]['core']):continue
            u=(b-a)/distance[k]
            if np.dot(out_a,u)<cosine or np.dot(out_b,-u)<cosine:continue
            photo=gap_support(a,b,gray,valid,board)
            edges.append(dict(a=la,b=lb,a_xy=a.tolist(),b_xy=b.tolist(),distance_px=float(distance[k]),raw_evidence=photo,raw_pass=photo['fraction']>=CONFIG['raw_same_frame_support_fraction']))
    result={}
    for mode,require_raw in (('chain_geom',False),('chain_raw',True)):
        parent=np.arange(n,dtype=int)
        def find(a):
            while parent[a]!=a:parent[a]=parent[parent[a]];a=int(parent[a])
            return a
        for edge in edges:
            if not require_raw or edge['raw_pass']:
                a,b=find(edge['a']),find(edge['b']);parent[b]=a
        clusters={}
        for node in nodes:clusters.setdefault(find(node['label']),[]).append(node)
        admitted=set();reports=[]
        for root,members in clusters.items():
            primary=any(m['primary'] for m in members);eligible=[m for m in members if m['eligible'] and not m['core']]
            observed=sum(m['two_sweep_span_px'] for m in eligible)
            independent=len(eligible)>=CONFIG['independent_chain_min_fragments'] and observed>=CONFIG['independent_chain_min_observed_span_px']
            if primary or independent:admitted.update(m['label'] for m in eligible)
            reports.append(dict(component_labels=[m['label'] for m in members],primary_anchor=primary,independent_chain=independent,observed_fragment_span_px=observed))
        new=loose&~protected;supplement=(np.isin(labels,list(admitted))&new)|base_supplement;candidate=protected|supplement;review=new&~supplement
        if (protected&~candidate).any() or (candidate&~loose).any() or not np.array_equal(supplement|review,new):raise AssertionError('Chain partition failed')
        result[mode]=dict(candidate=candidate,line_supplement=supplement,review=review)
        if require_raw and (candidate&~result['chain_geom']['candidate']).any():raise AssertionError('Raw-evidence links added a component absent from geometric links')
        result[mode]['clusters']=reports
    return result,dict(config=CONFIG,nodes=nodes,edges=edges,geometry_edges=len(edges),raw_supported_edges=sum(e['raw_pass'] for e in edges))
