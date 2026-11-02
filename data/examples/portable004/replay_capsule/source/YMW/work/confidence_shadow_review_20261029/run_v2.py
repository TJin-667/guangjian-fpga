"""Offline confidence-reference prototype; frozen formal masks are read-only."""
import argparse,hashlib,json,math,re,socket,sys,time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw
from evidence import compare,raw_supported_components,group_decision,distance_to
from raw_line_scan import scan_combined as scan_without_seed
from sleeve_runtime import load_sealed,predict,verify_inputs
from joint_package_contract import verify_package as verify_formal_package
from run_study import read,write,sha,labelled,sheet,csv_write,font

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2];FORMAL=HERE.parent/'joint_threshold_tuning_20261029';DATA=Path('E:/GuangjianData/reviews/joint_threshold_tuning_20261029/sleeve_01')
def need(x,why):
    if not x:raise ValueError(why)
def stations_mask(shape,records):
    mask=np.zeros(shape,bool)
    for r in records:
        if not r.get('raw_supported'):continue
        for x,y in r['support_station_xy']:
            xx,yy=int(round(x)),int(round(y))
            if 0<=yy<shape[0] and 0<=xx<shape[1]:mask[yy,xx]=True
    return mask
def merge_windows(records,shape):
    rows=[]
    for r in records:
        if not r.get('raw_supported'):continue
        x,y,w,h=r['bbox_xywh'];rows.append(dict(x0=max(0,x-5),y0=max(0,y-5),x1=min(shape[1],x+w+5),y1=min(shape[0],y+h+5),evidence=[dict(source=r['source'],kind=r.get('kind','shadow_line'),component=r['label'],frames=r['supported_frames'],directions=r['supported_directions'],priority=r['evidence_priority'])]))
    # These are review windows, not physical-scratch identities.
    changed=True
    while changed:
        changed=False
        for i in range(len(rows)):
            for j in range(i+1,len(rows)):
                a,b=rows[i],rows[j];iw=max(0,min(a['x1'],b['x1'])-max(a['x0'],b['x0']));ih=max(0,min(a['y1'],b['y1'])-max(a['y0'],b['y0']));small=min((a['x1']-a['x0'])*(a['y1']-a['y0']),(b['x1']-b['x0'])*(b['y1']-b['y0']))
                if iw*ih/max(1,small)>=.3:
                    rows[i]=dict(x0=min(a['x0'],b['x0']),y0=min(a['y0'],b['y0']),x1=max(a['x1'],b['x1']),y1=max(a['y1'],b['y1']),evidence=a['evidence']+b['evidence']);rows.pop(j);changed=True;break
            if changed:break
    for i,r in enumerate(rows):r.update(id=i+1,priority='multi_direction' if any(v['priority']=='multi_direction' for v in r['evidence']) else 'single_direction')
    rows.sort(key=lambda r:(r['priority']!='multi_direction',-len(set(v['source'] for v in r['evidence'])),-(r['x1']-r['x0'])))
    for i,r in enumerate(rows):r['id']=i+1
    return rows
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--limit',type=int);p.add_argument('--roles',nargs='+',choices=['development','development_hold_check','exposure_stress']);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    def deny(*a,**k):raise RuntimeError('Offline confidence experiment prohibits sockets')
    socket.socket=deny;plan=read(HERE/'PLAN_V2.json');write(out/'PLAN.json',plan);frozen=read(FORMAL/'FROZEN_SLEEVE_CONFIG.json');base_config=frozen['selected']['config'];need(frozen['selected']['id']==plan['formal_config_id'],'Wrong formal detector');formal_binding=verify_formal_package();data=read(DATA.parent/'run_01/DATASETS.json');data=[r for r in data if not a.roles or r['role'] in a.roles];data=sorted(data,key=lambda r:(r['role']!='development',r['role']!='development_hold_check',r['group_id']));data=data[:a.limit] if a.limit else data;write(out/'DATASETS.json',data)
    source_sha={str(p):sha(p) for p in list(HERE.glob('*.py'))+[HERE/'PLAN_V2.json']};source_sha[str(FORMAL/'FROZEN_SLEEVE_CONFIG.json')]=sha(FORMAL/'FROZEN_SLEEVE_CONFIG.json');all_sources={};results=[];contracts=[];case_runtime=None;cards=[]
    for rec in data:
        print('BEGIN',rec['group_id'],flush=True);x=load_sealed(rec['root']);formal_res=predict(x,base_config);formal=formal_res['candidate'].copy();formal_hash=hashlib.sha256(formal.tobytes()).hexdigest()
        saved_path=DATA/rec['group_id']/'masks.npz'
        with np.load(saved_path,allow_pickle=False) as z:saved={k:z[k].copy() for k in formal_res}
        differences={k:int(np.count_nonzero(formal_res[k]!=saved[k])) for k in formal_res};need(not any(differences.values()),'Formal detector reproduction differs');all_sources.update(x['files']);all_sources[str(saved_path)]=sha(saved_path)
        target=out/rec['group_id'];target.mkdir();mean=np.rint(x['planes']['gray'].astype('float32').mean(0)).astype('uint8');base_rgb=np.repeat(mean[:,:,None],3,axis=2);base_rgb[formal]=[255,210,0]
        labelled(base_rgb,[f'{rec["sample"]} | 正式参考掩膜，冻结5.2/14.4','黄色=正式参考；置信度实验不增删这里的像素',rec['group_id']]).save(target/'formal.png')
        all_records=[];shadow_metrics={};shadow_arrays={};shadow_masks={}
        for name,overrides in plan['shadow_profiles'].items():
            config={**base_config,**overrides};res=predict(x,config);mask=res['candidate'];diff,metric=compare(formal,mask,plan['comparison']);need(name!='rim_control' or metric['nonrim_pixels']==0,'Rim-only control created a nonrim change')
            if name=='rim_control':supported=np.zeros_like(formal);rows=[]
            else:
                cmp=plan['comparison'];supported,rows=raw_supported_components(diff['nonrim'],x['planes']['gray'],x['planes']['valid'],x['board'],x['r'],plan['raw_line_check'],min_area=cmp['min_new_piece_area'],min_span=cmp['min_new_piece_span'],min_line_fraction=cmp['min_new_piece_line_fraction'],max_width=cmp['max_new_piece_median_width'],strong_reference=base_config['strong'])
            for row in rows:row.update(source=name,kind='parameter_relaxation_extra')
            all_records.extend(rows);metric.update(raw_supported_components=sum(r['raw_supported'] for r in rows),profile_config=config);shadow_metrics[name]=metric;shadow_masks[name]=mask.copy();shadow_arrays[name+'_candidate']=mask;shadow_arrays[name+'_gained']=diff['gained'];shadow_arrays[name+'_lost']=diff['lost'];shadow_arrays[name+'_structured_evidence']=supported
            rgb=base_rgb.copy();rgb[diff['gained']]=[0,220,240];rgb[diff['lost']]=[255,100,30];labelled(rgb,[f'{rec["sample"]} | {name} 对照（不并入检测）',f'青=新增{metric["gained_pixels"]}，橙=丢失{metric["lost_pixels"]}；非真伪标签',rec['group_id']]).save(target/(name+'.png'))
        scan_mask,scan_rows=scan_without_seed(formal,x['r'],x['v'],x['board'],x['planes']['gray'],x['planes']['valid'],plan)
        for row in scan_rows:row['source']='seed_independent_scan'
        all_records.extend(scan_rows);windows=merge_windows(all_records,formal.shape);station_evidence=stations_mask(formal.shape,all_records);board_pixels=int(x['board'].sum());unknown_fraction=float(((~x['v'])&x['board']).sum()/max(1,board_pixels));status=group_decision(unknown_fraction,len(windows),plan);status='REVIEW_ANALYSIS_CAPACITY' if any(r.get('kind')=='raw_scan_capacity_review' for r in scan_rows) else status
        review=Image.fromarray(base_rgb);d=ImageDraw.Draw(review)
        for win in windows[:12]:
            d.rectangle((win['x0'],win['y0'],win['x1']-1,win['y1']-1),outline='#ff42ae',width=2);d.text((win['x0']+2,max(0,win['y0']-22)),str(win['id']),font=font(17),fill='#ff42ae')
        labelled(np.asarray(review),[f'{rec["sample"]} | {status}',f'粉框=复检区{len(windows)}（展示前12）；正式黄色掩膜不变',rec['group_id']]).save(target/'review_regions.png')
        rawview=np.repeat(mean[:,:,None],3,axis=2);rawview[station_evidence]=[255,55,175];labelled(rawview,['原片局部线证据：粉点=原片验证过的采样中心','这是复检证据，不是新增正式划痕掩膜',rec['group_id']]).save(target/'raw_evidence_stations.png')
        write(target/'RAW_EVIDENCE.json',all_records);write(target/'SHADOW_COMPARISONS.json',shadow_metrics);write(target/'REVIEW_REGIONS.json',windows)
        np.savez_compressed(target/'confidence_reference_arrays.npz',formal_detector_mask=formal,raw_validated_station_mask=station_evidence,weak_scan_region_evidence=scan_mask,**shadow_arrays)
        record=dict(**rec,status=status,formal_config_id=plan['formal_config_id'],formal_pixels=int(formal.sum()),review_windows=len(windows),multi_direction_windows=sum(w['priority']=='multi_direction' for w in windows),unknown_board_fraction=unknown_fraction,
            raw_supported_unseeded_components=sum(r['raw_supported'] and r['kind']=='globally_unseeded_continuous_evidence' for r in scan_rows),raw_supported_local_seedless_fragments=sum(r['raw_supported'] and not r['has_strong_seed'] for r in scan_rows),raw_supported_scan_components=sum(r['raw_supported'] for r in scan_rows),shadow_supported_components=sum(r['raw_supported'] for r in all_records if r['source']!='seed_independent_scan'),confidence_probability=None,automatic_pass=False,shadows={n:{k:v for k,v in m.items() if k not in ('nonrim_components','profile_config')} for n,m in shadow_metrics.items()})
        need(hashlib.sha256(formal.tobytes()).hexdigest()==formal_hash,'Confidence experiment mutated detector mask');verify_inputs(x);contracts.append(dict(group_id=rec['group_id'],formal_all10_differences=differences,formal_mask_unchanged=True,rim_only_nonrim_zero=shadow_metrics['rim_control']['nonrim_pixels']==0,confidence_probability_emitted=False))
        write(target/'RESULT.json',record);results.append(record);tiles=[('正式参考',Image.open(target/'formal.png').copy()),('复检区域',Image.open(target/'review_regions.png').copy()),('无种子扫描原片证据',Image.open(target/'raw_evidence_stations.png').copy())];sheet(tiles,target/'overview.png',columns=3,cell=(365,425))
        cards.append(f'<section><h2>{rec["sample"]} {rec["low"]}/{rec["high"]} · {status}</h2><p>{rec["group_id"]}，复检窗口{len(windows)}；未标为通过概率。</p><a href="{rec["group_id"]}/overview.png"><img src="{rec["group_id"]}/overview.png"></a><p>'+ ' · '.join(f'<a href="{rec["group_id"]}/{name}.png">{name}</a>' for name in ('formal','review_regions','raw_evidence_stations',*plan['shadow_profiles']))+'</p></section>')
        if rec['group_id']=='sample004_A_v1_20261028_220937_87f02b':case_runtime=dict(formal=formal.copy(),stations=station_evidence.copy(),windows=windows,mean=mean.copy(),gray=x['planes']['gray'].copy(),all_records=all_records)
        print('DONE',rec['sample'],'windows',len(windows),'global_unseeded',record['raw_supported_unseeded_components'],'seedless_fragments',record['raw_supported_local_seedless_fragments'],flush=True)
    # Evaluation reference is loaded only after all detector/shadow predictions.
    if case_runtime is not None:
        annotation_path=REPO/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json';annotation=read(annotation_path);xy=np.asarray(annotation['path_points']);xs=xy[:,0].astype(int);ys=np.rint(xy[:,1]).astype(int);yy=ys[:,None]+np.arange(-3,4);xx=np.broadcast_to(xs[:,None],yy.shape);formal_hit=case_runtime['formal'][yy,xx].any(axis=1);station_hit=cv2.dilate(case_runtime['stations'].astype('uint8'),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)))[ys,xs]>0
        inside=np.zeros(len(xs),bool)
        for win in case_runtime['windows']:inside|=(xs>=win['x0'])&(xs<win['x1'])&(ys>=win['y0'])&(ys<win['y1'])
        evaluation=dict(group_id=annotation['group_id'],manual_path_loaded_after_predictions=True,development_case_not_independent=True,formal_path_support=int(formal_hit.sum()),path_positions=len(xs),not_recall=True,uncovered_positions=int((~formal_hit).sum()),uncovered_near_raw_validated_stations=int((~formal_hit&station_hit).sum()),uncovered_inside_review_windows=int((~formal_hit&inside).sum()),formal_mask_not_augmented=True)
        write(out/'SAMPLE004_CASE_CHECK.json',evaluation);x0=int(xs.min())-35;x1=int(xs.max())+40;y0=int(ys.min())-35;y1=int(ys.max())+35;croptiles=[]
        for name,image in [('原片CH2高曝800',np.repeat(case_runtime['gray'][3,:,:,None],3,axis=2)),('原片CH4高曝800',np.repeat(case_runtime['gray'][7,:,:,None],3,axis=2))]:croptiles.append((name,Image.fromarray(image[y0:y1,x0:x1]).resize(((x1-x0)*2,(y1-y0)*2),Image.Resampling.NEAREST)))
        formal_rgb=np.repeat(case_runtime['mean'][:,:,None],3,axis=2);formal_rgb[case_runtime['formal']]=[255,210,0];croptiles.append(('正式检测不变',Image.fromarray(formal_rgb[y0:y1,x0:x1]).resize(((x1-x0)*2,(y1-y0)*2),Image.Resampling.NEAREST)));raw=np.repeat(case_runtime['mean'][:,:,None],3,axis=2);raw[case_runtime['stations']]=[255,55,175];croptiles.append(('粉点：原片支持的复检证据',Image.fromarray(raw[y0:y1,x0:x1]).resize(((x1-x0)*2,(y1-y0)*2),Image.Resampling.NEAREST)));sheet(croptiles,out/'sample004_case_comparison.png',columns=2,cell=(640,320))
    write(out/'RESULTS.json',results);write(out/'CONTRACT_CHECKS.json',contracts);csv_write(out/'SUMMARY.csv',[{k:v for k,v in r.items() if k not in ('shadows','duplicate_result_folders')} for r in results])
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>置信度参考：参数扰动与无种子线</title><style>body{font-family:system-ui;background:#eef2f7;color:#17314c;margin:24px}main{max-width:1600px;margin:auto}section{background:white;padding:16px;margin:20px 0}img{max-width:100%;height:auto}p{line-height:1.7}</style><main><h1>正式检测不变：参数扰动与无种子线复检证据</h1><p>黄色为冻结正式参考结果，粉框为待人工复检区域，粉点为原片验证过的局部线采样。对照新增和无种子证据均不并入正式掩膜。不输出已校准正确率，也不把无告警当自动通过。只有三块开发板，007～010未用。</p><p><a href="sample004_case_comparison.png">004已确认漏段开发案例</a> · <a href="SUMMARY.csv">全部组汇总</a> · <a href="PLAN.json">初始工程规则</a></p>'+''.join(cards)+'</main>',encoding='utf-8')
    need(all(sha(p)==v for p,v in all_sources.items()),'Original input changed');need(all(sha(p)==v for p,v in source_sha.items()),'Confidence source changed');need(verify_formal_package()==formal_binding,'Formal package changed')
    write(out/'VERIFICATION.json',dict(status='PASS',source_sha256=source_sha,input_files_sha256=all_sources,input_unique_files=len(all_sources),groups=len(data),frames=8*len(data),physical_boards=len(set(r['sample'] for r in data)),formal_binding_sha256=formal_binding,formal_all10_reproduced=True,formal_masks_unchanged=True,all_rim_controls_have_zero_nonrim_additions=True,
        no_unseeded_evidence_merged_into_detection=True,manual_path_used_for_prediction=False,no_calibrated_probability=True,no_automatic_pass=True,independent_validation=False,FPGA_work_deferred=True,FPGA_changed=False,bit_programmed=False,new_captures=0,TJ_model_run=False,runtime_seconds=time.monotonic()-start))
    print('CONFIDENCE_SHADOW_PASS',len(data),'groups',round(time.monotonic()-start,2),'seconds',flush=True)
if __name__=='__main__':main()
