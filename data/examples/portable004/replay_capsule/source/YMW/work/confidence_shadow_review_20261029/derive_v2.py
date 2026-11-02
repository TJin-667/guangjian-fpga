"""Preserve the unsuccessful v1 case and derive an explicit v2 batch entry."""
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
plan=json.loads((HERE/'PLAN.json').read_text('utf-8'))
plan['schema']='confidence-shadow-evidence-v2'
plan['raw_direct_scan']=dict(length=13,flank=2.5,screen_mean=1.5,grid_stride=4,max_proposals=12000,rim_tolerance_px=2,support_fraction=.75,mean_contrast=2.,min_stations=5,min_span=20,max_station_gap=8.5,angle_degrees=30)
plan['v2_reason']='v1 residual-fragment gate failed on the known004 missing line. v2 proposes stations directly from raw directional contrast before exact profile/track checks. Development-driven revision, not independent validation.'
(HERE/'PLAN_V2.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
source=(HERE/'run.py').read_text('utf-8')
old='from evidence import compare,raw_supported_components,scan_without_seed,group_decision,distance_to'
new='from evidence import compare,raw_supported_components,group_decision,distance_to\nfrom raw_line_scan import scan_combined as scan_without_seed'
assert source.count(old)==1
source=source.replace(old,new).replace("HERE/'PLAN.json'","HERE/'PLAN_V2.json'")
marker="status=group_decision(unknown_fraction,len(windows),plan)"
assert source.count(marker)==1
source=source.replace(marker,marker+";status='REVIEW_ANALYSIS_CAPACITY' if any(r.get('kind')=='raw_scan_capacity_review' for r in scan_rows) else status")
(HERE/'run_v2.py').write_text(source,encoding='utf-8')
print('V2_DERIVED_V1_UNCHANGED')
