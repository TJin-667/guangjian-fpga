"""Real XSim H1/H2 against pinned XDL NPZs, not regenerated TJ goldens.

Preparation is read-only for peer inputs. Each simulation uses a separate work
directory, exact vector hashes, per-case receipts and a positive pass sentinel.
"""
import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from reference import gray_rgb565, expand_rgb565

ROOT = Path(__file__).resolve().parents[1]
XDL_COMMIT = '8e7dec0daaedb0f08ef80b707c83ba37de7e7002'
YMW_COMMIT = 'de18e3b604158c1b53b87b08f22ddc59ed52cfe2'
DATA_COMMIT = '7ccb753ffacff752a5cd65d4b3a13ff7be9875c6'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def safe_child(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'path escapes input root: {name}')
    return path


def stats(gray, mask, rgbmax):
    b = mask.astype(bool)
    return [int(gray.size), int(gray.sum(dtype=np.uint64)), int((gray <= 5).sum()),
            int((gray >= 250).sum()), int(rgbmax.sum()), int(b.sum()),
            int(gray[b].sum(dtype=np.uint64)), int((gray[b] <= 10).sum()),
            int((gray[b] >= 250).sum()), int(rgbmax[b].sum())]


def write_case(work, cases, name, words, arrays, expected=None, source=None,
               roi=None, mode=0, error=0, h2=True):
    h, w = words.shape
    roi = list(roi or (0, 0, w, h))
    x, y, rw, rh = roi
    gray, mask, rgbmax = (arrays[k] for k in ('gray', 'board_mask', 'rgb_any_max'))
    if expected is None:
        expected = stats(gray[y:y+rh, x:x+rw], mask[y:y+rh, x:x+rw], rgbmax[y:y+rh, x:x+rw])
    number = len(cases)
    stem = f'{number:03d}_{name}'
    # Reference gray/mask are carried independently of the RGB565 DUT input.
    vector = words.astype(np.uint32) | (gray.astype(np.uint32) << 16) | (mask.astype(np.uint32) << 24)
    np.savetxt(work/'h1'/(stem+'.mem'), vector.ravel(), fmt='%07x')
    c = dict(name=name, width=w, height=h, roi=roi, mode=mode, error=error,
             expected_statistics=expected, source=source, input=stem+'.mem', h2=h2)
    c['h1_vector_sha256'] = sha(work/'h1'/c['input'])
    if h2:
        np.savetxt(work/'h2'/(stem+'.mem'), words.ravel(), fmt='%04x')
        g = arrays['gray'].astype(np.uint64)
        s = arrays['sum9'].astype(np.uint64)
        n = arrays['residual_n'].astype(np.uint16).astype(np.uint64)
        np.savetxt(work/'h2'/(stem+'.gold'), (g | (s << 8) | (n << 23)).ravel(), fmt='%010x')
        c['h2_vector_sha256'] = sha(work/'h2'/c['input'])
        c['golden'] = stem+'.gold'
        c['golden_sha256'] = sha(work/'h2'/c['golden'])
        c['threshold'] = 8 if number % 2 else 20
    cases.append(c)


def synthetic_arrays(words, mask):
    gray = gray_rgb565(words)
    summed = cv2.boxFilter(gray, cv2.CV_32S, (9, 9), normalize=False, borderType=cv2.BORDER_REFLECT_101)
    return dict(gray=gray, sum9=summed.astype('<u2'),
                residual_n=(81*gray.astype(np.int32)-summed).astype('<i2'),
                board_mask=mask.astype(np.uint8), rgb_any_max=np.any(expand_rgb565(words)==255, axis=2).astype(np.uint8))


def prepare(a):
    a.work.mkdir(parents=True, exist_ok=False)
    for suite in ('h1', 'h2'):
        (a.work/suite).mkdir()
    cases = []
    rng = np.random.default_rng(20261013)
    words = rng.integers(0, 65536, (17, 23), dtype=np.uint16)
    # Include only one channel at max: e.g. saturated red is gray~76, not near white.
    words[0, :6] = [0, 65535, 0xf800, 0x07e0, 0x001f, 0xf81f]
    checker = (np.indices(words.shape).sum(axis=0) % 2).astype(np.uint8)
    for name, mask in [('checker', checker), ('empty', np.zeros_like(checker)), ('all', np.ones_like(checker))]:
        write_case(a.work, cases, name, words, synthetic_arrays(words, mask))
    values = np.arange(65536, dtype=np.uint16).reshape(256, 256)
    write_case(a.work, cases, 'all_rgb565', values, synthetic_arrays(values, (values%3==0)))
    write_case(a.work, cases, 'offset_output_roi', words, synthetic_arrays(words, checker), roi=(3, 2, 11, 9), h2=False)
    for mode, error, name in [(1, 1, 'empty_roi'), (2, 2, 'early_eof'), (3, 3, 'abort'), (4, 0, 'reset')]:
        write_case(a.work, cases, name, words, synthetic_arrays(words, checker),
                   roi=(0, 0, 0 if mode==1 else 23, 17), mode=mode, error=error, h2=False)
        write_case(a.work, cases, 'recover_'+name, words, synthetic_arrays(words, checker), h2=False)
    peer = None
    if not a.synthetic_only:
        if a.reference_root is None or a.dataset_root is None:
            raise ValueError('--reference-root and --dataset-root required for real frames')
        manifest_path = a.reference_root/'references/reference_manifest.json'
        m = json.loads(manifest_path.read_text(encoding='utf-8'))
        if m['data_commit'] != DATA_COMMIT or len(m['frames']) != 60 or m['dataset_revision'] != 2:
            raise ValueError('unexpected peer data identity')
        peer = dict(xdl_commit=XDL_COMMIT, ymw_commit=YMW_COMMIT, data_commit=m['data_commit'],
                    detector_commit=m['detector_commit'], manifest_sha256=sha(manifest_path))
        for frame in m['frames']:
            npz = safe_child(a.reference_root/'references', frame['path'])
            if sha(npz) != frame['sha256']:
                raise ValueError(f'NPZ hash mismatch: {npz}')
            with np.load(npz, allow_pickle=False) as archive:
                arrays = {k: archive[k] for k in archive.files}
            for k, meta in frame['arrays'].items():
                arr = arrays[k]
                if (arr.dtype.str != meta['dtype'] or list(arr.shape) != meta['shape'] or
                    hashlib.sha256(arr.tobytes(order='C')).hexdigest() != meta['sha256_c_order']):
                    raise ValueError(f'array integrity: {npz} {k}')
            png = safe_child(a.dataset_root, frame['input_png'])
            if sha(png) != frame['input_png_sha256']:
                raise ValueError(f'PNG hash mismatch: {png}')
            raw = png.with_suffix('.rgb565')
            words = np.fromfile(raw, dtype='>u2').reshape(frame['saved_height'], frame['saved_width'])
            image = cv2.imdecode(np.fromfile(png, dtype=np.uint8), cv2.IMREAD_COLOR)
            if not np.array_equal(expand_rgb565(words)[..., ::-1], image):
                raise ValueError(f'PNG/RGB565 differ: {raw}')
            if not np.array_equal(gray_rgb565(words), arrays['gray']):
                raise ValueError('gray decode differs before RTL')
            sf, b = frame['saved_frame_integer_statistics'], frame['board_integer_statistics']
            expected = [sf[k] for k in ('pixel_count', 'gray_sum', 'near_black_le5_count', 'near_white_ge250_count', 'rgb_any_max_count')]
            expected += [b[k] for k in ('pixel_count', 'gray_sum', 'gray_le10_count', 'gray_ge250_count', 'rgb_any_max_count')]
            if stats(arrays['gray'], arrays['board_mask'], arrays['rgb_any_max']) != expected:
                raise ValueError('XDL arrays disagree with XDL statistics')
            source = dict(group_id=frame['group_id'], channel=frame['channel'], npz_sha256=frame['sha256'],
                          rgb565_sha256=sha(raw), input_png=frame['input_png'], png_sha256=sha(png),
                          roi_x=frame['roi_x'], roi_y=frame['roi_y'])
            write_case(a.work, cases, frame['group_id']+'_'+frame['channel'], words, arrays, expected, source)
            print('PREPARED', cases[-1]['name'], flush=True)
    with (a.work/'h1/h1_board_cases.txt').open('w', encoding='ascii', newline='\n') as f:
        for c in cases:
            f.write(' '.join(map(str, [c['input'], c['width'], c['height'], *c['roi'], c['mode'], c['error'], *c['expected_statistics']]))+'\n')
    with (a.work/'h2/h2_cases.txt').open('w', encoding='ascii', newline='\n') as f:
        for c in cases:
            if c['h2']:
                f.write(' '.join(map(str, [c['input'], c['golden'], c['width'], c['height'], 0, 0, c['width'], c['height'], c['threshold'], 0, 0, 1]))+'\n')
    dump(a.work/'cases.json', dict(peer=peer, cases=cases, generator_sha256=sha(Path(__file__)),
         case_lists_sha256={s:sha(a.work/s/f'{"h1_board" if s=="h1" else "h2"}_cases.txt') for s in ('h1','h2')}))
    print('PREPARATION_PASS', len(cases), flush=True)


def run(a):
    data = json.loads((a.work/'cases.json').read_text(encoding='utf-8'))
    suite = a.suite
    work = a.work/suite
    cases = [c for c in data['cases'] if suite=='h1' or c['h2']]
    top = 'tb_h1_board' if suite=='h1' else 'tb_h2'
    core = 'roi_h1_stream' if suite=='h1' else 'h2_background9'
    receipt_file = 'h1_board_receipt.csv' if suite=='h1' else 'h2_receipt.csv'
    sentinel = 'H1_BOARD_ALL_CASES_PASS' if suite=='h1' else 'H2_ALL_CASES_PASS'
    case_file = work/f'{"h1_board" if suite=="h1" else "h2"}_cases.txt'
    if sha(case_file) != data['case_lists_sha256'][suite]:
        raise ValueError('case list changed')
    for c in cases:
        if sha(work/c['input']) != c[suite+'_vector_sha256']:
            raise ValueError('input vector changed')
        if suite=='h2' and sha(work/c['golden']) != c['golden_sha256']:
            raise ValueError('golden vector changed')
    sources = [ROOT/'rtl/rgb565_gray.v', ROOT/f'rtl/{core}.v', ROOT/f'sim/{top}.sv']
    source_hashes = {p.relative_to(ROOT).as_posix():sha(p) for p in sources}
    commands = [['xvlog.bat','-sv',*map(str,sources)], ['xelab.bat',top,'-s','xdl_reference_sim'],
                ['xsim.bat','xdl_reference_sim','-runall']]
    start = time.monotonic()
    for n, command in enumerate(commands):
        command[0] = str(a.vivado_bin/command[0])
        print('RUN', suite, command[0], flush=True)
        with (work/f'{n}_tool.log').open('w', encoding='utf-8') as log:
            p = subprocess.run(command, cwd=work, stdout=log, stderr=subprocess.STDOUT)
        output = (work/f'{n}_tool.log').read_text(encoding='utf-8', errors='replace')
        if p.returncode or 'ERROR:' in output or 'Fatal:' in output:
            raise RuntimeError(output[-9000:])
    if f'{sentinel} {len(cases)}' not in output:
        raise ValueError('pass sentinel missing')
    with (work/receipt_file).open(newline='') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != len(cases):
        raise ValueError('receipt count mismatch')
    keys = ['pixel_count','gray_sum','near_black','near_white','rgb_any_max','board_count','board_gray_sum','board_dark','board_white','board_rgb_any_max']
    for index, (c, r) in enumerate(zip(cases, rows), 1):
        if int(r['case_index']) != index:
            raise ValueError('receipt order mismatch')
        expected_error = 'reset' if suite=='h1' and c['mode']==4 else str(c['error'])
        if r['error'] != expected_error:
            raise ValueError('receipt error mismatch')
        if expected_error=='0':
            if int(r['output_pixels']) != c['roi'][2]*c['roi'][3]:
                raise ValueError('pixel count mismatch')
            if suite=='h1' and [int(r[k]) for k in keys] != c['expected_statistics']:
                raise ValueError('statistics receipt mismatch')
            if suite=='h2' and int(r['memory_reads']) != (c['width']+8)*(c['height']+8):
                raise ValueError('memory read count mismatch')
    if any(sha(p) != source_hashes[p.relative_to(ROOT).as_posix()] for p in sources):
        raise ValueError('source changed during simulation')
    real = [c for c in cases if c['source']]
    report = dict(status='PASS', suite=suite, peer=data['peer'], real_frames=len(real),
                  real_pixels_compared=sum(c['width']*c['height'] for c in real),
                  synthetic_cases=len(cases)-len(real), source_sha256=source_hashes,
                  generator_sha256=data['generator_sha256'], runner_sha256=sha(Path(__file__)),
                  cases_sha256=sha(a.work/'cases.json'), receipt_sha256=sha(work/receipt_file),
                  tool_bin=str(a.vivado_bin), python=sys.version, numpy=np.__version__, opencv=cv2.__version__,
                  wall_seconds=round(time.monotonic()-start,3), hardware_tested=False,
                  ddr_adapter_integrated=False, controller_implemented=False,
                  cases=[dict(name=c['name'], source=c['source'], rtl=r) for c,r in zip(cases,rows)])
    dump(work/'verification.json', report)
    print(json.dumps({k:v for k,v in report.items() if k!='cases'}, indent=2), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work', required=True, type=Path)
    ap.add_argument('--prepare', action='store_true')
    ap.add_argument('--synthetic-only', action='store_true')
    ap.add_argument('--dataset-root', type=Path)
    ap.add_argument('--reference-root', type=Path)
    ap.add_argument('--suite', choices=['h1','h2'])
    ap.add_argument('--vivado-bin', type=Path)
    a = ap.parse_args()
    a.work = a.work.resolve()
    if a.prepare:
        prepare(a)
    if a.suite:
        if a.vivado_bin is None:
            ap.error('--vivado-bin required for --suite')
        run(a)
    if not a.prepare and not a.suite:
        ap.error('select --prepare and/or --suite')


if __name__ == '__main__':
    main()
