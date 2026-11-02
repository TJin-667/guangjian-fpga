"""Maximum6/20 envelope diagnostic, separate from the frozen knee selection."""
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from sleeve_guard import prepare,apply
from run_joint import topology
from run_body import path_support
from run_study import read,write,sha,labelled,sheet,csv_write

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2];ROOT=Path('E:/GuangjianData/reviews/joint_threshold_tuning_20261029')
def main():
    out=ROOT/'full_sleeve_02';out.mkdir(exist_ok=False);frozen=read(ROOT/'sleeve_01/FROZEN_CONFIG.json');digest=sha(ROOT/'sleeve_01/FROZEN_CONFIG.json');c=frozen['selected']['config'];records=read(ROOT/'run_01/DATASETS.json');annotation=read(REPO/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json');rows=[];draft=[]
    for rec in records:
        group=rec['group_id'];source=ROOT/'sleeve_01'/group
        with np.load(source/'masks.npz',allow_pickle=False) as z:original=z['original'].copy();guide=z['guide6_20'].copy();body=z['without_sleeve'].copy()
        with np.load(Path(rec['root'])/'arrays/all8_B1.npz',allow_pickle=False) as z:r=np.abs(z['residual_n'].astype('int32'))
        res=apply(body,prepare(original,guide,r),1e9,c['strong']);mask=res['candidate'];t=topology(body,mask)
        if t['merged_reference_label_clusters'] or (res['side_addition']&~guide).any():raise AssertionError('Full envelope guard failed')
        target=out/group;target.mkdir();np.savez_compressed(target/'masks.npz',candidate=mask,side_addition=res['side_addition']);native=np.asarray(Image.open(source/'original.png'))[100:].copy();native[mask&~original]=[0,225,240];im=labelled(native,[f'{rec["sample"]}：完整6/20侧向上限，仍检查碰合','完整套是对照，不代表已证明背景误检可接受',group]);im.save(target/'selected.png')
        row=dict(group_id=group,sample=rec['sample'],role=rec['role'],candidate_pixels=int(mask.sum()),side_added_pixels=int(res['side_addition'].sum()),retracted6_20_pixels=int((guide&~mask).sum()),new_merges=t['merged_reference_label_clusters'],path_positions=path_support(mask,annotation['path_points']) if group==annotation['group_id'] else None);rows.append(row)
        if rec['role']=='development_hold_check':
            d=read(REPO/f'YMW/handoffs/p0_annotation_multiview_20261026/{rec["sample"]}_annotations_DRAFT.json');roi=read(Path(rec['root'])/'summary.json')['roi_xywh'];pp=[]
            for item in d['annotations']:
                if item['class']!='scratch':continue
                xy=np.rint(np.asarray(item['points_xy'])-np.array(roi[:2])).astype(int);path=np.zeros_like(mask,np.uint8);cv2.polylines(path,[xy.reshape(-1,1,2)],False,1,1);ys,xs=np.nonzero(path);count=lambda m:int(cv2.dilate(m.astype('uint8'),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)))[ys,xs].sum());pp.append(dict(annotation_id=item['annotation_id'],original=count(original),guide=count(guide),full_sleeve=count(mask),state=item['state']))
            draft.append(dict(group_id=group,not_recall=True,draft_only=True,paths=pp))
    write(out/'RESULTS.json',rows);csv_write(out/'SUMMARY.csv',rows);write(out/'DRAFT_CHECKS.json',draft)
    if sha(ROOT/'sleeve_01/FROZEN_CONFIG.json')!=digest:raise AssertionError('Diagnostic changed frozen choice')
    write(out/'VERIFICATION.json',dict(status='PASS',groups=23,full6_20_cap=True,new_base_merges_zero=True,selected_config_unchanged=True,not_independent_validation=True))
    print('FULL_ENVELOPE_PASS',len(rows),flush=True)
if __name__=='__main__':main()
