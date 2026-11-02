import unittest
import numpy as np
from fragment_chain import chain

class ChainTests(unittest.TestCase):
    def inputs(self,line=True,shift=0,gap=4):
        shape=(60,80);core=np.zeros(shape,bool);core[30,10:18]=True;loose=core.copy();start=18+gap;loose[30+shift,start:start+3]=True
        gray=np.full((8,*shape),100,'uint8')
        if line:gray[:,30,10:start+3]=94
        return core,loose,np.zeros(shape,bool),gray,np.ones((8,*shape),bool),np.ones(shape,bool),start
    def test_raw_chain_retains_short_fragment_without_painting_gap(self):
        a,b,c,g,v,board,start=self.inputs();r,_=chain(a,b,c,g,v,board)
        self.assertTrue(r['chain_raw']['line_supplement'][30,start]);self.assertFalse(r['chain_raw']['candidate'][30,18:start].any())
    def test_flat_gap_is_review(self):
        a,b,c,g,v,board,start=self.inputs(False);r,_=chain(a,b,c,g,v,board)
        self.assertTrue(r['chain_geom']['line_supplement'][30,start]);self.assertTrue(r['chain_raw']['review'][30,start])
    def test_parallel_side_offset_does_not_join(self):
        a,b,c,g,v,board,start=self.inputs(True,shift=5);r,_=chain(a,b,c,g,v,board);self.assertFalse(r['chain_geom']['line_supplement'].any())
    def test_long_gap_stays_review(self):
        a,b,c,g,v,board,start=self.inputs(True,gap=12);r,_=chain(a,b,c,g,v,board);self.assertFalse(r['chain_raw']['line_supplement'].any())
    def test_protected_pixels_always_unchanged(self):
        a,b,c,g,v,board,start=self.inputs();r,_=chain(a,b,c,g,v,board)
        for x in r.values():self.assertFalse((a&~x['candidate']).any());self.assertFalse((x['candidate']&~b).any());self.assertTrue(np.array_equal(x['line_supplement']|x['review'],b&~a))
if __name__=='__main__':unittest.main(verbosity=2)
