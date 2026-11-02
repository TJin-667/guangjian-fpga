"""Adapter for an explicitly supplied SDK executor; no constructor opens sockets."""
import copy
import inspect
import json
from pathlib import Path

from .contracts import require, sha
from .validation import Payload


SDK_SHA256 = {
    'acquisition_executor.py': 'cd39146d87c1951bd33881d8534bf775f54862290b6ce20d47873c83ef18b621',
    'identity_diag.py': 'd997d95a55759d2ed3fc4f676c123a9c51f7141a8fa8d86327606113760a6a95',
    'acquisition_support.py': 'dc47f6c7f9d746d5a4e8fa0aeb2d7a79e9a8b4947e866eca4485e821ea95c11a',
}


class CaptureFailure(RuntimeError):
    def __init__(self, code, *, needs_reset=False, cost=None, receipt=None):
        super().__init__(code)
        self.code, self.needs_reset = code, needs_reset
        self.cost, self.receipt = cost or {}, receipt


def verify_sdk_source(executor):
    root = Path(inspect.getfile(type(executor))).resolve().parent
    for name, expected in SDK_SHA256.items():
        require(sha((root / name).read_bytes()) == expected, 'SDK_SOURCE_CHANGED_' + name)


class SdkPort:
    execution_mode = 'sdk_adapter'

    def __init__(self, executor, lights_off):
        verify_sdk_source(executor)
        require(executor.mode == 'strict', 'SDK_STRICT_REQUIRED')
        self.executor, self._off = executor, lights_off

    def capture(self, request, context, profile, attempt_id, timeout_s, cancel):
        e = self.executor
        previous_publication = copy.deepcopy(getattr(e, '_publication', None))
        try:
            result = e.acquire(light_channel=request.channel, brightness=profile.brightness,
                               exposure_lines=request.exposure_lines, gain16=request.gain16,
                               roi=context.roi, board_mask=context.mask,
                               settle_frames=profile.settle_frames, discard_frames=profile.discard_frames,
                               timeout_s=timeout_s, cancel=cancel, sample_id=context.sample_id,
                               round_id=context.pose_id + '/' + attempt_id)
        except Exception as exc:
            cost = {}
            path = getattr(exc, 'record_path', None)
            if path is not None:
                try:
                    cost = json.loads(Path(path).read_bytes()).get('cost', {})
                except (OSError, ValueError):
                    cost = {'unavailable': True}
            publication = getattr(e, '_publication', None)
            raise CaptureFailure(getattr(exc, 'code', 'SDK_ERROR'), needs_reset=getattr(exc, 'needs_reset', True),
                                 cost=cost, receipt=copy.deepcopy(publication[0]) if publication and publication != previous_publication else None) from exc
        publication = e._publication
        require(publication is not None, 'SDK_PUBLICATION_MISSING')
        receipt, bank = copy.deepcopy(publication)
        require(receipt['session'] == e.session and receipt['request_id'] == e._request_id
                and receipt['frame_id'] == e._frame_id and all(receipt[k] == v for k, v in e._capture_context.items()), 'SDK_REQUEST_CONTEXT')
        record = json.loads(result.record_path.read_bytes())
        require(record == result.metadata and record['bank'] == bank
                and record['sample_id'] == context.sample_id and record['round_id'] == context.pose_id + '/' + attempt_id, 'SDK_COMMITTED_RECORD')
        raw = (result.record_path.parent / 'image.rgb565').read_bytes()
        require(raw == result.raw_rgb565, 'SDK_COMMITTED_RAW')
        return Payload(record, result.png_path.read_bytes(), raw, receipt, self.execution_mode)

    def lights_off(self):
        return self._off(self.executor)

    def close(self):
        self.executor.close()
