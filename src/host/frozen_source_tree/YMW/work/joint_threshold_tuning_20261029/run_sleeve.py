"""Third phase: couple threshold/body shortlists to bounded6/20 side sleeves."""
import argparse,hashlib,importlib.util,itertools,json,socket,sys,time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from joint_gate import build_cache,cutoff
from body_guard import supplements,extend
from sleeve_guard import prepare as prepare_sleeve,apply as apply_sleeve
from run_joint import topology,cid
from run_body import path_support
from run_study import read,write,sha,labelled,sheet,csv_write

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2];FIRST=Path('E:/GuangjianData/reviews/joint_threshold_tuning_20261029/run_01');BODY=FIRST.parent/'body_01';PREVIOUS=Path('E:/GuangjianData/reviews/seeded_component_tuning_20261029/run_01')
def need(x,why):
    if not x:raise ValueError(why)
def rank(r):return (r['balanced_added_area_per_mp'],r['balanced_compact_count_per_mp'],r['side_radius'],r['config']['reach'],r['id'])
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    def deny(*a,**k):raise RuntimeError('Offline only')
    socket.socket=deny;plan=read(HERE/'SLEEVE_PLAN.json');body_plan=read(HERE/'BODY_PLAN.json');body_search=read(BODY/'SEARCH_RESULTS.json');need(read(BODY/'VERIFICATION.json')['status']=='PASS','Body phase incomplete');write(out/'SLEEVE_PLAN.json',plan)
    data=read(FIRST/'DATASETS.json');snapshots=read(FIRST/'VERIFICATION.json')['input_files_sha256'];need(all(sha(p)==v for p,v in snapshots.items()),'Input SHA changed');sources={str(p):sha(p) for p in list(HERE.glob('*.py'))+[HERE/'SLEEVE_PLAN.json']}
    for directory,names in [(HERE.parent/'seeded_component_tuning_20261029',['seeded_gate.py','run_study.py']),(HERE.parent/'weak_component_experiment_20261029',['component_gate.py','fragment_chain.py'])]:
        for name in names:sources[str(directory/name)]=sha(directory/name)
    shortlist=[]
    for weak,strong,gate in itertools.product(body_plan['weak'],body_plan['strong'],body_plan['gates']):
        choices=[r for r in body_search if r['weak']==weak and r['strong']==strong and r['gate']==gate and all(x['retained_anchor_fraction']>=.6 for x in r['development'].values()) and r['balanced_compact_count_per_mp']<=4.1 and np.mean([x['isolated_area_per_mp'] for x in r['development'].values()])<=body_plan['selection']['isolated_added_area_per_mp_budget']]
        if choices:shortlist.append(min(choices,key=lambda r:(-r['development']['sample004']['path_positions'],r['balanced_added_area_per_mp'],r['reach'],r['half_width'],r['id'])))
    need(shortlist,'No eligible threshold/gate body shortlist');write(out/'BODY_SHORTLIST.json',shortlist)
    spec=importlib.util.spec_from_file_location('_sleeve_app',REPO/'YMW/work/b1_detection_console_20261027/common.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app);app.verify_app();vendor,binding=app.verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
    from light_inspection.real_baseline import hysteresis_connect
    annotation_path=REPO/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json';annotation=read(annotation_path);points=annotation['path_points'];sources[str(annotation_path)]=sha(annotation_path);reproduced={}
    def get(rec,weaks):
        root=Path(rec['root'])
        with np.load(root/'arrays/original_eight_frames.npz',allow_pickle=False) as z:planes={k:z[k].copy() for k in z.files}
        with np.load(root/'arrays/all8_B1.npz',allow_pickle=False) as z:saved={k:z[k].copy() for k in z.files}
        fused=fusion.fuse_two_stage(planes['residual_n'],planes['valid'],board=planes['board'])['final'];diff={k:int(np.count_nonzero(saved[k]!=fused[k])) for k in saved};need(not any(diff.values()),'Original B1 differs');reproduced[rec['group_id']]=diff
        r=np.abs(fused['residual_n'].astype('int32'));v=~fused['unknown'];board=planes['board'];guide=hysteresis_connect(r,v,486,1620)['mask']&board;original=saved['mask'];caches={}
        for weak in set([6.]+list(weaks)):
            wp=hysteresis_connect(r,v,cutoff(weak),1620)['mask']&board;pool=hysteresis_connect(r,v,cutoff(weak),1134)['mask']&board;caches[weak]=build_cache(r,v,board,guide,wp,pool,planes['gray'],planes['valid'],policy='fixed6_20_isolated_supplements')
        return dict(record=rec,r=r,v=v,board=board,original=original,guide=guide,caches=caches,planes=planes,mean=np.rint(planes['gray'].astype('float32').mean(0)).astype('uint8'),sleeve=prepare_sleeve(original,guide,r),tip_cache={})
    dev={}
    for rec in data:
        if rec['role']=='development':dev[rec['sample']]=get(rec,body_plan['weak']);print('SLEEVE_CACHE',rec['sample'],flush=True)
    search=[]
    for index,body_choice in enumerate(shortlist):
        c=body_choice['config'];bases={}
        for sample,inp in dev.items():
            base,anchor,s6,low=supplements(inp['caches'][6.],inp['caches'][c['weak']],c,inp['original']);ordinary=hysteresis_connect(inp['r'],inp['v'],cutoff(c['weak']),cutoff(c['strong']))['mask']&inp['board'];res=extend(base,anchor,ordinary,inp['r'],c,c['reach'],c['half_width'],inp['tip_cache']);bases[sample]=res['candidate']
        for radius in plan['side_radius_px']:
            records={}
            for sample,inp in dev.items():
                res=apply_sleeve(bases[sample],inp['sleeve'],radius,c['strong']);mask=res['candidate'];mp=inp['board'].sum()/1e6
                records[sample]=dict(path_positions=path_support(mask,points) if sample=='sample004' else None,candidate_pixels=int(mask.sum()),added_pixels=int((mask&~inp['original']).sum()),added_area_per_mp=float((mask&~inp['original']).sum()/mp),side_added_pixels=int(res['side_addition'].sum()),retracted6_20_pixels=int((inp['guide']&~mask).sum()))
            config={**c,'side_radius':radius};search.append(dict(id=cid(config),config=config,source_body_id=body_choice['id'],side_radius=radius,balanced_added_area_per_mp=float(np.mean([m['added_area_per_mp'] for m in records.values()])),balanced_compact_count_per_mp=body_choice['balanced_compact_count_per_mp'],development=records))
        if index%20==0:print('SLEEVE_SEARCH',index+1,'/',len(shortlist),flush=True)
    eligible=[r for r in search if r['development']['sample004']['path_positions']>=plan['known004_path_floor']];need(eligible,'No sleeve point qualifies');maximum=max(r['development']['sample004']['path_positions'] for r in eligible);near=[r for r in eligible if r['development']['sample004']['path_positions']>=maximum-plan['near_max_support_tolerance_positions']];best=min(near,key=rank);c=best['config']
    write(out/'SEARCH_RESULTS.json',search);rows=[]
    for r in sorted(search,key=lambda r:(-r['development']['sample004']['path_positions'],rank(r))):
        row=dict(id=r['id'],source_body_id=r['source_body_id'],**r['config'],balanced_added_area_per_mp=r['balanced_added_area_per_mp'],balanced_compact_count_per_mp=r['balanced_compact_count_per_mp'])
        for sample,m in r['development'].items():row.update({sample+'_'+k:v for k,v in m.items()})
        rows.append(row)
    csv_write(out/'SEARCH.csv',rows);frozen=dict(schema='original8-with-six20-side-envelope-v1',selected=best,max_eligible_known_path_positions=maximum,near_max_tolerance=5,immutable='original8/20',side_upper_envelope='6/20',profile=[13,2.5],plan_sha256=sha(out/'SLEEVE_PLAN.json'),development_only=True,frozen_before_other_group_checks=True);write(out/'FROZEN_CONFIG.json',frozen);frozen_sha=sha(out/'FROZEN_CONFIG.json');print('SLEEVE_FROZEN',json.dumps(c),'support',best['development']['sample004']['path_positions'],'maximum',maximum,flush=True)
    results=[];checks=[];cards=[];primary=[];by_board={s:[] for s in dev}
    for rec in data:
        inp=dev[rec['sample']] if rec['role']=='development' else get(rec,[c['weak']]);original=inp['original'];guide=inp['guide'];base,anchor,s6,low=supplements(inp['caches'][6.],inp['caches'][c['weak']],c,original);ordinary=hysteresis_connect(inp['r'],inp['v'],cutoff(c['weak']),cutoff(c['strong']))['mask']&inp['board'];body=extend(base,anchor,ordinary,inp['r'],c,c['reach'],c['half_width'],inp['tip_cache']);res=apply_sleeve(body['candidate'],inp['sleeve'],c['side_radius'],c['strong']);mask=res['candidate'];t=topology(base,mask)
        check=dict(group_id=rec['group_id'],original_losses=int((original&~mask).sum()),outside_matching_threshold=int((mask&~ordinary).sum()),side_outside6_20=int((res['side_addition']&~guide).sum()),side_exceeds_radius=int((res['side_addition']&(inp['sleeve']['distance']>c['side_radius'])).sum()),new_base_merges=t['merged_reference_label_clusters'])
        _,labels=cv2.connectedComponents(mask.astype('uint8'),connectivity=8);bad=0
        for label in np.unique(labels[mask&~original]):
            if label and not ((labels==label)&inp['v']&(inp['r']>cutoff(c['strong']))).any():bad+=1
        check['unseeded_components_with_additions']=bad;need(not any(v for k,v in check.items() if k!='group_id'),'Sleeve contract failed');checks.append(check)
        with np.load(PREVIOUS/rec['group_id']/'masks.npz',allow_pickle=False) as z:previous=z['candidate'].copy()
        row=dict(**rec,config_id=best['id'],weak=c['weak'],strong=c['strong'],gate=c['gate'],side_radius=c['side_radius'],reach=c['reach'],half_width=c['half_width'],original_pixels=int(original.sum()),guide6_20_pixels=int(guide.sum()),previous_pixels=int(previous.sum()),candidate_pixels=int(mask.sum()),added_pixels=int((mask&~original).sum()),side_added_pixels=int(res['side_addition'].sum()),retracted6_20_pixels=int((guide&~mask).sum()),guide_merge_clusters=topology(original,guide)['merged_reference_label_clusters'],selected_merge_clusters=topology(original,mask)['merged_reference_label_clusters'])
        if rec['group_id']==annotation['group_id']:row.update(original_path_positions=path_support(original,points),guide_path_positions=path_support(guide,points),previous_path_positions=path_support(previous,points),without_sleeve_path_positions=path_support(body['candidate'],points),selected_path_positions=path_support(mask,points),ordinary_path_positions=path_support(ordinary,points))
        target=out/rec['group_id'];target.mkdir();np.savez_compressed(target/'masks.npz',original=original,guide6_20=guide,without_sleeve=body['candidate'],candidate=mask,side_addition=res['side_addition'],side_envelope=res['side_envelope'],isolated6=s6,isolated_low=low,terminal_extension=body['extension'],ordinary=ordinary);write(target/'METRICS.json',row);results.append(row)
        modes={'original':original,'guide6_20':guide,'previous':previous,'without_sleeve':body['candidate'],'selected':mask};names={'original':'原8/20','guide6_20':'6/20侧向上限','previous':'上一版完整保护6/20','without_sleeve':'本组参数：侧面不增厚','selected':'本次：6/20套内有限增厚'};tiles=[]
        for name,plane in modes.items():
            rgb=np.repeat(inp['mean'][:,:,None],3,axis=2);rgb[original]=[255,210,0];rgb[plane&~original]=[0,225,240];im=labelled(rgb,[f'{rec["sample"]} | {names[name]} | {int(plane.sum())}px','黄=旧8/20，青=新增；侧向增长受6/20约束',rec['group_id']]);im.save(target/(name+'.png'));need(np.array_equal(np.asarray(Image.open(target/(name+'.png')))[100:],rgb),'Rendered sleeve image differs');tiles.append((names[name],im))
        sheet(tiles,target/'comparison.png',columns=5,cell=(345,415));rgb=np.repeat(inp['mean'][:,:,None],3,axis=2);rgb[original]=[255,210,0];rgb[mask&~original]=[0,225,240];rgb[guide&~mask]=[255,120,40];labelled(rgb,['橙=仍从6/20收回的区域；非已确认误检','黄色保留，青色补充；旧bit数据离线处理',rec['group_id']]).save(target/'retracted.png')
        by_board[rec['sample']].append((f'{rec["low"]}/{rec["high"]} '+('旧姿态' if rec['role']=='development_hold_check' else ''),Image.open(target/'selected.png').copy()))
        if rec['role']!='exposure_stress':primary.append((rec['sample']+' '+('旧姿态' if rec['role']=='development_hold_check' else '主组'),Image.open(target/'selected.png').copy()))
        if rec['group_id']==annotation['group_id']:
            a=np.asarray(points);x0=int(a[:,0].min())-35;x1=int(a[:,0].max())+40;y0=int(a[:,1].min())-35;y1=int(a[:,1].max())+35;ct=[]
            for name,plane in modes.items():
                rgb=np.asarray(Image.open(target/(name+'.png')))[100:];crop=Image.fromarray(rgb[y0:y1,x0:x1]).resize(((x1-x0)*2,(y1-y0)*2),Image.Resampling.NEAREST);crop.save(target/(name+'_weak_crop.png'));ct.append((names[name]+f'：{path_support(plane,points)}/268',crop))
            ct.append(('原片CH4 高曝光800',Image.fromarray(inp['planes']['gray'][7,y0:y1,x0:x1]).convert('RGB').resize(((x1-x0)*2,(y1-y0)*2),Image.Resampling.NEAREST)));sheet(ct,out/'sample004_weak_comparison.png',columns=3,cell=(565,285))
        cards.append(f'<section><h2>{rec["sample"]} {rec["low"]}/{rec["high"]} {rec["role"]}</h2><p>套内侧增厚{row["side_added_pixels"]}px，仍从6/20收回{row["retracted6_20_pixels"]}px；原8/20全部保留</p><a href="{rec["group_id"]}/comparison.png"><img src="{rec["group_id"]}/comparison.png"></a><p>'+ ' · '.join(f'<a href="{rec["group_id"]}/{k}.png">{names[k]}原尺寸</a>' for k in modes)+f' · <a href="{rec["group_id"]}/retracted.png">橙色收回区域</a></p></section>');print('SLEEVE_FINAL',rec['group_id'],'side',row['side_added_pixels'],'retracted',row['retracted6_20_pixels'],'path',row.get('selected_path_positions'),flush=True)
    write(out/'DATASET_RESULTS.json',results);write(out/'CONTRACT_CHECKS.json',checks);csv_write(out/'SUMMARY.csv',[{k:v for k,v in r.items() if k!='duplicate_result_folders'} for r in results]);sheet(primary,out/'five_primary_groups.png',columns=5,cell=(330,400))
    for sample,tiles in by_board.items():sheet(tiles,out/(sample+'_all_groups.png'),columns=3,cell=(370,430))
    # Old proposed paths are post-selection checks, never background labels.
    draft=[]
    for sample in ('sample004','sample005'):
        pp=REPO/f'YMW/handoffs/p0_annotation_multiview_20261026/{sample}_annotations_DRAFT.json';d=read(pp);rec=next(x for x in data if x['group_id']==d['group_id']);summary=read(Path(rec['root'])/'summary.json');roi=summary['roi_xywh'];rr=[]
        with np.load(out/rec['group_id']/'masks.npz',allow_pickle=False) as z:mm={k:z[k].copy() for k in ('original','guide6_20','candidate')}
        for item in d['annotations']:
            if item['class']!='scratch':continue
            a=np.rint(np.asarray(item['points_xy'])-np.array(roi[:2])).astype(int);p=np.zeros_like(mm['candidate'],np.uint8);cv2.polylines(p,[a.reshape(-1,1,2)],False,1,1);ys,xs=np.nonzero(p);counts={k:int(cv2.dilate(v.astype('uint8'),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)))[ys,xs].sum()) for k,v in mm.items()};rr.append(dict(annotation_id=item['annotation_id'],state=item['state'],path_pixels=len(xs),near_path_radius3=counts))
        draft.append(dict(group_id=d['group_id'],reference_path=str(pp),reference_sha256=sha(pp),draft_not_truth=True,not_recall=True,paths=rr))
    write(out/'DRAFT_PATH_POSTCHECKS.json',draft)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>6/20侧向保护套实验</title><style>body{font-family:system-ui;background:#eef2f7;color:#17314c;margin:24px}main{max-width:1800px;margin:auto}section{background:white;padding:14px;margin:20px 0}img{max-width:100%;height:auto}p{line-height:1.7}</style><main><h1>旧8/20作下限，6/20作侧向膨胀上限</h1><p>主干允许套内适度增厚；真实端部延伸和独立有种子弱线另作受控补充。方向、实际连续像素及防碰合约束继续有效。黄=旧8/20，青=新增，橙=收回而非误检真值。仅三块开发板，未切换现用程序。</p><p><a href="sample004_weak_comparison.png">004原片局部</a> · <a href="SEARCH.csv">保护套联合参数</a> · <a href="SUMMARY.csv">23组指标</a> · <a href="../run_01/index.html">66组阈值对照</a> · <a href="../body_01/index.html">不增厚对照</a></p>'+''.join(cards)+'</main>',encoding='utf-8')
    need(sha(out/'FROZEN_CONFIG.json')==frozen_sha,'Chosen sleeve config changed');need(all(sha(p)==v for p,v in snapshots.items()),'Inputs changed');need(all(sha(p)==v for p,v in sources.items()),'Code changed during run')
    write(out/'VERIFICATION.json',dict(status='PASS',source_sha256=sources,input_files_sha256=snapshots,input_unique_files=len(snapshots),initial_joint_configs=7128,body_configs=1782,sleeve_shortlist=len(shortlist),sleeve_configs=len(search),original_b1_differences=reproduced,groups=23,frames=184,physical_boards=3,
        all_original8_20_pixels_retained=True,side_added_outside6_20_zero=True,side_distance_cap_pass=True,new_anchor_merges_zero=True,unseeded_components_with_additions_zero=True,matching_threshold_containment=True,manual_path_used_for_development_selection=True,manual_path_used_for_inference=False,independent_test=False,FPGA_changed=False,bit_programmed=False,new_captures=0,formal_detector_changed=False,runtime_seconds=time.monotonic()-start))
    print('SLEEVE_STUDY_PASS',round(time.monotonic()-start,2),'seconds',flush=True)
if __name__=='__main__':main()
