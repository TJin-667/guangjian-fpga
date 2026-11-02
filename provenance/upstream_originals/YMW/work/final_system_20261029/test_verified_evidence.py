import hashlib,json,shutil,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import verified_evidence as evidence

FIXTURE=Path('E:/GuangjianData/fpga_0108_board_20261028/sdk_08/case5/fusion')

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir();self.cache=self.root/'cache'
        for name in ('RESULT.json','fpga_result.r32'):shutil.copyfile(FIXTURE/name,self.source/name)
    def tearDown(self):self.temp.cleanup()
    def first(self):
        with patch.object(socket,'socket',side_effect=AssertionError('Cache never contacts board')):
            x,mode=evidence.load(self.source,base=self.cache,allow_fixture=True)
        self.assertEqual(mode,'FULL_STRICT_AUDIT');return x
    def test_cache_hit_reuses_identical_planes_without_calling_strict_loader_again(self):
        first=self.first()
        with patch.object(evidence.archive,'load',side_effect=AssertionError('No redundant H2/CRC replay')):
            second,mode=evidence.load(self.source,base=self.cache,allow_fixture=True)
        self.assertEqual(mode,'VERIFIED_HASH_REUSE')
        for k in ('gray','sat1','board','words'):self.assertTrue(np.array_equal(first[k],second[k]))
    def test_full_audit_mode_does_not_accept_cached_arrays(self):
        self.first()
        with patch.object(evidence.archive,'load',side_effect=RuntimeError('FULL_AUDIT_CALLED')):
            with self.assertRaisesRegex(RuntimeError,'FULL_AUDIT_CALLED'):evidence.load(self.source,mode='audit',base=self.cache,allow_fixture=True)
    def test_payload_change_is_refused_even_with_existing_cache(self):
        self.first();p=self.source/'fpga_result.r32';raw=bytearray(p.read_bytes());raw[0]^=1;p.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'source changed'):evidence.load(self.source,base=self.cache,allow_fixture=True)
    def test_cached_native_array_change_is_refused(self):
        self.first();p=evidence.cache_path(self.source,self.cache)/'native.npz';p.write_bytes(p.read_bytes()+b'bad')
        with self.assertRaisesRegex(ValueError,'native cache changed'):evidence.load(self.source,base=self.cache,allow_fixture=True)
    def test_loopback_cache_cannot_be_used_as_physical_evidence(self):
        self.first()
        with self.assertRaisesRegex(ValueError,'SOFTWARE_FIXTURE_NOT_BOARD'):evidence.load(self.source,base=self.cache)
    def test_loader_binding_change_is_refused(self):
        self.first();p=evidence.cache_path(self.source,self.cache)/'CACHE.json';r=json.loads(p.read_text('utf-8'));r['loader_binding']={};p.write_text(json.dumps(r),'utf-8')
        with self.assertRaisesRegex(ValueError,'binding changed'):evidence.load(self.source,base=self.cache,allow_fixture=True)
    def test_cache_flag_cannot_upgrade_a_software_source_to_real_board(self):
        self.first();p=evidence.cache_path(self.source,self.cache)/'CACHE.json';r=json.loads(p.read_text('utf-8'));r['physical_hardware']=True;p.write_text(json.dumps(r),'utf-8')
        with self.assertRaisesRegex(ValueError,'provenance differs'):evidence.load(self.source,base=self.cache)
    def test_replaced_array_and_updated_digest_still_must_match_original_planes(self):
        self.first();folder=evidence.cache_path(self.source,self.cache);p=folder/'native.npz'
        with np.load(p,allow_pickle=False) as z:arrays={k:z[k].copy() for k in z.files}
        arrays['gray'][0,0,0]^=1;np.savez_compressed(p,**arrays);receipt=folder/'CACHE.json';r=json.loads(receipt.read_text('utf-8'));r['native_sha256']=hashlib.sha256(p.read_bytes()).hexdigest();receipt.write_text(json.dumps(r),'utf-8')
        with self.assertRaisesRegex(ValueError,'not the original evidence'):evidence.load(self.source,base=self.cache,allow_fixture=True)
    def test_cache_cannot_omit_raw_source_hashes(self):
        self.first();p=evidence.cache_path(self.source,self.cache)/'CACHE.json';r=json.loads(p.read_text('utf-8'));key=next(k for k in r['files_sha256'] if k.endswith('image.dual_view'));del r['files_sha256'][key];p.write_text(json.dumps(r),'utf-8')
        with self.assertRaisesRegex(ValueError,'mandatory verified source'):evidence.load(self.source,base=self.cache,allow_fixture=True)
    def test_optional_cache_disk_error_keeps_the_completed_full_audit_available(self):
        with patch.object(evidence,'seal',side_effect=PermissionError('CACHE_DISK_UNAVAILABLE')):
            x,mode=evidence.load(self.source,base=self.cache,allow_fixture=True)
        self.assertEqual(mode,'FULL_STRICT_AUDIT_CACHE_UNAVAILABLE');self.assertIn('CACHE_DISK_UNAVAILABLE',x['cache_unavailable_reason']);self.assertEqual(x['gray'].shape[0],8)

if __name__=='__main__':unittest.main(verbosity=2)
