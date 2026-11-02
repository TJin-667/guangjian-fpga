"""Count reported wait/drop frames only when a complete transaction is proven.

A publication/cancellation failure can occur AFTER image/identity validation.
That image must not drive the controller, but its proven frame cost is retained.
Before that point, unknown device counts stay None and only a lower bound is used.
"""
import json
from pathlib import Path


def proven_frames(call, call_directory, dependencies):
    if not call:
        return None
    try:
        root = Path(call_directory)
        tag, meta = call["identity"], call["diagnostic"]
        trace = [json.loads(line) for line in (root/"frame_trace.jsonl").read_text(
            encoding="utf-8").splitlines()]
        if not any(event["event"]=="result_verified" and event.get("identity")==tag
                   and event.get("bank")==call["bank"] for event in trace):
            return None
        raw_path = next((root/place/"image.rgb565" for place in
                         ("committed","pending","quarantined")
                         if (root/place/"image.rgb565").is_file()),None)
        if raw_path is None:
            return None
        dependencies.sdk.identity_diag.require_association(
            meta,tag["session"],tag["request_id"],tag["frame_id"],
            raw_path.read_bytes(),expected_context=tag)
        wait, drop = call["device_reported_settle_frames"], call["device_reported_discard_frames"]
        if (type(wait) is not int or type(drop) is not int or
                wait!=call["requested"]["settle_frames"] or drop!=call["requested"]["discard_frames"] or
                meta["parameters"]!=call["actual_parameters"]):
            return None
        return wait+drop+1
    except (OSError,ValueError,KeyError,TypeError,StopIteration):
        return None
