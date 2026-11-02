"""File-only helpers; importing this package never contacts a board."""
import hashlib
import json
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def safe_path(root, relative):
    root = Path(root).resolve()
    require(isinstance(relative, str) and relative and '\\' not in relative and ':' not in relative,
            'Unsafe relative path')
    pieces = PurePosixPath(relative)
    require(not pieces.is_absolute() and not any(p in ('..', '.') for p in pieces.parts), 'Unsafe path')
    require('/'.join(pieces.parts) == relative and not any(c in relative for c in '<>"|?*\x00'), 'Noncanonical path')
    target = (root / relative).resolve()
    require(target.is_relative_to(root) and target != root, 'Path escapes package')
    return target


def verify_inventory(folder):
    folder = Path(folder).resolve()
    files = read_json(folder / 'output_manifest.json')['files']
    observed = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    require(observed == set(files) | {'output_manifest.json'}, 'Package inventory differs')
    for name, expected in files.items():
        path = safe_path(folder, name)
        require(not path.is_symlink() and digest(path) == expected, 'Package hash differs: ' + name)
    return files


def seal_folder(folder):
    folder = Path(folder)
    require(not (folder / 'output_manifest.json').exists(), 'Refusing to replace a sealed inventory')
    files = {p.relative_to(folder).as_posix(): digest(p) for p in sorted(folder.rglob('*')) if p.is_file()}
    write_json(folder / 'output_manifest.json', dict(schema=1, files=files))


def extract_zip(archive, target):
    """Strict Windows-safe flat-root archive import. Caller owns a NEW target."""
    archive, target = Path(archive), Path(target)
    require(not target.exists(), 'ZIP extraction destination already exists')
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        require(0 < len(members) <= 20000, 'ZIP member count out of range')
        require(sum(m.file_size for m in members) <= 2 * 1024**3, 'ZIP expands beyond 2 GiB')
        seen = set()
        for m in members:
            require(m.orig_filename == m.filename and '\\' not in m.orig_filename,
                    'Noncanonical raw ZIP member name')
            name = m.filename.rstrip('/')
            safe_path(target, name)
            require(not any(p.endswith((' ', '.')) or re.match(r'(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)', p)
                            for p in PurePosixPath(name).parts), 'Unsafe Windows ZIP name')
            require(name.casefold() not in seen, 'Duplicate ZIP path')
            seen.add(name.casefold())
            require(not stat.S_ISLNK(m.external_attr >> 16) and not m.flag_bits & 1, 'Symlink/encrypted ZIP rejected')
        target.mkdir(parents=True, exist_ok=False)
        for m in members:
            path = safe_path(target, m.filename.rstrip('/'))
            if m.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with z.open(m) as source, path.open('xb') as dest:
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        dest.write(block)
    return target


def verify_vendor():
    manifest = read_json(ROOT / 'vendor_manifest.json')
    for name, sha in manifest['files'].items():
        require(digest(safe_path(ROOT, name)) == sha, 'Frozen XDL source changed: ' + name)
    return manifest
