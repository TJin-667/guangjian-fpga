import unittest
import numpy as np
from body_guard import extend,reject_merges
C=dict(strong=14)
def scene():
    base=np.zeros((80,100),bool);base[40,10:30]=True;ordinary=base.copy();ordinary[40,30:65]=True;ordinary[41,15:26]=True;r=np.zeros(base.shape,np.int32);r[base]=1800;r[ordinary&~base]=500
    return base,ordinary,r
class BodyTests(unittest.TestCase):
    def test_original_preserved_side_fringe_removed(self):
        b,o,r=scene();x=extend(b,b,o,r,C,32,2);self.assertTrue(x['candidate'][b].all());self.assertFalse(x['candidate'][41,15:26].any());self.assertTrue(x['candidate'][40,30:50].all())
    def test_reach_is_bounded(self):
        b,o,r=scene();x=extend(b,b,o,r,C,16,1);self.assertFalse(x['candidate'][40,46:].any())
    def test_no_bridge_between_distinct_anchors(self):
        b,o,r=scene();b[40,48:68]=True;o|=b;r[b]=1800;x=extend(b,b,o,r,C,64,2)
        self.assertFalse(x['candidate'][40,30:48].any())
    def test_real_gap_not_painted(self):
        b,o,r=scene();o[40,35]=False;x=extend(b,b,o,r,C,64,2);self.assertFalse(x['candidate'][40,35]);self.assertFalse(x['candidate'][40,36:65].any())
    def test_unseeded_parent_does_not_extend(self):
        b,o,r=scene();r[b]=900;x=extend(b,b,o,r,C,64,2);self.assertFalse(x['extension'].any())
    def test_small_seed_dot_not_reliable_tip(self):
        b=np.zeros((80,100),bool);b[40,20]=True;o=b.copy();o[40,21:50]=True;r=np.zeros(b.shape,np.int32);r[b]=2000;x=extend(b,b,o,r,C,64,2);self.assertFalse(x['extension'].any())
    def test_width_bounded_near_tip(self):
        b,o,r=scene();o[35:46,30:60]=True;x=extend(b,b,o,r,C,32,1);self.assertFalse(x['candidate'][35:39,30:60].any());self.assertFalse(x['candidate'][42:46,30:60].any())
    def test_lower_piece_merging_anchors_is_rejected_whole(self):
        b=np.zeros((40,50),bool);b[20,5:10]=True;b[20,30:35]=True;p=np.zeros_like(b);p[20,9:31]=True;x=reject_merges(b,p);self.assertFalse(x.any())
    def test_other_components_do_not_borrow_reliable_tip(self):
        b,o,r=scene();o[40,35]=False;b[40,50:54]=True;o|=b;r[b]=1800;x=extend(b,b,o,r,C,64,1);self.assertFalse(x['extension'][40,36:50].any())
if __name__=='__main__':unittest.main(verbosity=2)
