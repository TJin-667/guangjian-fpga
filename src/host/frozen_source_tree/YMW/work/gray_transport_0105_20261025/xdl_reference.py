"""Load unchanged, Git-blob-pinned XDL interfaces for offline integration only."""
import hashlib,importlib,json,sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE/'integration_refs/xdl_a47a'
EXPECTED={
    '__init__.py':'9ad42f5a80c47d3bc51f2e5e5c84b2d3a2a76100',
    'models.py':'e095a79a53364e1a0ebc8ae63750ed4afc6fbaa8',
    'provenance.py':'56b7bc291f7ad525e354cdd33ca86cfe67d73bc7',
    'features.py':'23148f5a843b4652dccdf4a59c2ec2a26609b424',
    'fusion.py':'1ce9880f6696841a0fafcca09b204680297edc8e',
    'run.py':'74b43f419b9361f453ef8cd0a15ecad0d737773e',
}

def verify():
    rows=json.loads((ROOT/'SNAPSHOT.json').read_bytes())
    if rows['source_commit']!='a47aaf7fda815a61c88f6a398c9d34f41a5c8782':raise ValueError('XDL snapshot changed')
    if {row['path']:row['git_blob_sha'] for row in rows['files']}!={'exposure_fusion_v1/'+k:v for k,v in EXPECTED.items()}:
        raise ValueError('XDL pinned source inventory changed')
    for row in rows['files']:
        p=ROOT/row['path'];data=p.read_bytes()
        actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if actual!=row['git_blob_sha']:raise ValueError('Changed pinned XDL source: '+str(p))
    return rows

def load(name):
    if name not in ('models','provenance','features','fusion','run'):raise ValueError('Unsupported XDL interface')
    verify()
    for path in [ROOT,HERE.parent/'inspection_console_0105_20261022/vendor']:
        if str(path) not in sys.path:sys.path.insert(0,str(path))
    module=importlib.import_module('exposure_fusion_v1.'+name)
    # A training process may already have imported the same exact XDL version
    # from its normal checkout. Reuse its classes instead of loading a second
    # incompatible ObservationGroup class merely because the paths differ.
    for key,loaded in list(sys.modules.items()):
        part='__init__.py' if key=='exposure_fusion_v1' else key.removeprefix('exposure_fusion_v1.')+'.py'
        if not key.startswith('exposure_fusion_v1') or part not in EXPECTED:continue
        data=Path(loaded.__file__).read_bytes()
        actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if actual!=EXPECTED[part]:raise ValueError('Loaded XDL interface differs from pinned source: '+key)
    if name in ('features','fusion','run'):
        ref=importlib.import_module('software.ymw_integer_reference')
        if hashlib.sha256(Path(ref.__file__).read_bytes()).hexdigest()!='caefc8519c355cc7670cf7fb95986f0cc4fd2885ffb618061dc9899ba84186de':
            raise ValueError('Changed integer reference')
    return module
