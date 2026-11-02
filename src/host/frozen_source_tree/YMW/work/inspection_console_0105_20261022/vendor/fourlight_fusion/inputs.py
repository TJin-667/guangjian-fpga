"""Read-only strict 0105 fourlight adapter. No socket or acquisition operations."""
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from fusion import integer_gray,integer_h2


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition,message):
    if not condition:raise ValueError(message)


def read_json(path):return json.loads(Path(path).read_bytes())


def safe_path(root,relative):
    root=Path(root).resolve();path=(root/relative).resolve()
    require(not Path(relative).is_absolute() and path.is_relative_to(root),'Unsafe package path')
    return path


def validate_sequence(plan,frames):
    require(len(frames)==4,'Exactly four directions required')
    first=frames[0]['identity'];previous=None
    for i,row in enumerate(frames):
        require(row['channel']==i+1 and row['direction']==['top','right','bottom','left'][i],'Direction/order mismatch')
        expected={k:plan[k] for k in ('exposure_lines','gain16','brightness','settle_frames','discard_frames')}
        expected['light_mask']=1<<i
        require(row['actual_parameters']==expected,'Actual parameter mismatch')
        ident=row['identity']
        require(ident['session']==first['session'] and ident['roi_generation']==first['roi_generation'],'Mixed session/ROI generation')
        if previous:
            for k in ('request_id','dvp_sequence','publish_sequence','config_epoch','camera_generation','light_generation','frame_id'):
                require(ident[k]>previous[k],'Reused or non-increasing identity: '+k)
        previous=ident
    for key in ('png_sha256','raw_sha256'):
        require(len({r[key] for r in frames})==4,'Copied image is not an independent direction')


def validate_masks(native,common,roi,count):
    x,y,w,h=roi
    require(native.dtype==np.uint8 and native.shape==(h,w) and common.dtype==np.uint8 and common.ndim==2,'Mask shapes/dtypes')
    require(x>=0 and y>=0 and w>0 and h>0 and x+w<=common.shape[1] and y+h<=common.shape[0],'ROI outside full frame')
    require(np.isin(native,[0,1]).all() and np.isin(common,[0,1]).all(),'Nonbinary mask')
    require(int(native.sum())==count>0 and int(common.sum())==count,'Mask denominator/common outside ROI')
    require(np.array_equal(common[y:y+h,x:x+w],native),'Common/native disagreement')


CRC_TABLE=[]
for _b in range(256):
    _value=_b<<56
    for _ in range(8):_value=((_value<<1)^0x42F0E1EBA9EA3693 if _value&(1<<63) else _value<<1)&((1<<64)-1)
    CRC_TABLE.append(_value)


def crc64(raw):
    value=0
    for b in raw:value=CRC_TABLE[(value>>56)^b]^((value<<8)&((1<<64)-1))
    return value


def feature_statistics(h2):
    absolute=np.abs(h2['residual_n'].astype(np.int32))
    return dict(strong_count=int((absolute>1620).sum(dtype=np.uint64)),
        weak_count=int((absolute>648).sum(dtype=np.uint64)),
        sum9_total=int(h2['sum9'].sum(dtype=np.uint64)),
        residual_n_total=int(h2['residual_n'].sum(dtype=np.int64)))


def load_group(root,expected):
    root=Path(root).resolve();plan=read_json(root/'plan.json');frames=read_json(root/'frames.json')
    summary=read_json(root/'operator_summary.json');manifest=read_json(root/'output_manifest.json')['files']
    observed={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    require(observed==set(manifest)|{'output_manifest.json'},'Package member inventory changed')
    for name,value in manifest.items():require(digest(safe_path(root,name))==value,'Member hash changed: '+name)
    require(plan['sample_id']==expected['sample_id'] and plan['roi']==expected['roi'],'Sample/ROI differs from fixed index')
    require(summary['captures_complete'] and summary['operator_same_pose_confirmed'] and summary['frames']==frames,'Incomplete or inconsistent operator summary')
    require(summary['saved_images']==4 and summary['capture_attempts']==4,'Not one complete four-frame group')
    validate_sequence(plan,frames)
    h,w=plan['native_mask_shape_hw'];native=np.fromfile(root/'native_mask.bin',np.uint8).reshape(h,w)
    common=np.fromfile(root/'common_mask.bin',np.uint8).reshape(plan['common_mask_shape_hw'])
    require(common.shape==(1080,1920),'Expected 1920x1080 common coordinates')
    validate_masks(native,common,plan['roi'],plan['mask_pixels'])
    require(plan['mask_pixels']==expected['native_inner_board_pixels'],'Fixed index board denominator mismatch')
    for file,key in [('native_mask.bin','native_mask_sha256'),('common_mask.bin','common_mask_sha256')]:
        require(digest(root/file)==plan[key]==expected[key],'Fixed mask hash mismatch')
    source=np.load(root/'source_mask.npy',allow_pickle=False)
    source=source.astype(np.uint8)
    # The source polygon is retained solely as provenance; never use it as H1 denominator.
    require(digest(root/'source_full.png')==plan['source_full_png_sha256']==expected['source_full_png_sha256'],'Source full PNG changed')
    require(digest(root/'source_geometry.json')==plan['source_geometry_sha256']==expected['source_geometry_sha256'],'Source geometry changed')
    records=[];checks=[]
    board=native.astype(bool)
    for row,official in zip(frames,expected['frames']):
        for key in ('channel','direction','identity','actual_parameters','png_sha256','raw_sha256'):
            require(row[key]==official[key],'Fixed index frame mismatch: '+key)
        result=read_json(safe_path(root,row['result_json']));diag=result['diagnostic']
        require(result['status']=='COMMITTED' and result['strict_verified'] and result['evidence_source']=='real_board','Not a strict committed real frame')
        require(result['sample_id']==plan['sample_id'] and result['roi']==plan['roi'],'Result sample/ROI mismatch')
        for key in ('identity','actual_parameters','camera_readback','statistics','features'):
            require(result[key]==row[key],'Frame/result disagreement: '+key)
        require(diag['identity']==row['identity'] and diag['parameters']==row['actual_parameters'] and diag['roi']==plan['roi'],'Diagnostic binding mismatch')
        require(all(diag[k] for k in ('valid','bound','parameters_valid','mask_valid')) and diag['error']==0,'Diagnostic invalid')
        require(result['mask_sha256']==plan['native_mask_sha256'],'Result mask binding mismatch')
        camera=row['camera_readback']
        require(camera['locked'] and camera['error']==0 and camera['mode']==3 and camera['raw_registers']['0x3503']==3,'AE/AG manual readback')
        require(camera['exposure_raw']==plan['exposure_lines']*16 and camera['gain16']==plan['gain16'],'Camera parameter readback mismatch')
        png=safe_path(root,row['png']);rawpath=safe_path(root,row['raw']);raw=rawpath.read_bytes()
        require(digest(png)==row['png_sha256'] and digest(rawpath)==row['raw_sha256'],'Image SHA mismatch')
        committed=safe_path(root,row['result_json']).parent
        require(png.read_bytes()==(committed/'image.png').read_bytes() and raw==(committed/'image.rgb565').read_bytes(),'Image alias differs')
        bgr=cv2.imdecode(np.frombuffer(png.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        require(bgr is not None and bgr.shape==(h,w,3),'PNG saved dimensions')
        words=np.frombuffer(raw,dtype='>u2');require(words.size==w*h,'RGB565 length')
        words=words.reshape(h,w);r=(words>>11)&31;g=(words>>5)&63;b=words&31
        decoded=np.stack(((b<<3)|(b>>2),(g<<2)|(g>>4),(r<<3)|(r>>2)),axis=2).astype(np.uint8)
        require(np.array_equal(bgr,decoded),'PNG/RGB565 pixels mismatch')
        require(crc64(raw)==result['crc64']==diag['rgb_crc64'],'CRC64 mismatch')
        gray=integer_gray(bgr);rgbmax=(bgr==255).any(axis=2);h2=integer_h2(gray)
        stats=dict(pixel_count=w*h,gray_sum=int(gray.sum()),near_black=int((gray<=5).sum()),near_white=int((gray>=250).sum()),
            rgb_any_max=int(rgbmax.sum()),board_count=int(board.sum()),board_gray_sum=int(gray[board].sum()),
            board_dark=int((gray[board]<=10).sum()),board_white=int((gray[board]>=250).sum()),board_rgb_any_max=int(rgbmax[board].sum()))
        feature=feature_statistics(h2)
        require(stats==row['statistics']==diag['statistics'],'H1 independent mismatch')
        require(feature==row['features']==diag['features'],'H2 integral-sum mismatch')
        # Independent direct 81-term summation guards the integral implementation.
        padded=np.pad(gray,4,mode='reflect').astype(np.uint32);direct=np.zeros(gray.shape,np.uint32)
        for dy in range(9):
            for dx in range(9):direct+=padded[dy:dy+h,dx:dx+w]
        require(np.array_equal(direct,h2['sum9']),'Direct81 H2 mismatch')
        records.append(dict(bgr=bgr,frame=row,result=result))
        checks.append(dict(channel=row['channel'],png_sha256=row['png_sha256'],raw_sha256=row['raw_sha256'],
            alias_not_extra_observation=True,png_raw_pixels_equal=True,crc64_equal=True,H1_equal=True,H2_direct81_equal=True))
    return dict(sample_id=plan['sample_id'],roi=plan['roi'],board=board,records=records,checks=checks,plan=plan,summary=summary,
                member_files=len(observed),zip_compressed_bytes_verified=False,source_polygon_used_as_statistics_denominator=False)
