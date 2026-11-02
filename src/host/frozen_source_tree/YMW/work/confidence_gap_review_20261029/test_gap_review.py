import copy,json,unittest
from pathlib import Path
import cv2
import numpy as np
from gap_review import analyze,evaluate_probe,local_shape,probe_path

PLAN=json.loads((Path(__file__).resolve().parent/'PLAN.json').read_text('utf-8'))

def scene(continuous=True):
    formal=np.zeros((100,140),bool);formal[50,15:40]=True;formal[50,72:110]=True;board=np.ones_like(formal);gray=np.full((8,*formal.shape),100,np.uint8)
    for i in (3,7):
        gray[i][formal]=75
        if continuous:gray[i,50,40:72]=95
    valid=np.ones_like(gray,bool);residual=np.asarray([81*g.astype('int32')-cv2.boxFilter(g,cv2.CV_32S,(9,9),normalize=False,borderType=cv2.BORDER_REFLECT_101) for g in gray]);return formal,gray,valid,board,residual

def evaluate(x):return analyze(*x,PLAN)

class GapTests(unittest.TestCase):
    def test_subthreshold_continuous_line_between_detected_fragments(self):
        x=scene();r=evaluate(x);hits=[g for g in r['gaps'] if g['review']];self.assertTrue(hits);self.assertEqual(hits[0]['selected_probe']['category'],'suspected_subthreshold_gap');self.assertEqual(hits[0]['selected_probe']['supported_directions'],[2,4])
    def test_real_empty_break_not_filled_by_detected_endpoints(self):
        x=scene(False);r=evaluate(x);self.assertTrue(r['gaps']);self.assertFalse(any(g['review'] for g in r['gaps']));self.assertTrue(all(g['selected_probe']['best_fit']['raw_fraction']==0 for g in r['gaps']))
    def test_no_fake_smoothing_from_bright_endpoints(self):
        x=scene(False);x[1][:,50,15:40]=255;x[1][:,50,72:110]=255;x=list(x);x[-1]=np.asarray([81*g.astype('int32')-cv2.boxFilter(g,cv2.CV_32S,(9,9),normalize=False,borderType=cv2.BORDER_REFLECT_101) for g in x[1]]);self.assertFalse(any(g['review'] for g in evaluate(x)['gaps']))
    def test_different_frames_cannot_complete_each_others_gap(self):
        x=list(scene(False));x[1][3,50,40:56]=95;x[1][7,50,56:72]=95;x[-1]=np.asarray([81*g.astype('int32')-cv2.boxFilter(g,cv2.CV_32S,(9,9),normalize=False,borderType=cv2.BORDER_REFLECT_101) for g in x[1]]);self.assertFalse(any(g['review'] for g in evaluate(x)['gaps']))
    def test_invalid_gap_does_not_contribute_support(self):
        x=scene();x[2][:,40:60,40:72]=False;self.assertFalse(any(g['review'] for g in evaluate(x)['gaps']))
    def test_formal_mask_remains_byte_identical(self):
        x=scene();before=x[0].tobytes();r=evaluate(x);self.assertEqual(before,x[0].tobytes());self.assertTrue(r['formal_unchanged']);self.assertIsNone(r['confidence_probability']);self.assertFalse(r['automatic_pass'])
    def test_only_missing_samples_are_measured(self):
        x=scene();r=evaluate(x);g=r['gaps'][0]['selected_probe'];xy=np.array(g['missing_native_xy']);self.assertFalse(x[0][xy[:,1],xy[:,0]].any());self.assertEqual(g['missing_samples'],32)
    def test_threshold_curve_is_monotone_for_fixed_signed_frame(self):
        r=evaluate(scene());curves=[f['threshold_curve'] for g in r['gaps'] for f in g['selected_probe']['fits']]
        for c in curves:self.assertTrue(all(a['supported_missing']<=b['supported_missing'] for a,b in zip(c,c[1:])))
    def test_single_direction_is_enough_for_review(self):
        x=list(scene());x[1][7]=100;x[-1][7]=0;r=evaluate(x);self.assertTrue(any(g['review'] and g['selected_probe']['supported_directions']==[2] for g in r['gaps']))
    def test_parallel_lines_facing_sideways_do_not_propose_gap(self):
        x=list(scene(False));x[0][:]=False;x[0][40,20:100]=True;x[0][50,20:100]=True;r=evaluate(x);self.assertEqual(r['endpoint_pairs'],0)
    def test_shape_allows_closed_curve(self):
        theta=np.linspace(0,2*np.pi,120,endpoint=False);xy=np.stack([40+30*np.cos(theta),40+30*np.sin(theta)],axis=1);r=local_shape(xy,PLAN['shape']);self.assertEqual(r['shape_class'],'locally_line_like')
    def test_shape_detects_dense_blob_ambiguity(self):
        y,x=np.mgrid[0:20,0:20];r=local_shape(np.stack([x.ravel(),y.ravel()],axis=1),PLAN['shape']);self.assertEqual(r['shape_class'],'shape_ambiguous')
    def test_threshold_effect_alone_cannot_replace_raw_line(self):
        x=list(scene(False));x[-1][:,50,40:72]=-360;r=evaluate(x);self.assertFalse(any(g['review'] for g in r['gaps']))

if __name__=='__main__':unittest.main(verbosity=2)
