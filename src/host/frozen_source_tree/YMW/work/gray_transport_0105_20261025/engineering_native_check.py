"""Native 1920x1080 profile of the already verified two-frame engineering operator."""
import argparse
import datetime
import json
import math
import uuid
from pathlib import Path

import engineering_transport_check as base
import review_engineering_capture as audit

HERE = Path(__file__).resolve().parent
SMALL_REVIEW = HERE / 'verification/real_transport_20261026_01/verification.json'
APPROVAL = HERE / 'verification/native_prepare_01/verification.json'


class NativeRuntime(base.Runtime):
    roi = [0, 0, 1920, 1080]
    timeout_s = 300

    def prepare(self):
        plan = super().prepare()
        previous = json.loads(SMALL_REVIEW.read_bytes())
        base.require(previous['status']=='PASS' and previous['gray_payload_hardware_verified'],
                     'Small-ROI real transport review required')
        pixels = self.roi[2] * self.roi[3]
        # Keep the SDK's full-mask reservation, including safety allowance.
        base.require(math.ceil(pixels/32)+600 < 65536, 'Full-mask control sequence budget exceeded')
        plan.update(profile='native_1920x1080_two_frames',
            mask_scope='all ones in native saved domain; not a physical board label',
            per_capture_deadline_s=self.timeout_s, expected_RGB_bytes=pixels*2,
            expected_GRAY_SAT_bytes=pixels+math.ceil(pixels/8),
            expected_RGB_packets=math.ceil(pixels*2/1380),
            expected_GRAY_packets=math.ceil((pixels+math.ceil(pixels/8))/1380),
            mask_words_per_session=math.ceil(pixels/32))
        for path in [Path(__file__),SMALL_REVIEW,Path(audit.__file__)]:
            plan['source_sha256'][str(path)] = base.sdk.support.sha_file(path)
        return plan


def verify_delivery():
    record = json.loads(APPROVAL.read_bytes())
    base.require(record['status']=='PASS' and record['physical_captures']==0, 'Native profile approval missing')
    old = HERE / 'verification/engineering_operator_01/verification.json'
    base.require(base.sdk.support.sha_file(old)=='87f8b46e4f912f9b7f9e57e448ce4e364e044e00920b859875dd2bb574766f00',
                 'Original tested operator receipt changed')
    for source,digest in record['source_sha256'].items():
        base.require(base.sdk.support.sha_file(source)==digest, 'Native profile/source changed: '+source)
    original = json.loads(old.read_bytes())
    for name,digest in original['source_sha256'].items():
        base.require(base.sdk.support.sha_file(HERE/name)==digest, 'Tested base source changed: '+name)
    for source,digest in original['SDK_source_sha256'].items():
        base.require(base.sdk.support.sha_file(source)==digest, 'Tested SDK source changed: '+source)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check-only',action='store_true');group.add_argument('--run',action='store_true')
    args=parser.parse_args();verify_delivery();runtime=NativeRuntime()
    if args.check_only:
        plan=runtime.prepare()
        print(json.dumps(dict(status='NATIVE_PROFILE_OFFLINE_READY',roi=plan['roi'],
            RGB_bytes=plan['expected_RGB_bytes'],GRAY_SAT_bytes=plan['expected_GRAY_SAT_bytes'],
            mask_words_per_session=plan['mask_words_per_session'],captures_requested=0),indent=2))
    else:
        name=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
        out=Path.home()/'Documents/Guangjian0106Native'/name
        print('NATIVE CHECK: RGB then GRAY, two frames only. Full-mask upload may take several minutes.',flush=True)
        print('RESULT DIRECTORY (when finished): '+str(out),flush=True)
        result=base.execute(out,_runtime=runtime)
        print(json.dumps(dict(status=result['summary']['status'],output=result['output'],archive=result['archive'],
            frames_verified=result['summary']['captures_verified'],error=result['summary']['error']),indent=2))
        print('RESULT DIRECTORY: '+str(out))
        raise SystemExit(0 if result['summary']['status']=='ENGINEERING_TRANSPORT_VERIFIED' else 2)
