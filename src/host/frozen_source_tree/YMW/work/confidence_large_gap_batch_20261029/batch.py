"""Apply frozen orange-window review to all existing003/004/005 exposure groups."""
import os
for _thread_env in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[_thread_env]='1'
import argparse,concurrent.futures,gzip,hashlib,json,re,socket,sys,time,traceback
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw

HERE=Path(__file__).resolve().parent;CORE=HERE.parent/'confidence_large_gap004_20261029';sys.path.insert(0,str(CORE))
from large_gap import analyze_large_gaps
import importlib.util
spec=importlib.util.spec_from_file_location('_large_gap_window_utilities',CORE/'run.py');utilities=importlib.util.module_from_spec(spec);spec.loader.exec_module(utilities)
from sleeve_runtime import load_sealed,predict,verify_inputs
from joint_package_contract import verify_package as verify_formal
from run_study import read,write,sha,csv_write,font,sheet,labelled

def panel_header(rgb,record,line):
    return labelled(rgb,[f'{record["sample"]} | {record["low"]}/{record["high"]}行 | gain16=16 LED128',line,record['group_id']])

def worker(record,outroot,plan,core_plan,base_plan):
    cv2.setNumThreads(1);start=time.monotonic();target=Path(outroot)/record['group_id'];target.mkdir(exist_ok=False)
    def deny(*a,**k):raise RuntimeError('Offline batch prohibits sockets')
    socket.socket=deny;binding=verify_formal();x=load_sealed(record['root']);gray=x['planes']['gray'];gray_cached=gray.astype('float32');x['planes']['gray']=gray_cached
    result=predict(x,read(HERE.parent/'joint_threshold_tuning_20261029/FROZEN_SLEEVE_CONFIG.json')['selected']['config']);frozen_path=Path(plan['formal_masks'])/record['group_id']/'masks.npz';frozen_sha=sha(frozen_path)
    with np.load(frozen_path,allow_pickle=False) as z:
        if set(z.files)!=set(result):raise ValueError('Frozen output keys differ')
        differences={k:int(np.count_nonzero(result[k]!=z[k])) for k in result}
    if any(differences.values()):raise ValueError('Formal output differs '+repr(differences))
    formal=result['candidate'].copy();before=formal.tobytes();evidence=analyze_large_gaps(formal,gray_cached,x['planes']['valid'],x['board'],x['planes']['residual_n'],base_plan,core_plan);assert formal.tobytes()==before
    reproduction=None
    if record['group_id']=='sample004_A_v1_20261028_220937_87f02b':
        previous=Path('E:/GuangjianData/reviews/confidence_large_gap004_20261029/run_01/GAP_REVIEWS.json.gz')
        with gzip.open(previous,'rt',encoding='utf-8') as f:saved=json.load(f)
        reproduction=dict(previous_sha256=sha(previous),evidence_exact_equal=evidence==saved,float32_conversion_lossless=bool(np.array_equal(gray_cached.astype('uint8'),gray)))
        if not reproduction['evidence_exact_equal']:raise ValueError('Cached004 review differs from original algorithm')
    windows=utilities.windows_for(evidence['gaps']);reviews=[g for g in evidence['gaps'] if g['review']];points=np.zeros_like(formal);rows=[]
    for g in evidence['gaps']:
        q=g['selected_probe'];f=q['best_fit'];rows.append(dict(id=g['id'],review=g['review'],priority=q['visual']['priority'],longest_visual_gap_px=q['visual']['longest_visual_gap_px'],distance_px=g['distance_px'],aligned=g['aligned'],long_pair=g['long_pair'],category=q['category'],review_weak=q['review_weak_used'],frame=f['frame'],direction=f['direction'],exposure=f['exposure'],polarity=f['polarity'],raw_fraction=f['raw_fraction'],response_fraction=f['detail_response_fraction'],joint_fraction=f['joint_fraction'],threshold_growth=f['threshold_growth']))
        if g['review']:
            for xx,yy in q['supported_missing_native_xy']:points[yy,xx]=True
    assert not (points&formal).any()
    with gzip.open(target/'GAP_REVIEWS.json.gz','wt',encoding='utf-8',compresslevel=6) as f:json.dump(evidence,f,ensure_ascii=False,allow_nan=False)
    write(target/'REVIEW_WINDOWS.json',windows);csv_write(target/'GAP_SUMMARY.csv',rows);np.savez_compressed(target/'arrays.npz',formal_detector_mask=formal,review_supported_sample_mask=points)
    mean=np.rint(gray_cached.mean(0)).astype('uint8');rgb=np.repeat(mean[:,:,None],3,axis=2);detector=rgb.copy();detector[formal]=[255,210,0];orange=Image.fromarray(detector);d=ImageDraw.Draw(orange)
    for w in windows:
        x0=max(0,w['x0']);y0=max(0,w['y0']);x1=min(formal.shape[1]-1,w['x1']);y1=min(formal.shape[0]-1,w['y1']);d.rectangle((x0,y0,x1,y1),outline='#ff9100',width=2);d.text((x0,max(0,y0-21)),str(w['id']),font=font(16),fill='#ff9100')
    panel_header(detector,record,'黄色：冻结检测，结果逐像素核对一致').save(target/'detector.png');panel_header(np.asarray(orange),record,f'橙框：{len(windows)}个待复检区域；无框也不自动通过').save(target/'orange_review.png')
    rawtiles=[]
    for frame in (0,2,4,6,1,3,5,7):rawtiles.append((f'CH{frame//2+1} '+str(record['low'] if frame%2==0 else record['high'])+'行',Image.fromarray(gray[frame]).convert('RGB')))
    sheet(rawtiles,target/'original8_preview.jpg',columns=4,cell=(280,250))
    summary=dict(**record,formal_config_id=plan['formal_config_id'],formal_pixels=int(formal.sum()),formal_dimensions_xy=[formal.shape[1],formal.shape[0]],review_windows=len(windows),accepted_gap_pairs=len(reviews),large_accepted_gap_pairs=sum(g['selected_probe']['visual']['priority']=='large_visible_gap' for g in reviews),long_distance_accepted_pairs=sum(g['long_pair'] for g in reviews),evaluated_pairs=len(evidence['gaps']),tiny_probe_hypotheses_ignored=evidence['tiny_probe_hypotheses_ignored'],formal_output_differences=differences,formal_unchanged=True,confidence_probability=None,automatic_pass=False,runtime_seconds=time.monotonic()-start)
    write(target/'RESULT.json',summary)
    (target/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>'+record['group_id']+'</title><style>body{font:17px system-ui;max-width:1900px;margin:25px auto;color:#17314c}img{max-width:100%}.pair{display:grid;grid-template-columns:1fr 1fr;gap:15px}p{line-height:1.7}</style><h1>'+record['sample']+f' {record["low"]}/{record["high"]}行</h1><p>'+record['group_id']+'。黄色为冻结检测；橙框为复检建议，不能当作检出或真实划痕条数。原片预览仅缩放，不增强对比。</p><div class="pair"><a href="detector.png"><img src="detector.png"></a><a href="orange_review.png"><img src="orange_review.png"></a></div><p><a href="GAP_SUMMARY.csv">逐缺口汇总</a> · <a href="GAP_REVIEWS.json.gz">完整无损证据</a></p><h2>同组八帧原片预览</h2><a href="original8_preview.jpg"><img src="original8_preview.jpg"></a>',encoding='utf-8')
    verify_inputs(x);assert sha(frozen_path)==frozen_sha;assert verify_formal()==binding;input_hashes={**x['files'],str(frozen_path):frozen_sha};write(target/'receipt.json',dict(status='PASS',group_id=record['group_id'],input_files_sha256=input_hashes,formal_all10_differences=differences,formal_mask_byte_identical=True,cached004_reproduction=reproduction,gray_cached_as_lossless_float32=True,new_captures=0,FPGA_changed=False,manual_reference_used=False,runtime_seconds=time.monotonic()-start))
    return summary

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path);p.add_argument('--workers',type=int,choices=(1,2),default=2);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic();plan=read(HERE/'PLAN.json');core_plan=read(CORE/'PLAN.json');base_plan=read(CORE.parent/'confidence_gap_review_20261029/PLAN.json');records=read(plan['dataset_inventory']);records=sorted(records,key=lambda r:(r['sample'],r['low'],r['high'],r['group_id']));assert len(records)==23 and len(set(r['group_id'] for r in records))==23;assert {r['sample'] for r in records}==set(plan['specimens']);assert read(HERE.parent/'joint_threshold_tuning_20261029/FROZEN_SLEEVE_CONFIG.json')['selected']['id']==plan['formal_config_id'];source_paths=[*HERE.glob('*.py'),HERE/'PLAN.json',*CORE.glob('*.py'),CORE/'PLAN.json'];source_hashes={str(p):sha(p) for p in source_paths};write(out/'PLAN.json',plan);write(out/'EFFECTIVE_CORE_PLAN.json',{k:v for k,v in core_plan.items() if k!='only_existing_sample004_group'});write(out/'DATASETS.json',records);results=[];failures=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
        pending={pool.submit(worker,r,str(out),plan,core_plan,base_plan):r for r in records}
        for future in concurrent.futures.as_completed(pending):
            r=pending[future]
            try:summary=future.result();results.append(summary);print('DONE',len(results),'/',len(records),r['sample'],f'{r["low"]}/{r["high"]}',r['group_id'],'windows',summary['review_windows'],round(summary['runtime_seconds'],1),'s',flush=True)
            except Exception as error:failures.append(dict(group_id=r['group_id'],error=repr(error),trace=traceback.format_exc()));print('FAILED',r['group_id'],repr(error),flush=True)
            write(out/'PROGRESS.json',dict(completed=len(results),failed=len(failures),total=len(records)))
    write(out/'FAILURES.json',failures)
    if failures:raise RuntimeError('Batch has failed groups; preserve all outputs and inspect FAILURES.json')
    results.sort(key=lambda r:(r['sample'],r['low'],r['high'],r['group_id']));write(out/'RESULTS.json',results);csv_write(out/'SUMMARY.csv',[{k:v for k,v in r.items() if k not in ('duplicate_result_folders','formal_output_differences')} for r in results]);sections=[]
    for sample in plan['specimens']:
        sample_rows=[r for r in results if r['sample']==sample];tiles=[];body=[]
        for r in sample_rows:
            group=r['group_id'];kind='旧姿态' if r['role']=='development_hold_check' else '主组' if r['role']=='development' else '其他曝光组';title=f'{r["low"]}/{r["high"]}行 | '+kind+f' | 橙框{r["review_windows"]}';tiles.append((title,Image.open(out/group/'orange_review.png').copy()));body.append(f'<figure><figcaption>{title}<br>{group}</figcaption><a href="{group}/index.html"><img src="{group}/orange_review.png"></a><p><a href="{group}/detector.png">黄色冻结检测</a> · <a href="{group}/original8_preview.jpg">八帧原片预览</a> · <a href="{group}/index.html">并排查看与证据</a></p></figure>')
        sheet(tiles,out/(sample+'_all_exposures.png'),columns=3,cell=(460,520));(out/(sample+'.html')).write_text('<!doctype html><meta charset="utf-8"><title>'+sample+'曝光组复检对照</title><style>body{font:18px system-ui;color:#17314c;max-width:1700px;margin:30px auto}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}figure{margin:0;background:#eef2f7;padding:15px}img{max-width:100%}p{line-height:1.7}</style><h1>'+sample+f'：{len(sample_rows)}组既有数据</h1><p>不同摆放与时间已保留组ID。橙框数量不能解释为检出率或曝光优劣；未触发也不是自动通过。</p><div class="grid">'+''.join(body)+'</div>',encoding='utf-8');sections.append(f'<section><h2>{sample} · {len(sample_rows)}组</h2><a href="{sample}.html"><img src="{sample}_all_exposures.png"></a><p><a href="{sample}.html">打开逐组大图与八帧原片</a></p></section>')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>003/004/005橙框复检：全部曝光组</title><style>body{font:18px system-ui;max-width:1500px;margin:30px auto;color:#17314c}img{max-width:100%}p{line-height:1.8}section{background:#eef2f7;padding:18px;margin:25px 0}</style><h1>003、004、005：23组橙框复检对照</h1><p>23组184帧，三块实体工件。沿用004版固定规则：小于等于6像素的小间断不单独告警；走向相符时放宽搜索；黄色冻结检测不变，橙框仅提示人工复检。不同曝光与姿态不是独立工件，未使用007～010。</p><p><a href="SUMMARY.csv">全部汇总</a> · <a href="DATASETS.json">输入来源</a> · <a href="VERIFICATION.json">批次核验</a></p>'+''.join(sections),encoding='utf-8')
    inputs={};cached=None
    for r in results:
        receipt=read(out/r['group_id']/'receipt.json');inputs.update(receipt['input_files_sha256'])
        if receipt['cached004_reproduction'] is not None:cached=receipt['cached004_reproduction']
    assert cached and cached['evidence_exact_equal'];assert all(sha(p)==v for p,v in source_hashes.items());assert all(sha(p)==v for p,v in inputs.items())
    for html in out.rglob('*.html'):
        assert all((html.parent/ref).is_file() for ref in re.findall(r'(?:src|href)="([^"#]+)"',html.read_text('utf-8')) if ref!='VERIFICATION.json')
    write(out/'VERIFICATION.json',dict(status='PASS',groups=23,frames=184,physical_boards=3,specimen_group_counts={s:sum(r['sample']==s for r in results) for s in plan['specimens']},source_sha256=source_hashes,input_files_sha256=inputs,input_unique_files=len(inputs),all_formal10_outputs_reproduced=True,all_formal_masks_byte_identical=True,cached004_evidence_exact_equal=True,lossless_float32_gray_cache=True,manual_annotations_used=False,new_captures=0,FPGA_changed=False,TJ_model_run=False,calibrated_probability=False,automatic_pass=False,runtime_seconds=time.monotonic()-start));print('ALL_EXPOSURE_BATCH_PASS',round(time.monotonic()-start,2),'seconds',flush=True)

if __name__=='__main__':main()
