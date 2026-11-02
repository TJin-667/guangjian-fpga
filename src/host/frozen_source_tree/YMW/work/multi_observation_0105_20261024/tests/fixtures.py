import copy
import uuid

import cv2
import numpy as np

from multiobs.contracts import Context, sha
from multiobs.ports import CaptureFailure
from multiobs.validation import Payload, crc64, pixel_statistics


class Clock:
    def __init__(self):
        self.time = 0.0

    def __call__(self):
        return self.time


def context():
    return Context('sample_offline', 'fixed_pose', (4, 8, 17, 17), bytes([1]) * 289)


def identity(n, *, first_frame=100):
    return dict(session=123456789, request_id=n, config_epoch=n, dvp_sequence=1000+n,
                publish_sequence=2000+n, roi_generation=3, camera_generation=n,
                light_generation=n, frame_id=(first_frame+n-1) & 65535)


def payload(request, ctx, profile, ident, *, execution_mode='software_fake', source='software_fake'):
    w, h = ctx.roi[2:]
    words = ((np.arange(w*h, dtype=np.uint32) * 67) & 65535).astype('>u2').reshape(h, w)
    red, green, blue = (words >> 11) & 31, (words >> 5) & 63, words & 31
    image = np.stack(((blue << 3) | (blue >> 2), (green << 2) | (green >> 4), (red << 3) | (red >> 2)), axis=2).astype(np.uint8)
    ok, encoded = cv2.imencode('.png', image)
    assert ok
    png, raw = encoded.tobytes(), words.tobytes()
    stats, features = pixel_statistics(png, raw, ctx)
    params, eraw = request.parameters(profile), request.exposure_lines * 16
    registers = {'0x3503': 3, '0x3500': (eraw >> 16) & 15, '0x3501': (eraw >> 8) & 255,
                 '0x3502': eraw & 255, '0x350A': (request.gain16 >> 8) & 3, '0x350B': request.gain16 & 255}
    camera = dict(locked=True, error=0, mode=3, generation=ident['camera_generation'], raw_registers=registers,
                  exposure_raw=eraw, exposure_lines=float(request.exposure_lines), gain16=request.gain16)
    diagnostic = dict(firmware=0x0105, valid=True, bound=True, parameters_valid=True, mask_valid=True,
                      logical_association_available=True, error=0, bank=0, identity=copy.deepcopy(ident),
                      request_counter=ident['request_id'], parameters=params.copy(), roi=list(ctx.roi),
                      wait_complete_frames=1, discard_complete_frames=3, rgb_crc64=crc64(raw),
                      statistics=stats.copy(), features=features.copy())
    record = dict(call_id=uuid.uuid4().hex, status='COMMITTED', strict_verified=True, mode='strict',
                  firmware=0x0105, sample_id=ctx.sample_id, roi=list(ctx.roi), identity=copy.deepcopy(ident),
                  session=ident['session'], expected_request_id=ident['request_id'], wire_frame_id=ident['frame_id'],
                  frame_id=ident['frame_id'], roi_generation=ident['roi_generation'],
                  actual_parameters=params.copy(), requested=dict(params, roi=list(ctx.roi)),
                  mask_sha256=ctx.mask_sha256, diagnostic=diagnostic, camera_readback=camera,
                  device_reported_settle_frames=1, device_reported_discard_frames=3, evidence_source=source,
                  png_sha256=sha(png), raw_rgb565_sha256=sha(raw), crc64=crc64(raw),
                  complete_packets=(len(raw)+1379)//1380, expected_packets=(len(raw)+1379)//1380,
                  statistics=stats, features=features, bank=0,
                  cost=dict(capture_requests=1, complete_images_received=1, host_elapsed_s=0.01))
    return Payload(record, png, raw, copy.deepcopy(ident), execution_mode)


def reidentify(p, ident):
    p.receipt.clear()
    p.receipt.update(ident)
    r = p.record
    r.update(identity=ident.copy(), session=ident['session'], expected_request_id=ident['request_id'],
             wire_frame_id=ident['frame_id'], frame_id=ident['frame_id'], roi_generation=ident['roi_generation'])
    r['diagnostic'].update(identity=ident.copy(), request_counter=ident['request_id'])
    r['camera_readback']['generation'] = ident['camera_generation']
    return p


class FakePort:
    execution_mode = 'software_fake'

    def __init__(self, clock, behaviors=(), *, first_frame=100):
        self.clock, self.behaviors = clock, list(behaviors)
        self.first_frame, self.calls = first_frame, []
        self.off_called = self.closed = False
        self.off_ack = True
        self.delay = 0.01

    def capture(self, request, ctx, profile, attempt_id, timeout_s, cancel):
        self.calls.append(dict(action_id=request.action_id, attempt_id=attempt_id, timeout_s=timeout_s,
                               channel=request.channel, exposure_lines=request.exposure_lines, role=request.role))
        self.clock.time += self.delay
        behavior = self.behaviors.pop(0) if self.behaviors else None
        if isinstance(behavior, Exception):
            raise behavior
        value = payload(request, ctx, profile, identity(len(self.calls), first_frame=self.first_frame))
        if behavior:
            return behavior(value)
        return value

    def lights_off(self):
        self.off_called = True
        return dict(requested=True, acknowledged=self.off_ack, physical_off_verified=False)

    def close(self):
        self.closed = True
