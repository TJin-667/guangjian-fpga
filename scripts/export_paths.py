"""Portable locations for the submission copy; never modifies network settings."""
import ipaddress,json,os
from pathlib import Path
PACKAGE_ROOT=Path(__file__).resolve().parents[1]
SOURCE_ROOT=PACKAGE_ROOT/'src/host/frozen_source_tree'
def runtime_config():
    config=json.loads((PACKAGE_ROOT/'configs/runtime.json').read_text(encoding='utf-8'))
    local=PACKAGE_ROOT/'configs/runtime.local.json'
    if local.is_file():
        override=json.loads(local.read_text(encoding='utf-8-sig'))
        if not isinstance(override,dict) or set(override)-{'data_root','network'}:raise ValueError('Unknown local runtime configuration fields')
        if 'data_root' in override:config['data_root']=override['data_root']
        if 'network' in override:
            values=override['network']
            if not isinstance(values,dict) or set(values)-{'board','bind','port'}:raise ValueError('Unknown local network endpoint fields')
            config['network'].update(values)
    if not isinstance(config['data_root'],str) or not config['data_root'].strip():raise ValueError('A nonempty data_root is required')
    for name in ('board','bind'):ipaddress.IPv4Address(config['network'][name])
    port=config['network']['port']
    if type(port) is not int or not 1<=port<=65535:raise ValueError('UDP port must be an integer in1..65535')
    return config
def data_root():
    p=Path(os.environ.get('GUANGJIAN_DATA_ROOT') or runtime_config()['data_root'])
    p=(p if p.is_absolute() else PACKAGE_ROOT/p).resolve()
    protected=[PACKAGE_ROOT/name for name in ('src','scripts','board','provenance','configs','report','data')]
    if p==PACKAGE_ROOT or any(p.is_relative_to(root) for root in protected):raise ValueError('Data outputs must not overwrite packaged inputs')
    return p
def data_path(relative=''):
    p=(data_root()/relative).resolve()
    if not p.is_relative_to(data_root()):raise ValueError('Data path escapes configured root')
    return p
def lab_root():
    p=data_path('operator_lock');p.mkdir(parents=True,exist_ok=True);return p
def repo_path(relative):
    p=(SOURCE_ROOT/relative).resolve()
    if not p.is_relative_to(SOURCE_ROOT):raise ValueError('Source path escapes package')
    return p
def vendor_root():return PACKAGE_ROOT/'src/algorithm/vendor/xdl_b1'
def qualification_path():return PACKAGE_ROOT/'board/artifacts/QUALIFICATION.json'
def network(name):return runtime_config()['network'][name]
def artifact(name):
    names={'bit':'bx72_0109_fusion_EXPERIMENTAL_NOT_RELEASED.bit','bit_build_receipt':'BIT_BUILD_RECEIPT.json','route_verification':'ROUTE_VERIFICATION.json'}
    return PACKAGE_ROOT/'board/artifacts'/names[name]
def legacy_location(value):
    """Resolve an upstream locator inside the export, never through old drives."""
    s=str(value).replace('\\','/').rstrip('/')
    old_repo='C:/bx72_ymw_0105_20261015/repo'
    if s.casefold()==old_repo.casefold():return SOURCE_ROOT
    if s.casefold().startswith(old_repo.casefold()+'/'):return repo_path(s[len(old_repo)+1:])
    if s.casefold()=='c:/bx72_0105_lab':return lab_root()
    if s.endswith('/engineering_bit_01/QUALIFICATION.json'):return qualification_path()
    if s.startswith('E:/GuangjianData'):
        for key in ('bit','bit_build_receipt','route_verification'):
            if s.endswith('/'+artifact(key).name):return artifact(key)
        return data_path(s[len('E:/GuangjianData'):].lstrip('/'))
    raise ValueError('Unsupported upstream location: '+s)
