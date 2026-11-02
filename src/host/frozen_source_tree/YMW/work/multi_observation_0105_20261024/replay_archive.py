"""Read-only legacy-09 archive import. Never replay historical images as new capture."""
import argparse
import json
from pathlib import Path, PurePosixPath
import socket
from unittest.mock import patch
import zipfile

from multiobs.contracts import (CaptureRequest, Context, Observation, ObservationSet,
                                Profile, require, sha, validate_progress)
from multiobs.runner import write_json
from multiobs.validation import Payload, validate_payload


def replay(archive_path, expected_sha256, out):
    archive_path, out = Path(archive_path), Path(out)
    require(sha(archive_path.read_bytes()) == expected_sha256, 'ARCHIVE_SHA256')
    observations, previous = ObservationSet(), None
    checks = []
    with zipfile.ZipFile(archive_path) as z:
        names = z.namelist()
        require(len(names) == len(set(names)) and len(names) <= 20000, 'ZIP_INVENTORY')

        def member(name):
            path = PurePosixPath(name)
            require(not path.is_absolute() and '..' not in path.parts and '\\' not in name, 'ZIP_PATH')
            require(z.getinfo(name).file_size <= 64 * 1024 * 1024, 'ZIP_MEMBER_SIZE')
            return z.read(name)

        plan = json.loads(member('acquisition/plan.json'))
        frames = json.loads(member('acquisition/frames.json'))
        context = Context(plan['sample_id'], 'historical_09_pose', tuple(plan['roi']), member('acquisition/native_mask.bin'))
        require(len(frames) == 4, 'LEGACY_GROUP_SIZE')
        for row in frames:
            action = CaptureRequest('archive_CH' + str(row['channel']), row['channel'],
                                    row['actual_parameters']['exposure_lines'], 'base', 'historical import only', row['actual_parameters']['gain16'])
            observations.check_request(action)
            record = json.loads(member('acquisition/' + row['result_json']))
            for key in ('identity', 'actual_parameters', 'statistics', 'features', 'camera_readback', 'call_id'):
                require(row[key] == record[key], 'ARCHIVE_FRAME_ALIAS_' + key)
            require(row['png_sha256'] == record['png_sha256'] and row['raw_sha256'] == record['raw_rgb565_sha256'], 'ARCHIVE_HASH_ALIAS')
            png = member('acquisition/' + row['png'])
            raw = member('acquisition/' + row['raw'])
            committed = 'acquisition/' + row['result_json'].rsplit('/', 1)[0] + '/'
            require(png == member(committed + 'image.png') and raw == member(committed + 'image.rgb565'), 'ARCHIVE_IMAGE_ALIAS')
            payload = Payload(record, png, raw, record['identity'], 'archive_replay')
            validate_progress(previous, payload.receipt)
            checks.append(dict(channel=action.channel, **validate_payload(payload, action, context, Profile())))
            observation = Observation('historical_' + row['call_id'], action.action_id, row['call_id'], action.channel, 'base',
                                      action.parameters(Profile()), payload.receipt, row['call_id'], sha(png), sha(raw),
                                      record['evidence_source'], 'archive_replay',
                                      dict(archive=str(archive_path.resolve()), png_member='acquisition/' + row['png'],
                                           raw_member='acquisition/' + row['raw']), statistics=record['statistics'],
                                      features=record['features'], camera_readback=record['camera_readback'])
            observations.append(observation)
            previous = payload.receipt
    require(observations.base_complete, 'MISSING_BASE_DIRECTIONS')
    out.mkdir(parents=True, exist_ok=False)
    result = dict(scope='Historical archive compatibility only; no new capture or adaptive policy/fusion validation',
                  archive_sha256=expected_sha256, context=context.describe(), execution_mode='archive_replay',
                  newly_requested_frames=0, observations=observations.describe(), checks=checks,
                  new_strategy_or_E800_hardware_validated=False)
    write_json(out / 'archive_replay.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    with patch.object(socket, 'socket', side_effect=AssertionError('Archive replay forbids network access')):
        result = replay(args.archive, args.sha256, args.out)
    print(json.dumps(dict(frames=len(result['checks']), newly_requested_frames=0, checks=result['checks']), indent=2))
