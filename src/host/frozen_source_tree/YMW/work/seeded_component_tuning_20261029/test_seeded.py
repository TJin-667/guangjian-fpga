import unittest
import cv2
import numpy as np
from seeded_gate import build,choose,masks,profiles
from raw_profile import inspect_profile

BASE=dict(strong=12,span=6,line=.5,raw_fraction=.65,raw_mean=2.,chain='off',width=5,min_area=3,length=13,flank=3.)
def feature_cache(peaks=(973,),geometry_pass=True,raw_pass=True):
    rows=[dict(label=i+1,area=12,two_sweep_span_px=11 if geometry_pass else 2,line_fraction=.9,median_width_proxy_px=1,peak_n=p) for i,p in enumerate(peaks)]
    fractions=np.ones((len(peaks),8,8,2),np.float32)*(.9 if raw_pass else 0);means=np.ones_like(fractions)*(3 if raw_pass else 0)
    return dict(rows=rows,profiles={'13/3':(fractions,means)},edges=[])

class SeededTests(unittest.TestCase):
    def test_seed_required_even_perfect_raw_line(self):
        c=feature_cache((972,971,500,0));a,_=choose(c,BASE);self.assertFalse(a.any())
    def test_strict_seed_boundary(self):
        a,_=choose(feature_cache((971,972,973)),BASE);self.assertEqual(a.tolist(),[False,False,True])
    def test_new_strong_threshold_applies_all_routes(self):
        a,_=choose(feature_cache((973,1134,1135)),{**BASE,'strong':14});self.assertEqual(a.tolist(),[False,False,True])
    def test_tiny_raw_dots_do_not_bypass_area(self):
        c=feature_cache();c['rows'][0]['area']=2;a,_=choose(c,BASE);self.assertFalse(a.any())
    def test_broad_raw_blob_does_not_bypass_width(self):
        c=feature_cache();c['rows'][0]['median_width_proxy_px']=6;a,_=choose(c,BASE);self.assertFalse(a.any())
    def test_no_independent_chain_even_seeded(self):
        c=feature_cache((973,973,973),False,False);c['edges']=[dict(a=0,b=1,distance=2,facing=1,raw_fraction=1),dict(a=1,b=2,distance=2,facing=1,raw_fraction=1)]
        a,_=choose(c,{**BASE,'chain':'previous'});self.assertFalse(a.any())
    def test_seeded_chain_can_reach_geometry_anchor(self):
        c=feature_cache((973,973,973),False,False);c['rows'][0]['two_sweep_span_px']=11;c['edges']=[dict(a=0,b=1,distance=2,facing=1,raw_fraction=1),dict(a=1,b=2,distance=2,facing=1,raw_fraction=1)]
        a,_=choose(c,{**BASE,'chain':'previous'});self.assertTrue(a.all())
    def test_unseeded_chain_cannot_bridge(self):
        c=feature_cache((973,972,973),False,False);c['rows'][0]['two_sweep_span_px']=11;c['edges']=[dict(a=0,b=1,distance=2,facing=1,raw_fraction=1),dict(a=1,b=2,distance=2,facing=1,raw_fraction=1)]
        a,_=choose(c,{**BASE,'chain':'previous'});self.assertEqual(a.tolist(),[True,False,False])
    def test_core_anchor_requires_seed_in_added_piece(self):
        c=feature_cache((972,973),False,False);c['edges']=[dict(a=-1,b=0,distance=2,facing=1,raw_fraction=1),dict(a=-1,b=1,distance=2,facing=1,raw_fraction=1)]
        a,_=choose(c,{**BASE,'chain':'previous'});self.assertEqual(a.tolist(),[False,True])
    def test_profiles_keep_all_fits_for_new_thresholds(self):
        c=feature_cache((973,),False,False);f,m=c['profiles']['13/3'];f[0,0,0,0]=.7;m[0,0,0,0]=20;f[0,1,0,0]=.9;m[0,1,0,0]=3
        a,_=choose(c,{**BASE,'raw_fraction':.85,'raw_mean':3});self.assertTrue(a[0])
    def test_same_observation_contrast_not_mixed(self):
        c=feature_cache((973,),False,False);f,m=c['profiles']['13/3'];f[0,0,0,0]=1;m[0,0,0,0]=1;f[0,1,1,0]=.5;m[0,1,1,0]=10
        a,_=choose(c,BASE);self.assertFalse(a[0])
    def test_batched_profiles_agree_previous_scalar(self):
        rng=np.random.default_rng(77);gray=rng.integers(85,105,(8,48,48),dtype='uint8');gray[:,24,10:38]=90;valid=np.ones_like(gray,bool);board=np.ones((48,48),bool);centers=np.array([[24.,24.],[25.3,24.6],[2.,2.]])
        f,m=profiles(centers,gray,valid,board)
        for i,center in enumerate(centers):
            old=inspect_profile(center,gray,valid,board);margin=np.minimum(f[i]/.65,m[i]/2).max(initial=0)
            self.assertAlmostEqual(float(margin),old['evidence_margin'],places=5)
    def test_invalid_raw_samples_not_reconstructed(self):
        gray=np.full((8,40,40),100,np.uint8);gray[:,20,:]=90;valid=np.ones_like(gray,bool);valid[:,:,20]=False;board=np.ones((40,40),bool)
        f,m=profiles([[20.,20.]],gray,valid,board);self.assertFalse(((f>=.65)&(m>=2)).any())
    def test_output_preserves_native_pixels_no_gap_paint(self):
        gray=np.full((8,64,64),100,np.uint8);gray[:,20,:]=90;valid=np.ones_like(gray,bool);board=np.ones((64,64),bool);core=np.zeros_like(board);core[45,10:25]=True;loose=core.copy();loose[20,10:25]=True;response=np.zeros_like(board,dtype=np.int32);response[20,10:25]=973
        cache=build(response,board,board,core,loose,gray,valid);out,_=masks(cache,BASE)
        self.assertTrue(np.array_equal(out['candidate'],loose));self.assertFalse(out['candidate'][21:45].any());self.assertTrue(np.array_equal(out['supplement']|out['review'],loose&~core))
    def test_board_piece_without_seed_stays_review(self):
        gray=np.full((8,64,64),100,np.uint8);gray[:,20,:]=90;valid=np.ones_like(gray,bool);board=np.ones((64,64),bool);core=np.zeros_like(board);loose=core.copy();loose[20,10:25]=True;response=np.zeros_like(board,dtype=np.int32);response[20,10:25]=600
        cache=build(response,board,board,core,loose,gray,valid);out,_=masks(cache,BASE);self.assertFalse(out['candidate'].any());self.assertTrue(np.array_equal(out['review'],loose))

if __name__=='__main__':unittest.main(verbosity=2)
