"""Fixed two-frame engineering transport check, separate from production capture."""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import sdk_transport as sdk
import probe_0106_capabilities as probe
import review_board_handshake as handshake

HERE = Path(__file__).resolve().parent
HANDSHAKE = HERE / 'verification/board_handshake_20261026_01/raw/new_0106_check.json'
ROI = [896, 496, 81, 21]
PARAMETERS = dict(light_mask=1, brightness=128, exposure_lines=600, gain16=16,
                  settle_frames=1, discard_frames=3)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def changed(plan):
    different = []
    for name, digest in plan['source_sha256'].items():
        try:
            equal = sdk.support.sha_file(name) == digest
        except OSError:
            equal = False
        if not equal:
            different.append(name)
    return different


class Runtime:
    evidence_source = 'real_board'
    sensor_size = (1920, 1080)
    roi = ROI
    timeout_s = 45

    def __init__(self):
        self.core = probe.core_module()

    def prepare(self):
        sdk.verify_sources()
        reviewed = handshake.review(HANDSHAKE)
        _, _, bit, _ = probe.preflight()
        require(reviewed['status'] == 'PASS', '0106 handshake is not verified')
        names = [Path(__file__), Path(handshake.__file__), Path(probe.__file__), HANDSHAKE, bit,
                 HERE / 'verification/experimental_bit_01/INDEPENDENT_REVIEW.json']
        return dict(schema='guangjian-engineering-dual-format-plan-v1', evidence_source=self.evidence_source,
                    candidate_binding=dict(candidate_source_commit=sdk.SOURCE_COMMIT,
                        bit_path=str(bit.resolve()), bit_sha256=sdk.support.sha_file(bit)),
                    board='192.168.0.2', bind='192.168.0.3', port=5000,
                    sensor_size=list(self.sensor_size), roi=list(self.roi), parameters=PARAMETERS,
                    pixel_formats=[1, 49], maximum_capture_requests=2,
                    mask_scope='all ones in small diagnostic ROI; not a physical board segmentation/label',
                    training_data=False, same_frozen_input=False, release_ready=False,
                    source_sha256={**sdk.SOURCE_SNAPSHOT, **{str(p):sdk.support.sha_file(p) for p in names}})

    def guard(self):
        return self.core.operator_lock(Path('C:/BX72_0105_LAB'))

    def executor(self, plan, fmt, out):
        return sdk.TransportExecutor(board=plan['board'], bind=plan['bind'], port=plan['port'],
            ymw_root=self.core.load_engine().root / 'ymw', output_root=out,
            pixel_format=fmt, candidate_binding=plan['candidate_binding'], mode='strict',
            evidence_source='real_board', command_timeout=1.5, retries=3)


def audit_capture(result, plan, fmt):
    """Re-open committed files and independently recompute payload CRC and H1/H2."""
    folder = result.record_path.parent
    record = json.loads(result.record_path.read_bytes())
    require(record == result.metadata and record['status'] == 'COMMITTED' and record['strict_verified'],
            'SDK record is not the exact committed result')
    require(record['evidence_source'] == plan['evidence_source'], 'Evidence source changed')
    for name, digest in record['archived_file_sha256'].items():
        require(Path(name).name == name and sdk.support.sha_file(folder / name) == digest,
                'Archived bytes changed: ' + name)
    raw_name = 'image.rgb565' if fmt == 1 else 'image.gray_sat'
    require(record['raw_payload_file'] == raw_name, 'Incorrect raw file/format')
    payload = (folder / raw_name).read_bytes()
    meta = sdk.wire.decode_metadata((folder / 'metadata_packet.bin').read_bytes(), record['metadata_query_seq'])
    require(meta == record['diagnostic'], 'Metadata byte/object mismatch')
    require(meta['valid'] and meta['mask_valid'] and meta['parameters_valid'] and not meta['error'], 'Invalid metadata')
    require(meta['roi'] == plan['roi'] and meta['parameters'] == plan['parameters'] and meta['pixel_format'] == fmt,
            'Actual ROI/parameters/format changed')
    width, height = plan['roi'][2:]
    require(len(payload) == sdk.wire.payload_size(width, height, fmt) == meta['payload_bytes'], 'Payload size mismatch')
    require(sdk.wire.legacy.crc64_ecma(payload) == meta['payload_crc64'], 'Actual payload CRC64 mismatch')
    gray, sat = sdk.wire.planes_from_payload(payload, width, height, fmt)
    mask = np.ones((height, width), dtype=np.bool_)
    require((folder / 'board_mask.bin').read_bytes() == mask.astype(np.uint8).tobytes(), 'Diagnostic mask changed')
    statistics, features = sdk.wire.recompute(gray, sat, mask)
    require(statistics == meta['statistics'] and features == meta['features'], 'Recomputed H1/H2 differ')
    require((folder / 'image.gray8').read_bytes() == gray.tobytes(), 'Saved gray plane differs')
    require((folder / 'image.sat1').read_bytes() == np.packbits(sat.reshape(-1), bitorder='big').tobytes(),
            'Saved SAT plane/tail differs')
    require(payload == result.raw_payload == result.validated['payload'], 'SDK payload changed')
    count = math.ceil(len(payload) / 1380)
    require(record['complete_packets'] == record['expected_packets'] == count, 'Packet count mismatch')
    require(meta['fifo_reads'] == math.prod(plan['sensor_size']), 'Full-frame DDR drain mismatch')
    return dict(pixel_format=fmt, payload_bytes=len(payload), packets=count,
                payload_sha256=sdk.support.sha_bytes(payload), payload_crc64=meta['payload_crc64'],
                identity=meta['identity'], bank=meta['bank'], roi=meta['roi'],
                statistics=statistics, features=features, actual_payload_crc_and_H1_H2_recomputed=True,
                source_record=str(result.record_path))


def execute(out, *, _runtime=None):
    runtime = _runtime or Runtime()
    plan = runtime.prepare()
    require(plan['pixel_formats'] == [1,49] and plan['maximum_capture_requests'] == 2, 'Fixed engineering budget changed')
    out = Path(out).resolve()
    require(not any(p.exists() for p in [out, out.with_name(out.name+'.zip'), out.with_name(out.name+'.zip.sha256'),
                                      out.with_name(out.name+'.zip.receipt.json')]), 'Use a new output/archive directory')
    out.mkdir(parents=True, exist_ok=False)
    sdk.support.write_json(out / 'engineering_plan.json', plan)
    rows, cleanup, failure = [], [], None
    started = time.monotonic_ns()
    try:
        with runtime.guard():
            require(not changed(plan), 'Source/bit/handshake changed before engineering check')
            for fmt in plan['pixel_formats']:
                require(not changed(plan), 'Source changed between formats')
                executor = None
                off = dict(requested=False, acknowledged=False, physical_off_verified=False)
                try:
                    executor = runtime.executor(plan, fmt, out / f'format_{fmt:02x}')
                    require(type(executor) is sdk.TransportExecutor, 'Exact strict0106 SDK required')
                    width, height = plan['roi'][2:]
                    result = executor.acquire(**plan['parameters'], roi=plan['roi'],
                        board_mask=bytes([1]) * (width * height), timeout_s=runtime.timeout_s,
                        sample_id='ENGINEERING_TRANSPORT_NOT_TRAINING', round_id='dual_format_smoke')
                    row = audit_capture(result, plan, fmt)
                    require(result.record_path.resolve().is_relative_to(out / f'format_{fmt:02x}'), 'SDK output escaped')
                    rows.append(row)
                finally:
                    if executor is not None:
                        try:
                            off = executor.lights_off(timeout_s=3)
                        except BaseException as exc:
                            off = dict(requested=True, acknowledged=False, physical_off_verified=False, error=str(exc))
                        finally:
                            try:
                                executor.close()
                            except BaseException as exc:
                                off['close_error'] = str(exc)
                                off['acknowledged'] = False
                        cleanup.append(dict(pixel_format=fmt, **off))
                require(off['acknowledged'], 'OFF not acknowledged; stop before another capture')
            require(rows[0]['identity']['session'] != rows[1]['identity']['session'], 'Distinct executor sessions expected')
    except BaseException as exc:
        failure = dict(type=type(exc).__name__, message=str(exc), code=getattr(exc, 'code', None),
                       needs_reset=getattr(exc, 'needs_reset', None))
    differences = changed(plan)
    ok = failure is None and len(rows) == 2 and not differences
    summary = dict(schema='guangjian-engineering-dual-format-result-v1',
        status='ENGINEERING_TRANSPORT_VERIFIED' if ok else 'FAILED', evidence_source=plan['evidence_source'],
        error=failure, captures_verified=len(rows), rows=rows, cleanup=cleanup, source_changed=differences,
        operator_started_monotonic_ns=started, host_check_elapsed_s=(time.monotonic_ns()-started)/1e9,
        training_data=False, same_frozen_input=False, pixelwise_cross_format_equivalence=False,
        optical_quality_evaluated=False, external_IO_qualified=False, release_ready=False,
        production_gate_modified=False,
        scope='Two new engineering camera frames, each independently CRC/H1/H2 checked; not the same input or fusion data')
    return runtime.core.finalize_output(out, summary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.check_only:
        plan = Runtime().prepare()
        print(json.dumps(dict(status='OFFLINE_PREFLIGHT_PASS', captures_requested=0,
                              roi=plan['roi'], formats=plan['pixel_formats']), indent=2))
    else:
        require(args.out is not None, 'New output directory required')
        result = execute(args.out)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result['summary']['status'] == 'ENGINEERING_TRANSPORT_VERIFIED' else 2)
