"""Per-request committed image validation, independent of observation count."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np

from .contracts import require, sha, validate_identity


@dataclass(frozen=True)
class Payload:
    record: dict
    png: bytes
    raw: bytes
    receipt: dict  # trusted executor publication snapshot, not taken from record JSON
    execution_mode: str


@lru_cache(maxsize=1)
def reference():
    path = Path(__file__).resolve().parents[2] / 'inspection_console_0105_20261022/vendor/software/ymw_integer_reference.py'
    require(sha(path.read_bytes()) == 'caefc8519c355cc7670cf7fb95986f0cc4fd2885ffb618061dc9899ba84186de', 'FROZEN_REFERENCE_CHANGED')
    spec = importlib.util.spec_from_file_location('_multiobs_integer_reference', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def crc_table():
    values = []
    for b in range(256):
        v = b << 56
        for _ in range(8):
            v = ((v << 1) ^ (0x42F0E1EBA9EA3693 if v & (1 << 63) else 0)) & ((1 << 64) - 1)
        values.append(v)
    return values


def crc64(data):
    value, table = 0, crc_table()
    for b in data:
        value = table[(value >> 56) ^ b] ^ ((value << 8) & ((1 << 64) - 1))
    return value


def pixel_statistics(png, raw, context):
    _, _, w, h = context.roi
    require(type(png) is bytes and type(raw) is bytes and len(raw) == 2 * w * h, 'RAW_LENGTH')
    image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    require(image is not None and image.shape == (h, w, 3), 'PNG_DIMENSIONS')
    words = np.frombuffer(raw, '>u2').reshape(h, w)
    red, green, blue = (words >> 11) & 31, (words >> 5) & 63, words & 31
    decoded = np.stack(((blue << 3) | (blue >> 2), (green << 2) | (green >> 4), (red << 3) | (red >> 2)), axis=2).astype(np.uint8)
    require(np.array_equal(image, decoded), 'PNG_RAW_PIXELS')
    ref = reference()
    gray = ref.integer_gray(image)
    h2 = ref.integer_h2(gray)
    padded = np.pad(gray, 4, mode='reflect').astype(np.uint32)
    direct = np.zeros((h, w), np.uint32)
    for dy in range(9):
        for dx in range(9):
            direct += padded[dy:dy+h, dx:dx+w]
    require(np.array_equal(direct, h2['sum9']), 'H2_DIRECT81')
    board = np.frombuffer(context.mask, np.uint8).reshape(h, w).astype(bool)
    maximum = (image == 255).any(axis=2)
    stats = dict(pixel_count=w*h, gray_sum=int(gray.sum()), near_black=int((gray <= 5).sum()),
                 near_white=int((gray >= 250).sum()), rgb_any_max=int(maximum.sum()),
                 board_count=int(board.sum()), board_gray_sum=int(gray[board].sum()),
                 board_dark=int((gray[board] <= 10).sum()), board_white=int((gray[board] >= 250).sum()),
                 board_rgb_any_max=int(maximum[board].sum()))
    absolute = np.abs(h2['residual_n'].astype(np.int32))
    features = dict(strong_count=int((absolute > 1620).sum()), weak_count=int((absolute > 648).sum()),
                    sum9_total=int(h2['sum9'].sum(dtype=np.uint64)), residual_n_total=int(h2['residual_n'].sum(dtype=np.int64)))
    return stats, features


def validate_payload(payload, request, context, profile):
    """The caller separately tracks all observed receipts, including rejected images."""
    r, receipt = payload.record, payload.receipt
    validate_identity(receipt)
    require(payload.execution_mode in ('sdk_adapter', 'software_fake', 'archive_replay'), 'EXECUTION_MODE')
    expected_evidence = {'sdk_adapter': {'real_board', 'software_udp_peer', 'RTL_packet_replay'},
                         'software_fake': {'software_fake'}, 'archive_replay': {'real_board', 'software_udp_peer', 'RTL_packet_replay'}}
    require(r.get('evidence_source') in expected_evidence[payload.execution_mode], 'EVIDENCE_LABEL')
    expected = request.parameters(profile)
    for parameters in (r.get('actual_parameters'), r.get('diagnostic', {}).get('parameters')):
        require(type(parameters) is dict and set(parameters) == set(expected)
                and all(type(v) is int for v in parameters.values()), 'PARAMETER_TYPES')
    requested = r.get('requested')
    require(type(requested) is dict and set(requested) == set(expected) | {'roi'}
            and all(type(requested[k]) is int for k in expected), 'REQUEST_TYPES')
    require(r.get('status') == 'COMMITTED' and r.get('strict_verified') is True and r.get('mode') == 'strict', 'NOT_COMMITTED_STRICT')
    require(r.get('firmware') == 0x0105 and r.get('sample_id') == context.sample_id and r.get('roi') == list(context.roi), 'SAMPLE_ROI_FIRMWARE')
    require(r.get('identity') == receipt and r.get('session') == receipt['session']
            and r.get('expected_request_id') == receipt['request_id'] and r.get('wire_frame_id') == receipt['frame_id']
            and r.get('frame_id') == receipt['frame_id'] and r.get('roi_generation') == receipt['roi_generation'], 'REQUEST_RECEIPT_MISMATCH')
    require(r.get('actual_parameters') == expected and r.get('requested') == dict(expected, roi=list(context.roi)), 'PARAMETER_BINDING')
    require(r.get('mask_sha256') == context.mask_sha256, 'MASK_BINDING')
    d, camera = r.get('diagnostic', {}), r.get('camera_readback', {})
    require(d.get('identity') == receipt and d.get('parameters') == expected and d.get('roi') == list(context.roi)
            and d.get('firmware') == 0x0105 and d.get('request_counter') == receipt['request_id'], 'DIAGNOSTIC_BINDING')
    require(all(d.get(k) is True for k in ('valid', 'bound', 'parameters_valid', 'mask_valid', 'logical_association_available'))
            and type(d.get('error')) is int and d['error'] == 0 and d.get('bank') in (0, 1) and r.get('bank') == d['bank'], 'DIAGNOSTIC_INVALID')
    regs = camera.get('raw_registers', {})
    required_regs = ('0x3503', '0x3500', '0x3501', '0x3502', '0x350A', '0x350B')
    require(all(type(regs.get(k)) is int and 0 <= regs[k] <= 255 for k in required_regs), 'CAMERA_REGISTER_SCHEMA')
    exposure_raw = ((regs['0x3500'] & 15) << 16) | (regs['0x3501'] << 8) | regs['0x3502']
    gain = ((regs['0x350A'] & 3) << 8) | regs['0x350B']
    require(camera.get('locked') is True and camera.get('error') == 0 and camera.get('mode') == regs['0x3503'] == 3,
            'CAMERA_MODE')
    require(camera.get('generation') == receipt['camera_generation']
            and camera.get('exposure_raw') == exposure_raw == 16 * request.exposure_lines
            and camera.get('exposure_lines') == request.exposure_lines and camera.get('gain16') == gain == request.gain16, 'CAMERA_READBACK')
    for name in ('settle', 'discard'):
        expected_count = expected[name + '_frames']
        require(r.get('device_reported_' + name + '_frames') == d.get('wait_complete_frames' if name == 'settle' else 'discard_complete_frames') == expected_count,
                'WAIT_DISCARD')
    require(type(payload.png) is bytes and type(payload.raw) is bytes, 'IMAGE_BYTES')
    require(sha(payload.png) == r.get('png_sha256') and sha(payload.raw) == r.get('raw_rgb565_sha256'), 'IMAGE_HASH')
    packets = (2 * context.roi[2] * context.roi[3] + 1379) // 1380
    require(r.get('complete_packets') == r.get('expected_packets') == packets, 'PACKET_COUNT')
    require(crc64(payload.raw) == r.get('crc64') == d.get('rgb_crc64'), 'IMAGE_CRC64')
    stats, features = pixel_statistics(payload.png, payload.raw, context)
    for values, expected_values in ((r.get('statistics'), stats), (d.get('statistics'), stats),
                                   (r.get('features'), features), (d.get('features'), features)):
        require(type(values) is dict and set(values) == set(expected_values)
                and all(type(v) is int for v in values.values()), 'STATISTICS_TYPES')
    require(stats == r.get('statistics') == d.get('statistics'), 'H1_MISMATCH')
    require(features == r.get('features') == d.get('features'), 'H2_MISMATCH')
    require(isinstance(r.get('call_id'), str) and len(r['call_id']) > 0, 'CALL_ID')
    # JSON round-trip also rejects non-JSON or nonfinite costs before journalling.
    try:
        require(type(r.get('cost', {})) is dict, 'COST_SCHEMA')
        json.dumps(r.get('cost', {}), allow_nan=False)
    except (ValueError, TypeError) as exc:
        from .contracts import ContractError
        raise ContractError('COST_SCHEMA') from exc
    return dict(png_raw_pixels_equal=True, crc64_equal=True, H1_equal=True, H2_direct81_equal=True)
