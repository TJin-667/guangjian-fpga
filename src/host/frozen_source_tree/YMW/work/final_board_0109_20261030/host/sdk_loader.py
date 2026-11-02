"""Private strict0109 modules; real sockets remain qualification gated."""
import importlib.util,sys,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent;ACCEPT=ROOT.parent/'acceptance_0107_20261026'
def load(name,path,**injected):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);module.__dict__.update(injected)
    sys.modules[name]=module;spec.loader.exec_module(module);return module
def load_sdk(qualification=None):
    record=None;proofs={}
    if qualification is not None:
        record,proofs=load('_offload109_qualification',HERE/'qualification.py').validate(qualification)
    load('_offload109_dual',ACCEPT/'dual_view.py')
    load('_offload109_wire',ROOT/'derived_sdk/host_transport_0109.py')
    module=load('_offload109_sdk',ROOT/'derived_sdk/sdk_transport_0109.py',ALLOW_REAL_0109=record is not None,CANDIDATE_SOURCE_COMMIT=None if record is None else record['candidate_source_commit'])
    for p in [Path(__file__),HERE/'engineering_executor.py',HERE/'offload_wire.py',HERE/'result_view.py']:
        module.SOURCE_SNAPSHOT[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    module.SOURCE_SNAPSHOT.update(proofs);return module
