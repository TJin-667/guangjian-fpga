import copy,json,sys,unittest
from pathlib import Path
import cv2
import numpy as np
from large_gap import analyze_large_gaps,visibility,robust_tips,propose
from evidence import distance_to

HERE=Path(__file__).resolve().parent;PLAN=json.loads((HERE/'PLAN.json').read_text('utf-8'));BASE=json.loads((HERE.parent/'confidence_gap_review_20261029/PLAN.json').read_text('utf-8'))

def scene(gap=40,weak=3,empty=False):
    shape=(100,240);formal=np.zeros(shape,bool);a=50;b=a+gap;formal[50,15:a]=True;formal[50,b:220]=True;gray=np.full((8,*shape),100,np.uint8);valid=np.ones_like(gray,bool);board=np.ones(shape,bool)
    for f in (3,7):
        gray[f][formal]=75
        if not empty:gray[f,50,a:b]=100-weak
    residual=np.asarray([81*g.astype('int32')-cv2.boxFilter(g,cv2.CV_32S,(9,9),normalize=False,borderType=cv2.BORDER_REFLECT_101) for g in gray]);return formal,gray,valid,board,residual

def evaluate(x,plan=PLAN):return analyze_large_gaps(*x,BASE,plan)

class LargeGapTests(unittest.TestCase):
    def test_few_pixel_gap_not_reviewed(self):
        r=evaluate(scene(gap=4));self.assertFalse(any(g['review'] for g in r['gaps']));self.assertGreater(r['tiny_probe_hypotheses_ignored'],0)
    def test_ignore_threshold_is_visual_missing_run_not_endpoint_distance(self):
        d=np.zeros((80,150),bool);d[40,10:140]=True;d[40,30:34]=False;d[40,70:74]=False;p=np.stack([np.arange(10,140),np.full(130,40)],axis=1);v=visibility(p,distance_to(d),PLAN);self.assertTrue(v['tiny_ignored']);self.assertLess(v['longest_visual_gap_px'],6)
    def test_clear_large_subthreshold_gap_uses_relaxed_review(self):
        r=evaluate(scene());hits=[g for g in r['gaps'] if g['review']];self.assertTrue(hits);self.assertTrue(any(g['selected_probe']['review_weak_used']==2 for g in hits))
    def test_aligned_gap_beyond_old64_can_be_reviewed(self):
        r=evaluate(scene(gap=100,weak=5));hits=[g for g in r['gaps'] if g['review'] and g['distance_px']>64];self.assertTrue(hits);self.assertTrue(all(g['aligned'] for g in hits))
    def test_short_gap_does_not_get_large_gap_relaxation(self):
        r=evaluate(scene(gap=10));self.assertFalse(any(g['review'] for g in r['gaps']));self.assertTrue(all(g['selected_probe']['review_weak_used']==3.2 for g in r['gaps']))
    def test_large_empty_break_not_labelled_raw_supported(self):
        r=evaluate(scene(empty=True));self.assertFalse(any(g['review'] for g in r['gaps']))
    def test_formal_mask_byte_identical(self):
        x=scene();before=x[0].tobytes();r=evaluate(x);self.assertEqual(before,x[0].tobytes());self.assertIsNone(r['confidence_probability']);self.assertFalse(r['automatic_pass'])
    def test_support_points_are_outside_visual_tolerance(self):
        x=scene();r=evaluate(x);distance=distance_to(x[0]);points=[p for g in r['gaps'] if g['review'] for p in g['selected_probe']['supported_missing_native_xy']];self.assertTrue(points)
        for xx,yy in points:self.assertGreater(distance[yy,xx],PLAN['visual_neighbor_tolerance_px'])
    def test_invalid_gap_cannot_support_review(self):
        x=scene();x[2][:,40:60,50:90]=False;self.assertFalse(any(g['review'] for g in evaluate(x)['gaps']))
    def test_single_direction_still_usable(self):
        x=scene();x[1][7]=100;x[4][7]=0;r=evaluate(x);self.assertTrue(any(g['review'] and g['selected_probe']['supported_directions']==[2] for g in r['gaps']))
    def test_extent_proposals_for_short_elongated_fragment(self):
        d=np.zeros((80,120),bool);d[38:43,20:55]=True;tips=robust_tips(d,BASE['gap'],PLAN);self.assertTrue(any(t['proposal_kind']=='short_fragment_extent' for t in tips))
    def test_capacity_limit_is_explicit(self):
        with self.assertRaisesRegex(RuntimeError,'CAPACITY'):evaluate(scene(),{**PLAN,'max_pairs':0})

if __name__=='__main__':unittest.main(verbosity=2)
