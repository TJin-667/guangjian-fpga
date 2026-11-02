"""Read-only CPU profile of the existing hybrid continuation; never contacts hardware."""
import os
for _key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_key] = '1'
import argparse
import cProfile
import gzip
import io
from pathlib import Path
import pstats
import socket
import sys
import time

HERE = Path(__file__).resolve().parent
BENCHMARK = HERE.parent / 'system_benchmark_0109_20261031'
sys.path.insert(0, str(BENCHMARK))
from core import Tools, environment, need, read, sha, verify_seal, verify_tool, write
import numpy as np


def no_network(*args, **kwargs):
    raise RuntimeError('Offline host study prohibits network access')


def load_group(tools, folder):
    folder = Path(folder).resolve()
    measurement = read(folder / 'MEASUREMENT.json')
    verify_seal(folder, read(folder / 'OUTPUT_MANIFEST.json')['files_sha256'])
    planes = []; sat = []; board = None
    for slot, record_name in enumerate(measurement['records'], 1):
        p = Path(record_name).resolve()
        need(p.is_relative_to(folder / 'captures'), 'Frame escapes saved group')
        r = read(p)
        files = {}
        for name, digest in r['archived_file_sha256'].items():
            need(Path(name).name == name and '/' not in name and '\\' not in name, 'Unsafe member')
            q = p.parent / name
            need(sha(q) == digest, 'Changed frame member')
            files[name] = q.read_bytes()
        wire = tools.sdk.wire
        meta = wire.decode_metadata(files['metadata_packet.bin'], r['metadata_query_seq'])
        need(meta == r['diagnostic'] and meta['identity'] == r['identity'], 'Metadata identity changed')
        need(r['strict_verified'] and r['status'] == 'COMMITTED' and r['firmware'] == 265, 'Unverified frame')
        need(meta['pixel_format'] == 49 and meta['roi'] == measurement['roi'], 'Wrong native ROI/format')
        params = meta['parameters']
        need(params['exposure_lines'] == (400 if slot % 2 else 800) and params['gain16'] == 16
             and params['brightness'] == 128 and params['light_mask'] == 1 << ((slot - 1) // 2), 'Unexpected observation')
        payload = files[r['raw_payload_file']]
        need(len(payload) == meta['payload_bytes'] and wire.legacy.crc64_ecma(payload) == meta['payload_crc64'], 'Raw CRC differs')
        g, s = wire.planes_from_payload(payload, *measurement['roi'][2:], 49)
        b = np.frombuffer(files['board_mask.bin'], np.uint8).reshape(g.shape)
        need(np.all(b <= 1) and b.any(), 'Invalid mask')
        b = b.astype(bool)
        if board is None:
            board = b
        need(np.array_equal(b, board) and wire.recompute(g, s, b) == (meta['statistics'], meta['features']), 'H1/H2 differs')
        need(g.tobytes() == files['image.gray8'] and np.packbits(s.reshape(-1), bitorder='big').tobytes() == files['image.sat1'], 'Saved planes differ')
        planes.append(g); sat.append(s)
    need(len(planes) == 8, 'Eight actual frames required')
    fusion = folder / 'fusion'
    raw_path = fusion / ('fpga_result.r32' if measurement['branch'] == 'PL' else 'pc_result.r32')
    result = read(fusion / 'RESULT.json')
    need(sha(raw_path) == result['result_sha256'], 'R32 changed')
    for slot, (item, name) in enumerate(zip(result['frames'], measurement['records']), 1):
        r = read(name)
        need(item['slot'] == slot and item['record'] == name and item['record_sha256'] == sha(name)
             and item['identity'] == r['identity'], 'R32 source binding differs')
    return dict(gray=np.stack(planes), sat1=np.stack(sat), board=board,
                words=np.frombuffer(raw_path.read_bytes(), '<u4').reshape(board.shape), measurement=measurement)


def check_result(tools, result, folder):
    arrays, evidence, scored = result
    final = Path(read(Path(folder) / 'MEASUREMENT.json')['final'])
    with np.load(final / 'formal_arrays.npz', allow_pickle=False) as z:
        need(set(z.files) == set(arrays) and all(np.array_equal(z[k], arrays[k]) for k in z.files), 'Formal output changed')
    with gzip.open(final / 'GAP_REVIEWS.json.gz', 'rt', encoding='utf-8') as stream:
        need(evidence == __import__('json').load(stream), 'Full review evidence changed')
    need(tools.algorithm.frozen_runtime.review.score_identity(scored) ==
         tools.algorithm.frozen_runtime.review.score_identity(read(final / 'REVIEW_PRIORITY.json')), 'Scores changed')


def profile(folder, out):
    socket.socket = socket.create_connection = no_network
    verify_tool()
    tools = Tools(False)
    x = load_group(tools, folder)
    out.mkdir(parents=True, exist_ok=False)
    rows = []
    for branch in ('hybrid_original', 'dense_diagnostic'):
        t = time.perf_counter()
        if branch == 'hybrid_original':
            context, _, provider = tools.hybrid(x['gray'], x['sat1'], x['board'], x['words'])
        else:
            context, _, words = tools.dense(x['gray'], x['sat1'], x['board'])
            need(np.array_equal(words, x['words']), 'Diagnostic R32 differs')
            provider = None
        context_seconds = time.perf_counter() - t
        profiler = cProfile.Profile()
        t = time.perf_counter()
        result = profiler.runcall(tools.algorithm.frozen_runtime.process, context)
        compute_seconds = time.perf_counter() - t
        check_result(tools, result, folder)
        profiler.dump_stats(str(out / (branch + '.pstats')))
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(45)
        (out / (branch + '.txt')).write_text(stream.getvalue(), encoding='utf-8')
        row = dict(branch=branch, context_seconds=context_seconds, profiled_compute_seconds=compute_seconds,
                   formal_arrays_review_and_scores_equal=True)
        if provider:
            row.update(computed_tiles=provider.computed_tiles, final_tiles=len(provider.cache),
                       peak_tile_cache_bytes=provider.peak_cache_bytes)
        rows.append(row)
        print(row, flush=True)
    write(out / 'PROFILE.json', dict(source=str(folder), environment=environment(), rows=rows,
          source_manifest_sha256=sha(Path(folder) / 'OUTPUT_MANIFEST.json'), new_CAP=0, hardware_contacted=False,
          scope='cProfile diagnostic overhead included; not an unbiased performance benchmark', system_speedup=None))
    verify_tool()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    profile(a.source, a.out)
