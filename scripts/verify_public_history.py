"""Check reachable Git blobs against the same external-content fingerprints."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
from publication_policy import fingerprints

ROOT = Path(__file__).resolve().parents[1]


def git(*arguments, input_bytes=None):
    return subprocess.run(['git', *arguments], cwd=ROOT, input=input_bytes,
                          capture_output=True, check=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--ref', default=None)
    group.add_argument('--all', action='store_true')
    args = parser.parse_args()
    rows, restricted = fingerprints(ROOT)
    revisions = ['--all'] if args.all else [git('rev-parse', '--verify', '--end-of-options', (args.ref or 'HEAD') + '^{commit}').decode().strip()]
    objects = {}
    for line in git('rev-list', '--objects', *revisions).decode('utf-8').splitlines():
        oid, _, path = line.partition(' ')
        objects[oid] = path
    checks = git('cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)',
                 input_bytes=''.join(oid + '\n' for oid in objects).encode())
    sizes = {size for size, _ in restricted}
    candidates = []
    blob_count = 0
    for line in checks.decode().splitlines():
        oid, kind, size = line.split()
        if kind == 'blob':
            blob_count += 1
            if int(size) in sizes:
                candidates.append(oid)
    matches = []
    if candidates:
        process = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=ROOT,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            for oid in candidates:
                process.stdin.write((oid + '\n').encode())
                process.stdin.flush()
                header = process.stdout.readline().decode().split()
                size = int(header[2])
                raw = process.stdout.read(size)
                if len(raw) != size or process.stdout.read(1) != b'\n':
                    raise RuntimeError('Incomplete Git blob')
                digest = hashlib.sha256(raw).hexdigest()
                if (size, digest) in restricted:
                    matches.append(dict(blob=oid, representative_path=objects[oid], sha256=digest))
        finally:
            process.stdin.close()
            process.stdout.close()
            if process.wait() != 0:
                raise RuntimeError('Git content inspection failed')
    result = dict(status='PUBLIC_HISTORY_VERIFIED' if not matches else 'RESTRICTED_CONTENT_IN_HISTORY',
        refs='all local refs' if args.all else args.ref or 'HEAD',
        commits=int(git('rev-list', '--count', *revisions)), git_blobs=blob_count,
        fingerprint_candidates=len(candidates), external_files=len(rows),
        restricted_content_fingerprints=len(restricted), matches=matches,
        scope='Reachable Git blobs only; does not erase GitHub caches, old clones or forks')
    print(json.dumps(result, ensure_ascii=False))
    if matches:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
