import json,unittest
from pathlib import Path
import numpy as np
from raw_line_scan_v3 import raw_direct_scan,dense_proposals
from test_evidence import scene
PLAN=json.loads((Path(__file__).resolve().parent/'PLAN_V4.json').read_text('utf-8'))
class RawScanTests(unittest.TestCase):
    def test_raw_continuous_line_without_strong_seed(self):
        formal,r,b,g,v=scene();before=formal.copy();mask,rows,stats=raw_direct_scan(formal,r,b,g,v,PLAN);self.assertTrue(rows);self.assertTrue(any(not x['has_strong_seed'] for x in rows));self.assertTrue(any(len(x['supported_directions'])>=2 for x in rows));self.assertTrue(np.array_equal(formal,before))
    def test_denser_proposals_keep_sparse_grid_candidates(self):
        formal,r,b,g,v=scene(curve=True); cfg=PLAN['raw_direct_scan']; sparse,_=dense_proposals(formal,g,b,{**cfg,'grid_stride':4}); dense,_=dense_proposals(formal,g,b,cfg); self.assertTrue(set(map(tuple,sparse)).issubset(set(map(tuple,dense))))
    def test_single_direction_retained(self):
        formal,r,b,g,v=scene(frames=(3,));mask,rows,stats=raw_direct_scan(formal,r,b,g,v,PLAN);self.assertTrue(rows);self.assertTrue(all(x['supported_directions']==[2] for x in rows))
    def test_flat_image_no_line_evidence(self):
        formal,r,b,g,v=scene();g[:]=100;mask,rows,stats=raw_direct_scan(formal,r,b,g,v,PLAN);self.assertFalse(rows)
    def test_step_edge_does_not_become_two_sided_line(self):
        formal,r,b,g,v=scene();g[:,:,:80]=80;g[:,:,80:]=100;mask,rows,stats=raw_direct_scan(formal,r,b,g,v,PLAN);self.assertFalse(rows)
    def test_invalid_raw_observations_cannot_supply_track(self):
        formal,r,b,g,v=scene();v[:]=False;mask,rows,stats=raw_direct_scan(formal,r,b,g,v,PLAN);self.assertFalse(rows)
    def test_curved_raw_line_can_form_local_track(self):
        formal,r,b,g,v=scene(curve=True);mask,rows,stats=raw_direct_scan(formal,r,b,g,v,PLAN);self.assertTrue(rows)
if __name__=='__main__':unittest.main(verbosity=2)
