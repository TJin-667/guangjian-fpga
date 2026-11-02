import hashlib,json,socket,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import engineering0108

class FormatPlanTests(unittest.TestCase):
    def test_new_format_has_a_new_plan_and_preserves_original_geometry_and_bytes(self):
        sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'p0_pair_console_0107_20261027_r56'));import console_workflow
        catalogue=console_workflow.catalog('E:/GuangjianData/P0Pairs/GUI_sample004_20261028_220937_1024af/pair',full_verify=False)
        base=Path('E:/GuangjianData/reviews/performance_closure_20261030/plan_tests');base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temp,patch.object(socket,'socket',side_effect=AssertionError('Plan must stay offline')):
            first=engineering0108.prepare(catalogue,Path(temp)/'plan');before=first.read_bytes();same=engineering0108.plan_for_format(first,50);self.assertEqual(same,first)
            second=engineering0108.plan_for_format(first,49);self.assertNotEqual(second,first);a=json.loads(before);b=json.loads(second.read_text('utf-8'))
            for key in ('roi','mask','mask_sha256','qualification_sha256','sample','pose','low_lines','high_lines','gain16','LED'):self.assertEqual(a[key],b[key],key)
            self.assertEqual(a['pixel_format'],50);self.assertEqual(b['pixel_format'],49);self.assertEqual(first.read_bytes(),before)
            with self.assertRaisesRegex(ValueError,'format must'):engineering0108.plan_for_format(first,48)

if __name__=='__main__':unittest.main(verbosity=2)
