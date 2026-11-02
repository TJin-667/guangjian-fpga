"""Verify the new integration layer without modifying frozen source bindings."""
import hashlib,json
from pathlib import Path,PurePosixPath
HERE=Path(__file__).resolve().parent

def verify():
    record=json.loads((HERE/'SYSTEM_BINDING.json').read_text('utf-8'))
    if record['schema']!='guangjian-final-system-binding-v1':raise ValueError('Wrong integration binding')
    for name,digest in record['files_sha256'].items():
        relative=PurePosixPath(name);path=(HERE/name).resolve()
        if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(HERE):raise ValueError('Unsafe integration member')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Integration source changed: '+name)
    return record
