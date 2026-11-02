"""Prioritize visually large gaps; all relaxed computations are review-only."""
import hashlib,math,sys
from pathlib import Path
import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'confidence_gap_review_20261029'))
from gap_review import endpoint_proposals,probe_path,evaluate_probe,allowed_samples,bilinear
from evidence import fragments,distance_to

def robust_tips(formal,base,plan):
    tips,_=endpoint_proposals(formal,{**base,'trace_steps':plan['endpoint_trace_steps']})
    for t in tips:t['proposal_kind']='local_skeleton'
    labels,rows=fragments(formal,min_area=max(base['min_component_area'],plan['extent_min_area']))
    for row in rows:
        if row['two_sweep_span_px']<base['min_component_span'] or row['two_sweep_span_px']>plan['extent_max_span'] or row['median_width_proxy_px']>base['max_component_width'] or row['line_fraction']<base['min_local_line_fraction']:continue
        x,y,w,h=row['bbox_xywh'];yy,xx=np.nonzero(labels[y:y+h,x:x+w]==row['label']);xy=np.stack([xx+x,yy+y],axis=1).astype(float);center=xy.mean(0);eigen,vectors=np.linalg.eigh(np.cov(xy.T,bias=True));ratio=float(eigen[-1]/max(eigen[0],1e-8))
        if ratio<plan['extent_min_eigen_ratio']:continue
        axis=vectors[:,-1];projection=(xy-center)@axis
        for index,sign in ((int(np.argmin(projection)),-1),(int(np.argmax(projection)),1)):
            point=xy[index];direction=sign*axis
            matching=next((t for t in tips if np.linalg.norm(point-t['xy'])<=1 and np.dot(direction,t['outward_xy'])>.96),None)
            if matching is not None:
                matching['trace_span_px']=max(matching['trace_span_px'],float(np.ptp(projection)));matching['proposal_kind']='local_skeleton_and_extent';continue
            tips.append(dict(component=row['label'],xy=point.tolist(),outward_xy=direction.tolist(),trace_span_px=float(np.ptp(projection)),proposal_kind='short_fragment_extent',eigen_ratio=ratio))
    return tips

def propose(formal,base,plan):
    tips=robust_tips(formal,base,plan);positions=np.array([t['xy'] for t in tips]);vectors=np.array([t['outward_xy'] for t in tips]);pairs=[]
    for i,a in enumerate(tips):
        distances=np.linalg.norm(positions-positions[i],axis=1)
        for j in np.flatnonzero((distances>=base['min_distance'])&(distances<=plan['aligned_max_endpoint_distance'])):
            if j<=i:continue
            unit=(positions[j]-positions[i])/distances[j];facing=min(float(vectors[i]@unit),float(vectors[j]@-unit));aligned=facing>=math.cos(math.radians(plan['aligned_facing_angle']));long=distances[j]>plan['normal_max_endpoint_distance']
            if facing<math.cos(math.radians(plan['normal_facing_angle'])) or (long and (not aligned or min(a['trace_span_px'],tips[j]['trace_span_px'])<plan['long_pair_min_trace_span'])):continue
            pairs.append(dict(a=a,b=tips[j],distance_px=float(distances[j]),facing_cosine=facing,aligned=aligned,long_pair=bool(long)))
    if len(pairs)>plan['max_pairs']:raise RuntimeError('REVIEW_ANALYSIS_CAPACITY: no weak proposals silently removed')
    return tips,pairs

def visibility(path,distance,plan):
    native=np.rint(path).astype(int);native[:,0]=np.clip(native[:,0],0,distance.shape[1]-1);native[:,1]=np.clip(native[:,1],0,distance.shape[0]-1);keep=np.r_[True,np.any(np.diff(native,axis=0),axis=1)];path=path[keep];native=native[keep];missing=distance[native[:,1],native[:,0]]>plan['visual_neighbor_tolerance_px'];arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(path,axis=0),axis=1))];runs=[];begin=None
    for i,value in enumerate(np.r_[missing,False]):
        if value and begin is None:begin=i
        if not value and begin is not None:runs.append(dict(begin=begin,end=i-1,length_px=float(arc[i-1]-arc[begin]+1),start_xy=path[begin].tolist(),end_xy=path[i-1].tolist()));begin=None
    maximum=max((r['length_px'] for r in runs),default=0.)
    return dict(longest_visual_gap_px=maximum,visual_missing_samples=int(missing.sum()),visual_runs=runs,tiny_ignored=maximum<=plan['ignore_gap_at_most_px'],priority='large_visible_gap' if maximum>=plan['large_gap_at_least_px'] else 'medium_visible_gap',visibility_is_measurement_only=True)

def retained_points(result,passed,gray,valid,board,residual,measurement_mask,config):
    path=np.asarray(result['path_xy']);native=np.rint(path).astype(int);xx,yy=native.T;missing=~measurement_mask[yy,xx];tangent=np.gradient(path,axis=0);tangent/=np.maximum(np.linalg.norm(tangent,axis=1)[:,None],1e-6);normal=np.stack([-tangent[:,1],tangent[:,0]],axis=1);positions=[path+offset*normal for offset in (-.5,0,.5,config['profile_flank'],-config['profile_flank'])];good=np.zeros(len(path),bool)
    for fit in passed:
        frame=fit['frame']-1;polarity=fit['polarity'];values=[bilinear(gray[frame],p) for p in positions];center=.25*values[0]+.5*values[1]+.25*values[2];contrast=np.minimum(polarity*(center-values[3]),polarity*(center-values[4]));allowed=np.logical_and.reduce([allowed_samples(p,valid[frame],board) for p in positions])&valid[frame,yy,xx]&board[yy,xx];good|=missing&allowed&(contrast>=config['raw_contrast'])&(polarity*residual[frame,yy,xx]>81*config['detail_weak'])
    return native[good].tolist()

def analyze_large_gaps(formal,gray,valid,board,residual,base_plan,plan):
    if formal.dtype!=bool or gray.shape!=(8,*formal.shape) or valid.shape!=gray.shape or residual.shape!=gray.shape:raise ValueError('Matching actual native eight-frame arrays required')
    digest=hashlib.sha256(formal.tobytes()).hexdigest();tips,pairs=propose(formal,base_plan['gap'],plan);distance=distance_to(formal);measurement_mask=distance<=plan['visual_neighbor_tolerance_px'];records=[];tiny=0;rejected=0;tested=0;rank={'suspected_subthreshold_gap':3,'raw_supported_unreported_gap':3,'partial_gap_evidence':1,'no_clear_gap_evidence':0}
    for pair in pairs:
        hypotheses=[]
        for kind in ('straight','tangent_curve'):
            p=probe_path(pair,kind);delta=p[-1]-p[0];normal=np.array([-delta[1],delta[0]])/np.linalg.norm(delta);t=np.linspace(0,1,len(p))[:,None]
            for bow in plan['curve_bows_px']:
                if abs(bow)>min(max(abs(v) for v in plan['curve_bows_px']),plan['max_bow_distance_fraction']*pair['distance_px']):continue
                path=p+bow*np.sin(np.pi*t)*normal;visual=visibility(path,distance,plan)
                if visual['tiny_ignored']:tiny+=1;continue
                config=base_plan['gap'].copy();relaxed=pair['aligned'] and visual['longest_visual_gap_px']>=plan['large_gap_at_least_px']
                if relaxed:config['detail_weak']=plan['aligned_large_review_weak']
                result=evaluate_probe(measurement_mask,gray,valid,board,residual,path,config,kind)
                if result is None:rejected+=1;continue
                tested+=1
                if pair['long_pair']:
                    for fit in result['fits']:
                        if fit['longest_raw_unsupported_missing']>plan['long_pair_max_raw_empty_samples'] and rank[fit['category']]==3:fit['category']='partial_gap_evidence'
                    result['fits'].sort(key=lambda f:(rank[f['category']],f['joint_fraction'],f['raw_fraction'],f['threshold_growth']),reverse=True);result['best_fit']=result['fits'][0];result['category']=result['best_fit']['category']
                passed=[f for f in result['fits'] if rank[f['category']]==3];directions=sorted(set(f['direction'] for f in passed));result['supported_directions']=directions
                result['supported_missing_native_xy']=retained_points(result,passed,gray,valid,board,residual,measurement_mask,config)
                result.update(visual=visual,bow_px=bow,review_weak_used=config['detail_weak'],aligned_large_relaxation=relaxed);hypotheses.append(result)
        if not hypotheses:continue
        hypotheses.sort(key=lambda r:(rank[r['category']],r['best_fit']['joint_fraction'],r['best_fit']['raw_fraction'],-abs(r['bow_px'])),reverse=True);selected=hypotheses[0]
        records.append(dict(id=len(records)+1,**pair,review=rank[selected['category']]==3,selected_probe=selected,alternatives=[dict(kind=h['probe_kind'],bow_px=h['bow_px'],category=h['category'],review_weak_used=h['review_weak_used'],longest_visual_gap_px=h['visual']['longest_visual_gap_px'],best_fit=h['best_fit']) for h in hypotheses[1:]]))
    if hashlib.sha256(formal.tobytes()).hexdigest()!=digest:raise AssertionError('Formal detection changed')
    return dict(endpoints=len(tips),endpoint_pairs=len(pairs),tested_probe_hypotheses=tested,tiny_probe_hypotheses_ignored=tiny,insufficient_missing_hypotheses=rejected,gaps=records,formal_unchanged=True,confidence_probability=None,automatic_pass=False)
