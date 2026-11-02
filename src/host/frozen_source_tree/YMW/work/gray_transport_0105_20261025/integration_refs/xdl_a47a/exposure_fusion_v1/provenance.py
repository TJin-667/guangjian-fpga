"""Frame identity and gray/SAT payload binding helpers."""

import hashlib
import json
from collections.abc import Mapping

import numpy as np


HARDWARE_ID_FIELDS = (
    "request_id", "config_epoch", "dvp_sequence", "publish_sequence",
    "roi_generation", "camera_generation", "light_generation", "bank",
)


def normalize_hardware_identity(value):
    if not isinstance(value, Mapping):
        raise ValueError("hardware_identity must be an object")
    missing = [name for name in HARDWARE_ID_FIELDS if name not in value]
    if missing:
        raise ValueError(f"hardware_identity is missing fields: {', '.join(missing)}")
    normalized = []
    for name in HARDWARE_ID_FIELDS:
        number = value[name]
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise ValueError(f"hardware_identity.{name} must be a nonnegative integer")
        normalized.append(number)
    return tuple(normalized)


def hardware_frame_identity(session_id, frame_id, hardware_identity):
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id is required for hardware frame identity")
    if isinstance(frame_id, bool) or not isinstance(frame_id, (int, str)) or str(frame_id) == "":
        raise ValueError("frame_id is required for hardware frame identity")
    return (session_id, *normalize_hardware_identity(hardware_identity), str(frame_id))


def gray_sat_payload_sha256(session_id, frame_id, hardware_identity, source_sha256,
                            roi_xywh, gray8, sat1):
    """Bind grayscale-source derivatives to the exact frame and ROI.

    Acquisition must calculate/record this digest from the same published frame;
    consumers recompute it and compare. It cannot be inferred from gray8 alone.
    """
    identity = hardware_frame_identity(session_id, frame_id, hardware_identity)
    if len(roi_xywh) != 4 or any(isinstance(v, bool) or not isinstance(v, int) for v in roi_xywh):
        raise ValueError("roi_xywh must contain four integers")
    gray = np.ascontiguousarray(gray8, dtype=np.uint8)
    sat = np.ascontiguousarray(sat1, dtype=np.uint8)
    if gray.ndim != 2 or sat.shape != gray.shape:
        raise ValueError("gray8 and SAT1 payload arrays must be same-shape 2D arrays")
    source_digest = str(source_sha256).lower()
    if len(source_digest) != 64 or any(c not in "0123456789abcdef" for c in source_digest):
        raise ValueError("source_sha256 must be a SHA-256 hex digest")
    metadata = {
        "schema": "XDL_GRAY8_SAT1_FRAME_V1",
        "identity": list(identity),
        "roi_xywh": list(roi_xywh),
        "shape_hw": list(gray.shape),
        "source_sha256": source_digest,
    }
    digest = hashlib.sha256()
    digest.update(b"XDL_GRAY8_SAT1_FRAME_V1\0")
    digest.update(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    digest.update(b"\0GRAY8\0")
    digest.update(gray.tobytes(order="C"))
    digest.update(b"\0SAT1\0")
    digest.update(sat.tobytes(order="C"))
    return digest.hexdigest()
