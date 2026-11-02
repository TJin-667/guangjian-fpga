"""Isolated host candidate; original bit-qualified source remains byte-identical."""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / 'final_board_0109_20261030'
RUNTIME = ORIGINAL / 'runtime'
HOST = ORIGINAL / 'host'
for p in (HOST, RUNTIME, HERE):
    if str(p) not in sys.path: sys.path.insert(0, str(p))

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text('utf-8-sig'))
def write(path, value): Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', 'utf-8')
def need(ok, why):
    if not ok: raise ValueError(why)

def verify():
    receipt = read(HERE / 'CANDIDATE_BINDING.json')
    actual = {p.relative_to(HERE).as_posix() for p in HERE.glob('*.py')} | {p.name for p in HERE.glob('*.cmd')}
    need(actual == set(receipt['program_sha256']), 'Missing or extra candidate program')
    for name, digest in receipt['program_sha256'].items():
        need(sha(HERE / name) == digest, 'Candidate source changed: ' + name)
    for name, digest in receipt.get('dependency_sha256', {}).items():
        need(sha(name) == digest, 'Candidate dependency changed: ' + name)
    for name, digest in read(ORIGINAL / 'SOURCE_BINDING.json')['files_sha256'].items():
        p = (ORIGINAL / name).resolve()
        need(p.is_relative_to(ORIGINAL.resolve()) and sha(p) == digest, 'Qualified0109 source changed: ' + name)
    from integrity import verify as parent_verify
    parent_verify()
    return receipt

def candidate_sources():
    verify()
    return {str(HERE / name): digest for name, digest in read(HERE / 'CANDIDATE_BINDING.json')['program_sha256'].items()} | {str(HERE / 'CANDIDATE_BINDING.json'): sha(HERE / 'CANDIDATE_BINDING.json')}
