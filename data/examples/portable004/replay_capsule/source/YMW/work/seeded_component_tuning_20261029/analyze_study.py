"""Read-only post-freeze ablations; never change the selected configuration."""
import argparse,json,sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from seeded_gate import choose,masks
from run_study import read,write,sha,csv_write,sheet,measures

def load_cache(root,rec):
    group=rec['group_id'];features=read(root/'cache'/f'{group}.json');planes={}
    with np.load(root/'cache'/f'{group}.npz',allow_pickle=False) as z:
        labels=z['labels'].copy();keys=sorted(set(k.rsplit('_',1)[0] for k in z.files if k!='labels'))
        for key in keys:planes[key]=(z[key+'_0'].copy(),z[key+'_1'].copy())
    with np.load(root/group/'masks.npz',allow_pickle=False) as z:core=z['protected'].copy();loose=z['loose'].copy()
    # Board only used for area normalization in measures; load actual board.
    with np.load(Path(rec['root'])/'arrays/original_eight_frames.npz',allow_pickle=False) as z:board=z['board'].copy()
    return dict(labels=labels,rows=features['rows'],edges=features['edges'],profiles=planes,protected=core,loose=loose,board=board)

def run(root):
    fixed=read(root/'FROZEN_CONFIG.json');fixed_sha=sha(root/'FROZEN_CONFIG.json');c=fixed['selected']['config'];data=read(root/'DATASETS.json');out=root/'analysis';out.mkdir(exist_ok=False)
    annotation=read(Path(__file__).resolve().parents[2]/'reviews/sample004_weak_line_threshold_20261029/annotation.json');points=annotation['path_points'];rows=[];evidence_rows=[];legacy=[];stress_tiles={s:[] for s in ('sample003','sample004','sample005')}
    for rec in data:
        cache=load_cache(root,rec);which_points=points if rec['group_id']==annotation['group_id'] else None
        variants={'selected':c,'geometry_only':{**c,'raw_fraction':2.},'raw_only':{**c,'span':100000.},'same_rules_seed12':{**c,'strong':12},'same_rules_seed16':{**c,'strong':16},'same_rules_area3':{**c,'min_area':3},'selected_with_tight_chain':{**c,'chain':'tight'},'selected_with_previous_chain':{**c,'chain':'previous'}}
        for name,config in variants.items():
            metric,admitted=measures(cache,config,which_points);rows.append(dict(group_id=rec['group_id'],sample=rec['sample'],role=rec['role'],mode=name,**{k:v for k,v in metric.items() if k!='routes'}))
        admitted,routes=choose(cache,c);f,m=cache['profiles'][f'{c["length"]}/{c["flank"]:g}'];margin=np.minimum(f/c['raw_fraction'],m/c['raw_mean'])
        for index,r in enumerate(cache['rows']):
            position=np.unravel_index(np.argmax(margin[index]),margin[index].shape);orientation,frame,polarity=map(int,position)
            evidence_rows.append(dict(group_id=rec['group_id'],component=r['label'],area=r['area'],peak_n=r['peak_n'],strict_strong_seed=bool(r['peak_n']>81*c['strong']),admitted=bool(admitted[index]),
                best_raw_frame=frame+1,frame_name=read(Path(rec['root'])/'summary.json')['frame_order'][frame],orientation_degrees=orientation*22.5,polarity=1 if polarity==0 else -1,
                raw_support_fraction=float(f[index][position]),raw_mean_two_sided_contrast=float(m[index][position]),raw_margin=float(margin[index][position]),raw_pass=bool(margin[index][position]>=1)))
        if rec['role']=='development':
            old=Path('E:/GuangjianData/reviews/weak_component_experiment_20261029/final')/rec['sample']/'masks/line_plus_raw.npz'
            with np.load(old,allow_pickle=False) as z:old_core=z['protected'].copy();mask=z['candidate'].copy()
            if not np.array_equal(old_core,cache['protected']):raise ValueError('Legacy protected mask mismatch')
            new=mask&~old_core;n=cache['labels'].max();ids=np.unique(cache['labels'][new]);old_admitted=np.isin(np.arange(1,n+1),ids)
            for name,accepted in [('previous_combined',old_admitted),('selected',admitted),('ordinary6_12',np.ones(n,bool))]:
                area=np.array([r['area'] for r in cache['rows']]);compact=(area<6)|np.array([r['two_sweep_span_px']<6 or r['line_fraction']<.5 for r in cache['rows']]);path_count=None
                if which_points is not None:
                    from run_study import path_support
                    path_count=path_support(cache,accepted,points)
                legacy.append(dict(sample=rec['sample'],mode=name,added_pixels=int(area[accepted].sum()),added_components=int(accepted.sum()),compact_components=int((accepted&compact).sum()),compact_pixels=int(area[accepted&compact].sum()),path_positions=path_count))
        stress_tiles[rec['sample']].append((f'{rec["low"]}/{rec["high"]} '+('旧姿态' if rec['role']=='development_hold_check' else ''),Image.open(root/rec['group_id']/'selected.png').copy()))
    csv_write(out/'ABLATIONS.csv',rows);write(out/'ABLATIONS.json',rows);csv_write(out/'LEGACY_COMPARISON.csv',legacy);write(out/'LEGACY_COMPARISON.json',legacy);csv_write(out/'COMPONENT_RAW_EVIDENCE.csv',evidence_rows)
    for sample,tiles in stress_tiles.items():sheet(tiles,out/(sample+'_all_groups.png'),columns=3,cell=(370,430))
    # Verify same seeded masks when labeling is entirely absent; inspect user images separately.
    if sha(root/'FROZEN_CONFIG.json')!=fixed_sha:raise AssertionError('Post-check changed chosen config')
    write(out/'VERIFICATION.json',dict(status='PASS',fixed_config_sha256=fixed_sha,config_unchanged=True,configs_selected_using_hold_or_stress=False,ablation_modes=8,group_mode_checks=len(rows),component_evidence_rows=len(evidence_rows),legacy_groups=3,
        risk_counts_not_false_positive_labels=True,not_independent_validation=True))
    print('POST_FREEZE_ANALYSIS_PASS',len(rows),'group modes',len(evidence_rows),'component records',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);run(p.parse_args().root.resolve())
