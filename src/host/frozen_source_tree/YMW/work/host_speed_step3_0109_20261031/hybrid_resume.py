# Derived independent host adapter; source SHA256 47152b55a87d565483f0cae74d27fc157282ceb6ae30fda1ea6e01c095a78bf8
"""Frozen postprocessing on lossless FPGA R32 plus eight archived native gray frames."""
from export_paths import legacy_location, data_path, lab_root, network
import importlib.util,sys
from pathlib import Path
import numpy as np
from residual_access import ResidualAccess
HERE=legacy_location('C:/bx72_ymw_0105_20261015/repo/YMW/work/final_board_0109_20261030/runtime')
WORK=HERE.parents[1]

def build_context(gray,sat,board,words,*,valid,residual):
    if gray.dtype!=np.uint8 or gray.shape!=(8,*board.shape) or board.dtype!=bool:raise ValueError('Native gray/board mismatch')
    if sat.shape!=gray.shape or sat.dtype not in (np.dtype(bool),np.dtype('uint8')) or np.any(sat>1):raise ValueError('Invalid native SAT')
    spec=importlib.util.spec_from_file_location('_final_system_verified_b1_common',WORK/'b1_detection_console_20261027/common.py');common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
    common.verify_app();vendor,_=common.verify_vendor();sys.path.insert(0,str(vendor))
    from dual_exposure_b1.fusion import single_features # pins frozen quality/connection module origin
    from light_inspection.real_baseline import assess_quality,hysteresis_connect
    sys.path.insert(0,str(WORK/'joint_threshold_tuning_20261029'))
    from sleeve_guard import prepare as prepare_sleeve
    decoder_path=WORK/'fusion_offload_0108_20261028/host/result_codec.py'
    spec=importlib.util.spec_from_file_location('_final_system_frozen_r32_codec',decoder_path);codec=importlib.util.module_from_spec(spec);spec.loader.exec_module(codec)
    fused,selected_gray=codec.decode_words(words,board,hysteresis_connect)
    if valid.dtype!=bool or valid.shape!=gray.shape or residual.dtype!=np.int16 or residual.shape!=gray.shape:raise ValueError('Cached exact derivative arrays required')
    yy,xx=np.indices(board.shape);source=fused['source_frame'];index=np.maximum(source.astype(int)-1,0)
    if np.any((source>0)&~valid[index,yy,xx]):raise ValueError('FPGA selected an invalid observation')
    expected_gray=gray[index,yy,xx].copy();expected_gray[source==0]=0
    if not np.array_equal(selected_gray,expected_gray):raise ValueError('Selected-source gray does not match archived source')
    expected_residual=residual[index,yy,xx].copy();expected_residual[source==0]=0
    if not np.array_equal(fused['residual_n'],expected_residual):raise ValueError('Selected-source residual differs from audited cache')
    unknown=~valid.any(0)
    if not np.array_equal(fused['unknown'],unknown):raise ValueError('FPGA unknown differs from exact tile validity')
    amplitude=np.abs(fused['residual_n'].astype('int32'));v=~unknown
    guide=hysteresis_connect(amplitude,v,486,1620)['mask']&board
    provider=residual
    context=dict(planes=dict(gray=gray,valid=valid,board=board,sat1=sat,residual_n=provider),r=amplitude,v=v,board=board,
                 original=fused['mask'],guide=guide,hysteresis=hysteresis_connect,caches={},tip_cache={},
                 sleeve=prepare_sleeve(fused['mask'],guide,amplitude),original_differences={})
    return context,fused,provider
