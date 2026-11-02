from export_paths import legacy_location, data_path, lab_root, network
import json,shutil,socket,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from archive0108 import load

FIXTURE=legacy_location('E:/GuangjianData/fpga_0108_board_20261028/sdk_08')

class ArchiveTests(unittest.TestCase):
    def test_labeled_gray_and_rgb_loopback_archives_import_without_socket(self):
        for case in ('case1','case5'):
            with patch.object(socket,'socket',side_effect=AssertionError('Archive import must be offline')):
                x=load(FIXTURE/case/'fusion',allow_fixture=True)
            self.assertEqual(x['gray'].shape,(8,13,19));self.assertFalse(x['physical_hardware'])
    def test_loopback_cannot_be_presented_as_real_board(self):
        with self.assertRaisesRegex(ValueError,'SOFTWARE_FIXTURE_NOT_BOARD'):load(FIXTURE/'case5/fusion')
    def copy_fixture(self,target):
        for name in ('RESULT.json','fpga_result.r32'):shutil.copyfile(FIXTURE/'case5/fusion'/name,target/name)
    def test_corrupt_fused_result_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.copy_fixture(p);raw=bytearray((p/'fpga_result.r32').read_bytes());raw[0]^=1;(p/'fpga_result.r32').write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'R32 content changed'):load(p,allow_fixture=True)
    def test_wrong_slot_order_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.copy_fixture(p);r=json.loads((p/'RESULT.json').read_text('utf-8'));r['frames'][0]['slot']=2;(p/'RESULT.json').write_text(json.dumps(r),'utf-8')
            with self.assertRaisesRegex(ValueError,'slot changed'):load(p,allow_fixture=True)
    def test_ready_plan_can_cancel_before_hardware_constructor(self):
        import sys
        from engineering0108 import prepare,capture
        root=Path(__file__).resolve().parent.parent/'p0_pair_console_0107_20261027_r56';sys.path.insert(0,str(root));import console_workflow
        catalogue=console_workflow.catalog(str(legacy_location('E:/GuangjianData/P0Pairs/GUI_sample004_20261028_220937_1024af/pair')),full_verify=False)
        import uuid
        output=legacy_location('E:/GuangjianData/reviews/final_system_20261029')/('offline_plan_'+uuid.uuid4().hex[:8])
        with patch.object(socket,'socket',side_effect=AssertionError('Plan preparation/cancel must not open sockets')):
            plan=prepare(catalogue,output);token=threading.Event();token.set()
            with self.assertRaises(InterruptedError):capture(plan,token)
        self.assertFalse((output/'run').exists())

if __name__=='__main__':unittest.main(verbosity=2)
