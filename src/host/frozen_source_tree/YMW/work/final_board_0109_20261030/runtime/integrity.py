"""Verify the independent UI and the immutable parent UI; never hardware IO."""
import hashlib,importlib.util,json
from pathlib import Path,PurePosixPath
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify():
    from export_guard import verify as verify_export
    verify_export()
    return json.loads((HERE/'RUNTIME_BINDING.json').read_text('utf-8'))
