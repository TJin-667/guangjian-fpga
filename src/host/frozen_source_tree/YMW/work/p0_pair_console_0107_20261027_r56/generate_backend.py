"""Reproduce the configurable backend from the pinned preserved r5.5 source."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'p0_pair_console_0107_20261027_r55/capture_backend.py'
def generate():
    proof=json.loads((HERE/'BACKEND_TRANSFORMS.json').read_bytes());raw=SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=proof['source_sha256']:raise ValueError('Pinned r55 backend changed')
    before=raw.decode('utf-8').replace('\r\n','\n');lines=before.splitlines(True)
    for item in reversed(proof['blocks']):
        if ''.join(lines[item['start']:item['end']])!=item['old']:raise ValueError('Backend transform context changed')
        lines[item['start']:item['end']]=item['new'].splitlines(True)
    after=''.join(lines);data=after.encode('utf-8')
    if hashlib.sha256(data).hexdigest()!=proof['generated_sha256']:raise ValueError('Derived backend mismatch')
    meta=dict(source=str(SOURCE),source_sha256=proof['source_sha256'],generated_sha256=proof['generated_sha256'],scope='Validated immutable per-run identity/exposure settings and original strict capture checks')
    return data,meta,before,after
if __name__=='__main__':
    data,meta,_,_=generate();(HERE/'capture_backend.py').write_bytes(data)
    (HERE/'BACKEND_DERIVATION.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
