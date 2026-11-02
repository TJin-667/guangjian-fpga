"""Read-only four-light inference. Run in a separate process from controller imports."""
import argparse
import csv
import sys
import time
from pathlib import Path
import cv2
import numpy as np
from common import ROOT, digest, read_json, write_json, require, safe_path, verify_inventory, verify_vendor


def engine():
    verify_vendor()
    sys.path.insert(0, str(ROOT / 'vendor/fourlight_fusion'))
    import fusion
    import inputs
    return fusion, inputs


def load_group(root, allow_peer=False):
    """Generic strict adapter; no sample IDs, references or candidate locations are inputs."""
    root = Path(root).resolve()
    files = verify_inventory(root)
    plan, frames, summary = [read_json(root / p) for p in ('plan.json', 'frames.json', 'operator_summary.json')]
    require(summary['captures_complete'] is True and summary['frames'] == frames and len(frames) == 4,
            'Incomplete four-direction group')
    require(summary['saved_images'] == 4 and summary['capture_attempts'] == 4, 'Four successful attempts required')
    evidence = summary['evidence_source']
    require(evidence == 'real_board' or (allow_peer and evidence == 'software_udp_peer'), 'Unsupported evidence source')
    require(summary.get('operator_confirmation_supplied') is True, 'Missing operator confirmation')
    if evidence == 'real_board':
        require(summary.get('operator_same_pose_confirmed') is True, 'Missing same-pose confirmation')
    require(plan['gain16'] == 16 and plan['brightness'] == 128 and plan['exposure_lines'] in (400, 500, 600, 700),
            'Unsupported first-version acquisition parameters')
    require(plan['settle_frames'] == 1 and plan['discard_frames'] == 3, 'Unexpected wait/discard rules')
    fusion, inputs = engine()
    x, y, w, h = plan['roi']
    require(plan['native_mask_shape_hw'] == [h, w] and plan['common_mask_shape_hw'] == [1080, 1920], 'Mask geometry')
    native = np.fromfile(root / 'native_mask.bin', np.uint8).reshape(h, w)
    common = np.fromfile(root / 'common_mask.bin', np.uint8).reshape(1080, 1920)
    inputs.validate_masks(native, common, plan['roi'], plan['mask_pixels'])
    for name, key in [('native_mask.bin', 'native_mask_sha256'), ('common_mask.bin', 'common_mask_sha256'),
                      ('source_full.png', 'source_full_png_sha256'), ('source_geometry.json', 'source_geometry_sha256')]:
        require(digest(root / name) == plan[key], 'Source/mask identity differs: ' + name)
    records, checks, previous = [], [], None
    board = native.astype(bool)
    for channel, row in enumerate(frames, 1):
        require(row['channel'] == channel and row['direction'] == ['top', 'right', 'bottom', 'left'][channel - 1], 'Wrong direction order')
        expected = {k: plan[k] for k in ('exposure_lines', 'gain16', 'brightness', 'settle_frames', 'discard_frames')}
        expected['light_mask'] = 1 << (channel - 1)
        record_path = safe_path(root, row['result_json'])
        r = read_json(record_path)
        d, camera, ident = r['diagnostic'], r['camera_readback'], r['identity']
        require(r['status'] == 'COMMITTED' and r['strict_verified'] is True and r['mode'] == 'strict'
                and r['firmware'] == d['firmware'] == 0x0105 and r['evidence_source'] == evidence == row['evidence_source'],
                'Not a strict bound 0105 frame')
        require(r['sample_id'] == plan['sample_id'] and r['roi'] == d['roi'] == plan['roi']
                and r['call_id'] == row['call_id'] == record_path.parent.parent.name, 'Frame sample/ROI/call differs')
        for key in ('identity', 'actual_parameters', 'camera_readback', 'statistics', 'features'):
            require(r[key] == row[key], 'Frame/result differs: ' + key)
        require(r['actual_parameters'] == d['parameters'] == expected and ident == d['identity']
                and all(d[k] for k in ('valid', 'bound', 'parameters_valid', 'mask_valid')) and not d['error']
                and r['mask_sha256'] == plan['native_mask_sha256'], 'Diagnostic parameter/mask binding failed')
        require(camera['locked'] and camera['mode'] == camera['raw_registers']['0x3503'] == 3 and not camera['error']
                and camera['exposure_raw'] == 16 * plan['exposure_lines'] and camera['exposure_lines'] == plan['exposure_lines']
                and camera['gain16'] == plan['gain16'] and camera['generation'] == ident['camera_generation'], 'Camera readback failed')
        if previous:
            require(ident['session'] == previous['session'] and ident['roi_generation'] == previous['roi_generation'], 'Mixed acquisition session')
            for key, bits in dict(request_id=32, dvp_sequence=32, publish_sequence=32, config_epoch=32,
                                  camera_generation=16, light_generation=16, frame_id=16).items():
                require(0 < ((ident[key] - previous[key]) & ((1 << bits) - 1)) < (1 << (bits - 1)), 'Repeated/non-forward identity: ' + key)
        previous = ident
        for key in ('settle', 'discard'):
            require(r['device_reported_' + key + '_frames'] == row['device_reported_' + key + '_frames'] == plan[key + '_frames'], 'Wait/discard mismatch')
        png_path, raw_path = safe_path(root, row['png']), safe_path(root, row['raw'])
        raw = raw_path.read_bytes()
        require(digest(png_path) == row['png_sha256'] == r['png_sha256'] and
                digest(raw_path) == row['raw_sha256'] == r['raw_rgb565_sha256'], 'Image hash differs')
        require(raw == (record_path.parent / 'image.rgb565').read_bytes() and
                png_path.read_bytes() == (record_path.parent / 'image.png').read_bytes(), 'Committed image alias differs')
        require(len(raw) == 2 * w * h and r['complete_packets'] == r['expected_packets'] == (2 * w * h + 1379) // 1380, 'Incomplete raw frame')
        bgr = cv2.imdecode(np.frombuffer(png_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        require(bgr is not None and bgr.shape == (h, w, 3), 'Image dimensions differ')
        words = np.frombuffer(raw, '>u2').reshape(h, w)
        red, green, blue = (words >> 11) & 31, (words >> 5) & 63, words & 31
        decoded = np.stack(((blue << 3) | (blue >> 2), (green << 2) | (green >> 4), (red << 3) | (red >> 2)), axis=2).astype(np.uint8)
        require(np.array_equal(decoded, bgr), 'PNG/RGB565 pixel mismatch')
        require(inputs.crc64(raw) == r['crc64'] == d['rgb_crc64'], 'CRC64 mismatch')
        f = fusion.single_features(bgr)
        gray, maximum = f['gray'], (bgr == 255).any(axis=2)
        stats = dict(pixel_count=w*h, gray_sum=int(gray.sum()), near_black=int((gray <= 5).sum()), near_white=int((gray >= 250).sum()),
                     rgb_any_max=int(maximum.sum()), board_count=int(board.sum()), board_gray_sum=int(gray[board].sum()),
                     board_dark=int((gray[board] <= 10).sum()), board_white=int((gray[board] >= 250).sum()), board_rgb_any_max=int(maximum[board].sum()))
        require(stats == r['statistics'] == d['statistics'], 'H1 pixel recomputation differs')
        require(inputs.feature_statistics(f) == r['features'] == d['features'], 'H2 pixel recomputation differs')
        records.append(dict(bgr=bgr, features=f, frame=row))
        checks.append(dict(channel=channel, png_sha256=row['png_sha256'], raw_sha256=row['raw_sha256'],
                           H1_equal=True, H2_equal=True, pixels_and_crc_equal=True))
    require(len({r['call_id'] for r in frames}) == 4, 'Reused call')
    return dict(plan=plan, summary=summary, records=records, board=board, checks=checks,
                manifest_sha256=digest(root / 'output_manifest.json'), input_members=len(files))


def png(path, pixels):
    ok, encoded = cv2.imencode('.png', pixels)
    require(ok, 'PNG encoding failed')
    Path(path).write_bytes(encoded.tobytes())


def analyze(source, out, allow_peer=False):
    started = time.monotonic()
    out = Path(out)
    require(not out.exists(), 'Analysis output already exists')
    group = load_group(source, allow_peer)
    out.mkdir(parents=True, exist_ok=False)
    fusion, _ = engine()
    board, records, plan = group['board'], group['records'], group['plan']
    residual = np.stack([r['features']['residual_n'] for r in records])
    valid = np.stack([r['features']['valid'] for r in records])
    quality = [fusion.tile_quality(r['bgr'], board) for r in records]
    q = np.stack([r['quality_q8'] for r in quality])
    write_json(out / 'tiles.json', [r['tiles'] for r in quality])
    rows, components, modes = [], [], {}
    for channel, rec in enumerate(records, 1):
        png(out / ('CH%d.png' % channel), rec['bgr'])
        overlay = rec['bgr'].copy()
        overlay[rec['features']['mask'] & board] = (0, 0, 255)
        png(out / ('CH%d_candidates.png' % channel), overlay)
        rows.append(dict(channel=channel, direction=rec['frame']['direction'], **rec['frame']['statistics'],
                         single_candidate_pixels=int((rec['features']['mask'] & board).sum()),
                         usable_board_pixels=int((rec['features']['valid'] & board).sum())))
    base = records[0]['bgr']
    for mode in ('B1', 'M1'):
        result = fusion.fuse(residual, valid, mode, q if mode == 'M1' else None)
        final = result['mask'] & board
        unknown = result['unknown'] & board
        np.savez_compressed(out / (mode + '_arrays.npz'), **result, final_candidate=final, board_mask=board,
                            quality_q8=q if mode == 'M1' else np.zeros((0,), np.uint16))
        overlay = base.copy()
        overlay[unknown] = (255, 0, 255)
        overlay[final] = (0, 0, 255)
        png(out / (mode + '_overlay.png'), overlay)
        png(out / (mode + '_mask.png'), final.astype(np.uint8) * 255)
        risk = np.zeros_like(base)
        risk[board] = (48, 80, 48)
        risk[unknown] = (255, 0, 255)
        maximum = np.stack([(r['bgr'] == 255).any(axis=2) for r in records])
        risk[maximum.any(axis=0) & board] = (0, 165, 255)
        risk[unknown] = (255, 0, 255)
        png(out / (mode + '_quality.png'), risk)
        count, labels, stats, centers = cv2.connectedComponentsWithStats(final.astype(np.uint8), connectivity=8)
        for i in range(1, count):
            xx, yy, ww, hh, area = map(int, stats[i])
            components.append(dict(mode=mode, candidate_region_id=i, area_pixels=area,
                                   roi_x=xx, roi_y=yy, width=ww, height=hh,
                                   full_x=xx+plan['roi'][0], full_y=yy+plan['roi'][1]))
        modes[mode] = dict(candidate_pixels=int(final.sum()), candidate_connected_regions=count-1,
                           unobserved_board_pixels=int(unknown.sum()), unobserved_board_fraction=float(unknown.sum()/board.sum()),
                           indication='OBSERVATION_INSUFFICIENT_REVIEW' if unknown.any() else
                                      ('CANDIDATES_REQUIRE_REVIEW' if final.any() else 'NO_OBVIOUS_CANDIDATES_NOT_A_PASS'))
    for name, data in [('frame_metrics.csv', rows), ('candidate_regions.csv', components)]:
        with (out / name).open('w', encoding='utf-8-sig', newline='') as stream:
            fields = list(data[0]) if data else ['mode', 'candidate_region_id', 'area_pixels', 'roi_x', 'roi_y', 'width', 'height', 'full_x', 'full_y']
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(data)
    result = dict(schema=1, status='ANALYZED_REVIEW_REQUIRED', sample_id=plan['sample_id'], roi=plan['roi'],
                  evidence_source=group['summary']['evidence_source'], input_folder=str(Path(source).resolve()),
                  input_manifest_sha256=group['manifest_sha256'], input_checks=group['checks'], modes=modes,
                  exposure_lines=plan['exposure_lines'], gain16=plan['gain16'], brightness=plan['brightness'],
                  rule_version='fourlight-fusion-1', thresholds_strict=[648, 1620], reference_annotations_used=False,
                  weak_line_experiment_enabled=False, detector_rules_modified=False,
                  analysis_location='PC', physical_scratch_count_available=False, accuracy_or_recall_measured=False,
                  computer_analysis_elapsed_ms=(time.monotonic()-started)*1000,
                  vendor_manifest_sha256=digest(ROOT/'vendor_manifest.json'))
    write_json(out / 'analysis_summary.json', result)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--allow-peer', action='store_true', help='Explicit localhost test data only')
    args = p.parse_args()
    try:
        result = analyze(args.source, args.out, args.allow_peer)
        print(result['status'] + ': ' + result['sample_id'])
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
