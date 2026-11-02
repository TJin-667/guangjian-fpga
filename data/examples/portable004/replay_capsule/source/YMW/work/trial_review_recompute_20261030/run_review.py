"""Recompute unchanged review rules for archived trial masks on native frames."""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
import argparse,concurrent.futures,copy,csv,gzip,hashlib,html,importlib.util,json,re,shutil,socket,sys,time,traceback
from pathlib import Path
import cv2,numpy as np
from PIL import Image,ImageDraw,ImageFont

HERE=Path(__file__).resolve().parent;WORK=HERE.parent;REPO=WORK.parent.parent
TRIAL=WORK/'weak_stability_tuning_20261030';ARCHIVE=TRIAL/'results/final'
sys.path.insert(0,str(WORK/'confidence_review_priority_20261029'))
import review as frozen_review
from priority import attach_scores,verify_frozen,file_sha
from large_gap import analyze_large_gaps
windows_for=frozen_review.windows_for
BASELINE=Path('E:/GuangjianData/reviews/confidence_review_priority_20261029/batch_01')
BASE_EVIDENCE=Path('E:/GuangjianData/reviews/confidence_large_gap_batch_20261029/batch_01')
NEW_FINAL=Path('E:/GuangjianData/UnifiedInspection/20261030_021519_f1a8798c/final/sample004_g1793297183316478400')
NEW_ID=NEW_FINAL.name;OLD_ID='sample004_A_v1_20261028_220937_87f02b'

def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def write(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n','utf-8')
def digest(mask):return hashlib.sha256(mask.tobytes()).hexdigest()
def need(ok,why):
    if not ok:raise ValueError(why)
def gzread(p):
    with gzip.open(p,'rt',encoding='utf-8') as f:return json.load(f)
def gzwrite(p,value):
    with gzip.open(p,'wt',encoding='utf-8',compresslevel=6) as f:json.dump(value,f,ensure_ascii=False,allow_nan=False)
def csvwrite(p,rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with Path(p).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def load_private(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def score_identity(s):
    return {k:s[k] for k in ('schema','windows','review_window_count','status','status_text','confidence_probability','automatic_pass','coverage','score_rule','priority_order','manual_acceptance','formal_detector_unchanged')}
def compact(w):
    e=w['representative_evidence']
    return dict(id=w['id'],bbox=[w[k] for k in ('x0','y0','x1','y1')],score=w['evidence_support_score'],priority=w['review_priority'],largest_gap=e['largest_visual_gap_px'],source=e['source'],joint=e['counts']['joint'],samples=e['largest_run']['samples'])
def stable(w):return {k:v for k,v in compact(w).items() if k!='id'}
def compare_windows(old,new):
    oldrows=[compact(w) for w in old['windows']];newrows=[compact(w) for w in new['windows']];overlaps=[]
    for a in oldrows:
        for b in newrows:
            aa,bb=a['bbox'],b['bbox'];intersection=max(0,min(aa[2],bb[2])-max(aa[0],bb[0]))*max(0,min(aa[3],bb[3])-max(aa[1],bb[1]))
            if intersection:
                area_a=(aa[2]-aa[0])*(aa[3]-aa[1]);area_b=(bb[2]-bb[0])*(bb[3]-bb[1]);overlaps.append(dict(old_id=a['id'],new_id=b['id'],intersection_pixels=intersection,intersection_over_smaller=intersection/max(1,min(area_a,area_b)),IoU=intersection/max(1,area_a+area_b-intersection),same_bbox=aa==bb,score_before=a['score'],score_after=b['score']))
    key=lambda w:json.dumps(stable(w),sort_keys=True)
    unchanged=sorted(key(w) for w in old['windows'])==sorted(key(w) for w in new['windows'])
    return dict(old_count=len(oldrows),new_count=len(newrows),old=oldrows,new=newrows,geometry_scores_and_sources_unchanged=unchanged,exact_scored_json_equal=score_identity(old)==score_identity(new),spatial_overlaps=overlaps,ids_are_version_local=True)

def native_arrays(rec,expected,inputs):
    if rec.get('new_native'):
        common=load_private('_review_native_vendor',WORK/'b1_detection_console_20261027/common.py');common.verify_app();vendor,_=common.verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
        study=load_private('_review_native_study',TRIAL/'run_study.py');x,_,_=study.new_context();arrays=x['planes'];inputs.update(x['files'])
        for p,v in x['files'].items():
            if p in expected:need(v==expected[p],'Native source differs from trial proof')
    else:
        p=Path(rec['root'])/'arrays/original_eight_frames.npz';need(str(p) in expected and file_sha(p)==expected[str(p)],'Sealed native planes changed');inputs[str(p)]=expected[str(p)]
        with np.load(p,allow_pickle=False) as z:arrays={k:z[k].copy() for k in ('gray','valid','board','residual_n')}
    need(arrays['gray'].dtype==np.uint8 and arrays['gray'].shape==(8,*arrays['board'].shape),'Actual native gray required')
    gray=arrays['gray'].astype(np.float32);need(np.array_equal(gray.astype(np.uint8),arrays['gray']),'Lossy cache');arrays['gray']=gray
    return arrays

def worker(rec,outroot,plan,base_plan,core_plan):
    cv2.setNumThreads(1);start=time.monotonic();socket.socket=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Offline review only'))
    verify_frozen();gid=rec['group_id'];out=Path(outroot);inputs={};expected=read(ARCHIVE/'INPUT_SHA256.json');arrays=native_arrays(rec,expected,inputs)
    gray,valid,board,residual=(arrays[k] for k in ('gray','valid','board','residual_n'))
    source=ARCHIVE/gid/'masks.npz';manifest=read(TRIAL/'PUBLISH_MANIFEST.json')['files_sha256'];bound={k.replace('\\','/'):v for k,v in manifest.items()};need(file_sha(source)==bound[source.relative_to(TRIAL).as_posix()],'Archived trial masks changed');inputs[str(source)]=file_sha(source)
    with np.load(source,allow_pickle=False) as z:masks={name:z[('frozen' if name=='frozen' else ident)+'__candidate'].copy() for name,ident in plan['versions'].items()}
    original=NEW_FINAL if rec.get('new_native') else BASELINE/gid
    evidence_path=(NEW_FINAL/'GAP_REVIEWS.json.gz') if rec.get('new_native') else BASE_EVIDENCE/gid/'GAP_REVIEWS.json.gz'
    scored_path=original/'REVIEW_PRIORITY.json';inputs[str(evidence_path)]=file_sha(evidence_path);inputs[str(scored_path)]=file_sha(scored_path)
    prior_mask=NEW_FINAL/'formal_arrays.npz' if rec.get('new_native') else BASE_EVIDENCE/gid/'arrays.npz'
    inputs[str(prior_mask)]=file_sha(prior_mask)
    with np.load(prior_mask,allow_pickle=False) as z:need(np.array_equal(masks['frozen'],z['candidate' if rec.get('new_native') else 'formal_detector_mask']),'Review baseline mask mismatch')
    prior=gzread(evidence_path);prior_scored=read(scored_path);baseline=attach_scores(prior,windows_for(prior['gaps']),gray,valid,board,residual,base_plan,core_plan)
    need(score_identity(baseline)==score_identity(prior_scored),'Baseline score reproduction differs '+gid)
    regenerated=False
    if gid in (NEW_ID,OLD_ID):
        rebuilt=analyze_large_gaps(masks['frozen'],gray,valid,board,residual,base_plan,core_plan);need(rebuilt==prior,'Full baseline proposal/evidence changed '+gid);regenerated=True
    cache={digest(masks['frozen']):(prior,baseline,'frozen')};summaries=[];scored_all={};rows_all={}
    preview=ARCHIVE/gid/'original8_preview.jpg';inputs[str(preview)]=file_sha(preview)
    for name,ident in plan['versions'].items():
        target=out/name/gid;target.mkdir(parents=True,exist_ok=False);formal=masks[name];before=digest(formal);key=digest(formal);reuse=None
        if key in cache:
            evidence,scored0,reuse=cache[key];scored=copy.deepcopy(scored0)
        else:
            evidence=analyze_large_gaps(formal,gray,valid,board,residual,base_plan,core_plan);scored=attach_scores(evidence,windows_for(evidence['gaps']),gray,valid,board,residual,base_plan,core_plan);cache[key]=(evidence,copy.deepcopy(scored),name)
        need(digest(formal)==before,'Review changed detection input')
        points=np.zeros_like(formal);largest_points=np.zeros_like(formal)
        for gap in evidence['gaps']:
            if gap['review']:
                for x,y in gap['selected_probe']['supported_missing_native_xy']:points[y,x]=True
        for w in scored['windows']:
            for x,y in w['representative_evidence']['joint_supported_native_xy']:largest_points[y,x]=True
        need(not (points&formal).any() and not (largest_points&formal).any(),'Review support lies on formal candidate')
        need(all(w['evidence_support_score'] in range(0,101,5) and w['confidence_probability'] is None and not w['automatic_pass'] for w in scored['windows']),'Score semantics changed')
        scored.update(group_id=gid,sample=rec['sample'],low=rec['low'],high=rec['high'],formal_config_id=ident,version=name,detector_experimental=name!='frozen',review_code_commit=plan['review_source_commit'],review_rules_changed=False)
        gzwrite(target/'GAP_REVIEWS.json.gz',evidence);write(target/'REVIEW_PRIORITY.json',scored);write(target/'REVIEW_WINDOWS.json',windows_for(evidence['gaps']))
        np.savez_compressed(target/'arrays.npz',formal_detector_mask=formal,review_supported_sample_mask=points,representative_largest_gap_support=largest_points)
        shutil.copy2(preview,target/'original8_preview.jpg')
        display={**rec,'sample':rec['sample']+' · '+({'frozen':'原冻结','A':'试验A 5.2/12','B':'试验B 5.2/12.4','C':'试验C 面积6'}[name])}
        rows=frozen_review.render_group(target,display,arrays,formal,scored)
        for row in rows:row.update(sample=rec['sample'],version=name,detector_id=ident)
        rows_all[name]=rows;scored_all[name]=scored
        summary=dict(group_id=gid,sample=rec['sample'],low=rec['low'],high=rec['high'],role=rec['role'],version=name,detector_id=ident,windows=len(scored['windows']),high_priority=sum(w['review_priority']=='high' for w in scored['windows']),medium_priority=sum(w['review_priority']=='medium' for w in scored['windows']),scores=[w['evidence_support_score'] for w in scored['windows']],formal_mask_sha256=before,evidence_reused_from=reuse,fresh_analysis=reuse is None,endpoint_count=evidence['endpoints'],gap_pairs=evidence['endpoint_pairs'],formal_unchanged_by_review=True,automatic_pass=False)
        write(target/'RECEIPT.json',summary);summaries.append(summary)
    comparisons={name:compare_windows(scored_all['frozen'],scored_all[name]) for name in ('A','B','C')}
    target=out/'comparisons'/gid;target.mkdir(parents=True);write(target/'DIFFERENCES.json',comparisons)
    tiles=[]
    for name in plan['versions']:
        row=next(r for r in summaries if r['version']==name);tiles.append((f'{name} | {row["windows"]}框 | '+','.join(map(str,row['scores'])),Image.open(out/name/gid/'priority_review.png').copy()))
    sheet(tiles,target/'comparison.png',columns=4,cell=(400,490))
    for p,v in inputs.items():need(file_sha(p)==v,'Input changed during group review')
    write(target/'RECEIPT.json',dict(status='PASS',baseline_scores_exact_equal=True,full_baseline_evidence_regenerated_equal=regenerated,input_sha256=inputs,actual_frames=8,versions=4,unique_masks=len(cache),runtime_seconds=time.monotonic()-start))
    return dict(record=rec,summaries=summaries,comparisons=comparisons,rows=rows_all,inputs=inputs,unique_masks=len(cache),baseline_regenerated=regenerated,runtime_seconds=time.monotonic()-start)

def font(size):return ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',size)
def sheet(tiles,path,columns=4,cell=(400,490)):
    import math
    w,h=cell;im=Image.new('RGB',(w*columns,h*math.ceil(len(tiles)/columns)),'#eef2f7');d=ImageDraw.Draw(im)
    for i,(title,tile) in enumerate(tiles):
        x=i%columns*w;y=i//columns*h;d.text((x+6,y+4),title,font=font(16),fill='#17314c');tile=tile.copy();tile.thumbnail((w-12,h-43),Image.Resampling.LANCZOS);im.paste(tile,(x+(w-tile.width)//2,y+36))
    im.save(path)

def finalize(out,records,results,plan,source_sha,start):
    rows=[row for result in results for row in result['summaries']];csvwrite(out/'SUMMARY.csv',[{**r,'scores':','.join(map(str,r['scores']))} for r in rows]);write(out/'GROUP_RESULTS.json',rows)
    for name in plan['versions']:
        human=[]
        for result in results:human+=result['rows'][name]
        frozen_review.overview(out/name,records,human)
        write(out/name/'SUMMARY.json',dict(version=name,detector_id=plan['versions'][name],groups=len(records),windows=len(human),review_rules_unchanged=True,score_rules_unchanged=True,human_acceptance='PENDING',automatic_pass=False,probability_calibrated=False))
    sections=[];table=[];differences={}
    for result in results:
        rec=result['record'];gid=rec['group_id'];differences[gid]=result['comparisons'];lookup={r['version']:r for r in result['summaries']};links=' · '.join(f'<a href="../../{name}/{gid}/index.html">{name}原片与逐框证据</a>' for name in plan['versions'])
        body=f'<h1>{rec["sample"]} {rec["low"]}/{rec["high"]}行</h1><p>{gid}</p><p>A弱5.2强12；B弱5.2强12.4；C面积6；复检规则和分数规则全部保持原样。R编号只属于各版本，不能直接按编号视为同一缺口。</p><p>{links}</p><img src="comparison.png"><p><a href="DIFFERENCES.json">坐标、分数、原片来源及空间重叠关系</a> · <a href="../../index.html">全部组</a></p>'
        (out/'comparisons'/gid/'index.html').write_text(frozen_review.page('四版复检对照',body),'utf-8')
        cells=''.join(f'<td>{lookup[name]["windows"]}框 / '+','.join(map(str,lookup[name]['scores']))+'</td>' for name in plan['versions'])
        table.append(f'<tr><td><a href="comparisons/{gid}/index.html">{rec["sample"]} {rec["low"]}/{rec["high"]}<br>{gid}</a></td>{cells}</tr>')
    focus=[r for r in results if r['record']['group_id'] in (NEW_ID,OLD_ID)]
    for result in focus:
        gid=result['record']['group_id'];sections.append(f'<h2>{"本次004" if gid==NEW_ID else "旧004"}</h2><a href="comparisons/{gid}/index.html"><img src="comparisons/{gid}/comparison.png"></a>')
    totals={name:dict(windows=sum(r['windows'] for r in rows if r['version']==name),high=sum(r['high_priority'] for r in rows if r['version']==name),medium=sum(r['medium_priority'] for r in rows if r['version']==name),changed_groups=sum(not r['comparisons'][name]['geometry_scores_and_sources_unchanged'] for r in results) if name!='frozen' else 0) for name in plan['versions']}
    for sample in ('sample003','sample004','sample005'):
        tiles=[]
        for result in results:
            rec=result['record']
            if rec['sample']!=sample:continue
            for row in result['summaries']:tiles.append((f'{rec["low"]}/{rec["high"]} {row["version"]} | {row["windows"]}框',Image.open(out/row['version']/rec['group_id']/'priority_review.png').copy()))
        sheet(tiles,out/(sample+'_all_versions.png'),columns=4,cell=(340,415))
    body='<h1>冻结版与A/B/C：复检提示重算</h1><p>24组192帧，三块物理工件。仅改变正式检测输入掩膜；复检与证据分规则完全不变。橙框少/分数高不代表整板更好，也不代表没有漏检。新窗口不继承此前人工接受结论。</p><p><a href="SUMMARY.csv">逐组汇总</a> · <a href="WINDOW_DIFFERENCES.json">全部框变化</a> · <a href="VERIFICATION.json">核验</a></p>'+''.join(sections)+'<table><tr><th>工件/曝光/组ID</th><th>冻结</th><th>A</th><th>B</th><th>C</th></tr>'+''.join(table)+'</table>'
    (out/'index.html').write_text(frozen_review.page('试验版复检对照',body),'utf-8');write(out/'WINDOW_DIFFERENCES.json',differences);write(out/'TOTALS.json',totals)
    inputs={}
    for result in results:
        for p,v in result['inputs'].items():need(p not in inputs or inputs[p]==v,'Conflicting input hashes');inputs[p]=v
    for p,v in inputs.items():need(file_sha(p)==v,'Input changed at end')
    need(all(file_sha(p)==v for p,v in source_sha.items()),'Source changed during review');verify_frozen();write(out/'INPUT_SHA256.json',inputs)
    # Existence check includes all frozen renderer navigation and source-frame images.
    write(out/'VERIFICATION.json',dict(status='VERIFYING'))
    links=0
    for page in out.rglob('*.html'):
        for ref in re.findall(r'(?:href|src)="([^"#]+)"',page.read_text('utf-8')):
            need((page.parent/ref.split('#')[0]).resolve().is_file(),'Broken local link '+str(page)+' '+ref);links+=1
    verification=dict(status='PASS',groups=len(records),frames=8*len(records),physical_boards=3,trial_results=3*len(records),baseline_score_reproductions=len(records),exact_baseline_full_evidence_checks=sum(r['baseline_regenerated'] for r in results),unique_group_mask_cases=sum(r['unique_masks'] for r in results),fresh_trial_proposal_analyses=sum(r['fresh_analysis'] for r in rows),identical_mask_reuse_recorded=True,review_rules_unchanged=True,score_rules_unchanged=True,formal_masks_unchanged_by_review=True,automatic_pass=False,probability_calibrated=False,source_files=len(source_sha),input_files=len(inputs),HTML_links=links,production_changed=False,new_captures=0,FPGA_changed=False,runtime_seconds=time.monotonic()-start)
    write(out/'VERIFICATION.json',verification);print('REVIEW_RECOMPUTE_PASS',json.dumps(totals),round(time.monotonic()-start,1),'s',flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--workers',type=int,default=2);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic();plan=read(HERE/'PLAN.json');verify_frozen();base_plan=read(WORK/'confidence_gap_review_20261029/PLAN.json');core_plan=read(WORK/'confidence_large_gap004_20261029/PLAN.json')
    sources={str(HERE/'PLAN.json'):file_sha(HERE/'PLAN.json'),str(Path(__file__)):file_sha(Path(__file__)),str(TRIAL/'PUBLISH_MANIFEST.json'):file_sha(TRIAL/'PUBLISH_MANIFEST.json')};binding=verify_frozen()
    sources.update({str(REPO/k):v for k,v in binding['files_sha256'].items()});write(out/'SOURCE_SHA256.json',sources);write(out/'PLAN.json',plan);write(out/'REVIEW_BASE_PLAN.json',base_plan);write(out/'REVIEW_CORE_PLAN.json',core_plan)
    records=read(ARCHIVE/'DATASETS.json');need(len(records)==24,'Expected24 sealed groups');records.sort(key=lambda r:(0 if r['group_id']==NEW_ID else 1 if r['group_id']==OLD_ID else 2 if r['role']=='development' else 3,r['sample'],r['group_id']));write(out/'DATASETS.json',records);results=[];failures=[]
    for name in plan['versions']:(out/name).mkdir()
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.workers) as pool:
        jobs={pool.submit(worker,r,str(out),plan,base_plan,core_plan):r for r in records}
        for f in concurrent.futures.as_completed(jobs):
            rec=jobs[f]
            try:
                result=f.result();results.append(result);print('DONE',len(results),'/',len(records),rec['group_id'],[(r['version'],r['windows'],r['scores'],r['evidence_reused_from']) for r in result['summaries']],round(result['runtime_seconds'],1),'s',flush=True)
            except Exception as error:failures.append(dict(group_id=rec['group_id'],error=repr(error),trace=traceback.format_exc()));print('FAILED',rec['group_id'],repr(error),flush=True)
            write(out/'PROGRESS.json',dict(done=len(results),failed=len(failures),total=len(records)))
    write(out/'FAILURES.json',failures);need(not failures,'Some groups failed; inspect FAILURES.json, do not promote partial results')
    order={r['group_id']:i for i,r in enumerate(records)};results.sort(key=lambda r:order[r['record']['group_id']]);finalize(out,records,results,plan,sources,start)

if __name__=='__main__':main()
