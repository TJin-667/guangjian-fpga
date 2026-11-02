"""Independent rendered-image/link and old-source audit, outside all timing."""
import argparse
from pathlib import Path
import re
from urllib.parse import unquote
from intermediates import base, HERE, bindings
import numpy as np
from PIL import Image


def audit(study, out):
    base.socket.socket = base.socket.create_connection = base.no_network
    tools = base.Tools(False); bindings(tools)
    result = base.read(study / 'RESULT.json')
    base.need(result['status'] == 'PASS_SOURCE_BOUND_HANDOFF_AND_FULL_EXPORT', 'Incomplete study')
    programs = base.read(study / 'EXECUTED_SOURCES.json')['files_sha256']
    base.need(all(base.sha(HERE / name) == sha for name, sha in programs.items()), 'Executed source differs')
    pairs = links = 0
    for group in result['groups']:
        for repetition in range(1, result['repetitions'] + 1):
            a = study / group['group'] / f'step1_r{repetition}' / 'final'
            b = study / group['group'] / f'reuse_r{repetition}' / 'final'
            files_a = {p.relative_to(a).as_posix() for p in a.rglob('*') if p.is_file()}
            files_b = {p.relative_to(b).as_posix() for p in b.rglob('*') if p.is_file()}
            base.need(files_a == files_b, 'Missing export member')
            for name in files_a:
                if Path(name).suffix.lower() in ('.png', '.jpg', '.jpeg'):
                    with Image.open(a / name) as im: pixels = np.array(im)
                    with Image.open(b / name) as im: base.need(np.array_equal(pixels, np.array(im)), 'Changed image pixels')
                    pairs += 1
            for folder in (a, b):
                for page in folder.rglob('*.html'):
                    for target in re.findall(r'(?:src|href)=[\"\']([^\"\']+)', page.read_text('utf-8'), re.I):
                        if target.startswith(('#', 'https:', 'http:', 'data:', 'javascript:')): continue
                        name = unquote(target.split('#', 1)[0].split('?', 1)[0])
                        if name:
                            base.need((page.parent / name).exists(), 'Broken link: ' + name)
                            links += 1
    out.mkdir(parents=True, exist_ok=False)
    base.write(out / 'AUDIT.json', dict(status='PASS_EXPORT_PIXELS_LINKS_AND_UNCHANGED_QUALIFIED_SOURCES',
               source=str(study), source_result_sha256=base.sha(study / 'RESULT.json'), image_pairs=pairs,
               local_links=links, source_bindings=bindings(tools), hardware_contacted=False, new_CAP=0))
    print(f'PASS: {pairs} image pairs; {links} links', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--study', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); audit(a.study, a.out)
