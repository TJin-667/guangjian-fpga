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
    from export_guard import verify as verify_export
    verify_export()
    receipt=read(HERE/'CANDIDATE_BINDING.json')
    receipt['submission_export']='v1.0.0-rc.1 portability-only derivatives'
    return receipt


def candidate_sources():
    from export_guard import candidate_sources as export_sources
    return export_sources()
