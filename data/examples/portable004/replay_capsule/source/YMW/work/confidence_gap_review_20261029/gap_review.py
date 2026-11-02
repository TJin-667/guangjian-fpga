"""Review detected-fragment gaps and local station shape; never augment detection."""
import hashlib,math,sys
from pathlib import Path
import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'confidence_shadow_review_20261029'))
from evidence import fragments,thin

N8=((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1))

def longest_true(values):
    best=current=0
    for value in values:
        current=current+1 if value else 0;best=max(best,current)
    return best

def local_shape(points,config):
    """Local point-cloud descriptors allow curved/closed lines, not just global PCA."""
    xy=np.unique(np.asarray(points,float).reshape(-1,2),axis=0);n=len(xy)
    if not n:return dict(stations=0,span_px=0.,local_good_fraction=0.,median_width_proxy_px=None,shape_class='insufficient_shape_evidence')
    span=float(np.linalg.norm(np.ptp(xy,axis=0)));good=[];widths=[]
    cells={};radius=config['radius']
    for i,p in enumerate(xy):cells.setdefault(tuple(np.floor(p/radius).astype(int)),[]).append(i)
    for p in xy:
        cell=np.floor(p/radius).astype(int);ids=[j for dy in (-1,0,1) for dx in (-1,0,1) for j in cells.get((cell[0]+dx,cell[1]+dy),[])];near=xy[ids];near=near[np.linalg.norm(near-p,axis=1)<=radius]
        if len(near)<config['min_local_neighbors']:continue
        eigen=np.linalg.eigvalsh(np.cov(near.T,bias=True));coherence=float(1-eigen[0]/max(eigen[1],1e-8));width=float(4*math.sqrt(max(0,eigen[0])));good.append(coherence>=config['local_coherence']);widths.append(width)
    fraction=float(np.mean(good)) if good else 0.;width=float(np.median(widths)) if widths else None
    passed=n>=config['min_stations'] and span>=config['min_span'] and fraction>=config['min_good_fraction'] and width is not None and width<=config['max_median_width_proxy']
    return dict(stations=n,span_px=span,local_windows=len(good),local_good_fraction=fraction,median_width_proxy_px=width,shape_class='locally_line_like' if passed else 'shape_ambiguous',width_is_station_geometry_not_physical=True)

def endpoint_proposals(formal,config):
    labels,rows=fragments(formal,min_area=config['min_component_area']);tips=[]
    for row in rows:
        if row['two_sweep_span_px']<config['min_component_span'] or row['median_width_proxy_px']>config['max_component_width'] or row['line_fraction']<config['min_local_line_fraction']:continue
        x,y,w,h=row['bbox_xywh'];sk=thin(np.pad(labels[y:y+h,x:x+w]==row['label'],1))
        def neighbors(p):
            return [(p[0]+dy,p[1]+dx) for dy,dx in N8 if 0<=p[0]+dy<sk.shape[0] and 0<=p[1]+dx<sk.shape[1] and sk[p[0]+dy,p[1]+dx]]
        for p in map(tuple,np.argwhere(sk)):
            ns=neighbors(p)
            if len(ns)!=1:continue
            trace=[p];previous=p;current=ns[0]
            for _ in range(config['trace_steps']):
                trace.append(current);ns=[v for v in neighbors(current) if v!=previous]
                if len(ns)!=1:break
                previous,current=current,ns[0]
            if len(trace)<3 or np.linalg.norm(np.asarray(trace[-1])-p)<config['min_trace_span']:continue
            outward=np.asarray(p,float)-np.mean(trace[1:],axis=0);length=float(np.linalg.norm(outward))
            if not length:continue
            tips.append(dict(component=row['label'],xy=[float(p[1]-1+x),float(p[0]-1+y)],outward_xy=[float(outward[1]/length),float(outward[0]/length)],trace_span_px=float(np.linalg.norm(np.asarray(trace[-1])-p))))
    pairs=[];cosine=math.cos(math.radians(config['facing_angle_degrees']))
    points=np.array([t['xy'] for t in tips]);vectors=np.array([t['outward_xy'] for t in tips])
    for i,a in enumerate(tips):
        distances=np.linalg.norm(points-points[i],axis=1)
        for j in np.flatnonzero((distances>=config['min_distance'])&(distances<=config['max_distance'])):
            if j<=i:continue
            # The same component can have an open-loop gap; do not forbid it.
            unit=(points[j]-points[i])/distances[j];facing=min(float(vectors[i]@unit),float(vectors[j]@-unit))
            if facing<cosine:continue
            pairs.append(dict(a=a,b=tips[j],distance_px=float(distances[j]),facing_cosine=facing))
    if len(pairs)>config['max_pairs']:raise RuntimeError('GAP_ANALYSIS_CAPACITY: do not silently drop weak proposals')
    return tips,pairs

def probe_path(pair,kind):
    a=np.asarray(pair['a']['xy']);b=np.asarray(pair['b']['xy']);distance=np.linalg.norm(b-a);t=np.linspace(0,1,max(8,int(math.ceil(distance*2))+1))[:,None]
    if kind=='straight':p=a+(b-a)*t
    else:
        m0=distance*np.asarray(pair['a']['outward_xy']);m1=-distance*np.asarray(pair['b']['outward_xy']);p=(2*t**3-3*t**2+1)*a+(t**3-2*t**2+t)*m0+(-2*t**3+3*t**2)*b+(t**3-t**2)*m1
    arclength=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))];s=np.linspace(0,arclength[-1],int(math.ceil(arclength[-1]))+1)
    return np.stack([np.interp(s,arclength,p[:,axis]) for axis in (0,1)],axis=1)

def bilinear(image,points):
    return cv2.remap(image.astype('float32',copy=False),points[:,0].astype('float32')[None,:],points[:,1].astype('float32')[None,:],cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT).ravel()

def allowed_samples(points,valid,board):
    h,w=board.shape;x=np.floor(points[:,0]).astype(int);y=np.floor(points[:,1]).astype(int);inside=(x>=0)&(y>=0)&(x+1<w)&(y+1<h);x=np.clip(x,0,w-2);y=np.clip(y,0,h-2)
    for dy,dx in ((0,0),(0,1),(1,0),(1,1)):inside&=valid[y+dy,x+dx]&board[y+dy,x+dx]
    return inside

def evaluate_probe(formal,gray,valid,board,residual,path,config,kind):
    """Statistics use only actual missing native samples, never the endpoints."""
    h,w=board.shape;native=np.rint(path).astype(int);native[:,0]=np.clip(native[:,0],0,w-1);native[:,1]=np.clip(native[:,1],0,h-1);keep=np.r_[True,np.any(np.diff(native,axis=0),axis=1)];path=path[keep];native=native[keep];xx,yy=native.T;missing=~formal[yy,xx];n=int(missing.sum())
    if n<config['min_missing_samples'] or missing.mean()<config['min_missing_fraction']:return None
    tangent=np.gradient(path,axis=0);tangent/=np.maximum(np.linalg.norm(tangent,axis=1)[:,None],1e-6);normal=np.stack([-tangent[:,1],tangent[:,0]],axis=1);positions=[path+offset*normal for offset in (-.5,0,.5,config['profile_flank'],-config['profile_flank'])];fits=[]
    for frame in range(8):
        allowed=np.logical_and.reduce([allowed_samples(p,valid[frame],board) for p in positions])&valid[frame,yy,xx]&board[yy,xx];samples=[bilinear(gray[frame],p) for p in positions];center=.25*samples[0]+.5*samples[1]+.25*samples[2];plus,minus=samples[3:]
        for polarity,contrast in ((1,np.minimum(center-plus,center-minus)),(-1,np.minimum(plus-center,minus-center))):
            q=polarity*residual[frame,yy,xx].astype('float64')/81;raw=(contrast>=config['raw_contrast'])&allowed;response=(q>config['detail_weak'])&allowed;baseline=(q>config['baseline_weak'])&allowed;fraction=lambda mask:float((mask&missing).sum()/n);curve=[dict(weak=level,supported_missing=int(((q>level)&allowed&missing).sum()),fraction=fraction((q>level)&allowed),longest_unsupported_missing=longest_true(missing&~((q>level)&allowed))) for level in config['thresholds']]
            raw_fraction=fraction(raw);low=fraction(response);high=fraction(baseline);joint=fraction(raw&response);longest=longest_true(missing&~raw);valid_fraction=fraction(allowed);coherent=valid_fraction>=config['min_valid_fraction'] and raw_fraction>=config['raw_fraction'] and low>=config['min_response_fraction'] and joint>=config['min_joint_fraction'] and longest<=max(config['max_raw_empty_minimum'],config['max_raw_empty_fraction']*n)
            category='suspected_subthreshold_gap' if coherent and low-high>=config['min_threshold_growth'] else 'raw_supported_unreported_gap' if coherent and high>=config['min_response_fraction'] else 'partial_gap_evidence' if valid_fraction>=config['min_valid_fraction'] and raw_fraction>=.35 and low>=.35 else 'no_clear_gap_evidence'
            fits.append(dict(frame=frame+1,direction=frame//2+1,exposure='low' if frame%2==0 else 'high',polarity=polarity,category=category,raw_fraction=raw_fraction,detail_response_fraction=low,baseline_response_fraction=high,threshold_growth=low-high,joint_fraction=joint,valid_fraction=valid_fraction,longest_raw_unsupported_missing=longest,median_signed_response=float(np.median(q[missing&allowed])) if (missing&allowed).any() else None,median_raw_contrast=float(np.median(contrast[missing&allowed])) if (missing&allowed).any() else None,threshold_curve=curve))
    order={'suspected_subthreshold_gap':3,'raw_supported_unreported_gap':3,'partial_gap_evidence':1,'no_clear_gap_evidence':0};fits.sort(key=lambda r:(order[r['category']],r['joint_fraction'],r['raw_fraction'],r['threshold_growth']),reverse=True);best=fits[0];passed=[r for r in fits if order[r['category']]==3];good=np.zeros(len(path),bool)
    # Mark only actually sampled missing pixels with same-frame evidence, not a painted bridge.
    for fit in passed:
        frame=fit['frame']-1;pol=fit['polarity'];values=[bilinear(gray[frame],p) for p in positions];c=.25*values[0]+.5*values[1]+.25*values[2];contrast=np.minimum(pol*(c-values[3]),pol*(c-values[4]));allowed=np.logical_and.reduce([allowed_samples(p,valid[frame],board) for p in positions]);good|=missing&allowed&(contrast>=config['raw_contrast'])&(pol*residual[frame,yy,xx]>81*config['detail_weak'])
    x0,y0=native.min(axis=0);x1,y1=native.max(axis=0)
    return dict(probe_kind=kind,bbox_xywh=[int(x0),int(y0),int(x1-x0+1),int(y1-y0+1)],missing_samples=n,path_samples=len(path),path_xy=path.tolist(),missing_native_xy=native[missing].tolist(),supported_missing_native_xy=native[good].tolist(),category=best['category'],best_fit=best,fits=fits,supported_directions=sorted(set(r['direction'] for r in passed)),probe_not_defect_geometry=True)

def analyze(formal,gray,valid,board,residual,plan,prior_records=()):
    if formal.dtype!=bool or gray.shape!=(8,*formal.shape) or valid.shape!=gray.shape or residual.shape!=gray.shape or board.shape!=formal.shape:raise ValueError('Matching eight actual native planes required')
    before=hashlib.sha256(formal.tobytes()).hexdigest();tips,pairs=endpoint_proposals(formal,plan['gap']);gaps=[]
    rank={'suspected_subthreshold_gap':3,'raw_supported_unreported_gap':3,'partial_gap_evidence':1,'no_clear_gap_evidence':0}
    for i,pair in enumerate(pairs):
        probes=[r for kind in ('straight','tangent_curve') if (r:=evaluate_probe(formal,gray,valid,board,residual,probe_path(pair,kind),plan['gap'],kind)) is not None]
        if not probes:continue
        probes.sort(key=lambda r:(rank[r['category']],r['best_fit']['joint_fraction'],r['best_fit']['raw_fraction']),reverse=True);best=probes[0];gaps.append(dict(id=len(gaps)+1,a=pair['a'],b=pair['b'],distance_px=pair['distance_px'],facing_cosine=pair['facing_cosine'],selected_probe=best,alternative_probe_summaries=[dict(kind=r['probe_kind'],category=r['category'],best_fit=r['best_fit']) for r in probes[1:]],review=rank[best['category']]==3))
    shaped=[]
    for row in prior_records:
        if row.get('raw_supported'):
            shaped.append(dict(source=row.get('source'),kind=row.get('kind'),label=row['label'],bbox_xywh=row['bbox_xywh'],supported_directions=row['supported_directions'],**local_shape(row['support_station_xy'],plan['shape'])))
    if hashlib.sha256(formal.tobytes()).hexdigest()!=before:raise AssertionError('Formal detector mutated')
    return dict(endpoint_count=len(tips),endpoint_pairs=len(pairs),gaps=gaps,shape_reviews=shaped,formal_unchanged=True,automatic_pass=False,confidence_probability=None)
