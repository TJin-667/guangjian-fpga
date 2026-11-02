"""Use unchanged fast-focus code with a privately injected qualified0108 SDK.

No global imports are replaced, no firmware gate is relaxed, and no original
capture source is edited. Only preview transport/runtime dependencies differ.
"""
import builtins,sys,types
from pathlib import Path
from types import SimpleNamespace as NS
from archive0108 import HOST,QUALIFICATION,read,sha
HERE=Path(__file__).resolve().parent
CAPTURE=HERE.parent/'p0_pair_console_0107_20261027_r56'
sys.path.insert(0,str(CAPTURE))
import console_workflow as legacy

class Runtime(legacy.Runtime):
    def candidate(self):
        sys.path.insert(0,str(HOST));from qualification import validate
        q,files=validate(QUALIFICATION)
        binding={k:q[k] for k in ('candidate_source_commit','bit_path','bit_sha256')}
        return dict(ready=True,binding=binding),{},files
    def focus_plan(self):
        candidate,_,sources=self.candidate();w,h=self.sensor_size
        return dict(preview_lines=600,source_contract=dict(board='192.168.0.2',bind='192.168.0.3',port=5000),candidate=candidate),NS(roi=[0,0,w,h],mask=bytes([1])*(w*h)),sources
    def archive(self,out,summary):
        summary.update(preview_backend='qualified0108',required_firmware=264,evidence_source=self.evidence_source,
            preview_source_sha256=sha(CAPTURE/'fast_focus.py'),qualification_sha256=sha(QUALIFICATION),
            per_frame_CRC64_verified=summary.get('frames',0)>0,counts_as_P0_group=False)
        return super().archive(out,summary)

def load_bridge(*,sdk=None):
    """Compile exact old source; __import__ override belongs only to this module."""
    legacy.verify_bundle()
    if sdk is None:
        sys.path.insert(0,str(HOST));from sdk_loader import load_sdk
        sdk=load_sdk(qualification=QUALIFICATION)
    facade=NS(read=legacy.read,sha=legacy.sha,write=legacy.write,need=legacy.need,Runtime=Runtime,
        backend=NS(sdk=sdk,plan_for=lambda runtime,preview=False:runtime.focus_plan(),cancelled=legacy.backend.cancelled))
    source=CAPTURE/'fast_focus.py';module=types.ModuleType('_final0108_fast_focus');module.__file__=str(source)
    original_import=builtins.__import__
    def isolated_import(name,globals=None,locals=None,fromlist=(),level=0):
        if name=='console_workflow' and level==0:return facade
        return original_import(name,globals,locals,fromlist,level)
    module.__dict__.update(__builtins__={**vars(builtins),'__import__':isolated_import})
    exec(compile(source.read_bytes(),str(source),'exec'),module.__dict__)
    return module
