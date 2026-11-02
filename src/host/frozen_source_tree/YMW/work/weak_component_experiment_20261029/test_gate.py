"""Geometry and preservation checks independent of the human004 annotation."""
import unittest
import cv2
import numpy as np
from component_gate import geometry,accept,PRESETS,partition

class GateTests(unittest.TestCase):
    def check_shape(self,a):
        g=geometry(np.pad(a.astype(bool),2));self.assertTrue(accept(g,PRESETS['line10'])[0],g)
    def test_horizontal(self):
        a=np.zeros((50,70),'uint8');a[25,8:62]=1;self.check_shape(a)
    def test_vertical(self):
        a=np.zeros((70,50),'uint8');a[8:62,25]=1;self.check_shape(a)
    def test_diagonal(self):
        a=np.zeros((70,70),'uint8');cv2.line(a,(8,8),(60,60),1,1);self.check_shape(a)
    def test_curve(self):
        a=np.zeros((70,70),'uint8');cv2.ellipse(a,(35,35),(22,18),0,15,290,1,1);self.check_shape(a)
    def test_closed_loop(self):
        a=np.zeros((70,70),'uint8');cv2.circle(a,(35,35),22,1,1);self.check_shape(a)
    def test_s_curve(self):
        a=np.zeros((70,80),'uint8');x=np.arange(8,72);y=np.rint(35+12*np.sin((x-8)*np.pi/32)).astype(int);cv2.polylines(a,[np.stack([x,y],1).astype('int32')],False,1,1);self.check_shape(a)
    def test_true_fork(self):
        a=np.zeros((70,70),'uint8');cv2.line(a,(35,58),(35,32),1,1);cv2.line(a,(35,32),(12,10),1,1);cv2.line(a,(35,32),(58,10),1,1);self.check_shape(a)
    def test_tiny_review(self):
        for n in (1,2,3):
            a=np.zeros((9,9),bool);a[4,2:2+n]=True;self.assertFalse(accept(geometry(a),PRESETS['line10'])[0])
    def test_compact_blob_review(self):
        a=np.zeros((25,25),'uint8');a[5:20,5:20]=1;self.assertFalse(accept(geometry(a),PRESETS['line10'])[0])
    def test_preserve_and_partition(self):
        core=np.zeros((60,80),bool);core[5:15,5:30]=True;loose=core.copy();loose[40,10:60]=True;loose[30:32,65:67]=True;strong=loose.copy()
        results,_=partition(core,loose,strong)
        for name,r in results.items():
            self.assertFalse((core&~r['candidate']).any());self.assertFalse((r['candidate']&~loose).any());self.assertTrue(np.array_equal(r['line_supplement']|r['review'],loose&~core))
        self.assertTrue(results['line10']['line_supplement'][40,30]);self.assertTrue(results['line10']['review'][30,65])
    def test_outside_seed_piece_review(self):
        g=geometry(np.pad(np.ones((1,40),bool),3));g['board_strong12_pixels']=0;self.assertFalse(accept(g,PRESETS['line10'])[0])

if __name__=='__main__':unittest.main(verbosity=2)
