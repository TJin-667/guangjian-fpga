import unittest
import cv2
import numpy as np
from sleeve_guard import prepare,apply

class SleeveTests(unittest.TestCase):
    def test_side_growth_never_leaves_six_twenty(self):
        o=np.zeros((40,60),bool);o[20,10:40]=True;g=o.copy();g[19:22,10:40]=True;r=np.zeros(o.shape,np.int32);r[o]=1800;p=prepare(o,g,r);x=apply(o,p,3,14)
        self.assertFalse((x['side_addition']&~g).any());self.assertTrue(x['side_addition'].any());self.assertTrue(x['candidate'][o].all())
    def test_radius_zero_is_exact_control(self):
        o=np.zeros((40,60),bool);o[20,10:40]=True;g=cv2.dilate(o.astype('uint8'),np.ones((5,5),'uint8')).astype(bool);r=np.zeros(o.shape,np.int32);r[o]=1800;x=apply(o,prepare(o,g,r),0,14);self.assertTrue(np.array_equal(x['candidate'],o))
    def test_component_bridge_not_introduced_inside_envelope(self):
        o=np.zeros((40,60),bool);o[20,5:23]=True;o[20,26:45]=True;g=np.zeros_like(o);g[19:22,5:45]=True;r=np.zeros(o.shape,np.int32);r[o]=1800;x=apply(o,prepare(o,g,r),3,14)
        self.assertEqual(cv2.connectedComponents(x['candidate'].astype('uint8'),connectivity=8)[0],3)
    def test_distance_bound(self):
        o=np.zeros((40,60),bool);o[20,10:40]=True;g=np.ones_like(o);r=np.zeros(o.shape,np.int32);r[o]=1800;p=prepare(o,g,r);x=apply(o,p,1,14);self.assertFalse((x['side_addition']&(p['distance']>1)).any())
    def test_isolated_original_dot_cannot_swell(self):
        o=np.zeros((40,60),bool);o[20,20]=True;g=np.ones_like(o);r=np.zeros(o.shape,np.int32);r[o]=1800;x=apply(o,prepare(o,g,r),3,14);self.assertTrue(np.array_equal(x['candidate'],o))
    def test_unseeded_parent_not_used(self):
        o=np.zeros((40,60),bool);o[20,10:40]=True;g=np.ones_like(o);r=np.zeros(o.shape,np.int32);r[o]=500;x=apply(o,prepare(o,g,r),3,14);self.assertFalse(x['side_addition'].any())
if __name__=='__main__':unittest.main(verbosity=2)
