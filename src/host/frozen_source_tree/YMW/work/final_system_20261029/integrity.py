"""Verify the new integration layer without modifying frozen source bindings."""
import hashlib,json
from pathlib import Path,PurePosixPath
HERE=Path(__file__).resolve().parent

def verify():
    from export_guard import verify as verify_export
    verify_export()
    return json.loads((HERE/'SYSTEM_BINDING.json').read_text('utf-8'))
