"""Seed-independent raw-image line screening, followed by exact profile proof.

Directional mean filters ONLY propose stations. Final evidence must pass the
same actual-frame bilinear profiles and a coherent station track. Review-only.
"""
import math
import cv2
import numpy as np
from evidence import scan_without_seed,distance_to,cutoff
from seeded_gate import profiles

def kernels(length,flank,theta):
    radius=int(math.ceil(length/2+flank+2));size=2*radius+1;t=np.array([math.cos(theta),math.sin(theta)]);n=np.array([-t[1],t[0]]);ks=[np.zeros((size,size),np.float32) for _ in range(3)]
    def add(k,point,weight):
        px,py=np.rint(point*32)/32;x,y=int(math.floor(px)),int(math.floor(py));fx,fy=px-x,py-y
        for dy,dx,w in ((0,0,(1-fx)*(1-fy)),(0,1,fx*(1-fy)),(1,0,(1-fx)*fy),(1,1,fx*fy)):k[y+dy+radius,x+dx+radius]+=weight*w
    for j in range(-(length//2),length//2+1):
        for offset,weight in ((-.5,.25),(0,.5),(.5,.25)):add(ks[0],j*t+offset*n,weight/length)
        add(ks[1],j*t+flank*n,1/length);add(ks[2],j*t-flank*n,1/length)
    return ks,n

def dense_proposals(formal,gray,board,config):
    height,width=board.shape;yy,xx=np.indices(board.shape,dtype='float32');best=np.zeros(board.shape,np.float32);eligible=board&(distance_to(formal)>config['rim_tolerance_px'])
    for orientation in range(8):
        theta=orientation*math.pi/8;ks,n=kernels(config['length'],config['flank'],theta)
        for image in gray:
            image=image.astype('float32',copy=False);center,plus,minus=[cv2.filter2D(image,cv2.CV_32F,k,borderType=cv2.BORDER_REFLECT_101) for k in ks]
            for contrast in (np.minimum(center-plus,center-minus),np.minimum(plus-center,minus-center)):
                positive=cv2.remap(contrast,xx+float(n[0]),yy+float(n[1]),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101);negative=cv2.remap(contrast,xx-float(n[0]),yy-float(n[1]),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
                use=eligible&(contrast>=config['screen_mean'])&(contrast>=positive)&(contrast>=negative);best=np.maximum(best,np.where(use,contrast,0))
    stride=config['grid_stride'];points=[];strength=[]
    for y in range(0,height,stride):
        for x in range(0,width,stride):
            tile=best[y:y+stride,x:x+stride]
            if not tile.any():continue
            dy,dx=np.unravel_index(np.argmax(tile),tile.shape);points.append((x+dx,y+dy));strength.append(float(tile[dy,dx]))
    capacity=len(points)>config['max_proposals'];order=np.argsort(-np.asarray(strength),kind='stable')[:config['max_proposals']]
    return np.asarray(points,dtype=float)[order],dict(proposals_before_capacity=len(points),proposals_tested=len(order),capacity_exceeded=capacity,not_an_automatic_pass=True)

def connect_stations(points,orientation_hits,max_gap,angle):
    count=len(points);parent=np.arange(count);cells={};cell=max_gap;cosine=math.cos(math.radians(angle));vectors=np.array([[math.cos(i*math.pi/8),math.sin(i*math.pi/8)] for i in range(8)])
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=int(parent[i])
        return i
    for i,p in enumerate(points):
        c=(int(p[0]//cell),int(p[1]//cell))
        for dy in (-1,0,1):
            for dx in (-1,0,1):
                for j in cells.get((c[0]+dx,c[1]+dy),[]):
                    delta=p-points[j];distance=float(np.linalg.norm(delta))
                    if not 0<distance<=max_gap:continue
                    alignment=np.abs(vectors@(delta/distance));allowed=alignment>=cosine
                    if (orientation_hits[i]&allowed).any() and (orientation_hits[j]&allowed).any():parent[find(i)]=find(j)
        cells.setdefault(c,[]).append(i)
    clusters={}
    for i in range(count):clusters.setdefault(find(i),[]).append(i)
    return list(clusters.values())

def raw_direct_scan(formal,response,board,gray,valid_frames,plan):
    config=plan['raw_direct_scan'];points,stats=dense_proposals(formal,gray,board,config);evidence=np.zeros_like(formal);rows=[]
    if len(points)==0:return evidence,rows,stats
    chunks=[profiles(points[i:i+2048],gray,valid_frames,board,config['length'],config['flank']) for i in range(0,len(points),2048)];fraction=np.concatenate([v[0] for v in chunks]);means=np.concatenate([v[1] for v in chunks]);good=(fraction>=config['support_fraction'])&(means>=config['mean_contrast']);label=0
    for frame in range(8):
        for polarity in range(2):
            selected=np.flatnonzero(good[:,:,frame,polarity].any(axis=1))
            if len(selected)<config['min_stations']:continue
            xy=points[selected];fits=good[selected,:,frame,polarity]
            for ids in connect_stations(xy,fits,config['max_station_gap'],config['angle_degrees']):
                if len(ids)<config['min_stations']:continue
                track=xy[ids];extent=np.ptp(track,axis=0);span=float(np.linalg.norm(extent))
                if span<config['min_span']:continue
                label+=1;ix=track[:,0].astype(int);iy=track[:,1].astype(int);local_peak=int(response[iy,ix].max(initial=0));evidence[iy,ix]=True;x0,y0=track.min(axis=0).astype(int);x1,y1=track.max(axis=0).astype(int)
                rows.append(dict(label=label,bbox_xywh=[int(x0),int(y0),int(x1-x0+1),int(y1-y0+1)],area=len(ids),two_sweep_span_px=span,line_fraction=None,median_width_proxy_px=None,peak_n=local_peak,has_strong_seed=bool(local_peak>cutoff(plan['unseeded_scan']['strong_reference'])),
                    local_piece_has_strong_seed=bool(local_peak>cutoff(plan['unseeded_scan']['strong_reference'])),global_weak_component_has_seed=None,kind='raw_track_without_sampled_strong_seed' if local_peak<=cutoff(plan['unseeded_scan']['strong_reference']) else 'raw_track_with_sampled_strong_seed',
                    raw_supported=True,raw_fits=[dict(frame=frame+1,direction=frame//2+1,exposure='low' if frame%2==0 else 'high',polarity=1 if polarity==0 else -1,good_stations=len(ids),run_span_px=span)],supported_frames=[frame+1],supported_directions=[frame//2+1],support_station_xy=track.tolist(),evidence_priority='single_direction',screen_is_proposal_only=True,station_graph_not_defect_mask=True))
    # Combine supporting tracks only for review windows, never scratch identity.
    changed=True
    while changed:
        changed=False
        for i in range(len(rows)):
            a=rows[i];aset=set(map(tuple,a['support_station_xy']))
            for j in range(i+1,len(rows)):
                b=rows[j];shared=len(aset&set(map(tuple,b['support_station_xy'])))
                if shared<2:continue
                points2=sorted(aset|set(map(tuple,b['support_station_xy'])));aa=np.asarray(points2);x0,y0=aa.min(0).astype(int);x1,y1=aa.max(0).astype(int)
                a.update(bbox_xywh=[int(x0),int(y0),int(x1-x0+1),int(y1-y0+1)],support_station_xy=[list(p) for p in points2],supported_frames=sorted(set(a['supported_frames']+b['supported_frames'])),supported_directions=sorted(set(a['supported_directions']+b['supported_directions'])),raw_fits=a['raw_fits']+b['raw_fits'],has_strong_seed=a['has_strong_seed'] or b['has_strong_seed'],local_piece_has_strong_seed=a['has_strong_seed'] or b['has_strong_seed'],peak_n=max(a['peak_n'],b['peak_n']))
                a['evidence_priority']='multi_direction' if len(a['supported_directions'])>=2 else 'single_direction';a['kind']='raw_track_with_sampled_strong_seed' if a['has_strong_seed'] else 'raw_track_without_sampled_strong_seed';rows.pop(j);changed=True;break
            if changed:break
    for i,r in enumerate(rows):r['label']=100000+i;r['raw_scan_capacity']=stats
    stats['raw_track_regions']=len(rows);return evidence,rows,stats

def scan_combined(formal,response,valid_fused,board,gray,valid_frames,plan):
    old,rows=scan_without_seed(formal,response,valid_fused,board,gray,valid_frames,plan);dense,new,stats=raw_direct_scan(formal,response,board,gray,valid_frames,plan)
    for row in new:row['source_subtype']='dense_raw_track'
    for row in rows:row['source_subtype']='residual_fragment_track'
    # Capacity warning is not silently converted into evidence of correctness.
    if stats['capacity_exceeded']:
        new.append(dict(label=999999,bbox_xywh=[0,0,board.shape[1],board.shape[0]],raw_supported=True,supported_frames=[],supported_directions=[],support_station_xy=[],evidence_priority='capacity_review',has_strong_seed=False,kind='raw_scan_capacity_review',raw_scan_capacity=stats))
    return old|dense,rows+new
