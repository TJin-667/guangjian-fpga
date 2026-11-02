import unittest
import numpy as np
from joint_gate import cutoff,build_cache,output,decide

C=dict(weak=5.5,strong=14,policy='fixed6_20_isolated_supplements',min_area=3,span=6,line=.5,width=5,raw_fraction=.85,raw_mean=3.)
def fixture():
    board=np.ones((64,64),bool);reference=np.zeros_like(board);reference[42,8:24]=True
    ordinary=reference.copy();ordinary[41,10:22]=True;ordinary[20,10:28]=True
    moving=reference.copy();moving[41,10:22]=True
    response=np.zeros((64,64),np.int32);response[reference]=1700;response[41,10:22]=450;response[20,10:28]=1200
    gray=np.full((8,64,64),100,np.uint8);gray[:,20,4:40]=90;valid=np.ones_like(gray,bool)
    return response,board,reference,ordinary,moving,gray,valid

class JointTests(unittest.TestCase):
    def test_fractional_weak_cutoffs_not_integer_weak_rounding(self):
        self.assertEqual([cutoff(w) for w in (5,5.25,5.5,5.75,6)],[405,425,445,465,486])
    def test_point_two_weak_and_strong_steps(self):
        self.assertEqual([cutoff(w) for w in (5,5.2,5.4,5.6,5.8,6)],[405,421,437,453,469,486])
        self.assertEqual([cutoff(w) for w in (14,14.2,14.4,14.6,14.8,15,15.2,15.4,15.6,15.8,16)],[1134,1150,1166,1182,1198,1215,1231,1247,1263,1279,1296])
    def test_strict_integer_residual_boundary(self):
        values=np.arange(420,431);self.assertTrue(np.array_equal(values>81*5.25,values>cutoff(5.25)))
    def test_guard_rejects_whole_attached_growth(self):
        r,b,ref,plain,moving,g,v=fixture();cache=build_cache(r,b,b,ref,moving,plain,g,v,policy=C['policy']);out,_=output(cache,C)
        self.assertFalse(out['candidate'][41,10:22].any());self.assertTrue(out['candidate'][20,10:28].all());self.assertTrue(out['candidate'][ref].all())
    def test_moving_protection_hides_growth_before_filter(self):
        r,b,ref,plain,moving,g,v=fixture();cache=build_cache(r,b,b,ref,moving,plain,g,v,policy='same_weak20');out,_=output(cache,C)
        self.assertTrue(out['candidate'][41,10:22].all())
    def test_attached_seed_does_not_bypass_topology_guard(self):
        r,b,ref,plain,moving,g,v=fixture();r[41,15]=1400;cache=build_cache(r,b,b,ref,moving,plain,g,v,policy=C['policy']);out,_=output(cache,C)
        self.assertFalse(out['candidate'][41,10:22].any())
    def test_seed15_exact_boundary(self):
        r,b,ref,plain,moving,g,v=fixture();r[20,10:28]=1215;cache=build_cache(r,b,b,ref,moving,plain,g,v,policy=C['policy']);out,_=output(cache,{**C,'strong':15});self.assertFalse(out['candidate'][20,10:28].any())
        r[20,18]=1216;cache=build_cache(r,b,b,ref,moving,plain,g,v,policy=C['policy']);out,_=output(cache,{**C,'strong':15});self.assertTrue(out['candidate'][20,10:28].all())
    def test_seed16_exact_boundary(self):
        r,b,ref,plain,moving,g,v=fixture();r[20,10:28]=1296;cache=build_cache(r,b,b,ref,moving,plain,g,v,policy=C['policy']);out,_=output(cache,{**C,'strong':16});self.assertFalse(out['candidate'][20,10:28].any())
    def test_obvious_unseeded_raw_line_not_detected(self):
        r,b,ref,plain,moving,g,v=fixture();r[20,10:28]=600;cache=build_cache(r,b,b,ref,moving,plain,g,v,policy=C['policy']);out,_=output(cache,C);self.assertFalse(out['candidate'][20,10:28].any())
    def test_no_gap_paint_or_reference_erasure(self):
        r,b,ref,plain,moving,g,v=fixture();cache=build_cache(r,b,b,ref,moving,plain,g,v,policy=C['policy']);out,_=output(cache,C)
        self.assertFalse((out['candidate']&~plain).any());self.assertFalse((ref&~out['candidate']).any());self.assertFalse(out['candidate'][21:41].any())
    def test_invalid_profile_cannot_override_seed(self):
        r,b,ref,plain,moving,g,v=fixture();r[20,10:28]=600;v[:,:,10:29]=False;cache=build_cache(r,b,b,ref,moving,plain,g,v,policy=C['policy']);out,_=output(cache,C);self.assertFalse(out['candidate'][20,10:28].any())
    def test_unknown_policy_rejected(self):
        r,b,ref,plain,moving,g,v=fixture()
        with self.assertRaises(ValueError):build_cache(r,b,b,ref,moving,plain,g,v,policy='unseeded_magic')

if __name__=='__main__':unittest.main(verbosity=2)
