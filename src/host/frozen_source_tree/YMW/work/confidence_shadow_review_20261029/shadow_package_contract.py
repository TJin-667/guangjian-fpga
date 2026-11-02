"""Unique package binding name: never resolve a previous run_one module."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
def verify():
    p=HERE/'PACKAGE_BINDING.json';b=json.loads(p.read_text('utf-8'))
    for name,digest in b['files_sha256'].items():
        if hashlib.sha256((HERE/name).read_bytes()).hexdigest()!=digest:raise ValueError('Confidence reference package changed: '+name)
    return hashlib.sha256(p.read_bytes()).hexdigest()
