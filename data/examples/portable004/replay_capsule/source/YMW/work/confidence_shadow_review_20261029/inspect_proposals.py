"""Development-only diagnosis; reference is never supplied to inference."""
import json
from pathlib import Path
import cv2,numpy as np
from raw_line_scan_v3 import dense_proposals,connect_stations
from evidence import profiles
from run_study import read,write
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2];ROOT=Path('E:/GuangjianData/reviews/confidence_shadow_review_20261029')
plan=read(HERE/'PLAN_V3.json');cfg=plan['raw_direct_scan'];source=Path('E:/GuangjianData/B1Detection/sample004_400-800_20261029_011210_f71863d7');z=np.load(source/'arrays/original_eight_frames.npz');formal=np.load('E:/GuangjianData/reviews/joint_threshold_tuning_20261029/sleeve_01/sample004_A_v1_20261028_220937_87f02b/masks.npz')['candidate'];annotation=read(REPO/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json');xy=np.asarray(annotation['path_points']);path=np.zeros_like(formal,np.uint8);cv2.polylines(path,[np.rint(xy).astype('int32').reshape(-1,1,2)],False,1,1);dist=cv2.distanceTransform(1-path,cv2.DIST_L2,cv2.DIST_MASK_PRECISE);records=[]
for stride in (4,2):
    points,stats=dense_proposals(formal,z['gray'],z['board'],{**cfg,'grid_stride':stride});ix=points[:,0].astype(int);iy=points[:,1].astype(int);near=points[dist[iy,ix]<=3];f,m=profiles(near,z['gray'],z['valid'],z['board'],13,2.5);good=(f>=.75)&(m>=2);rr=[]
    for frame in (3,7):
        chosen=np.flatnonzero(good[:,:,frame,1].any(axis=1));p=near[chosen];fits=good[chosen,:,frame,1];clusters=connect_stations(p,fits,8.5,30);sizes=[dict(points=len(ids),span=float(np.linalg.norm(np.ptp(p[ids],axis=0)))) for ids in clusters];rr.append(dict(frame=frame+1,good_points=len(chosen),xy=p.tolist(),clusters=sizes))
    records.append(dict(stride=stride,total_proposals=len(points),near_reference_points=len(near),frame_checks=rr));print('STRIDE',stride,'near',len(near),'good',[(r['frame'],r['good_points'],sorted(r['clusters'],key=lambda v:-v['points'])[:4]) for r in rr],flush=True)
write(ROOT/'PROPOSAL_DIAGNOSIS.json',dict(development_reference_only=True,not_prediction=True,records=records))
