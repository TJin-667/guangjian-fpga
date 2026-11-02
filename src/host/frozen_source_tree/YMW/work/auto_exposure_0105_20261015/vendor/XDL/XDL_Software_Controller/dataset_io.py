"""Verified original-data boundary. No extraction, detector, replay, or hardware IO."""
from collections import Counter
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile

import cv2
import numpy as np
from capture_metrics import FrameInput, source_identity as _source_identity

SCAN_COMMIT = '7ccb753ffacff752a5cd65d4b3a13ff7be9875c6'
REPEAT_COMMIT = 'de18e3b604158c1b53b87b08f22ddc59ed52cfe2'
SCAN_INPUTS_SHA256 = 'e1cf8e2b23b1e9bc537f152369f2cbe5d7d7c39e4475ba7474895260ed474b01'
REPEAT_INDEX_SHA256 = '61c7863b9286c5aa27af46f4de3f10f7c01b5944e576a94921fa1585f376b5f4'
REPEAT_DATASET_ID = 'ch1_repeat_defect_near_normal_20261013'

def _require(ok, message):
    if not ok:
        raise ValueError(message)

def _json(data):
    def invalid(value):
        raise ValueError('non-finite JSON: ' + value)
    return json.loads(data, parse_constant=invalid)

def _relative(name):
    _require(isinstance(name, str) and name and '\\' not in name and ':' not in name,
             'unsafe relative path')
    p = PurePosixPath(name)
    _require(not p.is_absolute() and all(part not in ('', '.', '..') for part in name.split('/')),
             'path escape or ambiguous path: ' + name)
    return p

def _path(root, name):
    relative = _relative(name)
    root = Path(root).resolve()
    target = root.joinpath(*relative.parts).resolve()
    _require(target.is_relative_to(root) and target != root, 'path escapes storage root')
    return target

def _verify(data, sha, size=None):
    _require(size is None or len(data) == size, 'original byte size mismatch')
    _require(hashlib.sha256(data).hexdigest() == sha, 'original SHA256 mismatch')
    return data

def _read(root, name, sha, size=None):
    return _verify(_path(root, name).read_bytes(), sha, size)

def _repeat_index(root):
    index = _json(_read(root, 'dataset_index.json', REPEAT_INDEX_SHA256))
    _require(index['dataset_id'] == REPEAT_DATASET_ID and index['schema_version'] == 1,
             'unsupported repeat index')
    _require(len(index['records']) == 6 and len(index['archive_members']) == 24,
             'repeat requires six originals and 24 members')
    return index

def _zip_members(root, record, members):
    data = _read(root, record['archive'], record['archive_sha256'], record['archive_bytes'])
    expected = {m['member']: m for m in members}
    _require(len(expected) == len(members), 'duplicate ZIP member provenance')
    for m in members:
        _relative(m['member']); _relative(m['extracted_path'])
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            actual = archive.namelist()
            for name in actual:
                _relative(name)
            _require(len(actual) == len(set(actual)) and set(actual) == set(expected),
                     'unexpected or duplicate ZIP members')
            return {name: _verify(archive.read(name), item['sha256'], item['bytes'])
                    for name, item in expected.items()}
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ValueError('invalid ZIP or CRC') from exc

def _decode(png, raw, width, height):
    # Decode these already-hashed bytes, never reopen a pathname after hashing.
    image = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    _require(image is not None and image.dtype == np.uint8 and image.shape == (height, width, 3),
             'PNG dimensions or encoding mismatch')
    _require(len(raw) == width * height * 2, 'RGB565 dimensions mismatch')
    v = np.frombuffer(raw, dtype='>u2').reshape(height, width)
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    bgr = np.stack(((b << 3) | (b >> 2), (g << 2) | (g >> 4),
                    (r << 3) | (r >> 2)), axis=-1).astype(np.uint8)
    _require(np.array_equal(image, bgr), 'PNG/RGB565 pixel mismatch')
    return image

def _session_check(session, record, sample, png_name, raw_name):
    _require(session['sample_id'] == sample, 'session sample mismatch')
    expected = {'exposure_lines':record['exposure_lines'], 'gain16':record['gain16'],
                'brightness':record['brightness']}
    _require(all(session['requested'].get(k) == v for k, v in expected.items()),
             'requested settings mismatch')
    views = [v for v in session['views'] if v['channel'] == record['channel']]
    _require(len(views) == 1, 'missing or duplicate view')
    view = views[0]; frame = view['frame']
    _require(view['status'] == 'COMPLETE' and view['mask'] == 1 and view['brightness'] == 128,
             'incomplete CH1 view or LED mismatch')
    _require(view['png'] == png_name and view['rgb565'] == raw_name,
             'session member association mismatch')
    _require(frame['frame_id'] == record['frame_id'] and not frame['discarded'],
             'saved frame identity mismatch')
    _require((view['saved_width'], view['saved_height']) == (record['width'], record['height'])
             and tuple(view['roi']) == tuple(record['roi']), 'session saved geometry mismatch')
    _require(view['sha256_rgb565'] == record.get('sha256_rgb565', record.get('rgb565_sha256')),
             'session RGB565 hash mismatch')
    camera = session['camera_readback']
    for readback in (camera, frame['camera_before'], frame['camera_after']):
        _require(readback['locked'] is True and readback['error'] == 0
                 and readback['exposure_lines'] == record['exposure_lines']
                 and readback['gain16'] == record['gain16']
                 and readback['generation'] == camera['generation']
                 and readback['raw_registers'] == camera['raw_registers'],
                 'camera before/after/readback mismatch')
    if 'camera_generation' in record:
        _require(camera['generation'] == record['camera_generation']
                 and camera['raw_registers'] == record['register_values'], 'index camera mismatch')
    reg = camera['raw_registers']
    raw_exposure = (reg['0x3500'] << 16) | (reg['0x3501'] << 8) | reg['0x3502']
    _require(raw_exposure == record['exposure_lines'] * 16
             and ((reg['0x350A'] << 8) | reg['0x350B']) == record['gain16'],
             'raw register settings mismatch')
    roi_readback = frame.get('roi_readback')
    if roi_readback is not None:
        _require(roi_readback['valid'] is True and tuple(roi_readback['roi']) == tuple(record['roi']),
                 'saved frame ROI readback mismatch')
    return view

def source_identity(frame: FrameInput) -> str:
    """Use the single canonical metric-boundary identity; never storage paths."""
    result = _source_identity(frame)
    _require(result is not None, 'source provenance unavailable')
    return result

def _unique(frames):
    identities = [source_identity(f) for f in frames]
    _require(len(identities) == len(set(identities)), 'duplicate frame provenance')
    _require(len({f.observation_id for f in frames}) == len(frames), 'duplicate observation')
    return frames

def _frame(root, record, session, metadata, sample, pose, mode, dataset_id, capture_id):
    metadata['board_mask_needs_manual_review'] = metadata['needs_manual_review']
    metadata.update(storage_root=str(Path(root).resolve()), dataset_id=dataset_id,
                    capture_id=capture_id, frame_id=record['frame_id'], session=session,
                    dataset_commit=SCAN_COMMIT if mode == 'scan' else REPEAT_COMMIT,
                    physical_freshness_validation=False, hardware_validation_pending=True)
    return FrameInput(f'{mode}:{dataset_id}:{sample}:{pose}',
                      f'{capture_id}:CH1:F{record["frame_id"]}', sample, pose,
                      record['exposure_lines'], record['gain16'], record['channel'], record['brightness'],
                      record['width'], record['height'], tuple(record['roi']),
                      record.get('sha256_png', record.get('png_sha256')),
                      record.get('sha256_rgb565', record.get('rgb565_sha256')), mode, metadata)

def load_scan_inputs(scan_root: Path, expected_results: Path) -> list[FrameInput]:
    """Verify every indexed original member, then select CH1 pose A 400/500/600/700."""
    bundle = _json(_read(expected_results, 'analysis_inputs.json', SCAN_INPUTS_SHA256))
    _require(bundle['github_commit'] == SCAN_COMMIT and bundle['index']['dataset_revision'] == 2,
             'wrong scan commit or revision')
    index = bundle['index']; members = index['archive_members']; payloads = {}; member_map = {}
    for item in members:
        _relative(item['archive']); _relative(item['extracted_path'])
        name = item['member']; _require(name not in payloads, 'duplicate original member')
        payloads[name] = _read(scan_root, name, item['sha256'], item['bytes'])
        member_map[name] = item
    frames = []; geometry = {g['group_id']:g for g in bundle['geometry_records']}
    for exposure in (400, 500, 600, 700):
        group_id = f'E{exposure:04d}_G1'
        groups = [g for g in index['groups'] if g['group_id'] == group_id]
        rows = [r for r in index['images'] if r['group_id'] == group_id and r['channel'] == 1]
        _require(len(groups) == len(rows) == 1, 'missing or duplicate scan selection')
        group, row = groups[0], dict(rows[0])
        for source in (group, row):
            _require(source['pose_block'] == 'A' and source['specimen_id'] == 'sample001'
                     and source['exposure_lines'] == exposure and source['gain16'] == 16
                     and source['brightness'] == 128, 'wrong scan pose/sample/settings')
        row['roi'] = [row['roi_x'], row['roi_y'], row['width'], row['height']]
        _require(tuple(group['roi']) == tuple(row['roi']) and row['archive'] == group['archive'],
                 'scan index geometry/archive mismatch')
        prefix = group['original_zip_prefix']; png = row['zip_png_member']
        raw = str(PurePosixPath(png).with_suffix('.rgb565')); session_name = prefix + 'session.json'
        _require(png.startswith(prefix) and member_map[png]['archive'] == group['archive'],
                 'scan member association mismatch')
        session = _json(payloads[session_name])
        _session_check(session, row, 'sample001', PurePosixPath(png).name, PurePosixPath(raw).name)
        _verify(payloads[png], row['png_sha256']); _verify(payloads[raw], row['rgb565_sha256'])
        _decode(payloads[png], payloads[raw], row['width'], row['height'])
        region = geometry[group_id]
        _require(region['pose'] == 'A', 'mask pose mismatch')
        meta = {'storage_kind':'files', 'member':png, 'rgb565_member':raw,
                'session_member':session_name, 'session_sha256':member_map[session_name]['sha256'],
                'member_verification':{k:member_map[k] for k in (png,raw,session_name)},
                'analysis_polygon':region['analysis_polygon'], 'mask_source':region['analysis_mask_source'],
                'needs_manual_review':not group.get('auto_geometry_success',False),
                'group_id':group_id, 'dataset_revision':2, 'archive':group['archive'],
                'original_index_sha256':SCAN_INPUTS_SHA256, 'verified_member_count':len(members)}
        frames.append(_frame(scan_root,row,session,meta,'sample001','A','scan','YMW_manual_20261013',
                             prefix.rstrip('/')))
    return _unique(frames)

def _repeat_originals(root, index):
    output = []
    archives = set()
    for row in index['records']:
        _require(row['archive'] not in archives, 'duplicate archive provenance')
        archives.add(row['archive'])
        members = [m for m in index['archive_members'] if m['archive'] == Path(row['archive']).name]
        _require(len(members) == 4, 'repeat ZIP requires four members')
        payloads = _zip_members(root,row,members)
        by_extracted = {m['extracted_path']:m for m in members}
        _require(len(by_extracted) == 4, 'duplicate extracted provenance')
        selected = {key:by_extracted[row[key]] for key in ('png','rgb565','session')}
        session = _json(payloads[selected['session']['member']])
        _require(row['channel'] == 1 and row['exposure_lines'] == 600
                 and row['gain16'] == 16 and row['brightness'] == 128,
                 'unsupported repeat settings')
        _session_check(session,row,row['sample_id'],Path(selected['png']['member']).name,
                       Path(selected['rgb565']['member']).name)
        _verify(payloads[selected['png']['member']],row['sha256_png'])
        _verify(payloads[selected['rgb565']['member']],row['sha256_rgb565'])
        _decode(payloads[selected['png']['member']],payloads[selected['rgb565']['member']],row['width'],row['height'])
        output.append((row,session,members,selected))
    _require(Counter(r['sample_id'] for r,_,_,_ in output) == {'sample001':3,'sample002':3},
             'two independent boards require three repeats each')
    for sample in ('sample001','sample002'):
        group = [r for r,_,_,_ in output if r['sample_id'] == sample]
        _require({r['repeat_id'] for r in group} == {'r01','r02','r03'}, 'missing/duplicate repeat')
        _require(len({r['frame_id'] for r in group}) == 3, 'duplicate saved frame id')
    return output

def _logs(root,index, allow_missing=False):
    result = {}
    for item in index['supplementary_logs']:
        path = _path(root,item['path'])
        _require(item['path'] not in result, 'duplicate complete log')
        if allow_missing and not path.exists():
            result[item['path']] = None
            continue
        data = _verify(path.read_bytes(),item['sha256'],item['bytes'])
        result[item['path']] = [_json(line) for line in data.splitlines() if line.strip()]
    return result

def load_repeat_inputs(repeat_root: Path, regions: Path) -> list[FrameInput]:
    index = _repeat_index(repeat_root)
    originals = _repeat_originals(repeat_root,index)
    _logs(repeat_root,index)
    region_bytes = Path(regions).read_bytes(); regions_data = _json(region_bytes)
    _require(regions_data['version'] == 'repeat-regions-1'
             and regions_data['dataset_commit'] == REPEAT_COMMIT
             and set(regions_data['boards']) == {'sample001','sample002'}, 'repeat region provenance mismatch')
    frames = []
    for row, session, members, selected in originals:
        region = regions_data['boards'][row['sample_id']]
        first = next(r for r in index['records'] if r['sample_id'] == row['sample_id'] and r['repeat_id'] == 'r01')
        _require(region['source_png_sha256'] == first['sha256_png']
                 and region['source_repeat_id'] == 'r01' and region['manual_review_pending'] is True,
                 'region source hash or review flag mismatch')
        polygon = region['polygon']
        _require(len(polygon) == 4 and all(len(p) == 2 and all(type(v) is int for v in p)
                 and 0 <= p[0] < row['width'] and 0 <= p[1] < row['height'] for p in polygon),
                 'invalid fixed quadrilateral')
        contour = np.asarray(polygon,dtype=np.int32)
        _require(cv2.isContourConvex(contour) and cv2.contourArea(contour) > 0,
                 'contradictory quadrilateral geometry')
        meta = {'storage_kind':'zip', 'archive':row['archive'], 'archive_sha256':row['archive_sha256'],
                'archive_bytes':row['archive_bytes'], 'archive_members':members,
                'member':selected['png']['member'], 'rgb565_member':selected['rgb565']['member'],
                'session_member':selected['session']['member'], 'session_sha256':selected['session']['sha256'],
                'analysis_polygon':polygon, 'mask_source':region['mask_source'], 'needs_manual_review':True,
                'region_source_png_sha256':region['source_png_sha256'],
                'regions_sha256':hashlib.sha256(region_bytes).hexdigest(),
                'repeat_id':row['repeat_id'], 'acquisition_mode':row['acquisition_mode'],
                'preview_session_id':row.get('preview_session_id'), 'capture_log':row['capture_log'],
                'original_index_sha256':REPEAT_INDEX_SHA256, 'verified_member_count':24}
        frames.append(_frame(repeat_root,row,session,meta,row['sample_id'],
                             'repeat:'+row['sample_id'],'repeat',REPEAT_DATASET_ID,session['group_id']))
    return _unique(frames)

def read_frame(frame: FrameInput) -> np.ndarray:
    """Reverify current originals, return exact saved BGR8 pixels from the same bytes."""
    source_identity(frame)
    m = frame.source_metadata; root = Path(m['storage_root'])
    if m['storage_kind'] == 'zip':
        data = _zip_members(root,m,m['archive_members'])
        png, raw = data[m['member']], data[m['rgb565_member']]
        session_data = data[m['session_member']]
    elif m['storage_kind'] == 'files':
        data = {name:_read(root,name,item['sha256'],item['bytes'])
                for name,item in m['member_verification'].items()}
        png, raw, session_data = data[m['member']], data[m['rgb565_member']], data[m['session_member']]
    else:
        raise ValueError('unsupported original storage')
    _verify(png,frame.png_sha256); _verify(raw,frame.rgb565_sha256)
    _verify(session_data,m['session_sha256'])
    image = _decode(png,raw,frame.saved_width,frame.saved_height)
    record = {'exposure_lines':frame.exposure_lines, 'gain16':frame.gain16,
              'brightness':frame.led, 'channel':frame.channel, 'frame_id':m['frame_id'],
              'width':frame.saved_width, 'height':frame.saved_height, 'roi':frame.roi,
              'sha256_rgb565':frame.rgb565_sha256}
    session = _json(session_data)
    _session_check(session,record,frame.sample_id,PurePosixPath(m['member']).name,
                   PurePosixPath(m['rgb565_member']).name)
    _require(session['group_id'] == m['capture_id'], 'capture identity/session mismatch')
    return image

def historical_cost(repeat_root: Path) -> dict:
    """Full-log manual capture facts; missing evidence stays null, prefixes never sum."""
    index = _repeat_index(repeat_root); originals = _repeat_originals(repeat_root,index)
    logs = _logs(repeat_root,index,allow_missing=True); samples = {}
    for sample in ('sample001','sample002'):
        rows = [(r,s) for r,s,_,_ in originals if r['sample_id'] == sample]
        paths = {r['capture_log'] for r,_ in rows}
        prefixes = [s['total_complete_frames_received'] for _,s in rows]
        received = 0; evidence = []; known = True
        for path in sorted(paths):
            events = logs.get(path)
            if events is None or not any(e['event'] == 'done' and isinstance(e['value'],dict)
                                        and e['value'].get('failed') is False for e in events):
                known = False; evidence.append({'path':path,'received_frames':None}); continue
            matching = [(r,s) for r,s in rows if r['capture_log'] == path]
            if sample == 'sample001':
                # Preview logs also contain a `frame` event for each receive; use only
                # the complete-receive records, never count both representations.
                ids = [e['value']['frame_id'] for e in events if e['event'] == 'complete_received_frame']
                _require(ids and len(ids) == len(set(ids)), 'preview receive provenance mismatch')
                count = len(ids)
                _require(count >= max(prefixes), 'complete preview shorter than saved prefix')
            else:
                _require(len(matching) == 1, 'single session/log association mismatch')
                row, session = matching[0]
                saved = [e['value']['frame_id'] for e in events if e['event'] == 'frame']
                _require(saved == [row['frame_id']], 'single saved-frame log mismatch')
                _require(len(session['discarded_frames']) == 3 and session['saved_frames'] == 1
                         and session['total_complete_frames_received'] == 4
                         and session['total_capture_requests'] == 4, 'single capture cost mismatch')
                count = 4
            received += count; evidence.append({'path':path,'received_frames':count})
        samples[sample] = {'received_frames':received if known else None,
                           'prefix_counts':prefixes, 'prefix_lower_bound':max(prefixes),
                           'cost_scope':'shared_preview_full_log' if sample == 'sample001' else 'three_independent_singles',
                           'logs':evidence}
    counts = [s['received_frames'] for s in samples.values()]
    total = sum(counts) if all(n is not None for n in counts) else None
    return {'historical_capture_cost':{'received_frames':total, 'saved_images':6, 'samples':samples,
            'rgb565_payload_bytes':total*1920*1080*2 if total is not None else None,
            'evidence':'manual acquisition logs and original sessions', 'time_ms':None},
            'modeled_control_cost':None, 'measured_live_control_cost':None}
