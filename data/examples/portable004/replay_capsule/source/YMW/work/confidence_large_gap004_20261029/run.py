"""Existing004 only. Full-board proposals; known weak-path checks are post hoc."""
import argparse,gzip,json,re,socket,time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw
from large_gap import analyze_large_gaps
from sleeve_runtime import load_sealed,verify_inputs
from joint_package_contract import verify_package as verify_formal
from shadow_package_contract import verify as verify_shadow
from run_study import read,write,sha,csv_write,font,sheet

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2];PREVIOUS=HERE.parent/'confidence_gap_review_20261029';SHADOW=HERE.parent/'confidence_shadow_review_20261029'

def windows_for(gaps):
    rows=[]
    for g in gaps:
        if not g['review']:continue
        x,y,w,h=g['selected_probe']['bbox_xywh'];rows.append(dict(x0=x-4,y0=y-4,x1=x+w+4,y1=y+h+4,gap_ids=[g['id']],largest_visual_gap_px=g['selected_probe']['visual']['longest_visual_gap_px']))
    changed=True
    while changed:
        changed=False
        for i,a in enumerate(rows):
            for j in range(i+1,len(rows)):
                b=rows[j];overlap=max(0,min(a['x1'],b['x1'])-max(a['x0'],b['x0']))*max(0,min(a['y1'],b['y1'])-max(a['y0'],b['y0']));minimum=min((a['x1']-a['x0'])*(a['y1']-a['y0']),(b['x1']-b['x0'])*(b['y1']-b['y0']))
                if overlap/max(1,minimum)>.6:
                    rows[i]=dict(x0=min(a['x0'],b['x0']),y0=min(a['y0'],b['y0']),x1=max(a['x1'],b['x1']),y1=max(a['y1'],b['y1']),gap_ids=a['gap_ids']+b['gap_ids'],largest_visual_gap_px=max(a['largest_visual_gap_px'],b['largest_visual_gap_px']));rows.pop(j);changed=True;break
            if changed:break
    rows.sort(key=lambda r:-r['largest_visual_gap_px'])
    for i,row in enumerate(rows):row['id']=i+1
    return rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic();plan=read(HERE/'PLAN.json');base=read(PREVIOUS/'PLAN.json');formal_binding=verify_formal();shadow_binding=verify_shadow();sources={str(p):sha(p) for p in [*HERE.glob('*.py'),HERE/'PLAN.json']};inputs={};group=plan['only_existing_sample004_group'];rec=next(r for r in read(SHADOW/'results/RESULTS.json') if r['group_id']==group);root=Path(rec['root']);print('BEGIN_EXISTING004',group,flush=True)
    def deny(*a,**k):raise RuntimeError('Offline experiment prohibits sockets')
    socket.socket=deny
    for dependency in (PREVIOUS,SHADOW):
        manifest=read(dependency/'ARTIFACT_MANIFEST.json')['files_sha256']
        for name,digest in manifest.items():
            if name.endswith('.py') or name in ('PLAN.json','PLAN_V4.json'):
                if sha(dependency/name)!=digest:raise ValueError('Prior source changed '+name)
                inputs[str(dependency/name)]=digest
    x=load_sealed(root);inputs.update(x['files']);previous_npz=PREVIOUS/'results'/group/'arrays.npz';expected=read(PREVIOUS/'ARTIFACT_MANIFEST.json')['files_sha256'][previous_npz.relative_to(PREVIOUS).as_posix()];assert sha(previous_npz)==expected;inputs[str(previous_npz)]=expected
    with np.load(previous_npz,allow_pickle=False) as z:formal=z['formal_detector_mask'].copy();previous_gap=z['supported_gap_sample_mask'].copy()
    shadow_npz=SHADOW/'results'/group/'confidence_reference_arrays.npz';expected=read(SHADOW/'ARTIFACT_MANIFEST.json')['files_sha256'][shadow_npz.relative_to(SHADOW).as_posix()];assert sha(shadow_npz)==expected;inputs[str(shadow_npz)]=expected
    with np.load(shadow_npz,allow_pickle=False) as z:old_raw=z['raw_validated_station_mask'].copy();assert np.array_equal(formal,z['formal_detector_mask'])
    before=formal.tobytes();res=analyze_large_gaps(formal,x['planes']['gray'],x['planes']['valid'],x['board'],x['planes']['residual_n'],base,plan);assert before==formal.tobytes();verify_inputs(x);windows=windows_for(res['gaps']);mask=np.zeros_like(formal);review=[g for g in res['gaps'] if g['review']];flat=[]
    for g in res['gaps']:
        q=g['selected_probe'];f=q['best_fit'];flat.append(dict(id=g['id'],review=g['review'],priority=q['visual']['priority'],longest_visible_gap_px=q['visual']['longest_visual_gap_px'],distance_px=g['distance_px'],aligned=g['aligned'],long_pair=g['long_pair'],endpoint_a_kind=g['a']['proposal_kind'],endpoint_b_kind=g['b']['proposal_kind'],category=q['category'],review_weak=q['review_weak_used'],frame=f['frame'],polarity=f['polarity'],raw_fraction=f['raw_fraction'],response_fraction=f['detail_response_fraction'],threshold_growth=f['threshold_growth'],joint_fraction=f['joint_fraction']))
        if g['review']:
            for xx,yy in q['supported_missing_native_xy']:mask[yy,xx]=True
    assert not (mask&formal).any()
    with gzip.open(out/'GAP_REVIEWS.json.gz','wt',encoding='utf-8',compresslevel=6) as f:json.dump(res,f,ensure_ascii=False,allow_nan=False)
    csv_write(out/'GAP_SUMMARY.csv',flat);write(out/'REVIEW_WINDOWS.json',windows);np.savez_compressed(out/'arrays.npz',formal_detector_mask=formal,new_gap_sample_mask=mask,previous_gap_sample_mask=previous_gap,previous_raw_sample_mask=old_raw)
    # No manual coordinates were used to propose, rank or accept any gap.
    annotation_path=REPO/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json';annotation=read(annotation_path);inputs[str(annotation_path)]=sha(annotation_path);xy=np.asarray(annotation['path_points']);xs=xy[:,0].astype(int);ys=np.rint(xy[:,1]).astype(int);formal_hit=formal[ys[:,None]+np.arange(-3,4),xs[:,None]].any(1);kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7));near=lambda m:cv2.dilate(m.astype('uint8'),kernel)[ys,xs]>0;old_hit=near(old_raw|previous_gap);new_hit=near(mask);inside=np.zeros(len(xs),bool)
    for w in windows:inside|=(xs>=w['x0'])&(xs<w['x1'])&(ys>=w['y0'])&(ys<w['y1'])
    runs=[];begin=None
    for i,missing in enumerate(np.r_[~formal_hit,False]):
        if missing and begin is None:begin=i
        if not missing and begin is not None:
            segment=xy[begin:i];length=float(np.linalg.norm(np.diff(segment,axis=0),axis=1).sum()+1);runs.append(dict(start_index=begin,end_index=i-1,reference_positions=i-begin,approximate_path_length_px=length,start_xy=segment[0].tolist(),end_xy=segment[-1].tolist(),tiny_reference_gap=length<=plan['ignore_gap_at_most_px'],old_near_supported=int(old_hit[begin:i].sum()),new_near_supported=int(new_hit[begin:i].sum()),new_window_positions=int(inside[begin:i].sum())));begin=None
    evaluation=dict(development_case_only=True,not_recall=True,manual_path_loaded_after_predictions=True,formal_support=int(formal_hit.sum()),path_positions=len(xs),uncovered=int((~formal_hit).sum()),old_two_routes_near_support=int((~formal_hit&old_hit).sum()),new_near_support=int((~formal_hit&new_hit).sum()),union_near_support=int((~formal_hit&(old_hit|new_hit)).sum()),new_window_covered_uncovered_positions=int((~formal_hit&inside).sum()),reference_gap_runs=runs);write(out/'CASE_CHECK.json',evaluation)
    summary=dict(group_id=group,formal_pixels=int(formal.sum()),endpoint_proposals=res['endpoints'],endpoint_pairs=res['endpoint_pairs'],evaluated_gap_pairs=len(res['gaps']),tested_probe_hypotheses=res['tested_probe_hypotheses'],tiny_probe_hypotheses_ignored=res['tiny_probe_hypotheses_ignored'],accepted_pairs=len(review),review_windows=len(windows),large_accepted_pairs=sum(g['selected_probe']['visual']['priority']=='large_visible_gap' for g in review),long_distance_accepted_pairs=sum(g['long_pair'] for g in review),formal_unchanged=True,confidence_probability=None,automatic_pass=False);write(out/'RESULT.json',summary)
    mean=np.rint(x['planes']['gray'].astype('float32').mean(0)).astype('uint8');rgb=np.repeat(mean[:,:,None],3,axis=2);detected=rgb.copy();detected[formal]=[255,210,0];proposed=Image.fromarray(detected);draw=ImageDraw.Draw(proposed)
    for w in windows:draw.rectangle((w['x0'],w['y0'],w['x1'],w['y1']),outline='#ff9100',width=2);draw.text((w['x0'],w['y0']-22),str(w['id']),font=font(17),fill='#ff9100')
    proposed.save(out/'whole004_review.png');x0,x1=int(xs.min())-35,int(xs.max())+40;y0,y1=int(ys.min())-35,int(ys.max())+35;evidence=rgb.copy();evidence[old_raw|previous_gap]=[255,55,175];evidence[mask]=[0,235,245];tiles=[]
    for name,im in [('原片CH2高曝800',x['planes']['gray'][3]),('原片CH4高曝800',x['planes']['gray'][7]),('正式检测不变',detected),('橙框：大缺口复检建议',np.asarray(proposed)),('粉点：上版两条通路',np.where((old_raw|previous_gap)[:,:,None],[255,55,175],rgb).astype('uint8')),('青点：新增实际支持；不补线',evidence)]:
        image=Image.fromarray(im[y0:y1,x0:x1]).convert('RGB');image=image.resize((image.width*2,image.height*2),Image.Resampling.NEAREST);tiles.append((name,image))
    sheet(tiles,out/'weak004_comparison.png',columns=2,cell=(640,320))
    largest=max(runs,key=lambda r:r['approximate_path_length_px']);center=(np.array(largest['start_xy'])+np.array(largest['end_xy']))/2;case_gaps=[g for g in review if (lambda b:b[0]-5<=center[0]<=b[0]+b[2]+5 and b[1]-5<=center[1]<=b[1]+b[3]+5)(g['selected_probe']['bbox_xywh'])];case_gaps.sort(key=lambda g:(g['selected_probe']['visual']['longest_visual_gap_px'],-g['selected_probe']['best_fit']['joint_fraction']));write(out/'LARGEST_GAP_CHECK.json',dict(reference_run=largest,center_xy=center.tolist(),review_pair_ids=[g['id'] for g in case_gaps],has_review=bool(case_gaps),note='Post hoc development case; window coverage and actual supported samples are different'))
    if case_gaps:
        selected=case_gaps[0];write(out/'CENTRAL_GAP_EVIDENCE.json',selected);print('CENTRAL_GAP',selected['id'],selected['selected_probe']['best_fit']['frame'],selected['selected_probe']['best_fit']['raw_fraction'],flush=True)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>004明显大缺口复检</title><style>body{font:18px system-ui;color:#17314c;max-width:1400px;margin:30px auto}img{max-width:100%}p{line-height:1.7}</style><h1>只研究004已确认连续弱线</h1><p>忽略≤6像素微小间断；清晰相向的端点最大搜索160像素。橙框为复检建议，青点才是实际原片与响应支持，不补线、不输出正确概率。</p><p><a href="CASE_CHECK.json">逐段参考核对</a> · <a href="LARGEST_GAP_CHECK.json">最大缺口核对</a> · <a href="GAP_SUMMARY.csv">全部探查对汇总</a> · <a href="GAP_REVIEWS.json.gz">完整无损证据</a></p><img src="weak004_comparison.png"><h2>全幅诊断，仅研究004、不作跨工件效果结论</h2><img src="whole004_review.png">',encoding='utf-8');assert all((out/ref).is_file() for ref in re.findall(r'(?:src|href)="([^"#]+)"',(out/'index.html').read_text('utf-8')))
    assert all(sha(p)==d for p,d in inputs.items());assert all(sha(p)==d for p,d in sources.items());assert verify_formal()==formal_binding and verify_shadow()==shadow_binding
    write(out/'VERIFICATION.json',dict(status='PASS',source_sha256=sources,input_files_sha256=inputs,only_one_existing004_group=True,frames=8,new_captures=0,formal_mask_byte_identical=True,original_b1_differences=x['original_differences'],prior_confidence_sources_unchanged=True,manual_path_used_for_prediction=False,FPGA_changed=False,TJ_model_run=False,calibrated_probability=False,automatic_pass=False,runtime_seconds=time.monotonic()-start))
    print('LARGE_GAP004_COMPLETE',summary,'case',evaluation['union_near_support'],flush=True)

if __name__=='__main__':main()
