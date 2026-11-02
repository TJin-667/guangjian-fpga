"""Post-freeze sensitivity assets; chosen configuration is never rewritten."""
import argparse,hashlib,itertools,json,re,sys,time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from sleeve_runtime import load_sealed,predict,verify_inputs
from sleeve_guard import prepare,apply
from run_body import path_support
from run_joint import topology
from run_study import read,write,sha,labelled,sheet,csv_write

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2];ROOT=Path('E:/GuangjianData/reviews/joint_threshold_tuning_20261029')
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);start=time.monotonic();frozen=read(ROOT/'sleeve_01/FROZEN_CONFIG.json');frozen_sha=sha(ROOT/'sleeve_01/FROZEN_CONFIG.json');c=frozen['selected']['config'];data=read(ROOT/'run_01/DATASETS.json');plan=read(HERE/'PLAN.json');annotation=read(REPO/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json');points=annotation['path_points'];selected_rec=next(r for r in data if r['group_id']==annotation['group_id']);x=load_sealed(selected_rec['root']);mean=np.rint(x['planes']['gray'].astype('float32').mean(0)).astype('uint8');native_base=np.repeat(mean[:,:,None],3,axis=2);native_base[x['original']]=[255,210,0]
    threshold_dir=out/'threshold66';threshold_dir.mkdir();pair_rows=[];pair_tiles=[];cells={};chosen_comparison=None
    for weak,strong in itertools.product(plan['grid']['weak'],plan['grid']['strong']):
        config={**c,'weak':weak,'strong':strong};res=predict(x,config);mask=res['candidate'];rgb=native_base.copy();rgb[mask&~x['original']]=[0,225,240];name=f'weak{weak:g}_strong{strong:g}.png';support=path_support(mask,points)
        im=labelled(rgb,[f'004 受控结构＋侧向上限6/20：弱{weak:g}/强{strong:g}',f'手绘走廊支持{support}/268；其他限制保持冻结值',annotation['group_id']]);im.save(threshold_dir/name);pair_tiles.append((f'{weak:g}/{strong:g}：{support}位置',im));pair_rows.append(dict(weak=weak,strong=strong,weak_cutoff=int(np.floor(81*weak)),strong_cutoff=int(np.floor(81*strong)),path_positions=support,candidate_pixels=int(mask.sum()),added_pixels=int((mask&~x['original']).sum())));cells[(weak,strong)]=(name,support)
        if weak==c['weak'] and strong==c['strong']:
            with np.load(ROOT/'sleeve_01'/annotation['group_id']/'masks.npz',allow_pickle=False) as z:
                diff={k:int(np.count_nonzero(z[k]!=v)) for k,v in res.items()}
            if any(diff.values()):raise AssertionError('Reusable runtime differs from selected study output')
            chosen_comparison=diff
    verify_inputs(x);csv_write(out/'FINAL_RESTRICTIONS_66_PAIRS.csv',pair_rows);sheet(pair_tiles,out/'sample004_final66.png',columns=6,cell=(345,410));write(out/'REUSABLE_RUNTIME_COMPARISON.json',dict(status='PASS',group_id=annotation['group_id'],differences=chosen_comparison))
    html='<table><tr><th>弱／强</th>'+''.join(f'<th>{s:g}</th>' for s in plan['grid']['strong'])+'</tr>'
    for w in plan['grid']['weak']:
        html+=f'<tr><th>{w:g}</th>'
        for s in plan['grid']['strong']:
            name,support=cells[w,s];html+=f'<td><a href="threshold66/{name}">{support}/268<img src="threshold66/{name}" loading="lazy"></a></td>'
        html+='</tr>'
    html+='</table>'
    # Radius comparison for all23 groups, preserving selected thresholds/gates/tips.
    side_rows=[];side_cards=[];side_dir=out/'side_radii';side_dir.mkdir();drafts={}
    for sample in ('sample004','sample005'):
        d=read(REPO/f'YMW/handoffs/p0_annotation_multiview_20261026/{sample}_annotations_DRAFT.json');drafts[d['group_id']]=d
    draft_records=[]
    for rec in data:
        group=rec['group_id'];source=ROOT/'sleeve_01'/group
        with np.load(source/'masks.npz',allow_pickle=False) as z:original=z['original'].copy();guide=z['guide6_20'].copy();body=z['without_sleeve'].copy()
        with np.load(Path(rec['root'])/'arrays/all8_B1.npz',allow_pickle=False) as z:response=np.abs(z['residual_n'].astype('int32'))
        prep=prepare(original,guide,response);target=side_dir/group;target.mkdir();tiles=[];row_draft=[];native=np.asarray(Image.open(source/'original.png'))[100:];summary=read(Path(rec['root'])/'summary.json')
        for radius in (0,1,2,3):
            res=apply(body,prep,radius,c['strong']);mask=res['candidate'];t=topology(body,mask)
            if t['merged_reference_label_clusters'] or (res['side_addition']&~guide).any():raise AssertionError('Side sensitivity violated cap / merge guard')
            row=dict(group_id=group,sample=rec['sample'],role=rec['role'],side_radius=radius,candidate_pixels=int(mask.sum()),side_added_pixels=int(res['side_addition'].sum()),retracted6_20_pixels=int((guide&~mask).sum()),path_positions=path_support(mask,points) if group==annotation['group_id'] else None)
            side_rows.append(row);np.savez_compressed(target/f'radius{radius}.npz',candidate=mask,side_addition=res['side_addition']);rgb=native.copy();rgb[mask&~original]=[0,225,240]
            im=labelled(rgb,[f'{rec["sample"]} | 6/20套内侧增长半径{radius}px',f'新增侧像素{row["side_added_pixels"]}；弱{c["weak"]:g}/强{c["strong"]:g}，端部参数固定',group]);im.save(target/f'radius{radius}.png');tiles.append((f'侧增长{radius}px',im))
            if group in drafts:
                d=drafts[group];roi=summary['roi_xywh'];paths=[]
                for item in d['annotations']:
                    if item['class']!='scratch':continue
                    xy=np.rint(np.asarray(item['points_xy'])-np.array(roi[:2])).astype(int);pm=np.zeros_like(mask,np.uint8);cv2.polylines(pm,[xy.reshape(-1,1,2)],False,1,1);ys,xs=np.nonzero(pm);dilate=lambda m:cv2.dilate(m.astype('uint8'),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)))
                    paths.append(dict(annotation_id=item['annotation_id'],state=item['state'],path_pixels=len(xs),original_support=int(dilate(original)[ys,xs].sum()),guide_support=int(dilate(guide)[ys,xs].sum()),selected_support=int(dilate(mask)[ys,xs].sum())))
                row_draft.append(dict(side_radius=radius,paths=paths))
        sheet(tiles,target/'comparison.png',columns=4,cell=(360,425));side_cards.append(f'<section><h2>{rec["sample"]} {rec["low"]}/{rec["high"]} {rec["role"]}</h2><a href="side_radii/{group}/comparison.png"><img src="side_radii/{group}/comparison.png"></a><p>'+ ' · '.join(f'<a href="side_radii/{group}/radius{r}.png">半径{r}原尺寸</a>' for r in (0,1,2,3))+'</p></section>')
        if row_draft:draft_records.append(dict(group_id=group,draft_only=True,not_recall=True,radii=row_draft))
    write(out/'SIDE_RADIUS_RESULTS.json',side_rows);csv_write(out/'SIDE_RADIUS_RESULTS.csv',side_rows);write(out/'DRAFT_SIDE_CHECKS.json',draft_records)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>小数阈值与保护套敏感性</title><style>body{font-family:system-ui;background:#eef2f7;color:#17314c;margin:20px}main{max-width:2100px;margin:auto}table{border-collapse:collapse;background:white;width:100%}td,th{border:1px solid #d4dce6;padding:5px;font-size:13px}td img{width:100%;height:auto}section{background:white;padding:14px;margin:20px 0}section img{max-width:100%}</style><main><h1>最终限制条件固定：全部66组小数阈值</h1><p>点击表内图打开原尺寸。数字为004手绘走廊附近支持，不是召回率。以下半径0/1/2/3敏感性只改侧增长，端部参数与曝光保持不变。</p>'+html+'<h1>23组保护套松紧对照</h1>'+''.join(side_cards)+'</main>',encoding='utf-8')
    refs=re.findall(r'(?:src|href)="([^"#]+)"',(out/'index.html').read_text('utf-8'));missing=[r for r in refs if not (out/r).is_file()]
    if missing:raise AssertionError('Missing sensitivity assets')
    if sha(ROOT/'sleeve_01/FROZEN_CONFIG.json')!=frozen_sha:raise AssertionError('Postchecks altered chosen config')
    write(out/'VERIFICATION.json',dict(status='PASS',final_config_sha256=frozen_sha,threshold_pairs=66,side_group_radius_checks=len(side_rows),assets_checked=len(refs),missing_assets=[],selected_reusable_runtime_fields_zero_difference=True,config_unchanged=True,no_new_merges=True,side_cap6_20_pass=True,old_drafts_not_truth=True,not_independent_validation=True,runtime_seconds=time.monotonic()-start))
    (ROOT/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>光鉴联合阈值实验</title><style>body{font:18px system-ui;max-width:1000px;margin:50px auto;color:#17314c;line-height:1.8}a{display:block;padding:14px;background:#eef2f7;margin:12px 0}</style><h1>联合阈值与6/20侧向保护套</h1><p>现用程序和bit未切换；所有结果来自既有三块开发板。</p><a href="sleeve_01/index.html">当前折中实验版：23组原尺寸对照</a><a href="post_01/index.html">全部66组0.2步长阈值、保护套0/1/2/3像素对照</a><a href="body_01/index.html">主干限制对照：不进行侧向增厚</a><a href="run_01/index.html">早期对照：完整保护6/20，含7128配置</a>',encoding='utf-8')
    print('POST_SENSITIVITY_PASS',len(pair_rows),len(side_rows),flush=True)
if __name__=='__main__':main()
