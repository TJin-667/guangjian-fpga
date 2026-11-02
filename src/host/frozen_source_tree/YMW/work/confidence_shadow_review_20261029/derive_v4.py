"""Increase raw station proposal density without changing detection/line tests."""
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
plan=json.loads((HERE/'PLAN_V3.json').read_text('utf-8'))
plan['schema']='confidence-shadow-evidence-v4'
plan['raw_direct_scan']['grid_stride']=2
plan['raw_direct_scan']['max_proposals']=524288
plan['v4_reason']='Development-only proposal diagnosis showed stride4 retained too few exact-profile-supported stations to form a20px track on the known weak line; stride2 retains denser real stations. Contrast, polarity, seed policy and track evidence tests are unchanged. All FHD/stride2 proposal cells fit the explicit capacity.'
(HERE/'PLAN_V4.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
batch=(HERE/'run_v3.py').read_text('utf-8').replace("HERE/'PLAN_V3.json'","HERE/'PLAN_V4.json'")
(HERE/'run_v4.py').write_text(batch,encoding='utf-8')
test=(HERE/'test_raw_scan.py').read_text('utf-8').replace('from raw_line_scan import raw_direct_scan','from raw_line_scan_v3 import raw_direct_scan,dense_proposals').replace("'PLAN_V2.json'","'PLAN_V4.json'")
needle="    def test_single_direction_retained(self):"
extra="    def test_denser_proposals_keep_sparse_grid_candidates(self):\n        formal,r,b,g,v=scene(curve=True); cfg=PLAN['raw_direct_scan']; sparse,_=dense_proposals(formal,g,b,{**cfg,'grid_stride':4}); dense,_=dense_proposals(formal,g,b,cfg); self.assertTrue(set(map(tuple,sparse)).issubset(set(map(tuple,dense))))\n"
assert needle in test
(HERE/'test_raw_scan_v4.py').write_text(test.replace(needle,extra+needle),encoding='utf-8')
print('V4_DERIVED_NO_EVIDENCE_THRESHOLDS_RELAXED')
