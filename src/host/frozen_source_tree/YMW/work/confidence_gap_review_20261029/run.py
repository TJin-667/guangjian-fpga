"""Reproducible offline five-group study; predictions do not read manual paths."""
import argparse,hashlib,json,re,socket,time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw
from gap_review import analyze
from sleeve_runtime import load_sealed,verify_inputs
from joint_package_contract import verify_package as verify_formal
from shadow_package_contract import verify as verify_previous
from run_study import read,write,sha,font,sheet,csv_write,labelled

HERE=Path(__file__).resolve().parent;PRIOR=HERE.parent/'confidence_shadow_review_20261029';REPO=HERE.parents[2]

def plot_curve(fits,path,title):
    im=Image.new('RGB',(600,320),'white');d=ImageDraw.Draw(im);d.text((10,6),title,font=font(18),fill='#17314c');x0,y0,x1,y1=58,48,575,262;d.line((x0,y0,x0,y1,x1,y1),fill='#64748b',width=2)
    for f in (0,.25,.5,.75,1.):
        y=y1-(y1-y0)*f;d.line((x0,y,x1,y),fill='#e2e8f0');d.text((5,y-8),str(f),font=font(13),fill='#526374')
    for index,fit in enumerate(fits[:2]):
        curve=fit['threshold_curve'];xy=[(x0+(x1-x0)*i/(len(curve)-1),y1-(y1-y0)*r['fraction']) for i,r in enumerate(curve)];color=('#007a85','#ca650d')[index];d.line(xy,fill=color,width=3)
        for (x,y),r in zip(xy,curve):d.ellipse((x-3,y-3,x+3,y+3),fill=color)
        d.text((70,28+index*19),f'CH{fit["direction"]} {fit["exposure"]} polarity={fit["polarity"]}',font=font(13),fill=color)
    for i,r in enumerate(fits[0]['threshold_curve']):d.text((x0+(x1-x0)*i/(len(fits[0]['threshold_curve'])-1)-10,y1+8),str(r['weak']),font=font(12),fill='#526374')
    d.text((60,294),'仅统计未检出缺口内原始响应；降低阈值 →',font=font(14),fill='#526374');im.save(path)

def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic();formal_binding=verify_formal();previous_binding=verify_previous();plan=read(HERE/'PLAN.json');sources={str(p):sha(p) for p in [*HERE.glob('*.py'),HERE/'PLAN.json']};prior_manifest=read(PRIOR/'ARTIFACT_MANIFEST.json')['files_sha256'];inputs={};results=[];contracts=[];html=[];case=None;observed=[]
    def deny(*a,**k):raise RuntimeError('Offline review prohibits sockets')
    socket.socket=deny
    for rec in read(PRIOR/'results/RESULTS.json'):
        group=rec['group_id'];print('BEGIN',group,flush=True);root=Path(rec['root']);x=load_sealed(root);old=PRIOR/'results'/group
        for name in ('confidence_reference_arrays.npz','RAW_EVIDENCE.json'):
            path=old/name;expected=prior_manifest[path.relative_to(PRIOR).as_posix()]
            if sha(path)!=expected:raise ValueError('Previous bound evidence changed '+str(path))
            inputs[str(path)]=expected
        with np.load(old/'confidence_reference_arrays.npz',allow_pickle=False) as z:formal=z['formal_detector_mask'].copy()
        frozen_path=Path('E:/GuangjianData/reviews/joint_threshold_tuning_20261029/sleeve_01')/group/'masks.npz';expected=read(PRIOR/'results/SOURCE_INPUT_BINDINGS.json')['input_files_sha256'][str(frozen_path)]
        if sha(frozen_path)!=expected:raise ValueError('Frozen formal mask source changed')
        with np.load(frozen_path,allow_pickle=False) as z:
            if not np.array_equal(formal,z['candidate']):raise ValueError('Formal mask differs from frozen result')
        inputs[str(frozen_path)]=expected;inputs.update(x['files']);gray=x['planes']['gray'];before=formal.tobytes();res=analyze(formal,gray,x['planes']['valid'],x['board'],x['planes']['residual_n'],plan,read(old/'RAW_EVIDENCE.json'));verify_inputs(x)
        if formal.tobytes()!=before:raise AssertionError('Detection changed')
        target=out/group;target.mkdir();write(target/'GAP_REVIEWS.json',res['gaps']);write(target/'LOCAL_SHAPE_REVIEWS.json',res['shape_reviews']);reviews=[g for g in res['gaps'] if g['review']];partial=[g for g in res['gaps'] if g['selected_probe']['category']=='partial_gap_evidence'];native=np.zeros_like(formal)
        mean=np.rint(gray.astype('float32').mean(0)).astype('uint8');rgb=np.repeat(mean[:,:,None],3,axis=2);rgb[formal]=[255,210,0];view=Image.fromarray(rgb);d=ImageDraw.Draw(view)
        for gap in reviews:
            q=gap['selected_probe'];px,py,w,h=q['bbox_xywh'];d.rectangle((px-4,py-4,px+w+3,py+h+3),outline='#00e5ef',width=2);d.text((px,py-22),f'G{gap["id"]}',font=font(17),fill='#00e5ef')
            for xx,yy in q['supported_missing_native_xy']:native[yy,xx]=True
            fit=q['best_fit'];plot_curve([fit],target/f'G{gap["id"]:03d}_curve.png',f'G{gap["id"]}：缺口响应随阈值变化')
            observed.append(dict(group_id=group,sample=rec['sample'],gap_id=gap['id'],distance_px=gap['distance_px'],category=q['category'],direction=fit['direction'],exposure=fit['exposure'],polarity=fit['polarity'],raw_fraction=fit['raw_fraction'],threshold_growth=fit['threshold_growth'],detail_response_fraction=fit['detail_response_fraction'],missing_samples=q['missing_samples'],manual_class='',manual_notes=''))
        labelled(np.asarray(view),[rec['sample']+'：已有弱线之间的疑似漏段','黄色正式检测不变；青框仅为复检建议',group]).save(target/'gap_review.png');np.savez_compressed(target/'arrays.npz',formal_detector_mask=formal,supported_gap_sample_mask=native)
        record=dict(group_id=group,sample=rec['sample'],role=rec['role'],root=str(root),formal_pixels=int(formal.sum()),endpoints=res['endpoint_count'],geometry_pairs=res['endpoint_pairs'],evaluated_gaps=len(res['gaps']),gap_review_windows=len(reviews),partial_evidence_gaps=len(partial),no_clear_evidence_gaps=sum(g['selected_probe']['category']=='no_clear_gap_evidence' for g in res['gaps']),locally_line_like_prior_records=sum(r['shape_class']=='locally_line_like' for r in res['shape_reviews']),shape_ambiguous_prior_records=sum(r['shape_class']!='locally_line_like' for r in res['shape_reviews']),formal_unchanged=True,confidence_probability=None,automatic_pass=False)
        results.append(record);write(target/'RESULT.json',record);contracts.append(dict(group_id=group,original_b1_differences=x['original_differences'],formal_mask_byte_identical=True,prior_mask_matches_frozen=True));html.append(f'<section><h2>{group}</h2><p>几何缺口{len(res["gaps"])}；建议复检{len(reviews)}；部分证据{len(partial)}。未确认真伪。</p><img src="{group}/gap_review.png"><p><a href="{group}/GAP_REVIEWS.json">完整缺口响应曲线与来源</a> · <a href="{group}/LOCAL_SHAPE_REVIEWS.json">新增候选局部形状</a></p>'+''.join(f'<a href="{group}/G{g["id"]:03d}_curve.png"><img style="max-width:500px" src="{group}/G{g["id"]:03d}_curve.png"></a>' for g in reviews)+'</section>')
        if group=='sample004_A_v1_20261028_220937_87f02b':case=dict(formal=formal,gray=gray,gaps=res['gaps'],native=native,mean=mean)
        print('DONE',rec['sample'],'gaps',len(res['gaps']),'review',len(reviews),'partial',len(partial),flush=True)
    # The known path is evaluation-only; this remains development-driven work.
    if case:
        ann_path=REPO/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json';ann=read(ann_path);inputs[str(ann_path)]=sha(ann_path);xy=np.asarray(ann['path_points']);xs=xy[:,0].astype(int);ys=np.rint(xy[:,1]).astype(int);formal_hit=case['formal'][ys[:,None]+np.arange(-3,4),xs[:,None]].any(axis=1);hit=cv2.dilate(case['native'].astype('uint8'),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)))[ys,xs]>0;inside=np.zeros(len(xs),bool);overlap=[]
        for g in case['gaps']:
            x0,y0,w,h=g['selected_probe']['bbox_xywh'];positions=(xs>=x0-3)&(xs<x0+w+3)&(ys>=y0-3)&(ys<y0+h+3);overlap.append(dict(gap_id=g['id'],review=g['review'],category=g['selected_probe']['category'],path_positions=int(positions.sum()),uncovered_positions=int((positions&~formal_hit).sum())))
            if g['review']:inside|=positions
        write(out/'SAMPLE004_CASE_CHECK.json',dict(manual_path_loaded_after_predictions=True,development_case_not_independent=True,not_recall=True,path_positions=len(xs),formal_support=int(formal_hit.sum()),uncovered=int((~formal_hit).sum()),uncovered_near_gap_supported_samples=int((hit&~formal_hit).sum()),uncovered_in_gap_probe_windows=int((inside&~formal_hit).sum()),gap_overlap=overlap))
        x0,x1=int(xs.min())-35,int(xs.max())+40;y0,y1=int(ys.min())-35,int(ys.max())+35;tiles=[]
        for frame in (3,7):tiles.append((f'原片CH{frame//2+1} 800行',Image.fromarray(case['gray'][frame,y0:y1,x0:x1]).convert('RGB')))
        formal_rgb=np.repeat(case['mean'][:,:,None],3,axis=2);formal_rgb[case['formal']]=[255,210,0];tiles.append(('正式检测保持不变',Image.fromarray(formal_rgb[y0:y1,x0:x1])));probe=np.repeat(case['mean'][:,:,None],3,axis=2);probe[case['native']]=[0,235,245];tiles.append(('青点：缺口内原片＋响应支持',Image.fromarray(probe[y0:y1,x0:x1])));sheet(tiles,out/'sample004_case.png',columns=2,cell=(640,320))
    write(out/'RESULTS.json',results);write(out/'CONTRACT_CHECKS.json',contracts);csv_write(out/'SUMMARY.csv',results);csv_write(out/'MANUAL_GAP_LABELS.csv',observed);(out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>弱线断续区与局部形状复检</title><style>body{font:17px system-ui;background:#eef2f7;color:#17314c;max-width:1500px;margin:30px auto}section{background:white;padding:18px;margin:20px 0}img{max-width:100%}p{line-height:1.7}</style><h1>已有弱划痕之间的疑似漏段：独立复检参考</h1><p>青框/点不是补线。只比较缺口内部，不用两端已检出像素代替证据。仅初始工程规则；无证据不等于物理断口，无告警不自动放行。</p><p><a href="SAMPLE004_CASE_CHECK.json">004开发案例核对</a> · <a href="MANUAL_GAP_LABELS.csv">空白人工确认表</a></p><img src="sample004_case.png">'+''.join(html),encoding='utf-8');refs=re.findall(r'(?:src|href)="([^"#]+)"',(out/'index.html').read_text('utf-8'));assert all((out/ref).is_file() for ref in refs)
    assert all(sha(path)==digest for path,digest in inputs.items());assert all(sha(path)==digest for path,digest in sources.items());assert verify_formal()==formal_binding and verify_previous()==previous_binding
    write(out/'VERIFICATION.json',dict(status='PASS',groups=len(results),frames=8*len(results),physical_boards=len(set(r['sample'] for r in results)),source_sha256=sources,input_files_sha256=inputs,formal_masks_unchanged=True,prior_v4_source_unchanged=True,manual_path_used_in_prediction=False,new_captures=0,FPGA_changed=False,TJ_model_run=False,automatic_pass=False,calibrated_probability=False,runtime_seconds=time.monotonic()-start))
    print('GAP_REVIEW_COMPLETE',len(results),'groups',round(time.monotonic()-start,2),'seconds',flush=True)

if __name__=='__main__':main()
