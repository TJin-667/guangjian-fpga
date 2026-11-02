"""Reusable v4 review-evidence runtime, independent of manual annotations."""
import hashlib,importlib.util
from pathlib import Path
import numpy as np
from evidence import compare,raw_supported_components,group_decision
from raw_line_scan_v3 import scan_combined
from sleeve_runtime import predict

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_confidence_batch_utilities',HERE/'run_v4.py');batch=importlib.util.module_from_spec(spec);spec.loader.exec_module(batch)

def assess(context,formal_config,plan):
    x=context;formal_result=predict(x,formal_config);formal=formal_result['candidate'].copy();before=hashlib.sha256(formal.tobytes()).hexdigest();records=[];metrics={};arrays={}
    for name,overrides in plan['shadow_profiles'].items():
        config={**formal_config,**overrides};shadow=predict(x,config)['candidate'];diff,m=compare(formal,shadow,plan['comparison'])
        if name=='rim_control':
            if m['nonrim_pixels']:raise AssertionError('Rim control produced nonrim changes')
            evidence=np.zeros_like(formal);rows=[]
        else:
            c=plan['comparison'];evidence,rows=raw_supported_components(diff['nonrim'],x['planes']['gray'],x['planes']['valid'],x['board'],x['r'],plan['raw_line_check'],min_area=c['min_new_piece_area'],min_span=c['min_new_piece_span'],min_line_fraction=c['min_new_piece_line_fraction'],max_width=c['max_new_piece_median_width'],strong_reference=formal_config['strong'])
        for r in rows:r.update(source=name,kind='parameter_relaxation_extra')
        records.extend(rows);m.update(raw_supported_components=sum(r['raw_supported'] for r in rows),profile_config=config);metrics[name]=m
        arrays[name+'_candidate']=shadow;arrays[name+'_gained']=diff['gained'];arrays[name+'_lost']=diff['lost'];arrays[name+'_structured_evidence']=evidence
    scan,rows=scan_combined(formal,x['r'],x['v'],x['board'],x['planes']['gray'],x['planes']['valid'],plan)
    for r in rows:r['source']='seed_independent_scan'
    records.extend(rows);windows=batch.merge_windows(records,formal.shape);stations=batch.stations_mask(formal.shape,records);unknown=float(((~x['v'])&x['board']).sum()/max(1,x['board'].sum()));status=group_decision(unknown,len(windows),plan)
    if any(r.get('kind')=='raw_scan_capacity_review' for r in rows):status='REVIEW_ANALYSIS_CAPACITY'
    if hashlib.sha256(formal.tobytes()).hexdigest()!=before:raise AssertionError('Review changed detector')
    arrays.update(formal_detector_mask=formal,raw_validated_station_mask=stations,weak_scan_region_evidence=scan)
    result=dict(group_id=x['summary']['group_id'],status=status,formal_config_id=plan['formal_config_id'],formal_pixels=int(formal.sum()),review_windows=len(windows),multi_direction_windows=sum(w['priority']=='multi_direction' for w in windows),unknown_board_fraction=unknown,
        raw_supported_unseeded_components=sum(r['raw_supported'] and r['kind']=='globally_unseeded_continuous_evidence' for r in rows),raw_supported_local_seedless_fragments=sum(r['raw_supported'] and not r['has_strong_seed'] for r in rows),raw_supported_scan_components=sum(r['raw_supported'] for r in rows),
        confidence_probability=None,automatic_pass=False,formal_detector_unchanged=True,manual_reference_used=False)
    return dict(formal_result=formal_result,arrays=arrays,raw_evidence=records,shadow_comparisons=metrics,review_regions=windows,result=result)
