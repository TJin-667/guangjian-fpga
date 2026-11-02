"""Check existing installation against the received archive, without importing it."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    entries = json.loads(args.snapshot.read_text(encoding='utf-8-sig'))['critical_files']
    results = []
    for e in entries:
        path = Path(e['local_path'])
        present = path.is_file()
        raw = path.read_bytes() if present else b''
        results.append(dict(path=str(path), exists=present,
                            unchanged=present and len(raw) == e['bytes'] and hashlib.sha256(raw).hexdigest() == e['sha256']))
    repo = Path(__file__).resolve().parents[3]
    tracked_changes = subprocess.check_output(['git', '-C', str(repo), 'diff', '--name-only', 'HEAD'], text=True, encoding='utf-8').splitlines()
    report = dict(critical_files=results, unchanged=sum(r['unchanged'] for r in results), total=len(results),
                  tracked_changes=tracked_changes, passed=all(r['unchanged'] for r in results) and not tracked_changes,
                  board_contacted=False)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(dict(unchanged=report['unchanged'], total=report['total'], tracked_changes=tracked_changes, passed=report['passed'])))
    raise SystemExit(0 if report['passed'] else 1)
