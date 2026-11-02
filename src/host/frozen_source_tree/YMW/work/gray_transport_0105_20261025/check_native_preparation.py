"""No-hardware checks for native profile and the independent real-byte reviewer."""
import hashlib
import json
import socket
from pathlib import Path
from unittest.mock import patch

import numpy as np
import engineering_native_check as native
import review_engineering_capture as audit

HERE=Path(__file__).resolve().parent


def check():
    tests=[]
    def require(value,name):
        if not value:raise ValueError(name)
        tests.append(name)
    with patch.object(socket,'socket',side_effect=AssertionError('No hardware/socket permitted')):
        plan=native.NativeRuntime().prepare()
        require(plan['roi']==[0,0,1920,1080] and plan['pixel_formats']==[1,49] and
            plan['maximum_capture_requests']==2 and plan['mask_words_per_session']==64800 and
            plan['expected_RGB_bytes']==4147200 and plan['expected_GRAY_SAT_bytes']==2332800 and
            plan['expected_RGB_packets']==3006 and plan['expected_GRAY_packets']==1691 and
            plan['per_capture_deadline_s']==300 and 64800+600<65536 and not plan['training_data'] and
            not plan['same_frozen_input'] and not plan['release_ready'],
            'native plan, payload/packet/sequence budgets, no socket')
        require(audit.crc64(b'123456789')==0x6c40df5f0b497347,'independent CRC64 known check value')
        raw=b'\x00\x00\xff\xff\xf8\x00\x07\xe0\x00\x1f'
        gray,sat=audit.planes(raw,5,1,1)
        require(gray.tolist()==[[0,255,76,150,29]] and sat.tolist()==[[False,True,True,True,True]],
                'RGB565 black/white/primary palette and SAT')
        packed=bytes(range(8))+b'\xa5\x08\x80'
        gray,sat=audit.planes(packed,9,1,49)
        require(gray.tolist()==[list(range(9))] and sat.tolist()==[[True,False,True,False,False,True,False,True,True]],
                'interleaved SAT order and partial tail')
        try:audit.planes(packed[:-1]+b'\x81',9,1,49)
        except ValueError:rejected=True
        else:rejected=False
        require(rejected,'nonzero SAT tail padding rejected')
        gray=np.full((1080,1920),255,dtype=np.uint8)
        sat=np.ones_like(gray,dtype=bool)
        h1,h2=audit.h1_h2(gray,sat,sat)
        require(h1['gray_sum']==528768000 and h1['rgb_any_max']==2073600 and
            h2==dict(strong_count=0,weak_count=0,sum9_total=42830208000,residual_n_total=0),
            'native full white reflect/H2 total exceeds 32 bits without overflow')
        previous=json.loads(native.SMALL_REVIEW.read_bytes())
        repeated=audit.review(previous['source_run'])
        require(repeated==previous,'actual small-ROI directory/ZIP/raw CRC/H1/H2 re-review reproducible')
    return dict(schema='guangjian-native-profile-preparation-v1',status='PASS',tests=len(tests),checks=tests,
        physical_captures=0,hardware_contacted=False,network_sockets_created=0,
        source_sha256={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__),Path(native.__file__),Path(audit.__file__),native.SMALL_REVIEW]},
        native_plan=plan,native_payload_hardware_verified=False,release_ready=False)


if __name__=='__main__':
    out=HERE/'verification/native_prepare_01/verification.json'
    if out.exists():raise ValueError('Use a new preparation receipt')
    result=check();out.parent.mkdir(parents=True,exist_ok=True)
    out.write_bytes((json.dumps(result,indent=2)+'\n').encode())
    print(json.dumps({k:result[k] for k in ['status','tests','physical_captures','network_sockets_created']},indent=2))
