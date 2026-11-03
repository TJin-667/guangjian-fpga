"""Content fingerprints for originals kept outside the public distribution."""
from collections import defaultdict
from pathlib import Path
import hashlib
import json
import os

IGNORED_DIRECTORIES = {'.git', '.venv', '_work', '__pycache__'}


def fingerprints(root):
    rows = json.loads((Path(root) / 'external_dependencies.json').read_bytes())['files']
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['bytes'], row['sha256'])].append(row['path'])
    return rows, dict(grouped)


def public_files(root):
    for current, directories, filenames in os.walk(root):
        directories[:] = sorted(d for d in directories if d not in IGNORED_DIRECTORIES)
        for filename in sorted(filenames):
            yield Path(current) / filename


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()
