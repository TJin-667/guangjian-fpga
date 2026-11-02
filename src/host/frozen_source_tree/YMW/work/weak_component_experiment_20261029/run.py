"""Run the same predeclared component-admission experiment on three boards."""
import argparse,csv,hashlib,importlib.util,json,shutil,socket,sys,time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from component_gate import PRESETS,partition
from fragment_chain import CONFIG as CHAIN_CONFIG,chain
from raw_profile import CONFIG as PROFILE_CONFIG,raw_profile_gate

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
DATASETS={
    'sample003':Path('E:/GuangjianData/B1Detection/sample003_400-800_20261027_225421_9eb4eb3c'),
    'sample004':Path('E:/GuangjianData/B1Detection/sample004_400-800_20261029_011210_f71863d7'),
    'sample005':Path('E:/GuangjianData/B1Detection/sample005_400-800_20261028_015827_d6e9e487'),
}
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):
    with Path(p).open('w',encoding='utf-8',newline='\n') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def need(value,message):
    if not value:raise ValueError(message)
def no_socket(*a,**k):raise RuntimeError('Offline experiment prohibits sockets')
def load(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def font(size):return ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',size)
LABELS={'original':'原B1 8/20','protected':'6/20保护层','loose':'普通6/12','size3':'新增块面积≥3','line6':'新增线形：跨度≥6','line10':'新增线形：跨度≥10','line14':'新增线形：跨度≥14','chain_geom':'端点走向成链（几何对照）','chain_raw':'端点走向＋原片间隙证据','raw_profile':'原片连续线剖面准入','line_plus_raw':'线形成链＋原片线剖面'}
def labelled(rgb,lines):
    im=Image.new('RGB',(rgb.shape[1],rgb.shape[0]+100),'white');im.paste(Image.fromarray(rgb),(0,100));pen=ImageDraw.Draw(im)
    for i,line in enumerate(lines):pen.text((8,4+i*30),line,font=font(17),fill='#17314c')
    return im
def sheet(tiles,path,columns=4,cell=(360,410)):
    tw,th=cell;im=Image.new('RGB',(columns*tw,((len(tiles)+columns-1)//columns)*th),'#eef2f7');pen=ImageDraw.Draw(im)
    for i,(title,tile) in enumerate(tiles):
        x=i%columns*tw;y=i//columns*th;pen.text((x+5,y+5),title,font=font(17),fill='#17314c');tile=tile.copy();tile.thumbnail((tw-12,th-36),Image.Resampling.LANCZOS);im.paste(tile,(x+(tw-tile.width)//2,y+33))
    im.save(path)
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--annotation',type=Path,default=REPO/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json');a=p.parse_args();socket.socket=no_socket
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    app=load('_component_gate_app',REPO/'YMW/work/b1_detection_console_20261027/common.py');app.verify_app();vendor,binding=app.verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
    from light_inspection.real_baseline import hysteresis_connect
    config=dict(schema='weak6-new-component-admission-experiment-v3',protected=dict(weak=6,strong=20),loose=dict(weak=6,strong=12),presets=PRESETS,fragment_chain=CHAIN_CONFIG,raw_profile=PROFILE_CONFIG,
        geometry=dict(local_skeleton_radius_px=3,line_coherence_min=.55,curve_fork_support=True,all_pixels_native=True),
        policy='Keep protected6/20; partition only newly admitted6/12 board components into line supplements and retained review.',
        limits='Component-level admission and fragment relations, not per-pixel growth or painted gap bridges. Skeleton width is a descriptor, never physical width.',
        manual_annotation_used_for_prediction=False,new_hardware=False)
    write(out/'CONFIG.json',config)
    protected_sources={str(p):sha(p) for p in HERE.glob('*.py')};snapshot={};all_outputs={};runtime={};comparison_tiles=[]
    start=time.monotonic()
    for sample,root in DATASETS.items():
        print('BEGIN',sample,flush=True);summary=read(root/'summary.json');audit=read(root/'input_audit.json');seal=read(root/'OUTPUT_MANIFEST.json');group=summary['group_id']
        files={str(root/name):digest for name,digest in seal['files_sha256'].items()};files.update(audit['verified_artifacts']);files[str(root/'OUTPUT_MANIFEST.json')]=sha(root/'OUTPUT_MANIFEST.json')
        need(all(sha(path)==digest for path,digest in files.items()),'Source hash mismatch '+sample);snapshot.update(files)
        with np.load(root/'arrays/original_eight_frames.npz',allow_pickle=False) as z:planes={k:z[k].copy() for k in z.files}
        with np.load(root/'arrays/all8_B1.npz',allow_pickle=False) as z:saved={k:z[k].copy() for k in z.files}
        fused=fusion.fuse_two_stage(planes['residual_n'],planes['valid'],board=planes['board'])['final'];diff={k:int(np.count_nonzero(fused[k]!=saved[k])) for k in saved};need(not any(diff.values()),'Original B1 result differs '+sample)
        response=np.abs(fused['residual_n'].astype('int32'));valid=~fused['unknown'];board=planes['board'];original=saved['mask']
        protected=hysteresis_connect(response,valid,486,1620)['mask']&board;loose_result=hysteresis_connect(response,valid,486,972);loose=loose_result['mask']&board
        need(not (original&~protected).any(),'Original8/20 pixels lost')
        results,components=partition(protected,loose,loose_result['strong_mask']&board,residuals=planes['residual_n'],valid=planes['valid'])
        need(not (results['line14']['candidate']&~results['line10']['candidate']).any() and not (results['line10']['candidate']&~results['line6']['candidate']).any() and not (results['line6']['candidate']&~results['size3']['candidate']).any(),'Preset nesting failed')
        chained,chain_report=chain(protected,loose,results['line6']['line_supplement'],planes['gray'],planes['valid'],board);results.update(chained)
        need(not (results['line6']['candidate']&~results['chain_raw']['candidate']).any(),'Fragment relations lost the line6 candidate')
        profiled,profile_report=raw_profile_gate(protected,loose,planes['gray'],planes['valid'],board,results['chain_raw']['line_supplement']);results.update(profiled)
        need(not (results['chain_raw']['candidate']&~results['line_plus_raw']['candidate']).any(),'Raw profile union lost a chain candidate')
        target=out/sample;target.mkdir();(target/'full').mkdir();(target/'masks').mkdir();(target/'review').mkdir();write(target/'FRAGMENT_RELATIONS.json',chain_report);write(target/'RAW_PROFILES.json',profile_report)
        write(target/'COMPONENTS.json',components);mean=np.rint(planes['gray'].astype('float32').mean(0)).astype('uint8')
        masks={'original':original,'protected':protected,'loose':loose,**{key:r['candidate'] for key,r in results.items()}}
        rows=[];tiles=[]
        for name,mask in masks.items():
            addition=mask&~protected;review=results[name]['review'] if name in results else np.zeros_like(mask)
            row=dict(mode=name,candidate_pixels=int(mask.sum()),supplement_pixels=int(addition.sum()),review_pixels=int(review.sum()),
                protected6_20_losses=int((protected&~mask).sum()) if name!='original' else None,original8_20_losses=int((original&~mask).sum()),
                added_adjacent_to_protected=int((addition&cv2.dilate(protected.astype('uint8'),np.ones((3,3),'uint8')).astype(bool)).sum()),
                supplement_components=int(cv2.connectedComponents(addition.astype('uint8'),connectivity=8)[0]-1))
            if name in results:
                row['review_components']=int(cv2.connectedComponents(review.astype('uint8'),connectivity=8)[0]-1)
                np.savez_compressed(target/'masks'/f'{name}.npz',candidate=mask,line_supplement=addition,review=review,protected=protected)
            rgb=np.repeat(mean[:,:,None],3,axis=2)
            if name=='original':rgb[mask]=[255,210,0]
            else:rgb[protected]=[255,210,0];rgb[addition]=[0,225,240]
            image=labelled(rgb,[f'{sample} | {LABELS[name]} | 候选{row["candidate_pixels"]}px',f'黄=保护层，青=新增；离线实验，400/800行，1倍，LED128',group]);image.save(target/'full'/f'{name}.png');tiles.append((LABELS[name],image))
            need(np.array_equal(np.asarray(Image.open(target/'full'/f'{name}.png'))[100:],rgb),'Rendered pixels differ')
            cv2.imwrite(str(target/'masks'/f'{name}.png'),mask.astype('uint8')*255)
            if name in results:
                view=rgb.copy();view[review]=[255,120,40];labelled(view,[f'{sample} | {LABELS[name]}：复检层{row["review_pixels"]}px','黄=6/20保护，青=线形补充，橙=保留待复检；非真假标签',group]).save(target/'review'/f'{name}.png')
            rows.append(row)
        for name in ('original','protected','loose','raw_profile','line_plus_raw'):
            comparison_tiles.append((sample+' '+LABELS[name],Image.open(target/'full'/f'{name}.png').copy()))
        sheet(tiles,target/'overview.png')
        all_outputs[sample]=dict(sample=sample,group_id=group,source=str(root),shape_hw=list(board.shape),roi_xywh=summary['roi_xywh'],
            original_b1_differences=diff,modes=rows,new_components=len(components),
            geometry_only=False,geometry_and_native_gray_relations=True,false_positive_rate=None,recall=None,formal_detector_changed=False,
            geometry_relation_edges=chain_report['geometry_edges'],raw_supported_relation_edges=chain_report['raw_supported_edges'],raw_profile_accepted_components=profile_report['accepted_components'])
        runtime[sample]=dict(masks=masks,results=results,mean=mean,components=components)
        write(target/'METRICS.json',all_outputs[sample]);print('INFERENCE_DONE',sample,'new_components',len(components),flush=True)
    # Human reference is loaded only AFTER all three predictions are finished.
    annotation=read(a.annotation);need(annotation['group_id']==all_outputs['sample004']['group_id'],'Annotation belongs to a different group')
    path=np.asarray(annotation['path_points']);xs=path[:,0].astype(int);ys=np.rint(path[:,1]).astype(int)
    support=lambda mask,r:mask[ys[:,None]+np.arange(-r,r+1),xs[:,None]].any(axis=1)
    truth_stats={};croptiles=[];x0=xs.min()-35;x1=xs.max()+40;y0=ys.min()-35;y1=ys.max()+35
    (out/'sample004/crops').mkdir()
    for mode,mask in runtime['sample004']['masks'].items():
        truth_stats[mode]={f'path_support_r{r}':int(support(mask,r).sum()) for r in (0,3,5)}
        if mode in runtime['sample004']['results']:
            review=runtime['sample004']['results'][mode]['review'];truth_stats[mode]['loose_supported_but_routed_to_review_r3']=int((support(runtime['sample004']['masks']['loose'],3)&~support(mask,3)).sum());truth_stats[mode]['review_near_path_r3']=int(support(review,3).sum())
        rgb=np.asarray(Image.open(out/'sample004/full'/f'{mode}.png'))[100:];crop=Image.fromarray(rgb[y0:y1,x0:x1]).resize(((x1-x0)*2,(y1-y0)*2),Image.Resampling.NEAREST)
        label=LABELS[mode]+f'：标线附近{truth_stats[mode]["path_support_r3"]}/268';croptiles.append((label,crop));crop.save(out/'sample004/crops'/f'{mode}.png')
    write(out/'sample004/ANNOTATION_EVAL.json',dict(annotation_sha256=sha(a.annotation),evaluation_only=True,not_exact_recall=True,x_stations=len(xs),metrics=truth_stats))
    sheet(croptiles,out/'sample004/weak_line_comparison.png',columns=3,cell=(550,290));sheet(comparison_tiles,out/'three_board_comparison.png',columns=5,cell=(340,390))
    with (out/'SUMMARY.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['sample','mode','candidate_pixels','supplement_pixels','review_pixels','original8_20_losses','path_support_r3'];w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for sample,record in all_outputs.items():
            for row in record['modes']:w.writerow({k:(sample if k=='sample' else truth_stats[row['mode']]['path_support_r3'] if k=='path_support_r3' and sample=='sample004' else row.get(k)) for k in fields})
    sections=''
    for sample,record in all_outputs.items():
        cards=''
        for row in record['modes']:
            name=row['mode'];cards+=f'<figure><figcaption>{LABELS[name]} · {row["candidate_pixels"]}候选px · {row["review_pixels"]}复检px</figcaption><a href="{sample}/full/{name}.png"><img src="{sample}/full/{name}.png"></a>'+(f'<p><a href="{sample}/review/{name}.png">查看橙色复检层</a></p>' if name not in ('original','protected','loose') else '')+'</figure>'
        sections+=f'<h2>{sample}</h2><div class="grid">'+cards+'</div>'
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>新增弱块准入离线实验</title><style>body{font-family:system-ui;background:#eef2f7;color:#17314c;margin:24px}main{max-width:1800px;margin:auto}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}figure{margin:0;padding:10px;background:white}img{width:100%;height:auto}p{line-height:1.7}</style><main><h1>弱6固定：保护6/20，筛查6/12新增块</h1><p>原8/20正式结果仍保留。实验仅决定新增块进入线形补充还是人工复检；橙色不是已确认误检。骨架仅计算几何特征，输出仍为原候选像素，未把1px骨架当宽度。成链版检查端点走向和同一原帧的双侧对比，只建立碎片关系，不在间隙里画线。相同参数用于003/004/005，预测不读取人工标线；只在最后用004近似标线比较支持位置，非召回率。这里并非已实现逐像素沿线生长。没有新采集、烧录或TJ算法运行。</p><p><a href="sample004/weak_line_comparison.png">004弱段局部对照</a> · <a href="SUMMARY.csv">全部指标</a> · <a href="CONFIG.json">预先声明参数</a></p>'+sections+'</main>',encoding='utf-8')
    need(all(sha(path)==digest for path,digest in snapshot.items()),'Source/input changed at end');need(all(sha(path)==digest for path,digest in protected_sources.items()),'Experimental source changed while running')
    receipt=dict(status='PASS',algorithm_commit=binding['commit'],input_unique_files_verified=len(snapshot),input_files_sha256=snapshot,source_sha256=protected_sources,
        config_sha256=sha(out/'CONFIG.json'),all_original_inputs_unchanged=True,three_original_b1_reproduced=True,all_protected6_20_retained=True,
        all_experimental_outputs_subset_of_loose6_12=True,supplement_and_review_partition_all_new=True,new_pixels_adjacent_to_protected=0,
        annotation_evaluated_after_all_predictions=True,independent_frozen_test=False,samples=list(DATASETS),runtime_seconds=time.monotonic()-start,
        stage='new-component-admission-fragment-relations-and-native-line-profiles',fragment_directional_relations_implemented=True,native_line_profiles_implemented=True,per_pixel_directional_growth_implemented=False,formal_detector_changed=False,FPGA_changed=False,bit_programmed=False,new_captures=0,TJ_model_run=False)
    write(out/'VERIFICATION.json',receipt);write(out/'RESULTS.json',all_outputs)
    print('ALL_THREE_EXPERIMENTS_PASS',flush=True)
    for sample,record in all_outputs.items():
        for row in record['modes']:print(sample,row['mode'],row['candidate_pixels'],'extra',row['supplement_pixels'],'review',row['review_pixels'],'path',truth_stats[row['mode']]['path_support_r3'] if sample=='sample004' else '-',flush=True)
if __name__=='__main__':main()
