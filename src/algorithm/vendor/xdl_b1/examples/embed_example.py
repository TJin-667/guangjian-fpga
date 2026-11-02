"""Synthetic in-memory integration example. No camera, files, or real samples.

The production API is unchanged:
    single_features(frame) -> per-frame raw residual and validity
    fuse_two_stage(residuals, valid, board=board) -> directions, final
"""
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dual_exposure_b1.fusion import FRAME_ORDER, single_features, fuse_two_stage, maxabs_connect
import dual_exposure_b1.fusion as b1
import ymw_integer_reference
import light_inspection.real_baseline as baseline

# Frozen dependencies use these top-level names. Detect a host-module collision.
expected_software = Path(b1.__file__).resolve().parent / "frozen_reference" / "software"
if (Path(ymw_integer_reference.__file__).resolve().parent != expected_software
        or Path(baseline.__file__).resolve().parent != expected_software / "light_inspection"):
    raise RuntimeError("Frozen module path mismatch; see INTEGRATION.md")

# SYNTHETIC inputs only. Replace these with the host's eight completed frames.
height, width = 64, 96
yy, xx = np.indices((height, width))
frames_by_name = {}
for index, name in enumerate(FRAME_ORDER):
    gray = (65 + xx % 12 + index * 2).astype(np.uint8)
    gray[14 + index:16 + index, 12:50] = 12
    gray[30:48, 20 + index:22 + index] = 150
    gray[32:64, 64:96] = 255  # Entire tile invalid in every frame: unknown.
    frames_by_name[name] = np.repeat(gray[:, :, None], 3, axis=2)
board = np.ones((height, width), dtype=bool)
board[:4] = board[-4:] = False
board[:, :4] = board[:, -4:] = False

# Embedding block: preserve FRAME_ORDER; never feed intermediate binary masks.
assert set(frames_by_name) == set(FRAME_ORDER)
features = [single_features(frames_by_name[name]) for name in FRAME_ORDER]
residuals = np.stack([feature["residual_n"] for feature in features])
valid = np.stack([feature["valid"] for feature in features])
result = fuse_two_stage(residuals, valid, board=board)
final = result["final"]

# Direct eight-plane oracle, plus original single/low4/high4 inclusion.
direct = maxabs_connect(residuals, valid, source_ids=np.arange(1, 9), board=board)
for key in final:
    np.testing.assert_array_equal(final[key], direct[key])
for feature in features:
    assert not np.any((feature["mask"] & board) & ~final["mask"])
for offset, ids in ((0, [1, 3, 5, 7]), (1, [2, 4, 6, 8])):
    control = maxabs_connect(residuals[offset::2], valid[offset::2],
                             source_ids=np.array(ids), board=board)
    assert not np.any(control["mask"] & ~final["mask"])
assert final["unknown"][48, 80] and final["source_frame"][48, 80] == 0
assert final["residual_n"].dtype == np.int16
assert final["mask"].dtype == np.bool_
assert len(result["directions"]) == 4
assert all(value.shape == board.shape for value in final.values())

print(json.dumps({
    "fixture": "SYNTHETIC_NOT_REAL_SAMPLE",
    "frames": len(features), "shape_hw": list(board.shape),
    "candidate_pixels": int(final["mask"].sum()),
    "unknown_on_board": int((final["unknown"] & board).sum()),
    "two_stage_vs_direct": "PASS_ALL_FIELDS",
    "single_low4_high4_inclusion": "PASS",
    "numpy": np.__version__, "opencv": cv2.__version__,
}, ensure_ascii=False))
