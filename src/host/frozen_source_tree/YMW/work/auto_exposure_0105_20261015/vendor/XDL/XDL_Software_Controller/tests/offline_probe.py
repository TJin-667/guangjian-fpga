"""Run real replay with a Python audit hook restricting IO to offline result writes."""
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import replay


if __name__ == '__main__':
    args = sys.argv[1:]
    output = Path(args[args.index('--output') + 1]).resolve()
    forbidden, writes = [], []

    def audit(event, values):
        prohibited = event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.startfile')
        if event == 'open' and isinstance(values[0], (str, bytes)):
            name = os.fsdecode(values[0])
            prohibited = prohibited or bool(re.match(r'(?i)^(?:\\\\\.\\|COM\d+(?::|$)|/dev/)', name))
            mode, flags = values[1], values[2]
            writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
            if writing:
                path = Path(name).resolve()
                writes.append(str(path))
                prohibited = prohibited or not path.is_relative_to(output)
        if event in ('os.remove', 'os.rmdir', 'os.mkdir', 'os.rename'):
            targets = values[:2] if event == 'os.rename' else values[:1]
            prohibited = prohibited or any(not Path(p).resolve().is_relative_to(output) for p in targets)
        if prohibited:
            forbidden.append(event)
            raise RuntimeError('offline audit rejected ' + event)

    sys.addaudithook(audit)
    code = replay.main(args)
    print(json.dumps({'audit_scope': 'Python file/device/network/process operations during replay.main',
                      'forbidden_operations': forbidden, 'output_write_count': len(writes),
                      'write_paths': sorted(set(writes))}, allow_nan=False))
    raise SystemExit(code)
