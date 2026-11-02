"""Verify the independent UI and the immutable parent UI; never hardware IO."""
import hashlib,importlib.util,json
from pathlib import Path,PurePosixPath
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify():
    record=json.loads((HERE/'RUNTIME_BINDING.json').read_text('utf-8'))
    for name,digest in record['files_sha256'].items():
        relative=PurePosixPath(name);p=(HERE/name).resolve()
        if relative.is_absolute() or '..' in relative.parts or not p.is_relative_to(HERE) or sha(p)!=digest:raise ValueError('0109 runtime changed: '+name)
    stable=HERE.parents[1]/'final_system_20261029'
    if sha(stable/'SYSTEM_BINDING.json')!=record['inherited_stable_binding_sha256']:raise ValueError('Stable parent binding changed')
    spec=importlib.util.spec_from_file_location('_immutable_parent_integrity',stable/'integrity.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.verify()
    return record
