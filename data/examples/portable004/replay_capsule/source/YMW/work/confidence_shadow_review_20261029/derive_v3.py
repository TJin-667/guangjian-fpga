"""Remove score-biased probe truncation for FHD-sized confidence inputs."""
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
plan=json.loads((HERE/'PLAN_V2.json').read_text('utf-8'))
plan['schema']='confidence-shadow-evidence-v3'
plan['raw_direct_scan']['max_proposals']=262144
plan['v3_reason']='v2 exceeded12000 proposals and preferentially kept strongest stations, which is unsuitable for finding weak missed lines. v3 processes all currentFHD/stride4 proposals; future overflow yields a separate capacity warning, never a full-frame fake line.'
(HERE/'PLAN_V3.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
source=(HERE/'raw_line_scan.py').read_text('utf-8')
old="bbox_xywh=[0,0,board.shape[1],board.shape[0]],raw_supported=True"
assert source.count(old)==1
(HERE/'raw_line_scan_v3.py').write_text(source.replace(old,"bbox_xywh=[0,0,board.shape[1],board.shape[0]],raw_supported=False"),encoding='utf-8')
batch=(HERE/'run_v2.py').read_text('utf-8').replace('from raw_line_scan import scan_combined','from raw_line_scan_v3 import scan_combined').replace("HERE/'PLAN_V2.json'","HERE/'PLAN_V3.json'")
(HERE/'run_v3.py').write_text(batch,encoding='utf-8')
print('V3_DERIVED_PRIOR_VERSIONS_UNCHANGED')
