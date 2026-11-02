import hashlib
import unittest
import numpy as np
from codec import planes,encode,decode,packets,Receiver,HEADER,tile_quality_gray

class CodecTests(unittest.TestCase):
    def test_hand_authored_record(self):
        g=np.arange(1,10,dtype=np.uint8).reshape(1,9)
        s=np.array([1,0,0,0,0,0,0,1,1],bool).reshape(1,9)
        raw=encode(g,s)
        self.assertEqual(raw,bytes([1,2,3,4,5,6,7,8,0x81,9,0x80]))
        for a,b in zip(decode(raw,9,1),(g,s)):np.testing.assert_array_equal(a,b)

    def test_exhaustive_rgb565(self):
        w=np.arange(65536,dtype=np.uint32)
        r=(w>>11)&31;g=(w>>5)&63;b=w&31
        bgr=np.stack(((b<<3)|(b>>2),(g<<2)|(g>>4),(r<<3)|(r>>2)),axis=1).astype(np.uint8).reshape(256,256,3)
        gray,sat=planes(bgr)
        # Independent scalar oracle for every sensor code.
        oracle=[]
        for word in range(65536):
            rr=((word>>11)&31)*255//31;gg=((word>>5)&63)*255//63;bb=(word&31)*255//31
            # Bit replication is different from normalized floor expansion.
            rr=((word>>11)&31)<<3 | ((word>>11)&31)>>2
            gg=((word>>5)&63)<<2 | ((word>>5)&63)>>4
            bb=(word&31)<<3 | (word&31)>>2
            oracle.append((9798*rr+19235*gg+3735*bb+16384)//32768)
        np.testing.assert_array_equal(gray.reshape(-1),oracle)
        np.testing.assert_array_equal(sat.reshape(-1),(r==31)|(g==63)|(b==31))

    def test_boundaries_and_reassembly(self):
        for n in (1,7,8,9,1223,1224,1225,1380,1381,2073600):
            width,height=(1920,1080) if n==2073600 else (n,1)
            g=(np.arange(n)%256).astype(np.uint8).reshape(height,width)
            s=(np.arange(n)%5==0).reshape(height,width)
            raw=encode(g,s); ps=list(packets(raw,width,height,65535))
            receiver=Receiver(width,height,65535,hashlib.sha256(raw).hexdigest(),started=0)
            result=None
            for packet in reversed(ps): result=receiver.add(packet,now=.1) or result
            for a,b in zip(result,(g,s)):np.testing.assert_array_equal(a,b)

    def test_invalid_padding(self):
        with self.assertRaises(ValueError):decode(bytes([10,1]),1,1)

    def test_stale_wrong_format_crc_timeout(self):
        raw=bytes([10,0]); good=list(packets(raw,1,1,3))[0]
        for case in ('stale','format','content','timeout'):
            receiver=Receiver(1,1,3,hashlib.sha256(raw).hexdigest(),started=0)
            bad=bytearray(good)
            if case=='stale':bad[7]=4
            if case=='format':bad[18]=1
            if case=='content':bad[20]^=1
            with self.assertRaises((ValueError,TimeoutError)):receiver.add(bytes(bad),now=20 if case=='timeout' else 1)
            self.assertTrue(receiver.failed)

    def test_duplicates_conflict_and_missing(self):
        raw=encode(np.zeros((2,1000),np.uint8),np.zeros((2,1000),bool))
        ps=list(packets(raw,1000,2,1));r=Receiver(1000,2,1,hashlib.sha256(raw).hexdigest(),started=0)
        self.assertIsNone(r.add(ps[0],now=1));self.assertIsNone(r.add(ps[0],now=1));self.assertEqual(r.duplicates,1)
        self.assertFalse(r.done)
        bad=bytearray(ps[0]);bad[-1]^=1
        with self.assertRaises(ValueError):r.add(bytes(bad),now=1)

    def test_dimensions_and_dtype(self):
        with self.assertRaises(ValueError):decode(b'',0,1)
        with self.assertRaises(ValueError):decode(b'',1921,1)
        with self.assertRaises(ValueError):encode(np.zeros((1,1),np.uint16),np.zeros((1,1),bool))

if __name__=='__main__':unittest.main(verbosity=2)
