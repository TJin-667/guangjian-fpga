"""Read-only second check of rendered pixels, links and immutable source bindings."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import profile_saved as base
import numpy as np
from PIL import Image


def main(study, out):
    base.socket.socket = base.socket.create_connection = base.no_network
    base.verify_tool()
    result = base.read(study / 'RESULT.json')
    base.need(result['status'] == 'PASS_PAIRED_EXACT_HOST_STUDY' and result['full_export'], 'Incomplete full-export study')
    binding = base.read(study / 'EXECUTED_SOURCES.json')['files_sha256']
    base.need(all(base.sha(HERE / name) == digest for name, digest in binding.items()), 'Executed study source changed')
    root = HERE.parent / 'final_board_0109_20261030'
    immutable = base.read(root / 'SOURCE_BINDING.json')['files_sha256']
    base.need(all(base.sha(root / name) == digest for name, digest in immutable.items()), 'Qualified0109 source changed')
    image_pairs = links = 0
    for group in result['groups']:
        name = group['group']
        for repetition in range(1, result['repetitions'] + 1):
            a = study / name / f'original_r{repetition}'
            b = study / name / f'planned_r{repetition}'
            files_a = {p.relative_to(a).as_posix() for p in a.rglob('*') if p.is_file()}
            files_b = {p.relative_to(b).as_posix() for p in b.rglob('*') if p.is_file()}
            base.need(files_a == files_b, 'Missing export member')
            for relative in sorted(files_a):
                if Path(relative).suffix.lower() in ('.png', '.jpg', '.jpeg'):
                    with Image.open(a / relative) as im:
                        pixels = np.array(im)
                    with Image.open(b / relative) as im:
                        base.need(np.array_equal(pixels, np.array(im)), 'Rendered pixels changed: ' + relative)
                    image_pairs += 1
            for parent in (a, b):
                for page in parent.rglob('*.html'):
                    for target in re.findall(r'(?:src|href)=[\"\']([^\"\']+)', page.read_text('utf-8'), re.I):
                        if target.startswith(('#', 'https:', 'http:', 'data:', 'javascript:')):
                            continue
                        raw = unquote(target.split('#', 1)[0].split('?', 1)[0])
                        if not raw:
                            continue
                        base.need((page.parent / raw).exists(), 'Broken exported link: ' + str(page) + ' -> ' + raw)
                        links += 1
    out.mkdir(parents=True, exist_ok=False)
    base.write(out / 'AUDIT.json', dict(status='PASS_EXPORT_PIXELS_LINKS_AND_IMMUTABLE_SOURCES', image_pairs=image_pairs,
               existing_local_links=links, qualified_source_members=len(immutable), executed_sources=binding,
               source_study=str(study), source_result_sha256=base.sha(study / 'RESULT.json'),
               new_CAP=0, hardware_contacted=False, production_entry_changed=False))
    print(f'PASS: {image_pairs} image pairs, {links} links, {len(immutable)} immutable source members', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--study', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    main(a.study, a.out)
