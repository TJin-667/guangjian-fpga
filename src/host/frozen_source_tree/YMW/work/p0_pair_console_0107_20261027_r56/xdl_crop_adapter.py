"""Standalone cropped-source reader using the unchanged XDL model interfaces."""
import argparse
import hashlib
import importlib
import importlib.util
import json
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
EXPECTED={'__init__.py':'9ad42f5a80c47d3bc51f2e5e5c84b2d3a2a76100','models.py':'e095a79a53364e1a0ebc8ae63750ed4afc6fbaa8',
    'provenance.py':'56b7bc291f7ad525e354cdd33ca86cfe67d73bc7','features.py':'23148f5a843b4652dccdf4a59c2ec2a26609b424',
    'fusion.py':'1ce9880f6696841a0fafcca09b204680297edc8e','run.py':'74b43f419b9361f453ef8cd0a15ecad0d737773e'}
def blob(path):
    data=path.read_bytes();return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
def load(xdl_root=None):
    repo=HERE.parents[2]
    choices=[Path(xdl_root)] if xdl_root else [repo/'XDL',HERE.parent/'gray_transport_0105_20261025/integration_refs/xdl_a47a']
    package_root=next((p for p in choices if (p/'exposure_fusion_v1/run.py').exists()),None)
    if package_root is None:raise ValueError('XDL package not found; specify --xdl-root')
    for name,digest in EXPECTED.items():
        if blob(package_root/'exposure_fusion_v1'/name)!=digest:raise ValueError('XDL interface differs; review crop adapter compatibility: '+name)
    for path in [package_root,HERE.parent/'inspection_console_0105_20261022/vendor']:
        if path.exists() and str(path) not in sys.path:sys.path.insert(0,str(path))
    package=importlib.import_module('exposure_fusion_v1')
    for name,digest in EXPECTED.items():
        key='exposure_fusion_v1' if name=='__init__.py' else 'exposure_fusion_v1.'+name[:-3]
        loaded=sys.modules.get(key)
        if loaded is not None and blob(Path(loaded.__file__))!=digest:raise ValueError('Loaded XDL module differs: '+key)
    reference=importlib.import_module('software.ymw_integer_reference')
    if hashlib.sha256(Path(reference.__file__).read_bytes()).hexdigest()!='caefc8519c355cc7670cf7fb95986f0cc4fd2885ffb618061dc9899ba84186de':raise ValueError('Integer detector reference differs')
    source=HERE/'xdl_crop_runner.py';proof=json.loads((HERE/'XDL_CROP_DERIVATION.json').read_bytes())
    if hashlib.sha256(source.read_bytes()).hexdigest()!=proof['derived_sha256']:raise ValueError('Cropped-source adapter changed')
    key='_guangjian_xdl_crop_'+proof['derived_sha256'][:12]
    if key not in sys.modules:
        spec=importlib.util.spec_from_file_location(key,source);module=importlib.util.module_from_spec(spec);module.__package__='exposure_fusion_v1'
        sys.modules[key]=module;spec.loader.exec_module(module)
    return sys.modules[key]

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--xdl-root',type=Path)
    args=parser.parse_args();raise SystemExit(load(args.xdl_root).run_manifest(args.manifest,args.out))
