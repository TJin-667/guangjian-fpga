"""Change only source pixel-origin handling in the pinned XDL manifest reader."""
import difflib,hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'gray_transport_0105_20261025/integration_refs/xdl_a47a/exposure_fusion_v1/run.py'
EXPECTED_BLOB='74b43f419b9361f453ef8cd0a15ecad0d737773e'

def generate():
    data=SOURCE.read_bytes();blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    if blob!=EXPECTED_BLOB:raise ValueError('Pinned XDL runner changed')
    before=data.decode();after=before
    anchor='''    crop = source_gray[y:y + height, x:x + width]'''
    insertion='''    origin = record.get("source_origin_xy", [0, 0])
    if len(origin) != 2 or any(type(v) is not int or v < 0 for v in origin):
        raise ValueError("source_origin_xy requires two nonnegative integers")
    local_x, local_y = x - origin[0], y - origin[1]
    if local_x < 0 or local_y < 0:
        raise ValueError("Analysis ROI starts before the saved source origin")
    if record.get("source_coordinate_space") == "saved_roi":
        if origin != [x, y] or source_gray.shape != (height, width):
            raise ValueError("Saved native ROI source shape/origin differs")
        sensor = record.get("sensor_size_xy")
        if not isinstance(sensor, (list, tuple)) or len(sensor) != 2 or any(type(v) is not int or v <= 0 for v in sensor):
            raise ValueError("Saved ROI requires original sensor dimensions")
        if x + width > sensor[0] or y + height > sensor[1]:
            raise ValueError("ROI exceeds original sensor")
        hardware_roi = record.get("hardware_capture_roi_xywh", list(roi_xywh))
        if record.get("crop_applied_at") == "native_acquisition_ROI" and list(hardware_roi) != list(roi_xywh):
            raise ValueError("Native acquisition ROI and saved source ROI differ")
    crop = source_gray[local_y:local_y + height, local_x:local_x + width]'''
    if after.count(anchor)!=1:raise ValueError('Source crop hook differs')
    after=after.replace(anchor,insertion)
    old='expected_crop = expected_sat1[y:y + height, x:x + width]'
    if after.count(old)!=1:raise ValueError('SAT crop hook differs')
    after=after.replace(old,'expected_crop = expected_sat1[local_y:local_y + height, local_x:local_x + width]')
    return after.encode(),before,after

if __name__=='__main__':
    data,before,after=generate();(HERE/'xdl_crop_runner.py').write_bytes(data)
    (HERE/'XDL_CROP_DERIVATION.json').write_text(json.dumps(dict(upstream_git_blob=EXPECTED_BLOB,upstream_commit='0cb2c6e25878016cb8813169e514f155ab0cc574',
        derived_sha256=hashlib.sha256(data).hexdigest(),scope='source origin validation and source slicing only; original detector/fusion/training unchanged'),indent=2)+'\n',encoding='utf-8')
    (HERE/'XDL_CROP.diff').write_text(''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='XDL_pinned_run.py',tofile='YMW_xdl_crop_runner.py')),encoding='utf-8')
