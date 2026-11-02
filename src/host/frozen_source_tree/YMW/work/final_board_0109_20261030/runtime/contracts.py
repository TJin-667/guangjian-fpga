"""Backend-neutral native-plane and qualification contracts. No hardware IO."""
from dataclasses import dataclass
import numpy as np

ORDER=tuple(f'CH{i}_{role}' for i in range(1,5) for role in ('low','high'))
PARAMETER_FREEZE_ID='f09eb5885e1d'
SYSTEM_VERSION='v1.7-candidate'
DETECTOR_ID='387cfeac0426'
LEGACY_DETECTOR_ID='4c0be2d44fdd'
REVIEW_COMMIT='9a2a91e22302b301fb6a0f169a0773c17a17642c'

def result_version_label(result):
    """Historical results remain viewable, never relabelled as the new freeze."""
    if result.get('automatic_pass') is not False:raise ValueError('Invalid automatic pass')
    if result.get('detector_id')==DETECTOR_ID and result.get('parameter_freeze_id')==PARAMETER_FREEZE_ID:
        return '冻结组合 '+PARAMETER_FREEZE_ID
    if result.get('detector_id')==LEGACY_DETECTOR_ID and not result.get('parameter_freeze_id'):
        return '历史版本 '+LEGACY_DETECTOR_ID+'（非当前冻结）'
    raise ValueError('Wrong detector or parameter freeze identity')

@dataclass(frozen=True)
class BackendCapability:
    name:str
    all_eight_residuals:bool
    board_accepted:bool

STABLE=BackendCapability('stable0107_pc',True,True)
OFFLOAD=BackendCapability('offload0109',True,False)

def require_backend(name):
    if name==STABLE.name:return STABLE
    if name==OFFLOAD.name:raise ValueError('0109_NOT_QUALIFIED: final host adapter and board acceptance pending')
    raise ValueError('UNKNOWN_BACKEND')

def validate_planes(planes):
    gray=planes['gray'];board=planes['board'];shape=gray.shape
    if gray.dtype!=np.uint8 or len(shape)!=3 or shape[0]!=8 or min(shape[1:])<9:raise ValueError('NATIVE_GRAY8_EIGHT_REQUIRED')
    if board.dtype!=bool or board.shape!=shape[1:]:raise ValueError('NATIVE_BOARD_REQUIRED')
    if planes['valid'].dtype!=bool or planes['valid'].shape!=shape:raise ValueError('NATIVE_EIGHT_VALID_REQUIRED')
    sat=planes['sat1']
    if sat.shape!=shape or sat.dtype not in (np.dtype(bool),np.dtype('uint8')) or np.any(sat>1):raise ValueError('NATIVE_EIGHT_BINARY_SAT1_REQUIRED')
    r=planes['residual_n']
    if r.shape!=shape or r.dtype.kind!='i' or np.any(r.astype('int64') < -20655) or np.any(r.astype('int64')>20655):raise ValueError('EXACT_EIGHT_SIGNED_RN_REQUIRED')
    return shape

def pixel_to_sensor(x,y,roi):return x+roi[0],y+roi[1]
