"""Corruption rejection and exact host connection semantics, not optical tests."""
import sys,unittest
from pathlib import Path
import numpy as np
from result_codec import decode_words

REPO=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(REPO/'YMW/work/b1_detection_console_20261027'))
from common import verify_vendor
vendor,_=verify_vendor();sys.path.insert(0,str(vendor));from dual_exposure_b1 import fusion
from light_inspection.real_baseline import hysteresis_connect

def word(r,source=1,gray=100):
    amplitude=abs(r)
    return np.uint32((r&65535)|(source<<16)|((amplitude>648)<<20)|((amplitude>1620)<<21)|(gray<<22)) if source else np.uint32(0)

class CodecTests(unittest.TestCase):
    def setUp(self):self.board=np.ones((9,9),bool);self.words=np.full((9,9),word(0),dtype='<u4')
    def decode(self):return decode_words(self.words,self.board,hysteresis_connect)
    def test_valid_zero_preserves_source(self):
        result,gray=self.decode();self.assertFalse(result['unknown'].any());self.assertTrue((result['source_frame']==1).all());self.assertFalse(result['mask'].any())
    def test_all_unknown(self):
        self.words[:]=0;result,gray=self.decode();self.assertTrue(result['unknown'].all());self.assertFalse(result['mask'].any())
    def test_signed_limit_and_gray(self):
        self.words[0,0]=word(-20655,8,255);r,g=self.decode();self.assertEqual(r['residual_n'][0,0],-20655);self.assertEqual(g[0,0],255)
        self.assertEqual(r['source_direction'][0,0],4);self.assertEqual(r['source_exposure'][0,0],2)
    def test_strict_boundaries(self):
        for i,value in enumerate([-1621,-1620,-649,-648,0,648,649,1620,1621]):self.words[0,i]=word(value)
        r,g=self.decode();self.assertEqual(r['weak'][0].tolist(),[True,True,True,False,False,False,True,True,True]);self.assertEqual(int(r['strong'].sum()),2)
    def test_board_only_after_full_roi_connection(self):
        self.words[:]=0;self.words[4,1]=word(2000);self.words[4,2:8]=word(900)
        self.board[:]=False;self.board[4,1]=True;self.board[4,7]=True
        r,g=self.decode();self.assertTrue(r['mask'][4,7]);self.assertEqual(int(r['mask'].sum()),2)
    def test_reserved_rejected(self):
        self.words[0,0]|=np.uint32(1<<30)
        with self.assertRaises(ValueError):self.decode()
    def test_unknown_nonzero_rejected(self):
        self.words[0,0]=np.uint32(1)
        with self.assertRaises(ValueError):self.decode()
    def test_source_nine_rejected(self):
        self.words[0,0]=word(700,9)
        with self.assertRaises(ValueError):self.decode()
    def test_out_of_range_rejected(self):
        self.words[0,0]=word(-32768)
        with self.assertRaises(ValueError):self.decode()
    def test_incorrect_threshold_flags_rejected(self):
        self.words[0,0]=word(648)|np.uint32(1<<20)
        with self.assertRaises(ValueError):self.decode()
    def test_dtype_and_geometry_rejected(self):
        with self.assertRaises(ValueError):decode_words(self.words.astype(np.int32),self.board,hysteresis_connect)
        with self.assertRaises(ValueError):decode_words(self.words,self.board[:8],hysteresis_connect)

if __name__=='__main__':unittest.main()
