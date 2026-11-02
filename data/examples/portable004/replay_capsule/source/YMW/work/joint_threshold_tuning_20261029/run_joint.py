"""Joint threshold grid with predeclared selection and frozen other-group checks."""
import argparse,csv,hashlib,importlib.util,itertools,json,math,socket,sys,time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from joint_gate import build_cache,decide,output,cutoff
from run_study import read,write,sha,labelled,sheet,csv_write

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
PREVIOUS=Path('E:/GuangjianData/reviews/seeded_component_tuning_20261029/run_01')
def need(ok,why):
    if not ok:raise ValueError(why)
def cid(c):return hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()[:12]
def cfg(weak,strong,policy,area,geom,width,raw):return dict(weak=weak,strong=strong,policy=policy,min_area=area,span=geom[0],line=geom[1],width=width,raw_fraction=raw[0],raw_mean=raw[1])
def rank(r):return (-r['development']['sample004']['path_positions'],r['balanced_compact_count_per_mp'],r['balanced_compact_area_per_mp'],r['balanced_added_area_per_mp'],r['id'])
def topology(reference,core):
    _,rl=cv2.connectedComponents(reference.astype('uint8'),connectivity=8);_,cl=cv2.connectedComponents(core.astype('uint8'),connectivity=8)
    pairs=np.unique(np.c_[cl[reference],rl[reference]],axis=0);counts=np.bincount(pairs[:,0]) if len(pairs) else np.zeros(1,int)
    return dict(core_growth_pixels=int((core&~reference).sum()),merged_reference_label_clusters=int((counts[1:]>1).sum()),reference_labels_absorbed_into_merges=int(counts[1:][counts[1:]>1].sum()))
def add_eval(cache,anchor,points):
    cache['core_topology']=topology(cache['reference'],cache['protected']);cache['anchor_total']=int(anchor.sum());cache['anchor_in_core']=int((anchor&cache['protected']).sum())
    for r in cache['rows']:
        x,y,w,h=r['bbox_xywh'];piece=cache['labels'][y:y+h,x:x+w]==r['label'];r['reference_anchor_pixels']=int((piece&anchor[y:y+h,x:x+w]).sum())
    if points is not None:
        a=np.asarray(points);xs=a[:,0].astype(int);ys=np.rint(a[:,1]).astype(int);yy=ys[:,None]+np.arange(-3,4);xx=np.broadcast_to(xs[:,None],yy.shape)
        cache['eval_path_labels']=cache['labels'][yy,xx];cache['eval_path_core']=cache['protected'][yy,xx]
    return cache
def metrics(cache,config):
    admitted,routes=decide(cache,config);r=cache['rows'];area=np.array([v['area'] for v in r],dtype=int);anchor=np.array([v['reference_anchor_pixels'] for v in r],dtype=int)
    compact=np.array([v['area']<6 or v['two_sweep_span_px']<6 or v['line_fraction']<.5 for v in r],dtype=bool);branches=np.array([v['branch_clusters'] for v in r],dtype=int)
    mp=float(cache['board'].sum())/1e6;added=int(area[admitted].sum())+cache['core_topology']['core_growth_pixels']
    support=None
    if 'eval_path_labels' in cache:support=int((cache['eval_path_core']|np.r_[False,admitted][cache['eval_path_labels']]).any(axis=1).sum())
    return dict(added_pixels=added,filtered_piece_pixels=int(area[admitted].sum()),added_components=int(admitted.sum()),compact_components=int((admitted&compact).sum()),compact_pixels=int(area[admitted&compact].sum()),
        branch_clusters_in_added_pieces=int(branches[admitted].sum()),retained_anchor_fraction=float((cache['anchor_in_core']+anchor[admitted].sum())/cache['anchor_total']) if cache['anchor_total'] else 1.,
        compact_count_per_mp=float((admitted&compact).sum()/mp),compact_area_per_mp=float(area[admitted&compact].sum()/mp),added_area_per_mp=added/mp,path_positions=support,
        rejected_attached_pixels=int(cache['rejected_attached'].sum()),**cache['core_topology'],routes=routes),admitted
def evaluate(config,caches,plan):
    dev={};finger=hashlib.sha256()
    for sample,by_key in caches.items():
        c=by_key[(config['weak'],config['policy'])];m,a=metrics(c,config);dev[sample]=m;finger.update(a.tobytes());finger.update(str(c['core_topology']).encode())
    count=float(np.mean([r['compact_count_per_mp'] for r in dev.values()]));area=float(np.mean([r['compact_area_per_mp'] for r in dev.values()]));added=float(np.mean([r['added_area_per_mp'] for r in dev.values()]));s=plan['selection_before_hold_checks']
    okay=config['policy']==s['primary_safety_policy'] and dev['sample004']['path_positions']>=s['minimum_known004_path_positions'] and all(r['retained_anchor_fraction']>=s['minimum_old_conservative_line_anchor_retention_each_board'] for r in dev.values()) and count<=s['maximum_board_balanced_compact_components_per_mp'] and added<=s['maximum_board_balanced_added_area_per_mp']
    return dict(id=cid(config),config=config,qualified=bool(okay),balanced_compact_count_per_mp=count,balanced_compact_area_per_mp=area,balanced_added_area_per_mp=added,development=dev,prediction_fingerprint=finger.hexdigest())

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    def deny(*a,**k):raise RuntimeError('Offline study prohibits sockets')
    socket.socket=deny;start=time.monotonic();plan=read(HERE/'PLAN.json');write(out/'PLAN.json',plan);data=read(PREVIOUS/'DATASETS.json');need(len(data)==23,'Review inventory change')
    write(out/'DATASETS.json',data);sources={str(p):sha(p) for p in list(HERE.glob('*.py'))+[HERE/'PLAN.json']}
    for directory,names in [(HERE.parent/'seeded_component_tuning_20261029',['seeded_gate.py','run_study.py']),(HERE.parent/'weak_component_experiment_20261029',['component_gate.py','fragment_chain.py'])]:
        for name in names:sources[str(directory/name)]=sha(directory/name)
    spec=importlib.util.spec_from_file_location('_joint_app',REPO/'YMW/work/b1_detection_console_20261027/common.py');app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app);app.verify_app();vendor,binding=app.verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
    from light_inspection.real_baseline import hysteresis_connect
    annotation_path=REPO/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json';annotation=read(annotation_path);sources[str(annotation_path)]=sha(annotation_path)
    snapshots={};reproduced={};dev_inputs={};caches={};threshold_only=[];simple_comparison=[]
    def get_input(rec):
        root=Path(rec['root']);seal=read(root/'OUTPUT_MANIFEST.json');audit=read(root/'input_audit.json');files={str(root/k):v for k,v in seal['files_sha256'].items()};files.update(audit['verified_artifacts']);files[str(root/'OUTPUT_MANIFEST.json')]=sha(root/'OUTPUT_MANIFEST.json')
        for path,digest in files.items():
            if path not in snapshots:need(sha(path)==digest,'Source SHA mismatch '+path)
            need(path not in snapshots or snapshots[path]==digest,'Conflicting seals');snapshots[path]=digest
        with np.load(root/'arrays/original_eight_frames.npz',allow_pickle=False) as z:planes={k:z[k].copy() for k in z.files}
        with np.load(root/'arrays/all8_B1.npz',allow_pickle=False) as z:saved={k:z[k].copy() for k in z.files}
        fused=fusion.fuse_two_stage(planes['residual_n'],planes['valid'],board=planes['board'])['final'];diff={k:int(np.count_nonzero(saved[k]!=fused[k])) for k in saved};need(not any(diff.values()),'Frozen B1 mismatch');reproduced[rec['group_id']]=diff
        response=np.abs(fused['residual_n'].astype('int32'));valid=~fused['unknown'];board=planes['board'];reference=hysteresis_connect(response,valid,486,1620)['mask']&board
        need(not (saved['mask']&~reference).any(),'Original result lost');mean=np.rint(planes['gray'].astype('float32').mean(0)).astype('uint8')
        # Use the same already-published conservative anchors, mapped to native coordinates.
        old_features=read(PREVIOUS/'cache'/(rec['group_id']+'.json'));anchor=np.zeros_like(board)
        with np.load(PREVIOUS/'cache'/(rec['group_id']+'.npz'),allow_pickle=False) as z:old_labels=z['labels'].copy()
        ids=[r['label'] for r in old_features['rows'] if r['peak_n']>972 and r['area']>=3 and r['two_sweep_span_px']>=10 and r['line_fraction']>=.6 and r['median_width_proxy_px']<=5];anchor=np.isin(old_labels,ids)
        return dict(record=rec,planes=planes,response=response,valid=valid,board=board,reference=reference,original=saved['mask'],mean=mean,anchor=anchor,summary=read(root/'summary.json'))
    def build_for(inp,weak,policy):
        response,valid,board=inp['response'],inp['valid'],inp['board'];wp=hysteresis_connect(response,valid,cutoff(weak),1620)['mask']&board;ordinary=hysteresis_connect(response,valid,cutoff(weak),1134)['mask']&board
        c=build_cache(response,valid,board,inp['reference'],wp,ordinary,inp['planes']['gray'],inp['planes']['valid'],policy=policy)
        return add_eval(c,inp['anchor'],annotation['path_points'] if inp['record']['group_id']==annotation['group_id'] else None)
    def support(mask):
        xy=np.asarray(annotation['path_points']);x=xy[:,0].astype(int);y=np.rint(xy[:,1]).astype(int);return int(mask[y[:,None]+np.arange(-3,4),x[:,None]].any(axis=1).sum())
    for rec in data:
        if rec['role']!='development':continue
        inp=get_input(rec);sample=rec['sample'];dev_inputs[sample]=inp;caches[sample]={}
        for weak in plan['grid']['weak']:
            for policy in plan['grid']['protection_policy']:
                c=build_for(inp,weak,policy);caches[sample][(weak,policy)]=c
                print('CACHE',sample,weak,policy,'pieces',len(c['rows']),'core_growth',c['core_topology']['core_growth_pixels'],flush=True)
            for strong in plan['grid']['strong']:
                mask=hysteresis_connect(inp['response'],inp['valid'],cutoff(weak),81*strong)['mask']&inp['board'];top=topology(inp['reference'],mask)
                threshold_only.append(dict(sample=sample,weak=weak,strong=strong,candidate_pixels=int(mask.sum()),path_positions=support(mask) if sample=='sample004' else None,**top))
    previous_reproduction=[]
    for sample,inp in dev_inputs.items():
        old_config=cfg(6,14,'fixed6_20_isolated_supplements',6,[8,.6],5,[.85,3.]);res,_=output(caches[sample][(6,'fixed6_20_isolated_supplements')],old_config)
        with np.load(PREVIOUS/inp['record']['group_id']/'masks.npz',allow_pickle=False) as z:diff=int(np.count_nonzero(res['candidate']!=z['candidate']))
        need(diff==0,'Weak6 reproduction differs from prior chosen version');previous_reproduction.append(dict(sample=sample,candidate_differences=diff))
    write(out/'PREVIOUS_CONFIG_REPRODUCTION.json',previous_reproduction)
    g=plan['grid'];search=[]
    for weak,strong,policy,area,geom,width,raw in itertools.product(g['weak'],g['strong'],g['protection_policy'],g['min_area'],g['geometry'],g['width'],g['raw']):search.append(evaluate(cfg(weak,strong,policy,area,geom,width,raw),caches,plan))
    passing=sorted((r for r in search if r['qualified']),key=rank);need(passing,'No joint configuration qualifies; retain previous version');best=passing[0]
    # Also show each weak/strong pair's best qualifying tuning; missing pairs stay missing.
    per_pair=[]
    for weak,strong in itertools.product(g['weak'],g['strong']):
        rr=sorted((r for r in passing if r['config']['weak']==weak and r['config']['strong']==strong),key=rank)
        per_pair.append(dict(weak=weak,strong=strong,qualifying_configs=len(rr),best=rr[0] if rr else None))
    frozen=dict(schema='joint-weak-strong-admission-config-v1',selected=best,reference=[6,20],fixed_profile=[13,2.5],chain='off',strict_comparisons=True,plan_sha256=sha(out/'PLAN.json'),frozen_before_other_groups=True,development_only=True)
    write(out/'FROZEN_CONFIG.json',frozen);frozen_sha=sha(out/'FROZEN_CONFIG.json');write(out/'SEARCH_RESULTS.json',search);write(out/'PAIR_BEST.json',per_pair);csv_write(out/'THRESHOLD_ONLY_DEVELOPMENT.csv',threshold_only)
    flat=[]
    for r in sorted(search,key=lambda r:(not r['qualified'],rank(r))):
        row=dict(id=r['id'],qualified=r['qualified'],**r['config'],balanced_compact_count_per_mp=r['balanced_compact_count_per_mp'],balanced_added_area_per_mp=r['balanced_added_area_per_mp'])
        for sample,m in r['development'].items():row.update({sample+'_'+k:v for k,v in m.items() if k not in ('routes',)})
        flat.append(row)
    csv_write(out/'SEARCH.csv',flat);print('FROZEN',json.dumps(best['config']),'path',best['development']['sample004']['path_positions'],'qualified',len(passing),flush=True)
    # Finite developmental sensitivity record. It cannot change the frozen choice.
    alternatives={}
    for weak,strong in itertools.product(g['weak'],g['strong']):
        c={**best['config'],'weak':weak,'strong':strong};alternatives[f'{weak}/{strong}']=evaluate(c,caches,plan)
    write(out/'FIXED_RESTRICTIONS_66_PAIRS.json',alternatives)
    result_rows=[];checks=[];keytiles=[];cards=[];by_board={s:[] for s in ('sample003','sample004','sample005')}
    for rec in data:
        inp=dev_inputs[rec['sample']] if rec['role']=='development' else get_input(rec);chosen=best['config'];c=caches[rec['sample']][(chosen['weak'],chosen['policy'])] if rec['role']=='development' else build_for(inp,chosen['weak'],chosen['policy']);result,routes=output(c,chosen);m,admitted=metrics(c,chosen);reference=inp['reference'];mask=result['candidate']
        ordinary=hysteresis_connect(inp['response'],inp['valid'],cutoff(chosen['weak']),81*chosen['strong'])['mask']&inp['board'];need(not (mask&~ordinary).any(),'Selected not subset of matching plain threshold')
        with np.load(PREVIOUS/rec['group_id']/'masks.npz',allow_pickle=False) as z:previous=z['candidate'].copy();need(np.array_equal(reference,z['protected']),'Reference changed from previous run')
        original=inp['original'];added=result['supplement'];near=cv2.dilate(reference.astype('uint8'),np.ones((3,3),'uint8')).astype(bool)
        check=dict(group_id=rec['group_id'],original_losses=int((original&~mask).sum()),reference_losses=int((reference&~mask).sum()),pixels_outside_matching_threshold=int((mask&~ordinary).sum()),added_eight_adjacent_reference=int((added&near).sum()),unseeded_added_components=sum(bool(a and r['peak_n']<=81*chosen['strong']) for a,r in zip(admitted,c['rows'])),new_merges_of_reference=topology(reference,mask)['merged_reference_label_clusters'])
        need(not any(v for k,v in check.items() if k!='group_id'),'Final structural guard failed');checks.append(check)
        target=out/rec['group_id'];target.mkdir();np.savez_compressed(target/'masks.npz',original=original,reference=reference,previous=previous,ordinary=ordinary,**result,component_labels=c['labels'],admitted_component_ids=np.flatnonzero(admitted)+1)
        f,mm=c['profiles']['13/2.5'];margin=np.minimum(f/chosen['raw_fraction'],mm/chosen['raw_mean']);component_rows=[]
        for i,r in enumerate(c['rows']):
            pos=np.unravel_index(np.argmax(margin[i]),margin[i].shape);orientation,frame,polarity=map(int,pos)
            component_rows.append({**r,'admitted':bool(admitted[i]),'actual_seed_pass':bool(r['peak_n']>81*chosen['strong']),'raw_frame':frame+1,'raw_frame_name':inp['summary']['frame_order'][frame],'raw_orientation_degrees':orientation*22.5,'raw_polarity':1 if polarity==0 else -1,'raw_fraction':float(f[i][pos]),'raw_mean':float(mm[i][pos]),'raw_pass':bool(margin[i][pos]>=1)})
        write(target/'COMPONENTS.json',component_rows)
        row=dict(**rec,weak=chosen['weak'],strong=chosen['strong'],policy=chosen['policy'],original_pixels=int(original.sum()),reference_pixels=int(reference.sum()),previous_pixels=int(previous.sum()),candidate_pixels=int(mask.sum()),ordinary_pixels=int(ordinary.sum()),review_pixels=int(result['review'].sum()),**m)
        if rec['group_id']==annotation['group_id']:row.update(original_path_positions=support(original),reference_path_positions=support(reference),previous_path_positions=support(previous),ordinary_path_positions=support(ordinary))
        write(target/'METRICS.json',row);result_rows.append(row)
        modes={'original':original,'reference':reference,'previous':previous,'ordinary':ordinary,'selected':mask};names={'original':'原B1 8/20','reference':'固定6/20结构','previous':'上一版6/14筛选','ordinary':f'仅阈值 {chosen["weak"]}/{chosen["strong"]}','selected':'本次联合参数版'};tiles=[]
        for mode,plane in modes.items():
            rgb=np.repeat(inp['mean'][:,:,None],3,axis=2)
            if mode=='original':rgb[plane]=[255,210,0]
            else:rgb[reference]=[255,210,0];rgb[plane&~reference]=[0,225,240]
            im=labelled(rgb,[f'{rec["sample"]} {rec["low"]}/{rec["high"]}行 | {names[mode]} | {int(plane.sum())}px','黄=固定原结构，青=新增；离线实验，仍用原片',rec['group_id']]);im.save(target/(mode+'.png'));need(np.array_equal(np.asarray(Image.open(target/(mode+'.png')))[100:],rgb),'Image differs from mask');tiles.append((names[mode],im))
        sheet(tiles,target/'comparison.png',columns=5,cell=(345,415));review_rgb=np.repeat(inp['mean'][:,:,None],3,axis=2);review_rgb[reference]=[255,210,0];review_rgb[added]=[0,225,240];review_rgb[result['review']]=[255,120,40]
        labelled(review_rgb,['橙=未准入的弱阈值候选，非误检真值','黄=原有结构，青=有实际强种子的补充',rec['group_id']]).save(target/'review.png')
        by_board[rec['sample']].append((f'{rec["low"]}/{rec["high"]} '+('旧姿态' if rec['role']=='development_hold_check' else ''),Image.open(target/'selected.png').copy()))
        if rec['role']!='exposure_stress':keytiles.append((rec['sample']+' '+('旧姿态' if rec['role']=='development_hold_check' else '主组'),Image.open(target/'selected.png').copy()))
        if rec['group_id']==annotation['group_id']:
            xy=np.asarray(annotation['path_points']);x0=int(xy[:,0].min())-35;x1=int(xy[:,0].max())+40;y0=int(xy[:,1].min())-35;y1=int(xy[:,1].max())+35;crop_tiles=[]
            for mode in modes:
                rgb=np.asarray(Image.open(target/(mode+'.png')))[100:];crop=Image.fromarray(rgb[y0:y1,x0:x1]).resize(((x1-x0)*2,(y1-y0)*2),Image.Resampling.NEAREST);crop.save(target/(mode+'_weak_crop.png'));crop_tiles.append((names[mode]+f'：{support(modes[mode])}/268',crop))
            raw=Image.fromarray(inp['planes']['gray'][7,y0:y1,x0:x1]).convert('RGB').resize(((x1-x0)*2,(y1-y0)*2),Image.Resampling.NEAREST);crop_tiles.append(('原片CH4 高曝光800',raw));sheet(crop_tiles,out/'sample004_weak_comparison.png',columns=3,cell=(565,285))
        cards.append(f'<section><h2>{rec["sample"]} {rec["low"]}/{rec["high"]} {rec["role"]}</h2><p>{rec["group_id"]} · 新增{m["added_pixels"]}px</p><a href="{rec["group_id"]}/comparison.png"><img src="{rec["group_id"]}/comparison.png"></a><p>'+ ' · '.join(f'<a href="{rec["group_id"]}/{mode}.png">{names[mode]}原尺寸</a>' for mode in modes)+f' · <a href="{rec["group_id"]}/review.png">复检分流</a></p></section>')
        print('FINAL',rec['group_id'],'new',m['added_pixels'],'path',m['path_positions'],flush=True)
    write(out/'DATASET_RESULTS.json',result_rows);write(out/'CONTRACT_CHECKS.json',checks);csv_write(out/'SUMMARY.csv',[{k:v for k,v in r.items() if k not in ('routes','duplicate_result_folders')} for r in result_rows]);sheet(keytiles,out/'five_primary_groups.png',columns=5,cell=(330,400))
    for sample,tiles in by_board.items():sheet(tiles,out/(sample+'_all_groups.png'),columns=3,cell=(370,430))
    # Show all66 plain vs filtered threshold pairs, holding the chosen restrictions fixed.
    pair_tiles=[];target=out/'development_threshold_pairs';target.mkdir();pair_rows=[]
    for weak,strong in itertools.product(g['weak'],g['strong']):
        config={**best['config'],'weak':weak,'strong':strong};inp=dev_inputs['sample004'];cache=caches['sample004'][(weak,config['policy'])];res,_=output(cache,config);plain=hysteresis_connect(inp['response'],inp['valid'],cutoff(weak),81*strong)['mask']&inp['board'];pair_id=f'weak{weak:g}_strong{strong}'
        for name,mask in [('plain',plain),('filtered',res['candidate'])]:
            rgb=np.repeat(inp['mean'][:,:,None],3,axis=2);rgb[inp['reference']]=[255,210,0];rgb[mask&~inp['reference']]=[0,225,240]
            im=labelled(rgb,[f'004 弱{weak:g}/强{strong} | '+('仅阈值' if name=='plain' else '固定本次筛选条件'),f'标线附近支持{support(mask)}/268；严格阈值，非召回率',inp['record']['group_id']]);im.save(target/(pair_id+'_'+name+'.png'))
            if name=='filtered':pair_tiles.append((f'{weak:g}/{strong}：{support(mask)}位置',im))
        met,_=metrics(cache,config);pair_rows.append(dict(weak=weak,strong=strong,plain_path_positions=support(plain),filtered_path_positions=support(res['candidate']),**{k:v for k,v in met.items() if k!='routes'}))
    sheet(pair_tiles,out/'sample004_all66_pairs.png',columns=6,cell=(350,410));csv_write(out/'FIXED_RESTRICTIONS_66_PAIRS.csv',pair_rows)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>强弱阈值与筛选参数联合实验</title><style>body{font-family:system-ui;background:#eef2f7;color:#17314c;margin:24px}main{max-width:1800px;margin:auto}section{background:white;padding:14px;margin:20px 0}img{max-width:100%;height:auto}p{line-height:1.7}</style><main><h1>弱5～6、强14～16，以0.2为步长与新增约束联合比较</h1><p>固定6/20原有结构，仅让低弱阈值进入有实际强种子的隔离补充支路。另有随弱阈值变化的保护层对照，不能把其既有膨胀藏在保护层中。三块开发板，不是独立验证集；007～010未用，现用程序和bit未改。</p><p><a href="sample004_weak_comparison.png">004弱段原片对照</a> · <a href="sample004_all66_pairs.png">004全部66组阈值</a> · <a href="SEARCH.csv">全部联合参数</a> · <a href="SUMMARY.csv">23组结果</a></p>'+''.join(cards)+'</main>',encoding='utf-8')
    need(sha(out/'FROZEN_CONFIG.json')==frozen_sha,'Chosen config changed after freeze');need(all(sha(p)==v for p,v in snapshots.items()),'Input changed');need(all(sha(p)==v for p,v in sources.items()),'Study source changed')
    write(out/'VERIFICATION.json',dict(status='PASS',source_sha256=sources,input_files_sha256=snapshots,input_unique_files=len(snapshots),unique_groups=23,actual_frames=184,physical_boards=3,search_configs=len(search),qualified_configs=len(passing),distinct_development_predictions=len(set(r['prediction_fingerprint'] for r in search)),
        selected_config_sha256=frozen_sha,plan_sha256=sha(out/'PLAN.json'),original_b1_differences=reproduced,original_b1_all_zero=True,all_original_and_reference_pixels_retained=True,all_supplements_actual_seed=True,all_added_eight_adjacent_reference_zero=True,new_reference_merges_zero=True,
        manual_path_used_for_selection=True,manual_path_used_for_inference=False,independent_test=False,formal_detector_changed=False,FPGA_changed=False,bit_programmed=False,new_captures=0,algorithm_commit=binding['commit'],runtime_seconds=time.monotonic()-start))
    print('JOINT_STUDY_PASS',round(time.monotonic()-start,2),'seconds',len(snapshots),'source files',flush=True)
if __name__=='__main__':main()
