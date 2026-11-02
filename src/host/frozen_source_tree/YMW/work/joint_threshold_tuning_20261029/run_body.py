"""Second phase: original8/20 immutable, controlled6/20 and lower-weak additions."""
import argparse,hashlib,importlib.util,itertools,json,math,socket,sys,time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from joint_gate import build_cache,cutoff
from body_guard import supplements,extend
from component_gate import geometry
from run_joint import add_eval,topology,cid
from run_study import read,write,sha,labelled,sheet,csv_write

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2];FIRST=Path('E:/GuangjianData/reviews/joint_threshold_tuning_20261029/run_01');PREVIOUS=Path('E:/GuangjianData/reviews/seeded_component_tuning_20261029/run_01')
def need(x,why):
    if not x:raise ValueError(why)
def path_support(mask,points):
    a=np.asarray(points);x=a[:,0].astype(int);y=np.rint(a[:,1]).astype(int);return int(mask[y[:,None]+np.arange(-3,4),x[:,None]].any(axis=1).sum())
def isolate_metrics(mask,memo):
    key=hashlib.sha256(mask.tobytes()).digest()
    if key in memo:return memo[key]
    n,labels,stats,_=cv2.connectedComponentsWithStats(mask.astype('uint8'),connectivity=8);compact_count=compact_area=0
    for label in range(1,n):
        x,y,w,h,area=map(int,stats[label]);g=geometry(np.pad(labels[y:y+h,x:x+w]==label,1))
        if area<6 or g['two_sweep_span_px']<6 or g['line_fraction']<.5:compact_count+=1;compact_area+=area
    answer=dict(area=int(mask.sum()),components=n-1,compact_components=compact_count,compact_pixels=compact_area);memo[key]=answer;return answer
def body_rank(r):return (-r['development']['sample004']['path_positions'],r['balanced_compact_count_per_mp'],r['balanced_added_area_per_mp'],r['reach'],r['half_width'],r['id'])

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    def deny(*a,**k):raise RuntimeError('Offline only')
    socket.socket=deny;plan=read(HERE/'BODY_PLAN.json');write(out/'BODY_PLAN.json',plan);data=read(FIRST/'DATASETS.json');first_receipt=read(FIRST/'VERIFICATION.json');need(first_receipt['status']=='PASS','Initial joint phase not verified')
    snapshots=first_receipt['input_files_sha256'];need(all(sha(p)==v for p,v in snapshots.items()),'Input changed since joint phase');sources={str(p):sha(p) for p in list(HERE.glob('*.py'))+[HERE/'BODY_PLAN.json']}
    for directory,names in [(HERE.parent/'seeded_component_tuning_20261029',['seeded_gate.py','run_study.py']),(HERE.parent/'weak_component_experiment_20261029',['component_gate.py','fragment_chain.py'])]:
        for name in names:sources[str(directory/name)]=sha(directory/name)
    spec=importlib.util.spec_from_file_location('_body_app',REPO/'YMW/work/b1_detection_console_20261027/common.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app);app.verify_app();vendor,binding=app.verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
    from light_inspection.real_baseline import hysteresis_connect
    annotation_path=REPO/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json';annotation=read(annotation_path);points=annotation['path_points'];sources[str(annotation_path)]=sha(annotation_path);reproduced={}
    def get(rec,weaks):
        root=Path(rec['root'])
        with np.load(root/'arrays/original_eight_frames.npz',allow_pickle=False) as z:planes={k:z[k].copy() for k in z.files}
        with np.load(root/'arrays/all8_B1.npz',allow_pickle=False) as z:saved={k:z[k].copy() for k in z.files}
        fused=fusion.fuse_two_stage(planes['residual_n'],planes['valid'],board=planes['board'])['final'];diff={k:int(np.count_nonzero(fused[k]!=saved[k])) for k in saved};need(not any(diff.values()),'Frozen B1 mismatch');reproduced[rec['group_id']]=diff
        r=np.abs(fused['residual_n'].astype('int32'));v=~fused['unknown'];b=planes['board'];guide=hysteresis_connect(r,v,486,1620)['mask']&b;original=saved['mask'];caches={}
        old_features=read(PREVIOUS/'cache'/(rec['group_id']+'.json'))
        with np.load(PREVIOUS/'cache'/(rec['group_id']+'.npz'),allow_pickle=False) as z:ll=z['labels'].copy()
        ids=[x['label'] for x in old_features['rows'] if x['peak_n']>972 and x['area']>=3 and x['two_sweep_span_px']>=10 and x['line_fraction']>=.6 and x['median_width_proxy_px']<=5];anchor=np.isin(ll,ids)
        for weak in sorted(set([6.]+list(weaks))):
            wp=hysteresis_connect(r,v,cutoff(weak),1620)['mask']&b;plain14=hysteresis_connect(r,v,cutoff(weak),1134)['mask']&b;c=build_cache(r,v,b,guide,wp,plain14,planes['gray'],planes['valid'],policy='fixed6_20_isolated_supplements');caches[weak]=c
        return dict(record=rec,r=r,v=v,board=b,guide=guide,original=original,caches=caches,planes=planes,anchor=anchor,mean=np.rint(planes['gray'].astype('float32').mean(0)).astype('uint8'),tip_cache={},risk_cache={})
    dev={}
    for rec in data:
        if rec['role']=='development':dev[rec['sample']]=get(rec,plan['weak']);print('BODY_CACHE',rec['sample'],flush=True)
    search=[];plain_cache={};baseline_cache={}
    for weak,strong,gate in itertools.product(plan['weak'],plan['strong'],plan['gates']):
        c={**plan['gates'][gate],'weak':weak,'strong':strong,'policy':'fixed6_20_isolated_supplements'};prepared={}
        for sample,inp in dev.items():
            base,anchor,s6,low=supplements(inp['caches'][6.],inp['caches'][weak],c,inp['original']);isolated=(s6|low)&~inp['original'];im=isolate_metrics(isolated,inp['risk_cache']);mp=inp['board'].sum()/1e6
            _,bl=cv2.connectedComponents(base.astype('uint8'),connectivity=8);seed_labels=set(np.unique(bl[base&(inp['r']>81*strong)]).tolist())
            key=(sample,weak,strong)
            if key not in plain_cache:plain_cache[key]=hysteresis_connect(inp['r'],inp['v'],cutoff(weak),cutoff(strong))['mask']&inp['board']
            prepared[sample]=(base,anchor,s6,low,im,mp,(bl,seed_labels),plain_cache[key])
        for reach,half in itertools.product(plan['terminal_extension']['reach_px'],plan['terminal_extension']['half_width_px']):
            records={}
            for sample,inp in dev.items():
                base,anchor,s6,low,im,mp,prep,ordinary=prepared[sample];res=extend(base,anchor,ordinary,inp['r'],c,reach,half,inp['tip_cache'],prep);mask=res['candidate']
                anchor_total=int(inp['anchor'].sum());retained=int((inp['anchor']&mask).sum())/anchor_total if anchor_total else 1.
                records[sample]=dict(path_positions=path_support(mask,points) if sample=='sample004' else None,added_pixels=int((mask&~inp['original']).sum()),extension_pixels=int(res['extension'].sum()),retracted_6_20_pixels=int((inp['guide']&~mask).sum()),retained_anchor_fraction=retained,
                    isolated_pixels=im['area'],compact_components=im['compact_components'],compact_pixels=im['compact_pixels'],compact_count_per_mp=im['compact_components']/mp,isolated_area_per_mp=im['area']/mp,added_area_per_mp=float((mask&~inp['original']).sum()/mp))
            count=float(np.mean([x['compact_count_per_mp'] for x in records.values()]));isolated=float(np.mean([x['isolated_area_per_mp'] for x in records.values()]));area=float(np.mean([x['added_area_per_mp'] for x in records.values()]));s=plan['selection']
            okay=records['sample004']['path_positions']>=s['known004_path_floor'] and all(x['retained_anchor_fraction']>=s['conservative_anchor_retention_each_board'] for x in records.values()) and count<=s['compact_components_per_mp_budget'] and isolated<=s['isolated_added_area_per_mp_budget']
            config=dict(**c,gate=gate,reach=reach,half_width=half);search.append(dict(id=cid(config),config=config,weak=weak,strong=strong,gate=gate,reach=reach,half_width=half,qualified=bool(okay),balanced_compact_count_per_mp=count,balanced_added_area_per_mp=area,development=records))
    passing=sorted((r for r in search if r['qualified']),key=body_rank);need(passing,'No body-safe candidate qualifies; do not silently relax requirements');best=passing[0];chosen=best['config'];write(out/'SEARCH_RESULTS.json',search)
    flat=[]
    for rr in sorted(search,key=lambda r:(not r['qualified'],body_rank(r))):
        row={k:v for k,v in rr.items() if k not in ('config','development')};row.update(rr['config'])
        for sample,m in rr['development'].items():row.update({sample+'_'+k:v for k,v in m.items()})
        flat.append(row)
    csv_write(out/'SEARCH.csv',flat);frozen=dict(schema='original8-protected-tip-extension-v1',selected=best,immutable='original8/20',six_twenty_is_guide_only=True,plan_sha256=sha(out/'BODY_PLAN.json'),strict_comparisons=True,profile=[13,2.5],chain='off',frozen_before_other_groups=True,development_only=True);write(out/'FROZEN_CONFIG.json',frozen);frozen_sha=sha(out/'FROZEN_CONFIG.json')
    print('BODY_FROZEN',json.dumps(chosen),'known_path',best['development']['sample004']['path_positions'],'qualified',len(passing),flush=True)
    results=[];contracts=[];gallery=[];by_board={s:[] for s in dev};primary=[]
    for rec in data:
        inp=dev[rec['sample']] if rec['role']=='development' else get(rec,[chosen['weak']]);base,anchor,s6,low=supplements(inp['caches'][6.],inp['caches'][chosen['weak']],chosen,inp['original']);ordinary=hysteresis_connect(inp['r'],inp['v'],cutoff(chosen['weak']),cutoff(chosen['strong']))['mask']&inp['board'];res=extend(base,anchor,ordinary,inp['r'],chosen,chosen['reach'],chosen['half_width'],inp['tip_cache']);mask=res['candidate'];orig=inp['original'];guide=inp['guide'];added=mask&~orig
        t=topology(base,mask);check=dict(group_id=rec['group_id'],original_losses=int((orig&~mask).sum()),outside_matching_threshold=int((mask&~ordinary).sum()),new_base_merges=t['merged_reference_label_clusters'],added_outside_declared_routes=int((added&~(s6|low|res['extension'])).sum()),extension_outside_tip_corridors=int((res['extension']&~res['allowed_tip_regions']).sum()))
        _,lab=cv2.connectedComponents(mask.astype('uint8'),connectivity=8);bad=0
        for label in np.unique(lab[added]):
            if label and not ((lab==label)&(inp['r']>cutoff(chosen['strong']))&inp['v']).any():bad+=1
        check['unseeded_components_with_additions']=bad;need(not any(v for k,v in check.items() if k!='group_id'),'Body output contract failed');contracts.append(check)
        row=dict(**rec,config_id=best['id'],weak=chosen['weak'],strong=chosen['strong'],gate=chosen['gate'],reach=chosen['reach'],half_width=chosen['half_width'],original_pixels=int(orig.sum()),unconditional_6_20_pixels=int(guide.sum()),candidate_pixels=int(mask.sum()),added_pixels=int(added.sum()),isolated_supplement_pixels=int((s6|low).sum()),terminal_extension_pixels=int(res['extension'].sum()),retracted_from_6_20_pixels=int((guide&~mask).sum()),tip_count=res['tip_count'],ordinary_pixels=int(ordinary.sum()))
        if rec['group_id']==annotation['group_id']:row.update(original_path_positions=path_support(orig,points),guide_path_positions=path_support(guide,points),selected_path_positions=path_support(mask,points),ordinary_path_positions=path_support(ordinary,points))
        target=out/rec['group_id'];target.mkdir();np.savez_compressed(target/'masks.npz',original=orig,guide6_20=guide,isolated6=s6,isolated_low=low,ordinary=ordinary,**{k:v for k,v in res.items() if k!='tip_count'});write(target/'METRICS.json',row);results.append(row)
        with np.load(PREVIOUS/rec['group_id']/'masks.npz',allow_pickle=False) as z:previous=z['candidate'].copy()
        modes={'original':orig,'guide6_20':guide,'previous':previous,'selected':mask};names={'original':'原8/20','guide6_20':'未经收敛的6/20','previous':'上一版：完整保护6/20','selected':'主干保护＋端部受控延伸'};tiles=[]
        for name,plane in modes.items():
            rgb=np.repeat(inp['mean'][:,:,None],3,axis=2);rgb[orig]=[255,210,0];rgb[plane&~orig]=[0,225,240];im=labelled(rgb,[f'{rec["sample"]} | {names[name]} | {int(plane.sum())}px','黄=原8/20，青=相对原8/20新增；不是置信概率',rec['group_id']]);im.save(target/(name+'.png'));need(np.array_equal(np.asarray(Image.open(target/(name+'.png')))[100:],rgb),'Body image mismatch');tiles.append((names[name],im))
        sheet(tiles,target/'comparison.png',columns=4,cell=(370,430));removed_rgb=np.repeat(inp['mean'][:,:,None],3,axis=2);removed_rgb[orig]=[255,210,0];removed_rgb[added]=[0,225,240];removed_rgb[guide&~mask]=[255,120,40];labelled(removed_rgb,['橙=从6/20收回，非已确认误检','黄=原8/20保护，青=受控新增',rec['group_id']]).save(target/'retracted.png')
        by_board[rec['sample']].append((f'{rec["low"]}/{rec["high"]} '+('旧姿态' if rec['role']=='development_hold_check' else ''),Image.open(target/'selected.png').copy()))
        if rec['role']!='exposure_stress':primary.append((rec['sample']+' '+rec['role'],Image.open(target/'selected.png').copy()))
        if rec['group_id']==annotation['group_id']:
            a=np.asarray(points);x0=int(a[:,0].min())-35;x1=int(a[:,0].max())+40;y0=int(a[:,1].min())-35;y1=int(a[:,1].max())+35;ct=[]
            for name,plane in modes.items():
                rgb=np.asarray(Image.open(target/(name+'.png')))[100:];crop=Image.fromarray(rgb[y0:y1,x0:x1]).resize(((x1-x0)*2,(y1-y0)*2),Image.Resampling.NEAREST);crop.save(target/(name+'_weak_crop.png'));ct.append((names[name]+f'：{path_support(plane,points)}/268',crop))
            for frame in (3,7):ct.append((f'原片CH{frame//2+1} 高曝光800',Image.fromarray(inp['planes']['gray'][frame,y0:y1,x0:x1]).convert('RGB').resize(((x1-x0)*2,(y1-y0)*2),Image.Resampling.NEAREST)))
            sheet(ct,out/'sample004_weak_comparison.png',columns=3,cell=(565,285))
        gallery.append(f'<section><h2>{rec["sample"]} {rec["low"]}/{rec["high"]} {rec["role"]}</h2><p>从6/20收回{row["retracted_from_6_20_pixels"]}px，保留旧8/20全部像素</p><a href="{rec["group_id"]}/comparison.png"><img src="{rec["group_id"]}/comparison.png"></a><p>'+ ' · '.join(f'<a href="{rec["group_id"]}/{k}.png">{names[k]}原尺寸</a>' for k in modes)+f' · <a href="{rec["group_id"]}/retracted.png">橙色收回区域</a></p></section>');print('BODY_FINAL',rec['group_id'],'retracted',row['retracted_from_6_20_pixels'],'path',row.get('selected_path_positions'),flush=True)
    write(out/'DATASET_RESULTS.json',results);write(out/'CONTRACT_CHECKS.json',contracts);csv_write(out/'SUMMARY.csv',[{k:v for k,v in r.items() if k!='duplicate_result_folders'} for r in results]);sheet(primary,out/'five_primary_groups.png',columns=5,cell=(330,400))
    for sample,tiles in by_board.items():sheet(tiles,out/(sample+'_all_groups.png'),columns=3,cell=(370,430))
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>原主干保护与阈值联合收敛</title><style>body{font-family:system-ui;background:#eef2f7;color:#17314c;margin:24px}main{max-width:1700px;margin:auto}section{background:white;padding:14px;margin:20px 0}img{max-width:100%;height:auto}p{line-height:1.7}</style><main><h1>原8/20主干保护：处理6/20自带的外扩和合并</h1><p>6/20仅作引导，不再逐像素保护。黄=原8/20，青=受控新增，橙=收回的6/20像素而非误检真值。有种子端部延伸只选真实候选像素，不画桥。开发数据仅三块板；007～010未用，未切换现用程序。</p><p><a href="sample004_weak_comparison.png">004弱段与原片</a> · <a href="SEARCH.csv">1782配置</a> · <a href="SUMMARY.csv">全部组结果</a> · <a href="../run_01/index.html">先前完整保护6/20对照</a></p>'+''.join(gallery)+'</main>',encoding='utf-8')
    need(sha(out/'FROZEN_CONFIG.json')==frozen_sha,'Frozen body config changed');need(all(sha(p)==v for p,v in snapshots.items()),'Sources changed at end');need(all(sha(p)==v for p,v in sources.items()),'Code changed during run')
    write(out/'VERIFICATION.json',dict(status='PASS',source_sha256=sources,input_files_sha256=snapshots,input_unique_files=len(snapshots),search_configs=len(search),qualified_configs=len(passing),groups=23,frames=184,physical_boards=3,original_b1_differences=reproduced,all_original8_20_pixels_retained=True,six_twenty_pixels_may_be_retracted=True,new_anchor_component_merges_zero=True,unseeded_added_components_zero=True,output_subset_matching_threshold=True,no_gap_paint=True,annotation_used_for_development_selection=True,annotation_used_for_inference=False,independent_test=False,FPGA_changed=False,bit_programmed=False,new_captures=0,formal_detector_changed=False,runtime_seconds=time.monotonic()-start))
    print('BODY_STUDY_PASS',round(time.monotonic()-start,2),'seconds',flush=True)
if __name__=='__main__':main()
