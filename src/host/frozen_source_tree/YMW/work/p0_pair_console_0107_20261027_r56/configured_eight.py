"""Validate an eight-observation dataset; no acquisition or exposure selection."""
import copy
import hashlib
import re
import numpy as np
from capture_settings import MIN_LINES,MAX_LINES
from host_transport import planes_from_payload,legacy,decode_metadata

def validate_eight(records,*,sample_id,pose_id,low,high,roi,board):
    if any(not isinstance(s,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',s) for s in (sample_id,pose_id)):raise ValueError('sample/pose ID')
    if any(type(v) is not int or not MIN_LINES<=v<=MAX_LINES for v in (low,high)) or low>=high:raise ValueError('configured exposure pair')
    if not isinstance(records,list) or len(records)!=8:raise ValueError('exactly eight formal observations required')
    if not isinstance(board,np.ndarray) or board.dtype!=np.bool_ or board.shape!=(roi[3],roi[2]) or not board.any():raise ValueError('fixed board mask')
    expected={(channel,role) for channel in range(1,5) for role in ('low','high')};seen=set();session=None;last=None;fmt=None;observations=[]
    for record in records:
        channel,role=record['channel'],record['role'];key=(channel,role)
        if type(channel) is not int or key not in expected or key in seen:raise ValueError('direction/role missing or duplicated')
        if record['sample_id']!=sample_id or record['pose_id']!=pose_id:raise ValueError('sample/pose changed')
        result=record['validated'];m=result['metadata'];tag=m['identity'];params=m['parameters'];raw=result['payload']
        if decode_metadata(result['metadata_packet'],m['seq'])!=m:raise ValueError('metadata changed after strict validation')
        if result['board_mask_sha256']!=hashlib.sha256(board.astype(np.uint8).tobytes()).hexdigest():raise ValueError('board mask changed within round')
        if not m['valid'] or not m['logical_association_available'] or not m['mask_valid'] or m['error']:raise ValueError('uncommitted observation')
        if m['roi']!=list(roi) or params['gain16']!=16 or params['brightness']!=128 or params['light_mask']!=1<<(channel-1) or params['exposure_lines']!=(low if role=='low' else high):raise ValueError('fixed plan/readback mismatch')
        if (params['settle_frames'],params['discard_frames'])!=(1,3):raise ValueError('wait policy changed')
        if session is None:session=tag['session'];fmt=m['pixel_format']
        if tag['session']!=session or m['pixel_format']!=fmt:raise ValueError('session/format changed within round')
        if last is not None:
            if tag['roi_generation']!=last['roi_generation'] or tag['request_id']<=last['request_id']:raise ValueError('ROI generation/stale request')
            for k,bits,strict in [('dvp_sequence',32,True),('publish_sequence',32,True),('frame_id',16,True),('config_epoch',32,False),('camera_generation',16,False),('light_generation',16,False)]:
                delta=(tag[k]-last[k])&((1<<bits)-1)
                if delta>=1<<(bits-1) or (strict and delta==0):raise ValueError('nonforward '+k)
        if len(raw)!=m['payload_bytes'] or legacy.crc64_ecma(raw)!=m['payload_crc64'] or hashlib.sha256(raw).hexdigest()!=result['payload_sha256']:raise ValueError('archived payload changed')
        gray,sat=planes_from_payload(raw,roi[2],roi[3],fmt)
        if not np.array_equal(gray,result['gray']) or not np.array_equal(sat,result['sat']):raise ValueError('decoded training planes changed')
        if m['statistics']['board_count']!=int(board.sum()):raise ValueError('board mask count changed')
        observations.append({'observation_id':f'CH{channel}_{role}','channel':channel,'role':role,'parameters':copy.deepcopy(params),
            'identity':copy.deepcopy(tag),'roi':list(roi),'pixel_format':fmt,'payload_sha256':result['payload_sha256'],
            'label_status':'UNLABELED_PENDING_XDL','quality_and_confidence':'NOT_EVALUATED'})
        seen.add(key);last=tag
    if seen!=expected:raise ValueError('missing exposure pair')
    return {'schema':'fixed-eight-validated-input-v1','sample_id':sample_id,'pose_id':pose_id,'formal_observations':8,
        'low_exposure_lines':low,'high_exposure_lines':high,'roi':list(roi),'board_mask_sha256':hashlib.sha256(board.astype(np.uint8).tobytes()).hexdigest(),
        'online_exposure_search':False,'supplement_selection':False,'physical_pose_verified_by_software':False,
        'observations':observations}
