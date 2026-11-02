"""Shadow-evidence analysis; no labels, sample IDs or modifications to detector."""
import heapq,math,sys
from pathlib import Path
import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'joint_threshold_tuning_20261029'))
from joint_gate import cutoff
from component_gate import geometry,thin
from seeded_gate import profiles

def distance_to(mask):
    if mask.any():return cv2.distanceTransform((~mask).astype('uint8'),cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
    return np.full(mask.shape,1e6,np.float32)

def fragments(mask,*,min_area=1):
    n,labels,stats,centers=cv2.connectedComponentsWithStats(mask.astype('uint8'),connectivity=8);rows=[]
    for label in range(1,n):
        x,y,w,h,area=map(int,stats[label])
        if area<min_area:continue
        piece=labels[y:y+h,x:x+w]==label;g=geometry(np.pad(piece,1));rows.append(dict(label=label,bbox_xywh=[x,y,w,h],centroid_xy=centers[label].tolist(),**g))
    return labels,rows

def compare(formal,shadow,config):
    """Counts and structure are separate; rim growth is not missed-line proof."""
    if formal.dtype!=bool or shadow.dtype!=bool or formal.shape!=shadow.shape:raise ValueError('Native matching boolean masks required')
    gained=shadow&~formal;lost=formal&~shadow;dist=distance_to(formal);nonrim=gained&(dist>config['rim_tolerance_px']);rim=gained&~nonrim
    labels,rows=fragments(nonrim,min_area=config['min_new_piece_area']);accepted=[]
    for r in rows:
        r['line_like']=bool(r['two_sweep_span_px']>=config['min_new_piece_span'] and r['line_fraction']>=config['min_new_piece_line_fraction'] and r['median_width_proxy_px']<=config['max_new_piece_median_width'])
        if r['line_like']:accepted.append(r['label'])
    return dict(gained=gained,lost=lost,rim=rim,nonrim=nonrim,structured=np.isin(labels,accepted)&nonrim),dict(gained_pixels=int(gained.sum()),lost_pixels=int(lost.sum()),rim_pixels=int(rim.sum()),nonrim_pixels=int(nonrim.sum()),new_line_like_components=len(accepted),nonrim_components=rows,
        exact_jaccard=float((formal&shadow).sum()/max(1,(formal|shadow).sum())),overlap_not_probability=True)

def stations(piece,origin,stride=4,maximum=160):
    """Local stations spaced along actual skeleton graph, not a painted line."""
    sk=thin(np.pad(piece,1));n,parts,stats,_=cv2.connectedComponentsWithStats(sk.astype('uint8'),connectivity=8)
    if n>1:sk=parts==(1+int(np.argmax(stats[1:,4])))
    yy,xx=np.nonzero(sk)
    if not len(xx):return np.empty((0,2),float),np.empty(0,float)
    start=(int(yy[0]),int(xx[0]))
    def distances(start):
        d={start:0.};queue=[(0.,start)]
        while queue:
            cost,p=heapq.heappop(queue)
            if cost!=d[p]:continue
            y,x=p
            for dy,dx in ((-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)):
                q=(y+dy,x+dx)
                if 0<=q[0]<sk.shape[0] and 0<=q[1]<sk.shape[1] and sk[q]:
                    v=cost+(math.sqrt(2) if dx and dy else 1.)
                    if v<d.get(q,float('inf')):d[q]=v;heapq.heappush(queue,(v,q))
        return d
    first=distances(start);d=distances(max(first,key=first.get));buckets={}
    for p,cost in sorted(d.items(),key=lambda v:(v[1],v[0])):buckets.setdefault(int(cost//stride),(p,cost))
    chosen=[buckets[k] for k in sorted(buckets)]
    if len(chosen)>maximum:chosen=[chosen[i] for i in np.unique(np.rint(np.linspace(0,len(chosen)-1,maximum)).astype(int))]
    return np.asarray([[p[1]-1+origin[0],p[0]-1+origin[1]] for p,cost in chosen],float),np.asarray([cost for p,cost in chosen],float)

def longest_run(costs,accepted,max_gap):
    values=np.sort(np.asarray(costs)[accepted]);best_span=0.;best_count=0;start=last=None;count=0
    for value in values:
        if last is None or value-last>max_gap:start=value;count=1
        else:count+=1
        span=float(value-start)
        if (span,count)>(best_span,best_count):best_span,best_count=span,count
        last=value
    return best_span,best_count

def raw_supported_components(mask,gray,valid,board,response,config,*,min_area,min_span,min_line_fraction,max_width,strong_reference):
    """One real frame/polarity must support a run. Multi-view is extra evidence."""
    labels,rows=fragments(mask,min_area=min_area);selected=[];positions=[];cost_arrays=[];ranges=[]
    for r in rows:
        if r['two_sweep_span_px']<min_span or r['line_fraction']<min_line_fraction or r['median_width_proxy_px']>max_width:continue
        x,y,w,h=r['bbox_xywh'];piece=labels[y:y+h,x:x+w]==r['label'];xy,cost=stations(piece,(x,y),config['station_stride_geodesic_px'],config['max_stations_per_component'])
        if len(xy)<config['min_good_stations']:continue
        begin=len(positions);positions.extend(xy.tolist());ranges.append((begin,len(positions)));cost_arrays.append(cost);peak=int(response[y:y+h,x:x+w][piece].max(initial=0));selected.append({**r,'peak_n':peak,'has_strong_seed':bool(peak>cutoff(strong_reference)),'station_xy':xy.tolist(),'station_geodesic':cost.tolist()})
    evidence=np.zeros_like(mask);records=[]
    if not positions:return evidence,records
    # The helper retains every frame/orientation/polarity fit; never mix fits.
    chunks=[]
    for begin in range(0,len(positions),2048):chunks.append(profiles(np.asarray(positions[begin:begin+2048]),gray,valid,board,config['length'],config['flank']))
    fractions=np.concatenate([v[0] for v in chunks]);means=np.concatenate([v[1] for v in chunks]);all_good=(fractions>=config['support_fraction'])&(means>=config['mean_contrast'])
    for r,(begin,end),cost in zip(selected,ranges,cost_arrays):
        fits=[];supported_frames=[];all_supported=np.zeros(end-begin,bool)
        for frame in range(8):
            for polarity in range(2):
                hits=all_good[begin:end,:,frame,polarity].any(axis=1);span,count=longest_run(cost,hits,config['max_station_gap_px']);fraction=float(hits.mean());passed=bool(count>=config['min_good_stations'] and span>=config['min_run_span_px'] and fraction>=config['min_component_station_fraction'])
                if passed:
                    fits.append(dict(frame=frame+1,direction=frame//2+1,exposure='low' if frame%2==0 else 'high',polarity=1 if polarity==0 else -1,good_stations=int(hits.sum()),stations=len(hits),station_fraction=fraction,run_span_px=span,run_good_stations=count));supported_frames.append(frame+1);all_supported|=hits
        accepted=bool(fits);r.update(raw_supported=accepted,raw_fits=fits,supported_frames=sorted(set(supported_frames)),supported_directions=sorted(set((frame-1)//2+1 for frame in supported_frames)),support_station_xy=np.asarray(r['station_xy'])[all_supported].tolist(),evidence_priority='multi_direction' if len(set((frame-1)//2+1 for frame in supported_frames))>=2 else 'single_direction' if fits else 'none')
        if accepted:evidence|=labels==r['label']
        records.append(r)
    return evidence,records

def scan_without_seed(formal,response,valid_fused,board,gray,valid_frames,plan):
    scan=plan['unseeded_scan'];dist=distance_to(formal);result=np.zeros_like(formal);records=[]
    for weak in scan['weak_levels']:
        extra=(response>cutoff(weak))&valid_fused&board&(dist>plan['comparison']['rim_tolerance_px'])
        evidence,rows=raw_supported_components(extra,gray,valid_frames,board,response,plan['raw_line_check'],min_area=scan['min_area'],min_span=scan['min_span'],min_line_fraction=scan['min_line_fraction'],max_width=scan['max_median_width'],strong_reference=scan['strong_reference'])
        _,global_labels=cv2.connectedComponents(((response>cutoff(weak))&valid_fused).astype('uint8'),connectivity=8);seeded_labels=set(np.unique(global_labels[(response>cutoff(scan['strong_reference']))&valid_fused]).tolist())
        for r in rows:
            xy=np.rint(np.asarray(r['station_xy'])).astype(int);ids=np.unique(global_labels[xy[:,1],xy[:,0]]);ids=ids[ids>0]
            if len(ids)!=1:raise AssertionError('Local skeleton escaped its actual global weak component')
            globally_seeded=int(ids[0]) in seeded_labels
            r.update(scan_weak=weak,local_piece_has_strong_seed=r['has_strong_seed'],global_weak_component_has_seed=globally_seeded,kind='globally_unseeded_continuous_evidence' if not globally_seeded else 'weak_fragment_without_local_seed' if not r['has_strong_seed'] else 'seeded_but_unreported_evidence')
        result|=evidence;records.extend(rows)
    return result,records

def group_decision(unknown_fraction,credible_regions,plan):
    if unknown_fraction>=plan['group_policy']['unknown_board_fraction_review']:return 'REVIEW_INCOMPLETE_OBSERVATION'
    if credible_regions:return plan['group_policy']['credible_extra_line']
    return plan['group_policy']['no_trigger']
