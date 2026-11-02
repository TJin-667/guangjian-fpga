import unittest
import cv2
import numpy as np
from residual_access import ResidualAccess

class ResidualTests(unittest.TestCase):
    def test_all_pixels_and_reflect_edges_match_frozen_integer_definition(self):
        rng=np.random.default_rng(381)
        for h,w in ((9,9),(10,13),(31,33),(64,65),(71,143)):
            gray=rng.integers(0,256,(8,h,w),dtype=np.uint8);provider=ResidualAccess(gray,tile_size=16,max_tiles=3);yy,xx=np.indices((h,w))
            for f in range(8):
                expected=(81*gray[f].astype('int32')-cv2.boxFilter(gray[f],cv2.CV_32S,(9,9),normalize=False,borderType=cv2.BORDER_REFLECT_101)).astype('int16')
                self.assertTrue(np.array_equal(provider[f,yy,xx],expected))
            self.assertLessEqual(len(provider.cache),3)
    def test_sparse_order_duplicates_and_scalar_keep_identity(self):
        gray=np.arange(8*20*30,dtype='uint16').reshape(8,20,30).astype('uint8');p=ResidualAccess(gray)
        yy=np.array([0,19,8,8]);xx=np.array([29,0,9,9]);expected=81*gray[3].astype('int32')-cv2.boxFilter(gray[3],cv2.CV_32S,(9,9),normalize=False,borderType=cv2.BORDER_REFLECT_101)
        self.assertTrue(np.array_equal(p[3,yy,xx],expected[yy,xx]));self.assertEqual(p[3,8,9],expected[8,9])
    def test_input_immutable_snapshot(self):
        gray=np.zeros((8,20,30),'uint8');p=ResidualAccess(gray);gray[:]=255;self.assertEqual(p[0,3,4],0)
    def test_invalid_frame_or_coordinates_fail(self):
        p=ResidualAccess(np.zeros((8,20,30),'uint8'))
        for index in ((8,3,4),(0,-1,4),(0,20,4)):
            with self.assertRaises(IndexError):p[index]

if __name__=='__main__':unittest.main(verbosity=2)
