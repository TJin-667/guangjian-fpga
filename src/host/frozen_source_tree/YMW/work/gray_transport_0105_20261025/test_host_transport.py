import copy
import struct
import unittest
import numpy as np
import host_transport as h

class HostTransportTests(unittest.TestCase):
    def setUp(self):
        self.w,self.height=80,21
        self.words=((np.arange(self.w*self.height,dtype=np.uint32)*7919+31)&65535).astype('>u2')
        self.rgb=self.words.tobytes()
        self.gray,self.sat=h.planes_from_payload(self.rgb,self.w,self.height,1)
        self.board=np.arange(self.w*self.height).reshape(self.height,self.w)%5<2
        self.tag=dict(session=0x0123456789abcdef,request_id=7,config_epoch=4,dvp_sequence=100,publish_sequence=9,roi_generation=2,camera_generation=3,light_generation=2,frame_id=0)
        self.params=dict(exposure_lines=600,gain16=16,light_mask=1,brightness=128,settle_frames=1,discard_frames=3)
        self.roi=[5,7,self.w,self.height];self.seq=123

    def fixture(self,fmt=49):
        raw=self.rgb if fmt==1 else h.codec.encode(self.gray,self.sat)
        stat,features=h.recompute(self.gray,self.sat,self.board)
        p=bytearray(160);p[:8]=struct.pack('!4BHH',2,15,0,0,0x0106,self.tag['frame_id'])
        p[8:40]=struct.pack('!Q4I4H',*(self.tag[k] for k in h.TAG_KEYS));p[40]=1
        p[42:50]=struct.pack('!HH4B',*(self.params[k] for k in h.PARAM_KEYS))
        p[50:58]=struct.pack('!4H',*self.roi);p[58:98]=struct.pack('!10I',*(stat[k] for k in h.legacy.H1_KEYS))
        p[98:100]=bytes([1,3]);p[100:120]=struct.pack('!5I',0,1920*1080,self.tag['request_id'],features['strong_count'],features['weak_count'])
        p[120:136]=struct.pack('!Qq',features['sum9_total'],features['residual_n_total'])
        p[136:144]=h.legacy.crc64_ecma(self.rgb).to_bytes(8,'big')
        p[144:160]=struct.pack('!BBHIQ',fmt,0,0,len(raw),h.legacy.crc64_ecma(raw))
        metadata=struct.pack('!4sBBHH',b'LGHT',1,0x85,self.seq,160)+p
        count=(len(raw)+1379)//1380;packets=[]
        for i in range(count):
            part=raw[i*1380:(i+1)*1380]
            packets.append(h.codec.HEADER.pack(b'LGHT',1,0x90,self.tag['frame_id'],i,count,len(part),self.w,self.height,fmt,int(i==0)|(int(i==count-1)<<1))+part)
        return raw,metadata,packets

    def receiver(self,fmt=49,**kw):
        args=dict(identity={k:self.tag[k] for k in h.REQUEST_KEYS},parameters=self.params,roi=self.roi,board=self.board,pixel_format=fmt,started=0)
        args.update(kw);return h.StrictReceiver(**args)

    def loaded(self,fmt=49):
        raw,meta,packets=self.fixture(fmt);r=self.receiver(fmt)
        for p in packets:r.add_packet(p,now=1)
        return r,raw,meta,packets

    def test_crc_known_ecma_vector(self):
        self.assertEqual(h.legacy.crc64_ecma(b'123456789'),0x6c40df5f0b497347)

    def test_fixed_h1_black_thresholds_are_distinct(self):
        gray=np.full((9,9),11,np.uint8);gray.flat[:5]=[5,6,10,250,255]
        stat,_=h.recompute(gray,np.zeros((9,9),bool),np.ones((9,9),bool))
        self.assertEqual(stat['near_black'],1);self.assertEqual(stat['board_dark'],3)
        self.assertEqual(stat['near_white'],2);self.assertEqual(stat['board_white'],2)

    def test_both_formats_reorder_duplicate_and_provisional_then_commit(self):
        for fmt in (1,49):
            with self.subTest(fmt=fmt):
                raw,meta,packets=self.fixture(fmt);r=self.receiver(fmt)
                for p in reversed(packets):self.assertIsNone(r.add_packet(p,now=1))
                self.assertIsNone(r.add_packet(packets[0],now=1));self.assertFalse(r.committed)
                result=r.finalize(meta,expected_query_seq=self.seq,now=1)
                np.testing.assert_array_equal(result['gray'],self.gray);np.testing.assert_array_equal(result['sat'],self.sat)
                self.assertTrue(r.committed);self.assertFalse(result['physical_freshness_verified']);self.assertEqual(r.duplicates,1)

    def test_missing_packet_cannot_finalize(self):
        _,meta,packets=self.fixture();r=self.receiver();r.add_packet(packets[0],now=1)
        with self.assertRaises(ValueError):r.finalize(meta,expected_query_seq=self.seq,now=1)
        self.assertTrue(r.failed);self.assertFalse(r.parts)

    def test_conflicting_duplicate_is_terminal(self):
        _,_,packets=self.fixture();r=self.receiver();r.add_packet(packets[0],now=1)
        changed=bytearray(packets[0]);changed[-1]^=1
        with self.assertRaises(ValueError):r.add_packet(bytes(changed),now=1)
        with self.assertRaises(ValueError):r.add_packet(packets[1],now=1)

    def test_corrupt_image_rejected_by_payload_crc(self):
        _,meta,packets=self.fixture();r=self.receiver();changed=bytearray(packets[0]);changed[25]^=1
        r.add_packet(bytes(changed),now=1)
        for p in packets[1:]:r.add_packet(p,now=1)
        with self.assertRaisesRegex(ValueError,'CRC64'):r.finalize(meta,expected_query_seq=self.seq,now=1)

    def test_wrong_header_fields_rejected(self):
        _,_,packets=self.fixture()
        for offset in (0,4,5,6,8,10,12,14,16,18,19):
            with self.subTest(offset=offset):
                bad=bytearray(packets[0]);bad[offset]^=1;r=self.receiver()
                with self.assertRaises(ValueError):r.add_packet(bytes(bad),now=1)
                self.assertTrue(r.failed)

    def test_truncated_or_oversized_packet_rejected(self):
        _,_,packets=self.fixture()
        for p in (b'',packets[0][:-1],packets[0]+b'\0'):
            with self.assertRaises(ValueError):self.receiver().add_packet(p,now=1)

    def test_old_or_pending_metadata_not_committed(self):
        # Mutate committed identity, readbacks, wait counts and H1/H2 summaries.
        for offset in (10,11,12,14,18,26,30,42,44,46,48,52,54,56,58,60,62,64,68,88,108,114,118,122,130,154,155,156,158,162):
            with self.subTest(offset=offset):
                r,_,meta,_=self.loaded();bad=bytearray(meta);bad[offset]^=1
                with self.assertRaises(ValueError):r.finalize(bytes(bad),expected_query_seq=self.seq,now=1)
                self.assertTrue(r.failed);self.assertFalse(r.committed)

    def test_query_sequence_not_inferred_from_packet(self):
        r,_,meta,_=self.loaded()
        with self.assertRaisesRegex(ValueError,'query sequence'):r.finalize(meta,expected_query_seq=self.seq+1,now=1)

    def test_rgb_crc_semantics_and_missing_publication_identity(self):
        r,_,meta,_=self.loaded(1);bad=bytearray(meta);bad[146]^=1
        with self.assertRaisesRegex(ValueError,'RGB CRC'):r.finalize(bytes(bad),expected_query_seq=self.seq,now=1)
        for offset in (34,38):
            r,_,meta,_=self.loaded();bad=bytearray(meta);bad[offset:offset+4]=bytes(4)
            with self.assertRaises(ValueError):r.finalize(bytes(bad),expected_query_seq=self.seq,now=1)

    def test_deadline_includes_final_metadata(self):
        r,_,meta,_=self.loaded()
        with self.assertRaises(TimeoutError):r.finalize(meta,expected_query_seq=self.seq,now=31)

    def test_failed_receiver_never_recovers_implicitly(self):
        r,_,meta,_=self.loaded()
        with self.assertRaises(ValueError):r.finalize(meta[:-1],expected_query_seq=self.seq,now=1)
        with self.assertRaises(ValueError):r.finalize(meta,expected_query_seq=self.seq,now=1)

    def test_cancel_clears_bytes_and_blocks_commit(self):
        r,_,meta,_=self.loaded();r.cancel()
        self.assertTrue(r.failed);self.assertFalse(r.parts)
        with self.assertRaises(ValueError):r.finalize(meta,expected_query_seq=self.seq,now=1)

    def test_previous_publication_forward_and_stale(self):
        previous=copy.deepcopy(self.tag)
        for k in ('request_id','dvp_sequence','publish_sequence'):previous[k]-=1
        r,_,meta,_=self.loaded();r.finalize(meta,expected_query_seq=self.seq,now=1,previous_publication=previous)
        for key in ('request_id','dvp_sequence','publish_sequence','session'):
            bad=copy.deepcopy(previous);bad[key]=self.tag[key] if key!='session' else self.tag[key]+1
            r,_,meta,_=self.loaded()
            with self.assertRaises(ValueError):r.finalize(meta,expected_query_seq=self.seq,now=1,previous_publication=bad)

    def test_missing_trusted_executor_context_rejected(self):
        for key in h.REQUEST_KEYS:
            bad={k:self.tag[k] for k in h.REQUEST_KEYS if k!=key}
            with self.assertRaises(ValueError):self.receiver(identity=bad)
        for key in h.PARAM_KEYS:
            bad={k:v for k,v in self.params.items() if k!=key}
            with self.assertRaises(ValueError):self.receiver(parameters=bad)

    def test_wrong_board_mask_detected_by_h1(self):
        _,meta,packets=self.fixture();r=self.receiver(board=np.ones(self.board.shape,bool))
        for p in packets:r.add_packet(p,now=1)
        with self.assertRaisesRegex(ValueError,'H1/H2'):r.finalize(meta,expected_query_seq=self.seq,now=1)

    def test_capability_exact_version_formats_and_query_binding(self):
        p=struct.pack('!4sBBHH',b'LGHT',1,0x86,9,22)+struct.pack('!BHBBBHHHQH',1,0x0106,49,3,0,1380,1920,1080,0x42f0e1eba9ea3693,1)
        self.assertEqual(h.decode_capabilities(p,9)['format'],49)
        for offset in (0,4,5,6,8,10,11,13,14,15,16,18,20,22,30):
            with self.subTest(offset=offset):
                bad=bytearray(p);bad[offset]^=1
                with self.assertRaises(ValueError):h.decode_capabilities(bytes(bad),9)

if __name__=='__main__':unittest.main(verbosity=2)
