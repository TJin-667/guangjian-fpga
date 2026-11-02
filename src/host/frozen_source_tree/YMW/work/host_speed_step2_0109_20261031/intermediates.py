"""Source-bound local handoff of already audited H2/quality arrays.

This is an integrity cache, not a cryptographic attestation. The producer must
be the qualified strict SDK/engineering executor, or an explicitly labelled
offline reconstruction after a full source audit. Never relabel a reconstruction
as a new physical capture. No detector/review or wire protocol is changed.
"""
from export_paths import legacy_location, data_path, lab_root, network
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
STEP1 = HERE.parent / 'host_speed_step1_0109_20261031'
sys.path.insert(0, str(STEP1))
import profile_saved as base
import numpy as np

SCHEMA = 'guangjian-audited-H2-quality-handoff-v1'


def digest(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def bindings(tools):
    base.verify_tool()
    qualified = base.BENCHMARK.parent / 'final_board_0109_20261030'
    for name, sha in base.read(qualified / 'SOURCE_BINDING.json')['files_sha256'].items():
        p = (qualified / name).resolve()
        base.need(p.is_relative_to(qualified.resolve()) and base.sha(p) == sha, 'Qualified source changed')
    tools.algorithm.configuration()
    paths = [Path(__file__).resolve(), HERE / 'reuse_context.py',
             base.BENCHMARK / 'TOOL_BINDING.json',
             base.BENCHMARK.parent / 'final_board_0109_20261030/SOURCE_BINDING.json',
             base.BENCHMARK.parent / 'final_parameter_check_20261030/FROZEN_SOURCES.json']
    paths += [Path(inspect.getfile(fn)).resolve() for fn in (tools.h2, tools.quality, tools.decode, tools.connect)]
    return {str(p): base.sha(p) for p in paths}


def owned(a):
    b = np.array(a, copy=True, order='C')
    b.flags.writeable = False
    return b


def make_native(root, gray, sat, board, words, *, off_acknowledged):
    root = Path(root).resolve()
    source = base.read(root / 'RESULT.json')
    base.need(off_acknowledged and source.get('status') == 'SAME_INPUT_EQUAL'
              and not any(source.get('differences', {'missing': 1}).values()), 'Incomplete engineering/OFF lifecycle')
    base.need(source['schema'] == '0109-engineering-same-input-result-v1' and len(source['frames']) == 8, 'Wrong engineering source')
    roi = source['roi']; h, w = roi[3], roi[2]
    base.need(gray.dtype == np.uint8 and gray.shape == (8, h, w), 'Native eight GRAY8 required')
    base.need(sat.shape == gray.shape and sat.dtype in (np.dtype(bool), np.dtype('uint8')) and not np.any(sat > 1), 'Invalid SAT1')
    base.need(board.dtype == bool and board.shape == (h, w) and board.any(), 'Native board required')
    base.need(words.dtype == np.uint32 and words.shape == board.shape, 'Native R32 required')
    raw_path = root / 'fpga_result.r32'
    base.need(base.sha(raw_path) == source['result_sha256'] and words.tobytes() == raw_path.read_bytes(), 'R32 source differs')
    from device_profiles import validate
    validate(source)
    files = {str(root / 'RESULT.json'): base.sha(root / 'RESULT.json'), str(raw_path): source['result_sha256']}
    frames = []
    for slot, item in enumerate(source['frames'], 1):
        p = Path(item['record']).resolve(); r = base.read(p)
        base.need(item['slot'] == slot and base.sha(p) == item['record_sha256'], 'Record/slot binding differs')
        base.need(r['strict_verified'] and r['status'] == 'COMMITTED' and r['firmware'] == 265, 'Non-strict frame')
        base.need(r['identity'] == item['identity'] == r['diagnostic']['identity'] and r['roi'] == roi, 'Frame identity/ROI differs')
        params = r['actual_parameters']
        base.need(params == r['diagnostic']['parameters'] and params['exposure_lines'] == (source['low_lines'] if slot % 2 else source['high_lines'])
                  and params['gain16'] == 16 and params['brightness'] == 128 and params['light_mask'] == 1 << ((slot - 1) // 2), 'Actual parameters differ')
        base.need(r['evidence_source'] == source['evidence_source'] and r['complete_packets'] == r['expected_packets'] and r['cost']['missing_image_packets'] == 0, 'Mixed/incomplete source')
        files[str(p)] = item['record_sha256']
        for name, sha in r['archived_file_sha256'].items():
            base.need(Path(name).name == name and '/' not in name and '\\' not in name, 'Unsafe source member')
            files[str(p.parent / name)] = sha
        for key in ('SDK_executable_source_sha256', 'loaded_protocol_source_sha256'):
            for name, sha in r.get(key, {}).items():
                base.need(name not in files or files[name] == sha, 'Conflicting SDK binding')
                files[name] = sha
        base.need(gray[slot - 1].tobytes() == (p.parent / 'image.gray8').read_bytes(), 'Gray source differs')
        base.need(np.packbits(sat[slot - 1].reshape(-1), bitorder='big').tobytes() == (p.parent / 'image.sat1').read_bytes(), 'SAT source differs')
        base.need(board.astype(np.uint8).tobytes() == (p.parent / 'board_mask.bin').read_bytes(), 'Board source differs')
        frames.append(dict(slot=slot, record=str(p), record_sha256=item['record_sha256'], identity=r['identity'], parameters=params))
    ids = [r['identity'] for r in frames]
    base.need(len({r['session'] for r in ids}) == 1 and len({(r['session'], r['request_id'], r['frame_id']) for r in ids}) == 8, 'Repeated/mixed identities')
    for name in ('OFF.json', 'SUMMARY.json'):
        p = root.parent / name
        if p.is_file():
            record = base.read(p)
            base.need(record.get('acknowledged') if name == 'OFF.json' else record.get('cleanup', {}).get('acknowledged'), 'OFF receipt differs')
            files[str(p)] = base.sha(p)
    base.need(all(base.sha(p) == sha for p, sha in files.items()), 'Changed verified source')
    contract = dict(root=str(root), group=source['group'], digest128=source['digest128'], roi=roi,
                    low=source['low_lines'], high=source['high_lines'], frames=frames,
                    physical_hardware=source['physical_hardware'], evidence_source=source['evidence_source'])
    arrays = dict(gray=owned(gray), sat1=owned(sat.astype(bool)), board=owned(board), words=owned(words))
    identity = dict(contract=contract, native_sha256={k: digest(v) for k, v in arrays.items()}, files_sha256=files)
    return dict(**arrays, identity=identity, root=root)


def snapshot(native, residual, valid, origin):
    base.need(residual.dtype == np.int16 and residual.shape == native['gray'].shape, 'Exact int16 H2 required')
    base.need(valid.dtype == bool and valid.shape == residual.shape, 'Exact bool quality required')
    return dict(native=native, residual_n=owned(residual), valid=owned(valid), origin=origin)


def from_executor(executor, off_receipt):
    """Call before a warm-group reset discards _off_rows. No H2 recomputation."""
    base.need(off_receipt.get('acknowledged') and executor._off_slot == 8 and not executor._off_group_live
              and not executor._off_failed and executor.extension.group is None, 'Executor not completely released/OFF')
    rows = executor._off_rows
    base.need(len(rows) == 8, 'Eight audited rows required')
    for row in rows:
        cap = row['capture']; r = base.read(cap.record_path); v = cap.validated
        base.need(v['metadata'] == r['diagnostic'] and hashlib.sha256(v['payload']).hexdigest() == r['raw_payload_sha256'], 'Strict SDK return changed')
        base.need(np.array_equal(row['gray'], v['gray']) and v['board_mask_sha256'] == digest(executor._off_board.astype(np.uint8)), 'Executor native planes changed')
    gray = np.stack([r['gray'] for r in rows]); sat = np.stack([r['capture'].validated['sat'] for r in rows])
    native = make_native(executor._off_output, gray, sat, executor._off_board,
                         np.frombuffer((executor._off_output / 'fpga_result.r32').read_bytes(), '<u4').reshape(executor._off_board.shape), off_acknowledged=True)
    base.need(native['identity']['contract']['group'] == executor._off_group
              and native['identity']['contract']['digest128'] == executor._off_digest.hex(), 'Executor group differs')
    return snapshot(native, np.stack([r['residual_n'] for r in rows]), np.stack([r['valid'] for r in rows]),
                    'strict_live_SDK_and_engineering_same_input_audit')


def from_replay(tools, folder):
    """Offline reconstruction of the common capture audit, never a new capture."""
    x = base.load_group(tools, folder)
    base.need(x['measurement']['branch'] == 'PL', 'Actual saved PL result required')
    native = make_native(Path(folder) / 'fusion', x['gray'], x['sat1'], x['board'], x['words'],
                         off_acknowledged=base.read(Path(folder) / 'OFF.json').get('acknowledged'))
    residual = np.stack([tools.h2(g)['residual_n'] for g in x['gray']])
    valid = np.stack([tools.quality(g)['valid_mask'] for g in x['gray']])
    base.need(np.array_equal(tools.pack(x['gray'], residual, valid), x['words']), 'Replay audit and saved PL result differ')
    return snapshot(native, residual, valid, 'offline_reconstruction_of_existing_capture_audit_not_new_board_data')


def native_check(native):
    ident = native['identity']
    base.need(all(digest(native[k]) == sha for k, sha in ident['native_sha256'].items()), 'Native RAM content changed')
    base.need(all(base.sha(p) == sha for p, sha in ident['files_sha256'].items()), 'Verified source changed')


def seal(value, target, tools):
    native = value['native']; target = Path(target).resolve()
    base.need(target.is_relative_to(legacy_location('E:/GuangjianData').resolve()) and not target.exists(), 'New E-drive handoff required')
    base.need(not target.is_relative_to(native['root']) and not native['root'].is_relative_to(target), 'Handoff overlaps source')
    native_check(native)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.pending_' + uuid.uuid4().hex[:8]); temp.mkdir()
    # Uncompressed NPZ avoids a second CPU-intensive compression pass. Quality
    # is bit-packed exactly; this does not quantize signed residuals.
    np.savez(temp / 'intermediates.npz', residual_n=value['residual_n'],
             valid_bits=np.packbits(value['valid'].reshape(-1), bitorder='big'))
    receipt = dict(schema=SCHEMA, status='SEALED', identity=native['identity'], origin=value['origin'],
                   shape=list(value['residual_n'].shape), residual_dtype='int16', bitorder='big',
                   array_sha256=dict(residual_n=digest(value['residual_n']), valid=digest(value['valid'])),
                   producer_bindings=bindings(tools), data_sha256=base.sha(temp / 'intermediates.npz'),
                   security_scope='local_integrity_receipt_not_cryptographic_attestation')
    base.write(temp / 'CACHE.json', receipt)
    os.replace(temp, target)
    return target


def restore(native, target, tools):
    target = Path(target).resolve(); r = base.read(target / 'CACHE.json')
    base.need(r['schema'] == SCHEMA and r['status'] == 'SEALED' and r['bitorder'] == 'big', 'Incomplete handoff')
    base.need(r['identity'] == native['identity'], 'Handoff group/source/ROI/parameters differ')
    base.need(r['producer_bindings'] == bindings(tools), 'Handoff producer/reference source changed')
    native_check(native)
    base.need(base.sha(target / 'intermediates.npz') == r['data_sha256'], 'Handoff data changed')
    shape = native['gray'].shape
    base.need(r['shape'] == list(shape) and r['residual_dtype'] == 'int16', 'Handoff shape/type differs')
    with np.load(target / 'intermediates.npz', allow_pickle=False) as z:
        base.need(set(z.files) == {'residual_n', 'valid_bits'}, 'Unexpected handoff members')
        residual = z['residual_n']; bits = z['valid_bits']
    base.need(residual.dtype == np.int16 and residual.shape == shape and bits.dtype == np.uint8
              and bits.ndim == 1 and bits.size == (int(np.prod(shape)) + 7) // 8, 'Handoff arrays differ')
    valid = np.unpackbits(bits, bitorder='big', count=int(np.prod(shape))).reshape(shape).astype(bool)
    base.need(r['array_sha256'] == dict(residual_n=digest(residual), valid=digest(valid)), 'Handoff array digest differs')
    residual.flags.writeable = valid.flags.writeable = False
    return dict(residual_n=residual, valid=valid, receipt=r, native=native, cache=str(target))
