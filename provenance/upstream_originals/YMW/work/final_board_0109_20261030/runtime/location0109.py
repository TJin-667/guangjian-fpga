"""One qualified0109 positioning frame, then an operator-confirmed new ROI/plan."""
import contextlib,json,sys
from pathlib import Path
from archive0109 import HOST,QUALIFICATION,read,sha,need
from engineering0109 import prepare_native
HERE=Path(__file__).resolve().parent
WORK=HERE.parents[1]

def capture_preview(root,sample,pose,cancel,notify=lambda text:None):
    """UI confirmation precedes this function. Exactly one CAP, then OFF cleanup."""
    root=Path(root).resolve()
    need(root.is_relative_to(Path('E:/GuangjianData').resolve()) and not root.exists(),'New positioning directory onE required')
    if cancel.is_set():raise InterruptedError('Cancelled before board access')
    sys.path.insert(0,str(HOST))
    from sdk_loader import load_sdk
    from qualification import validate
    qualification,_=validate(QUALIFICATION);sdk=load_sdk(qualification=QUALIFICATION)
    peer=sdk.wire.pinned_module('_final0109_position_owner',HOST.parents[1]/'auto_exposure_0105_20261015/app_core.py','448fa6c6388093be794cf47f4932e77b688da92f74aa852ba8609b2cf5992857')
    engine=peer.load_engine();root.mkdir(parents=True,exist_ok=False)
    binding={k:qualification[k] for k in ('candidate_source_commit','bit_path','bit_sha256')}
    executor=None;frame=None;cleanup=None;failure=None
    with peer.operator_lock(Path('C:/BX72_0105_LAB')):
        try:
            if cancel.is_set():raise InterruptedError('Cancelled before executor construction')
            executor=sdk.TransportExecutor(board='192.168.0.2',port=5000,bind='192.168.0.3',ymw_root=engine.root/'ymw',output_root=root/'captures',pixel_format=50,mode='strict',evidence_source='real_board',candidate_binding=binding)
            notify('0109单张定位：首次全幅mask上传较慢，请等待；定位图不算正式八帧。')
            frame=executor.acquire(light_channel=1,brightness=128,exposure_lines=600,gain16=16,roi=[0,0,1920,1080],board_mask=bytes([1])*(1920*1080),settle_frames=1,discard_frames=3,timeout_s=300,sample_id=sample,round_id=pose+'_positioning_only',cancel=cancel)
            png=root/'positioning_rgb.png'
            executor.v1.save_png(png,(frame.record_path.parent/'same_frame.rgb565').read_bytes(),1920,1080)
        except BaseException as exc:failure=dict(type=type(exc).__name__,message=str(exc))
        finally:
            if executor is not None:
                try:cleanup=executor.lights_off(timeout_s=3)
                except BaseException as exc:cleanup=dict(acknowledged=False,error=str(exc))
                finally:executor.close()
    ok=failure is None and frame is not None and cleanup and cleanup.get('acknowledged')
    receipt=dict(status='POSITIONING_READY_REQUIRES_ROI_CONFIRMATION' if ok else 'FAILED',error=failure,cleanup=cleanup,sample=sample,pose=pose,positioning_only=True,formal_observations=0,new_CAP_limit=1,qualification=str(QUALIFICATION),qualification_sha256=sha(QUALIFICATION),candidate_bit_sha256=qualification['bit_sha256'])
    if frame is not None:receipt.update(record=str(frame.record_path),record_sha256=sha(frame.record_path))
    if ok:receipt.update(png=str(png),png_sha256=sha(png))
    path=root/'POSITIONING.json';path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8')
    if not ok:raise RuntimeError('0109定位未完成；保留记录：'+str(path)+'；'+str(failure or cleanup))
    return path

def prepare_selection(receipt_path,points,margin):
    """No CAP here. Preserve the selected native geometry and source hashes."""
    receipt_path=Path(receipt_path).resolve();root=receipt_path.parent;r=read(receipt_path)
    need(r['status']=='POSITIONING_READY_REQUIRES_ROI_CONFIRMATION' and r['cleanup']['acknowledged'],'Complete positioning/OFF required')
    need(sha(r['record'])==r['record_sha256'] and sha(r['png'])==r['png_sha256'],'Positioning evidence changed')
    need(sha(r['qualification'])==r['qualification_sha256'],'Positioning qualification changed')
    meta=read(r['record']);need(meta['status']=='COMMITTED' and meta['strict_verified'] and meta['firmware']==265 and meta['roi']==[0,0,1920,1080],'Strict full native0109 positioning frame required')
    sys.path.insert(0,str(WORK/'p0_pair_console_0107_20261027_r56'))
    import capture_backend,roi_geometry
    full=capture_backend.polygon_mask(points,(1920,1080));geometry=roi_geometry.build(points,(1920,1080),margin)
    x,y,w,h=geometry['roi_xywh'];mask=full[y:y+h,x:x+w].copy();need(int(mask.sum())==int(full.sum()),'Native ROI omitted board pixels')
    source=root/'selected_board_mask.bin';need(not source.exists(),'Positioning already confirmed; use its existing PLAN')
    source.write_bytes(mask.tobytes());(root/'crop_geometry.json').write_text(json.dumps(geometry,indent=2)+'\n','utf-8')
    plan=prepare_native(geometry['roi_xywh'],source,r['sample'],r['pose'],root/'plan')
    evidence=dict(positioning_receipt=str(receipt_path),positioning_receipt_sha256=sha(receipt_path),operator_confirmed=True,points_xy=points,roi_xywh=geometry['roi_xywh'],mask_sha256=sha(source),plan_sha256=sha(plan),formal_frames_captured_here=0)
    (root/'SELECTION.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n','utf-8')
    return plan
