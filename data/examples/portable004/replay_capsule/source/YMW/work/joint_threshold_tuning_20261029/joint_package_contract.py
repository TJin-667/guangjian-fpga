"""Unambiguous package-verifier import for this experimental directory."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
def verify_package():
    p=HERE/'PACKAGE_BINDING.json';binding=json.loads(p.read_text('utf-8-sig'))
    for name,digest in binding['files_sha256'].items():
        if hashlib.sha256((HERE/name).read_bytes()).hexdigest()!=digest:raise ValueError('Joint experimental package changed: '+name)
    return hashlib.sha256(p.read_bytes()).hexdigest()
