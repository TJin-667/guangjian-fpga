import json,socket,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from performance import Ledger,profiled_executor
from archive0108 import HOST
from roi_prepare0108 import executor_class

class LedgerTests(unittest.TestCase):
    def test_failed_nested_calls_are_kept_and_not_claimed_as_FPGA_cycles(self):
        clock=iter([0,10,20,30,40,50]);ledger=Ledger(lambda:next(clock))
        with ledger.span('outer'):
            with self.assertRaises(RuntimeError):
                with ledger.span('inner'):raise RuntimeError('expected')
        r=ledger.snapshot();self.assertFalse(r['events'][0]['success']);self.assertTrue(r['events'][1]['success'])
        self.assertIsNone(r['FPGA_core_cycles']);self.assertTrue(r['nested_events_must_not_be_summed'])
    def test_wire_bytes_come_from_SDK_cost_not_logical_RPC_size(self):
        ledger=Ledger();ledger.rpc(23,200_000_000,True,20,1098);ledger.capture_cost('frame',dict(udp_sent_bytes=40,udp_received_bytes=1098,command_retries=1))
        r=ledger.snapshot();self.assertEqual(r['rpc']['23']['logical_request_bytes'],20);self.assertEqual(r['summed_wire_cost']['udp_sent_bytes'],40)
        self.assertEqual(r['summed_wire_cost']['command_retries'],1)

class ProfiledFormatsTests(unittest.TestCase):
    def test_gray_and_dualview_actual_SDK_preserve_native_planes_fusion_and_live_cache(self):
        from sdk_loader import load
        from verified_evidence import seal_live,restore
        from archive0108 import load as audit
        from test_roi_prepare0108 import LocalSocket
        outputs=[]
        with tempfile.TemporaryDirectory() as directory,patch.object(socket,'socket',LocalSocket):
            root=Path(directory)
            for fmt in (50,49):
                implementation=load('_closure_profile_executor_'+str(fmt),HOST/'engineering_executor.py')
                peer_module=load('_closure_profile_peer_'+str(fmt),HOST/'software_offload_peer.py');Peer,engine=peer_module.make_peer()
                ledger=Ledger();Executor=profiled_executor(implementation,executor_class(implementation),ledger)
                target=root/str(fmt);target.mkdir();board=np.ones((13,19),bool);roi=[7,9,19,13]
                with Peer(engine.root/'ymw') as peer:
                    client=Executor(group_id=0x10899,group_digest=b'ROI_PREP_TEST_01',group_roi=roi,group_board=board,result_directory=target/'fusion',board='127.0.0.1',port=peer.endpoint[1],bind='127.0.0.1',ymw_root=engine.root/'ymw',output_root=target/'captures',pixel_format=fmt,mode='strict',evidence_source='software_udp_peer',sensor_size=(96,32),command_timeout=.08,retries=2)
                    try:
                        def args(slot):return dict(light_channel=(slot-1)//2+1,brightness=128,exposure_lines=400 if slot%2 else 800,gain16=16,roi=roi,board_mask=board.astype(np.uint8).tobytes(),settle_frames=1,discard_frames=3,timeout_s=15,sample_id='UNIT_SOFTWARE_PEER',round_id='NOT_HARDWARE',cancel=threading.Event())
                        client.acquire_roi_preparation(**args(1))
                        for slot in range(1,9):client.acquire(**args(slot))
                        client.lights_off(timeout_s=.5);seal_live(client,base=target/'cache')
                        cached=restore(target/'fusion',target/'cache',allow_fixture=True)
                    finally:client.close()
                strict=audit(target/'fusion',allow_fixture=True)
                for key in ('gray','sat1','board','words'):self.assertTrue(np.array_equal(cached[key],strict[key]),key)
                costs=ledger.snapshot();self.assertEqual(len([e for e in costs['events'] if e['name']=='formal_frame']),8)
                self.assertEqual(len([e for e in costs['events'] if e['name']=='pc_audit_H2']),8)
                self.assertEqual(costs['rpc']['23']['calls'],1);self.assertEqual(costs['rpc']['20']['calls'],8)
                self.assertGreater(costs['summed_wire_cost']['udp_received_bytes'],0);self.assertFalse(strict['physical_hardware'])
                outputs.append(cached)
        for key in ('gray','sat1','board','words'):self.assertTrue(np.array_equal(outputs[0][key],outputs[1][key]),key)

if __name__=='__main__':unittest.main(verbosity=2)
