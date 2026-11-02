import unittest
import numpy as np
import cv2
from raw_profile import inspect_profile,raw_profile_gate

class ProfileTests(unittest.TestCase):
    def make(self):return np.full((8,80,80),100,'uint8'),np.ones((8,80,80),bool),np.ones((80,80),bool)
    def test_raw_line_can_support_tiny_fragment(self):
        gray,v,b=self.make();gray[:,40,20:61]=92;core=np.zeros((80,80),bool);loose=core.copy();loose[40,39:42]=True
        r,_=raw_profile_gate(core,loose,gray,v,b,core);self.assertEqual(int(r['raw_profile']['line_supplement'].sum()),3)
    def test_isolated_dark_dot_does_not_pass_as_long_line(self):
        gray,v,b=self.make();gray[:,40,40]=80;self.assertFalse(inspect_profile((40,40),gray,v,b)['accepted'])
    def test_step_edge_has_no_two_sided_ridge(self):
        gray,v,b=self.make();gray[:,:,40:]=80;self.assertFalse(inspect_profile((40,40),gray,v,b)['accepted'])
    def test_diagonal_line(self):
        gray,v,b=self.make()
        for g in gray:cv2.line(g,(20,20),(60,60),85,1)
        self.assertTrue(inspect_profile((40,40),gray,v,b)['accepted'])
    def test_no_board_footprint_means_review(self):
        gray,v,b=self.make();gray[:,40,20:61]=92;b[:]=False;self.assertFalse(inspect_profile((40,40),gray,v,b)['accepted'])
    def test_profile_does_not_paint_gap_or_delete_protected(self):
        gray,v,b=self.make();gray[:,40,20:61]=92;core=np.zeros((80,80),bool);core[5:10,5:10]=True;loose=core.copy();loose[40,39:42]=True
        r,_=raw_profile_gate(core,loose,gray,v,b,np.zeros_like(core))
        for x in r.values():self.assertFalse((core&~x['candidate']).any());self.assertFalse((x['candidate']&~loose).any())
if __name__=='__main__':unittest.main(verbosity=2)
