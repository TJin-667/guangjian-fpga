import json,unittest
from pathlib import Path
import cv2
import numpy as np
from evidence import compare,scan_without_seed,group_decision,raw_supported_components,longest_run

PLAN=json.loads((Path(__file__).resolve().parent/'PLAN.json').read_text('utf-8'))
def scene(frames=(3,7),curve=False):
    shape=(128,160);gray=np.full((8,*shape),100,np.uint8);line=np.zeros(shape,np.uint8)
    if curve:
        xy=np.array([[x,int(round(64+8*np.sin((x-30)/30))) ] for x in range(25,135)],np.int32);cv2.polylines(line,[xy.reshape(-1,1,2)],False,1,1)
    else:line[64,25:135]=1
    for i in frames:gray[i][line>0]=94
    residuals=[]
    for image in gray:residuals.append(np.abs(image.astype('int32')*81-cv2.boxFilter(image,cv2.CV_32S,(9,9),normalize=False,borderType=cv2.BORDER_REFLECT_101)))
    r=np.max(residuals,axis=0);v=np.ones_like(gray,bool);board=np.ones(shape,bool);formal=np.zeros(shape,bool);return formal,r,board,gray,v

class EvidenceTests(unittest.TestCase):
    def test_rim_only_growth_not_a_missing_line(self):
        d=np.zeros((100,100),bool);d[45:50,20:80]=True;s=cv2.dilate(d.astype('uint8'),np.ones((3,3),'uint8')).astype(bool);arrays,m=compare(d,s,PLAN['comparison']);self.assertEqual(m['nonrim_pixels'],0);self.assertEqual(m['new_line_like_components'],0)
    def test_far_new_line_is_candidate_for_raw_review(self):
        d=np.zeros((100,100),bool);s=d.copy();s[50,20:80]=True;arrays,m=compare(d,s,PLAN['comparison']);self.assertEqual(m['new_line_like_components'],1)
    def test_lost_pixels_recorded_not_hidden_by_union(self):
        d=np.zeros((50,50),bool);d[20,10:40]=True;s=d.copy();s[20,22:25]=False;arrays,m=compare(d,s,PLAN['comparison']);self.assertEqual(m['lost_pixels'],3)
    def test_stable_masks_do_not_mean_automatic_pass(self):
        self.assertEqual(group_decision(0,0,PLAN),'NO_CLEAR_ALERT_UNCALIBRATED')
    def test_unknown_data_has_separate_review_reason(self):
        self.assertEqual(group_decision(.2,5,PLAN),'REVIEW_INCOMPLETE_OBSERVATION')
    def test_credible_extra_region_requests_review(self):
        self.assertEqual(group_decision(0,1,PLAN),'REVIEW_SUSPECTED_MISSING_STRUCTURE')
    def test_unseeded_line_can_prompt_without_becoming_detection(self):
        formal,r,b,g,v=scene();before=formal.copy();mask,rows=scan_without_seed(formal,r,b,b,g,v,PLAN);hits=[x for x in rows if x['raw_supported'] and not x['global_weak_component_has_seed']]
        self.assertTrue(hits);self.assertTrue(any(len(x['supported_directions'])>=2 for x in hits));self.assertTrue(np.array_equal(formal,before));self.assertEqual(formal.sum(),0)
    def test_one_direction_is_not_discarded(self):
        formal,r,b,g,v=scene(frames=(3,));mask,rows=scan_without_seed(formal,r,b,b,g,v,PLAN);self.assertTrue(any(x['raw_supported'] and x['evidence_priority']=='single_direction' for x in rows))
    def test_invalid_observation_cannot_supply_line_evidence(self):
        formal,r,b,g,v=scene();v[:]=False;mask,rows=scan_without_seed(formal,r,b,b,g,v,PLAN);self.assertFalse(any(x['raw_supported'] for x in rows))
    def test_constant_raw_image_cannot_confirm_residual_artifact(self):
        formal,r,b,g,v=scene();g[:]=100;mask,rows=scan_without_seed(formal,r,b,b,g,v,PLAN);self.assertFalse(any(x['raw_supported'] for x in rows))
    def test_isolated_dots_do_not_form_continuous_review_line(self):
        d=np.zeros((100,100),bool);s=d.copy();s[20:80:8,30:80:8]=True;arrays,m=compare(d,s,PLAN['comparison']);self.assertEqual(m['new_line_like_components'],0)
    def test_gentle_curved_line_allowed(self):
        formal,r,b,g,v=scene(curve=True);mask,rows=scan_without_seed(formal,r,b,b,g,v,PLAN);self.assertTrue(any(x['raw_supported'] for x in rows))
    def test_large_station_gap_cannot_fake_continuity(self):
        span,count=longest_run(np.array([0.,4.,8.,40.,44.]),np.ones(5,bool),8.1);self.assertEqual(span,8.);self.assertEqual(count,3)
    def test_input_masks_are_not_mutated(self):
        d=np.zeros((40,40),bool);d[10,10:25]=True;s=d.copy();s[30,10:25]=True;before=d.copy();compare(d,s,PLAN['comparison']);self.assertTrue(np.array_equal(d,before))
if __name__=='__main__':unittest.main(verbosity=2)
