"""Pinned development search, then frozen checks on other existing captures."""
import argparse,csv,hashlib,importlib.util,itertools,json,math,pickle,socket,sys,time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from seeded_gate import build,choose,masks

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):
    with Path(p).open('w',encoding='utf-8',newline='\n') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def need(ok,why):
    if not ok:raise ValueError(why)
def load(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def no_socket(*a,**k):raise RuntimeError('Offline study prohibits sockets')
def config_id(c):return hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()[:12]
def inventory(plan):
    by_group={}
    for p in sorted(Path('E:/GuangjianData/B1Detection').glob('sample00[345]_*/summary.json')):
        s=read(p)
        if not (p.parent/'OUTPUT_MANIFEST.json').exists():continue
        if s.get('gain16')!=16 or s.get('led')!=128:continue
        by_group.setdefault(s['group_id'],[]).append((p.parent,s))
    records=[]
    for group,choices in sorted(by_group.items()):
        root,s=max(choices,key=lambda v:v[0].name)
        role='development' if group in plan['development_groups'] else 'development_hold_check' if group in plan['development_hold_check_groups'] else 'exposure_stress'
        records.append(dict(group_id=group,sample=s['specimen'],low=s['low_lines'],high=s['high_lines'],role=role,root=str(root),duplicate_result_folders=[str(p) for p,_ in choices if p!=root]))
    need(len(records)==23,'Inventory changed; review PLAN before adding more groups')
    need(sum(v['low']==400 and v['high']==800 for v in records)==5,'Expected five unique400/800 groups')
    return records
def csv_write(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        fields=list(dict.fromkeys(k for r in rows for k in r));w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def component_arrays(cache):
    r=cache['rows']
    return {k:np.array([v[k] for v in r]) for k in ('area','two_sweep_span_px','line_fraction','median_width_proxy_px','peak_n')}
def path_support(cache,admitted,points):
    xy=np.asarray(points);x=xy[:,0].astype(int);y=np.rint(xy[:,1]).astype(int);yy=y[:,None]+np.arange(-3,4);xx=np.broadcast_to(x[:,None],yy.shape)
    lookup=np.r_[False,admitted];hit=cache['protected'][yy,xx]|lookup[cache['labels'][yy,xx]]
    return int(hit.any(axis=1).sum())
def measures(cache,c,points=None):
    admitted,routes=choose(cache,c);v=component_arrays(cache);area=v['area'];compact=(area<6)|(v['two_sweep_span_px']<6)|(v['line_fraction']<.5)
    anchor=(v['peak_n']>972)&(area>=3)&(v['two_sweep_span_px']>=10)&(v['line_fraction']>=.6)&(v['median_width_proxy_px']<=5)
    anchors=int(area[anchor].sum());mp=float(cache['board'].sum())/1e6
    return dict(added_pixels=int(area[admitted].sum()),added_components=int(admitted.sum()),compact_components=int((admitted&compact).sum()),compact_pixels=int(area[admitted&compact].sum()),
        anchor_pixels=anchors,retained_anchor_fraction=float(area[admitted&anchor].sum()/anchors) if anchors else 1.,
        compact_components_per_mp=float((admitted&compact).sum()/mp),compact_pixels_per_mp=float(area[admitted&compact].sum()/mp),added_pixels_per_mp=float(area[admitted].sum()/mp),
        path_positions=path_support(cache,admitted,points) if points is not None else None,routes=routes),admitted
def evaluate(c,dev,points,plan):
    records={};fingerprint=hashlib.sha256()
    for sample,cache in dev.items():
        r,admitted=measures(cache,c,points if sample=='sample004' else None);records[sample]=r;fingerprint.update(admitted.tobytes())
    # One development group per physical board. Other captures do not vote here.
    risk_count=float(np.mean([r['compact_components_per_mp'] for r in records.values()]));risk_area=float(np.mean([r['compact_pixels_per_mp'] for r in records.values()]));added=float(np.mean([r['added_pixels_per_mp'] for r in records.values()]))
    qualified=records['sample004']['path_positions']>=plan['selection_before_hold_checks']['known_004_path_min_positions'] and all(r['retained_anchor_fraction']>=.6 for r in records.values())
    return dict(id=config_id(c),config=c,qualified=qualified,balanced_compact_count_per_mp=risk_count,balanced_compact_area_per_mp=risk_area,balanced_added_pixels_per_mp=added,
        prediction_fingerprint=fingerprint.hexdigest(),development=records)
def rank(r):return (r['balanced_compact_count_per_mp'],r['balanced_compact_area_per_mp'],r['balanced_added_pixels_per_mp'],{'off':0,'tight':1,'previous':2}[r['config']['chain']],r['id'])
def font(size):return ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',size)
def labelled(rgb,lines):
    im=Image.new('RGB',(rgb.shape[1],rgb.shape[0]+100),'white');im.paste(Image.fromarray(rgb),(0,100));d=ImageDraw.Draw(im)
    for i,line in enumerate(lines):d.text((8,4+i*30),line,font=font(17),fill='#17314c')
    return im
def sheet(tiles,path,columns=3,cell=(380,440)):
    tw,th=cell;im=Image.new('RGB',(tw*columns,th*math.ceil(len(tiles)/columns)),'#eef2f7');d=ImageDraw.Draw(im)
    for i,(title,tile) in enumerate(tiles):
        x=i%columns*tw;y=i//columns*th;d.text((x+7,y+6),title,font=font(16),fill='#17314c');tile=tile.copy();tile.thumbnail((tw-14,th-42),Image.Resampling.LANCZOS);im.paste(tile,(x+(tw-tile.width)//2,y+37))
    im.save(path)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);a=parser.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);socket.socket=no_socket
    start=time.monotonic();plan=read(HERE/'PLAN.json');write(out/'PLAN.json',plan);data=inventory(plan);write(out/'DATASETS.json',data)
    sources={str(p):sha(p) for p in list(HERE.glob('*.py'))+[HERE/'PLAN.json']}
    for name in ('component_gate.py','fragment_chain.py'):
        p=HERE.parent/'weak_component_experiment_20261029'/name;sources[str(p)]=sha(p)
    app=load('_seeded_app',REPO/'YMW/work/b1_detection_console_20261027/common.py');app.verify_app();vendor,binding=app.verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
    from light_inspection.real_baseline import hysteresis_connect
    all_files={};verified=set();reproduced={};cache_dir=out/'cache';cache_dir.mkdir()
    annotation_path=REPO/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json';annotation=read(annotation_path)
    need(annotation['group_id'] in plan['development_groups'],'Path must match development group');points=annotation['path_points'];sources[str(annotation_path)]=sha(annotation_path)
    def prepare(rec,variants):
        root=Path(rec['root']);audit=read(root/'input_audit.json');seal=read(root/'OUTPUT_MANIFEST.json');files={str(root/k):v for k,v in seal['files_sha256'].items()};files.update(audit['verified_artifacts']);files[str(root/'OUTPUT_MANIFEST.json')]=sha(root/'OUTPUT_MANIFEST.json')
        for path,digest in files.items():
            if path not in verified:need(sha(path)==digest,'Input SHA mismatch '+path);verified.add(path)
            need(path not in all_files or all_files[path]==digest,'Conflicting seals');all_files[path]=digest
        with np.load(root/'arrays/original_eight_frames.npz',allow_pickle=False) as z:planes={k:z[k].copy() for k in z.files}
        with np.load(root/'arrays/all8_B1.npz',allow_pickle=False) as z:saved={k:z[k].copy() for k in z.files}
        fused=fusion.fuse_two_stage(planes['residual_n'],planes['valid'],board=planes['board'])['final'];diff={k:int(np.count_nonzero(saved[k]!=fused[k])) for k in saved};need(not any(diff.values()),'Frozen B1 reproduction differs')
        response=np.abs(fused['residual_n'].astype('int32'));valid=~fused['unknown'];board=planes['board'];protected=hysteresis_connect(response,valid,486,1620)['mask']&board;loose=hysteresis_connect(response,valid,486,972)['mask']&board
        need(not (saved['mask']&~protected).any(),'Original pixels lost in protected');cache=build(response,valid,board,protected,loose,planes['gray'],planes['valid'],profile_variants=variants)
        cache.update(original=saved['mask'],mean=np.rint(planes['gray'].astype('float32').mean(0)).astype('uint8'),record=rec,summary=read(root/'summary.json'),gray=planes['gray'])
        reproduced[rec['group_id']]=diff
        print('CACHE',rec['role'],rec['group_id'],'pieces',len(cache['rows']),flush=True)
        return cache
    variants=list(itertools.product(plan['profile_sensitivity']['length'],plan['profile_sensitivity']['flank']))
    dev={}
    for rec in data:
        if rec['role']=='development':dev[rec['sample']]=prepare(rec,variants)
    grid=plan['grid'];results=[]
    for strong,geom,raw,chain,width,area in itertools.product(grid['strong'],grid['geometry'],grid['raw_operating_points'],grid['chain'],grid['max_median_width_proxy'],grid['min_area']):
        c=dict(strong=strong,span=geom[0],line=geom[1],raw_fraction=raw[0],raw_mean=raw[1],chain=chain,width=width,min_area=area,length=13,flank=3.)
        results.append(evaluate(c,dev,points,plan))
    passing=sorted((r for r in results if r['qualified']),key=rank);need(passing,'No configuration qualifies; no fallback to looser requirements')
    top=[];seen=set()
    for r in passing:
        if r['prediction_fingerprint'] not in seen:top.append(r);seen.add(r['prediction_fingerprint'])
        if len(top)==plan['profile_sensitivity_top']:break
    existing={r['id'] for r in results}
    for base in top:
        for length,flank in variants:
            c={**base['config'],'length':length,'flank':flank}
            if config_id(c) not in existing:results.append(evaluate(c,dev,points,plan));existing.add(config_id(c))
    passing=sorted((r for r in results if r['qualified']),key=rank);best=passing[0];config=best['config']
    frozen=dict(schema='seeded-component-config-v1',weak=6,protected_strong=20,strict_comparisons=True,selected=best,plan_sha256=sha(out/'PLAN.json'),development_only=True,
        frozen_before_hold_check_predictions=True,independent_test=False,formal_detector_changed=False)
    write(out/'FROZEN_CONFIG.json',frozen);frozen_sha=sha(out/'FROZEN_CONFIG.json');write(out/'SEARCH_RESULTS.json',results)
    search_rows=[]
    for r in sorted(results,key=lambda r:(not r['qualified'],rank(r))):
        row={k:v for k,v in r.items() if k not in ('config','development')};row.update(r['config'])
        for sample,m in r['development'].items():row.update({sample+'_'+k:v for k,v in m.items() if k not in ('routes',)})
        search_rows.append(row)
    csv_write(out/'SEARCH.csv',search_rows)
    print('CONFIG_FROZEN',json.dumps(config),'tested',len(results),'qualified',len(passing),flush=True)
    # No hold-check/stress cache or prediction was created before this point.
    datasets=[];keytiles=[];gallery=[];checks=[]
    for index,rec in enumerate(data):
        cache=dev[rec['sample']] if rec['role']=='development' else prepare(rec,[(config['length'],config['flank'])])
        target=out/rec['group_id'];target.mkdir();result,routes=masks(cache,config);metric,admitted=measures(cache,config,points if rec['group_id']==annotation['group_id'] else None)
        core=cache['protected'];loose=cache['loose'];original=cache['original'];extra=result['supplement'];labels=cache['labels'];rows=cache['rows'];peak=np.array([0]+[r['peak_n'] for r in rows]);seeded_components=peak>81*config['strong']
        need(not (extra&~seeded_components[labels]).any(),'Unseeded addition');need(not (original&~result['candidate']).any(),'Original mask lost')
        row=dict(**rec,original_pixels=int(original.sum()),protected_pixels=int(core.sum()),loose_pixels=int(loose.sum()),candidate_pixels=int(result['candidate'].sum()),review_pixels=int(result['review'].sum()),**metric)
        row['plain_new_pixels']=int((loose&~core).sum());row['removed_from_plain_new_pixels']=row['plain_new_pixels']-row['added_pixels'];row['retained_plain_new_fraction']=row['added_pixels']/row['plain_new_pixels'] if row['plain_new_pixels'] else 0
        check=dict(group_id=rec['group_id'],original_pixel_losses=int((original&~result['candidate']).sum()),protected_pixel_losses=int((core&~result['candidate']).sum()),pixels_outside_loose=int((result['candidate']&~loose).sum()),unseeded_added_components=int((admitted&~seeded_components[1:]).sum()),added_adjacent_to_protected=int((extra&cv2.dilate(core.astype('uint8'),np.ones((3,3),'uint8')).astype(bool)).sum()),partition_complete=bool(np.array_equal(extra|result['review'],loose&~core)))
        need(not any(check[k] for k in ('original_pixel_losses','protected_pixel_losses','pixels_outside_loose','unseeded_added_components','added_adjacent_to_protected')) and check['partition_complete'],'Final contract failed');checks.append(check)
        np.savez_compressed(target/'masks.npz',original=original,protected=core,loose=loose,**result,component_labels=labels,admitted_component_ids=np.flatnonzero(admitted)+1)
        component_rows=[]
        for j,r in enumerate(rows):component_rows.append({**r,'strict_seed_pass':bool(seeded_components[j+1]),'admitted':bool(admitted[j])})
        write(target/'COMPONENTS.json',component_rows);write(target/'METRICS.json',row)
        # Cache feature arrays, never captured images masquerading as new data.
        np.savez_compressed(cache_dir/(rec['group_id']+'.npz'),labels=labels,**{f'{k}_{i}':x for k,v in cache['profiles'].items() for i,x in enumerate(v)})
        write(cache_dir/(rec['group_id']+'.json'),dict(rows=rows,edges=cache['edges']))
        modes={'original':original,'protected':core,'loose':loose,'selected':result['candidate']};tiles=[]
        names={'original':'原B1 8/20','protected':'6/20保护层','loose':'普通6/12','selected':'筛选后实验版'}
        for name,mask in modes.items():
            rgb=np.repeat(cache['mean'][:,:,None],3,axis=2)
            if name=='original':rgb[mask]=[255,210,0]
            else:rgb[core]=[255,210,0];rgb[mask&~core]=[0,225,240]
            image=labelled(rgb,[f'{rec["sample"]} {rec["low"]}/{rec["high"]}行 | {names[name]} | {int(mask.sum())}px',f'黄=原有保护，青=新增；旧bit采集，离线实验',rec['group_id']]);image.save(target/(name+'.png'))
            need(np.array_equal(np.asarray(Image.open(target/(name+'.png')))[100:],rgb),'Rendered full image differs');tiles.append((names[name],image))
        review_rgb=np.repeat(cache['mean'][:,:,None],3,axis=2);review_rgb[core]=[255,210,0];review_rgb[extra]=[0,225,240];review_rgb[result['review']]=[255,120,40]
        labelled(review_rgb,['待复检分流：橙色不代表已确认误检','黄=6/20保护，青=补充，橙=未准入普通6/12新增',rec['group_id']]).save(target/'review.png')
        sheet(tiles,target/'comparison.png',columns=4,cell=(360,425))
        if rec['role']!='exposure_stress':keytiles.append((rec['sample']+' '+('主组' if rec['role']=='development' else '旧姿态复查'),Image.open(target/'selected.png').copy()))
        if rec['group_id']==annotation['group_id']:
            xy=np.asarray(points);x0=int(xy[:,0].min())-35;x1=int(xy[:,0].max())+40;y0=int(xy[:,1].min())-35;y1=int(xy[:,1].max())+35;crops=[]
            for name in modes:
                rgb=np.asarray(Image.open(target/(name+'.png')))[100:];crop=Image.fromarray(rgb[y0:y1,x0:x1]).resize(((x1-x0)*2,(y1-y0)*2),Image.Resampling.NEAREST);crop.save(target/(name+'_weak_crop.png'));crops.append((names[name],crop))
            for frame in (3,7):
                raw=Image.fromarray(cache['gray'][frame][y0:y1,x0:x1]).convert('RGB').resize(((x1-x0)*2,(y1-y0)*2),Image.Resampling.NEAREST);raw.save(target/f'CH{frame//2+1}_high_weak_crop.png');crops.append((f'原片CH{frame//2+1} 高曝800',raw))
            sheet(crops,out/'sample004_weak_comparison.png',columns=3,cell=(560,285))
        gallery.append(f'<section><h2>{rec["sample"]} · {rec["low"]}/{rec["high"]} · {rec["role"]}</h2><p>{rec["group_id"]}；新增{row["added_pixels"]}px，待复检{row["review_pixels"]}px</p><a href="{rec["group_id"]}/comparison.png"><img src="{rec["group_id"]}/comparison.png"></a><p>'+ ' · '.join(f'<a href="{rec["group_id"]}/{n}.png">{names[n]}原尺寸</a>' for n in modes)+f' · <a href="{rec["group_id"]}/review.png">橙色复检层</a></p></section>')
        datasets.append(row);print('FINAL',rec['group_id'],'new',row['added_pixels'],'review',row['review_pixels'],flush=True)
    need(sha(out/'FROZEN_CONFIG.json')==frozen_sha,'Frozen config changed during checks')
    sheet(keytiles,out/'five_primary_groups.png',columns=5,cell=(330,400));write(out/'DATASET_RESULTS.json',datasets);write(out/'CONTRACT_CHECKS.json',checks)
    csv_write(out/'SUMMARY.csv',[{k:v for k,v in r.items() if k not in ('routes','duplicate_result_folders')} for r in datasets])
    # Old draft reference geometry is used only after every prediction, never as background truth.
    draft_evals=[]
    for name in ('sample004','sample005'):
        draft_path=REPO/f'YMW/handoffs/p0_annotation_multiview_20261026/{name}_annotations_DRAFT.json';draft=read(draft_path);rec=next(r for r in data if r['group_id']==draft['group_id']);target=out/rec['group_id'];roi=read(Path(rec['root'])/'summary.json')['roi_xywh'];evaluations=[]
        with np.load(target/'masks.npz',allow_pickle=False) as z:mm={k:z[k].copy() for k in ('original','protected','loose','candidate')}
        for annotation_item in draft['annotations']:
            if annotation_item['class']!='scratch':continue
            xy=np.rint(np.array(annotation_item['points_xy'])-np.array(roi[:2])).astype(int);pathmask=np.zeros_like(mm['candidate'],np.uint8);cv2.polylines(pathmask,[xy.reshape(-1,1,2)],False,1,1);ys,xs=np.nonzero(pathmask)
            counts={}
            for mode,mask in mm.items():
                dil=cv2.dilate(mask.astype('uint8'),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)));counts[mode]=int(dil[ys,xs].sum())
            evaluations.append(dict(annotation_id=annotation_item['annotation_id'],draft_state=annotation_item['state'],path_pixels=len(xs),near_path_counts_radius3=counts))
        draft_evals.append(dict(group_id=rec['group_id'],reference_path=str(draft_path),reference_sha256=sha(draft_path),draft_geometry_only=True,background_polygons_used=False,not_recall=True,paths=evaluations))
    write(out/'DRAFT_REFERENCE_CHECKS.json',draft_evals)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>有强种子的弱段补充：多组参数复核</title><style>body{font-family:system-ui;background:#eef2f7;color:#17314c;margin:24px}main{max-width:1600px;margin:auto}section{background:white;padding:16px;margin:20px 0}img{max-width:100%;height:auto}p{line-height:1.7}</style><main><h1>有强种子的弱段补充：23组开发数据复核</h1><p>固定弱6，保护6/20；无种子弱线不进入检测补充。黄=保护，青=新增，橙色复检层不是误检真值。三块板的23组不是23块独立样本。两组旧姿态只作开发复查；其他曝光只作稳健性检查，曝光仍固定400/800。007～010未使用。</p><p><a href="sample004_weak_comparison.png">004弱线原片与结果</a> · <a href="five_primary_groups.png">5组400/800总览</a> · <a href="SEARCH.csv">全部参数搜索表</a> · <a href="SUMMARY.csv">23组指标</a> · <a href="FROZEN_CONFIG.json">冻结实验参数</a></p>'+''.join(gallery)+'</main>',encoding='utf-8')
    need(all(sha(p)==v for p,v in all_files.items()),'Input changed at end');need(all(sha(p)==v for p,v in sources.items()),'Study source/reference changed during run')
    write(out/'VERIFICATION.json',dict(status='PASS',plan_sha256=sha(out/'PLAN.json'),selected_config_sha256=frozen_sha,source_sha256=sources,input_files_sha256=all_files,input_unique_files=len(all_files),unique_groups=len(data),actual_frames=8*len(data),physical_boards=3,
        original_b1_differences=reproduced,original_b1_all_fields_zero_difference=True,all_original_and_protected_pixels_retained=True,all_additions_actual_strong_seed=True,no_additions_adjacent_to_protected=True,no_gap_pixels_painted=True,
        parameter_configs=len(results),unique_development_predictions=len(set(r['prediction_fingerprint'] for r in results)),qualified_configs=len(passing),development_hold_check_groups=2,exposure_stress_groups=18,
        manual_reference_used_for_development_selection=True,manual_reference_used_for_inference=False,independent_test=False,background_truth_available=False,formal_detector_changed=False,bit_programmed=False,FPGA_changed=False,new_captures=0,
        algorithm_commit=binding['commit'],runtime_seconds=time.monotonic()-start))
    print('STUDY_PASS seconds',round(time.monotonic()-start,2),'files',len(all_files),flush=True)
if __name__=='__main__':main()
