"""Manifest runner. Incomplete capture groups produce a WAITING result, never padding."""

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from software.ymw_integer_reference import decode_rgb565, integer_gray
from .fusion import fuse_group, prepare_evidence
from .models import DIRECTIONS, ROLES, Observation, validate_group
from .provenance import gray_sat_payload_sha256, hardware_frame_identity


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_image(path, grayscale=False, source_width=None, source_height=None):
    path = Path(path)
    if path.suffix.lower() == ".rgb565":
        if not isinstance(source_width, int) or not isinstance(source_height, int):
            raise ValueError("RGB565 source requires integer source_width and source_height")
        data = decode_rgb565(path, source_width, source_height)
    elif path.suffix.lower() == ".npy":
        data = np.load(path, allow_pickle=False)
    else:
        data = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if data is None:
            raise ValueError(f"could not read image: {path}")
    if grayscale and data.ndim == 3:
        data = integer_gray(data)
    return data


def _resolved_path(value, base_dir):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def _verify_artifact(record, path_key, digest_key, base_dir):
    if path_key not in record or digest_key not in record:
        raise ValueError(f"every observation requires {path_key} and {digest_key}")
    path = _resolved_path(record[path_key], base_dir)
    if not path.is_file():
        raise ValueError(f"input artifact not found: {path}")
    digest = _sha256(path).lower()
    if digest != str(record[digest_key]).lower():
        raise ValueError(f"{digest_key} mismatch: {path}")
    return path, digest


def _verify_source_derivatives(source_path, gray8, sat1, roi_xywh, record, source_digest):
    if source_path.suffix.lower() == ".rgb565":
        source = _load_image(source_path, source_width=record.get("source_width"),
                             source_height=record.get("source_height"))
    else:
        source = _load_image(source_path)
    source_gray = integer_gray(source)
    x, y, width, height = roi_xywh
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("ROI must have nonnegative origin and positive dimensions")
    origin = record.get("source_origin_xy", [0, 0])
    if len(origin) != 2 or any(type(v) is not int or v < 0 for v in origin):
        raise ValueError("source_origin_xy requires two nonnegative integers")
    local_x, local_y = x - origin[0], y - origin[1]
    if local_x < 0 or local_y < 0:
        raise ValueError("Analysis ROI starts before the saved source origin")
    if record.get("source_coordinate_space") == "saved_roi":
        if origin != [x, y] or source_gray.shape != (height, width):
            raise ValueError("Saved native ROI source shape/origin differs")
        sensor = record.get("sensor_size_xy")
        if not isinstance(sensor, (list, tuple)) or len(sensor) != 2 or any(type(v) is not int or v <= 0 for v in sensor):
            raise ValueError("Saved ROI requires original sensor dimensions")
        if x + width > sensor[0] or y + height > sensor[1]:
            raise ValueError("ROI exceeds original sensor")
        hardware_roi = record.get("hardware_capture_roi_xywh", list(roi_xywh))
        if record.get("crop_applied_at") == "native_acquisition_ROI" and list(hardware_roi) != list(roi_xywh):
            raise ValueError("Native acquisition ROI and saved source ROI differ")
    crop = source_gray[local_y:local_y + height, local_x:local_x + width]
    if crop.shape != tuple(gray8.shape) or not np.array_equal(crop, gray8):
        raise ValueError("gray8 does not match frozen integer gray/crop from source")
    if source.ndim == 3:
        if source.shape[2] != 3:
            raise ValueError("color source must have exactly three channels for frozen SAT1 verification")
        expected_sat1 = np.any(source == 255, axis=2).astype(np.uint8)
        expected_crop = expected_sat1[local_y:local_y + height, local_x:local_x + width]
        actual = np.asarray(sat1)
        if actual.shape != expected_crop.shape or not np.array_equal(actual.astype(bool), expected_crop.astype(bool)):
            raise ValueError("SAT1 does not match source pixelwise max-code mask")
    else:
        supplied = record.get("frame_payload_sha256")
        if not isinstance(supplied, str) or len(supplied) != 64:
            raise ValueError("grayscale source requires acquisition-provided frame_payload_sha256")
        expected = gray_sat_payload_sha256(
            record["session_id"], record["frame_id"], record["hardware_identity"], source_digest,
            tuple(roi_xywh), gray8, sat1)
        if expected.lower() != supplied.lower():
            raise ValueError("frame_payload_sha256 mismatch for bound gray8/SAT1/hardware identity/ROI")


def _load_observation(record, base_dir):
    values = dict(record)
    sources = {
        "source_path": "source_sha256",
        "gray8_path": "gray8_sha256",
        "sat1_path": "sat1_sha256",
        "valid_mask_path": "valid_mask_sha256",
    }
    artifacts = {path_key: _verify_artifact(values, path_key, digest_key, base_dir)
                 for path_key, digest_key in sources.items()}
    source_path = artifacts["source_path"][0]
    values["gray8"] = _load_image(artifacts["gray8_path"][0], grayscale=True)
    values["sat1"] = _load_image(artifacts["sat1_path"][0])
    values["valid_mask"] = _load_image(artifacts["valid_mask_path"][0])
    _verify_source_derivatives(source_path, values["gray8"], values["sat1"],
                               values["roi_xywh"], values, artifacts["source_path"][1])
    for path_key in sources:
        values.pop(path_key, None)
    observation = Observation.from_mapping(values)
    provenance = {path_key: {"path": str(path), "sha256": digest}
                  for path_key, (path, digest) in artifacts.items()}
    return observation, provenance


def _missing_slots(records):
    seen = set()
    for record in records:
        if record.get("direction") in DIRECTIONS and record.get("exposure_role") in ROLES:
            seen.add((record["direction"], record["exposure_role"]))
    return [f"{direction}_{role}" for direction in DIRECTIONS for role in ROLES
            if (direction, role) not in seen]


def _group_file_key(group_id):
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", group_id).strip("._-")[:48] or "group"
    suffix = hashlib.sha256(group_id.encode("utf-8")).hexdigest()[:12]
    return f"{slug}_{suffix}"


def _publish_new_directory(output_dir, write_contents):
    if output_dir.exists():
        raise FileExistsError(f"output must be a new result directory: {output_dir}")
    if not output_dir.parent.is_dir():
        raise FileNotFoundError(f"output parent directory does not exist: {output_dir.parent}")
    with tempfile.TemporaryDirectory(prefix=f".{output_dir.name}.stage-", dir=output_dir.parent) as stage:
        stage_path = Path(stage)
        write_contents(stage_path)
        if output_dir.exists():
            raise FileExistsError(f"output was created during run; refusing overwrite: {output_dir}")
        os.rename(stage_path, output_dir)


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_fusion_figure(fused, path):
    score_scale = max(1e-6, float(np.percentile(fused.score, 99.0)))
    height, width = fused.score.shape
    scale = min(480.0 / width, 480.0 / height, 1.0)
    out_w, out_h = max(1, int(round(width * scale))), max(1, int(round(height * scale)))
    labels = ("bright evidence", "dark evidence", "winning direction (255=none)")
    panels = []
    for source, label in ((fused.bright, labels[0]), (fused.dark, labels[1])):
        normalized = np.clip(source / score_scale * 255.0, 0, 255).astype(np.uint8)
        image = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
        image = cv2.resize(image, (out_w, out_h), interpolation=cv2.INTER_AREA)
        panels.append((label, image))
    palette = np.array([[0, 0, 255], [0, 190, 0], [255, 80, 0], [0, 210, 255]], np.uint8)
    provenance = np.zeros((height, width, 3), np.uint8)
    for index, color in enumerate(palette):
        provenance[fused.source_direction == index] = color
    provenance = cv2.resize(provenance, (out_w, out_h), interpolation=cv2.INTER_NEAREST)
    panels.append((labels[2], provenance))
    panel_w, panel_h, label_h = 500, 500, 36
    canvas = np.full((panel_h + label_h + 24, 3 * panel_w + 4 * 16, 3), 248, np.uint8)
    for index, (label, image) in enumerate(panels):
        x = 16 + index * (panel_w + 16)
        y = label_h + 16
        x0, y0 = x + (panel_w - out_w) // 2, y + (panel_h - out_h) // 2
        canvas[y0:y0 + out_h, x0:x0 + out_w] = image
        cv2.putText(canvas, label, (x, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                    (20, 20, 20), 1, cv2.LINE_AA)
    cv2.putText(canvas, f"{fused.mode}; shared display scale p99={score_scale:.4g}; provenance colors CH1 red, CH2 green, CH3 blue, CH4 yellow",
                (16, canvas.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (20, 20, 20), 1, cv2.LINE_AA)
    if not cv2.imwrite(str(path), canvas):
        raise IOError(f"could not write fusion figure: {path}")


def run_manifest(manifest_path, output_dir):
    manifest_path = Path(manifest_path).resolve()
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError(f"output must be a new result directory: {output_dir}")
    if not output_dir.parent.is_dir():
        raise FileNotFoundError(f"output parent directory does not exist: {output_dir.parent}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    groups = manifest.get("groups", [])
    if not groups:
        raise ValueError("manifest must contain at least one group")
    group_ids = []
    waiting = []
    seen_identities = {}
    for group in groups:
        records = group.get("observations", [])
        group_id = group.get("group_id")
        if not isinstance(group_id, str) or not group_id.strip():
            raise ValueError("each group requires a nonempty group_id")
        group_ids.append(group_id)
        slot_counts = {}
        invalid_slots = []
        for record in records:
            try:
                identity = hardware_frame_identity(record.get("session_id"), record.get("frame_id"),
                                                   record.get("hardware_identity"))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"invalid hardware frame identity in group {group_id}: {exc}") from exc
            previous = seen_identities.get(identity)
            if previous is not None:
                raise ValueError(f"duplicate hardware frame identity across manifest: {previous} and {group_id}")
            seen_identities[identity] = group_id
            slot = (record.get("direction"), record.get("exposure_role"))
            if slot[0] not in DIRECTIONS or slot[1] not in ROLES:
                invalid_slots.append(slot)
            else:
                slot_counts[slot] = slot_counts.get(slot, 0) + 1
        duplicates = [slot for slot, count in slot_counts.items() if count > 1]
        if invalid_slots or duplicates or len(records) > 8:
            raise ValueError(f"invalid observation slots in group {group_id}: "
                             f"invalid={invalid_slots}, duplicates={duplicates}, count={len(records)}")
        missing = _missing_slots(records)
        if missing or len(records) < 8:
            waiting.append({"group_id": group_id, "specimen_id": group.get("specimen_id"),
                            "pose_id": group.get("pose_id", group.get("physical_pose_id")),
                            "missing_slots": missing,
                            "observation_count": len(records)})
    if len(set(group_ids)) != len(group_ids):
        raise ValueError("group_id must be unique within a manifest")
    file_keys = [_group_file_key(group_id) for group_id in group_ids]
    if len(set(file_keys)) != len(file_keys):
        raise ValueError("group_id values collide after output-name normalization")
    input_digest = _sha256(manifest_path)
    if waiting:
        result = {
            "status": "WAITING_FOR_PAIRED_DATA",
            "manifest_sha256": input_digest,
            "dataset_revision": manifest.get("dataset_revision"),
            "groups_waiting": waiting,
            "decision": "NO_EXPOSURE_SELECTED",
            "reason": "A complete same-pose CH1-CH4 low/high group is required; no frame was synthesized.",
        }
        def write_waiting(stage):
            _write_json(stage / "run_status.json", result)
            with (stage / "input_to_action_log.csv").open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.DictWriter(stream, fieldnames=["group_id", "specimen_id", "pose_id",
                                                              "input_status", "next_action", "reason"])
                writer.writeheader()
                for item in waiting:
                    writer.writerow({"group_id": item["group_id"], "specimen_id": item["specimen_id"],
                                     "pose_id": item["pose_id"], "input_status": "INCOMPLETE",
                                     "next_action": "WAIT_FOR_MISSING_FRAMES",
                                     "reason": ";".join(item["missing_slots"])})
        _publish_new_directory(output_dir, write_waiting)
        return 2

    base_dir = manifest_path.parent
    loaded_groups = []
    all_source_paths = set()
    for raw_group in groups:
        resolved_source_paths = [_resolved_path(record.get("source_path", ""), base_dir)
                                 for record in raw_group["observations"]]
        if len(set(resolved_source_paths)) != 8:
            raise ValueError(f"same resolved source file cannot fill two slots in group {raw_group['group_id']}")
        reused = all_source_paths.intersection(resolved_source_paths)
        if reused:
            raise ValueError(f"same resolved source file reused across groups: {sorted(map(str, reused))}")
        all_source_paths.update(resolved_source_paths)
        loaded = tuple(_load_observation(record, base_dir) for record in raw_group["observations"])
        obs = tuple(item[0] for item in loaded)
        artifacts_by_id = {item[0].observation_id: item[1] for item in loaded}
        group = {"specimen_id": raw_group["specimen_id"],
                 "pose_id": raw_group.get("pose_id", raw_group.get("physical_pose_id")),
                 "observations": obs}
        validate_group(group)
        loaded_groups.append((raw_group, group, artifacts_by_id))

    rows = []
    completed = []
    def write_complete(stage):
        for raw_group, group, artifacts_by_id in loaded_groups:
            evidence_cache = prepare_evidence(group)
            specimen_key = _group_file_key(raw_group["group_id"])
            obs = group["observations"]
            input_summary = []
            for observation in obs:
                valid_count = int(np.count_nonzero(observation.valid_mask))
                sat_count = int(np.count_nonzero(observation.sat1.astype(bool) & observation.valid_mask.astype(bool)))
                input_summary.append({
                    "observation_id": observation.observation_id,
                    "frame_id": observation.frame_id,
                    "session_id": observation.session_id,
                    "hardware_identity": dict(observation.hardware_identity),
                    "direction": observation.direction,
                    "exposure_role": observation.exposure_role,
                    "exposure_lines": observation.exposure_lines,
                    "gain16": observation.gain16,
                    "led": observation.led,
                    "roi_xywh": list(observation.roi_xywh),
                    "valid_mask_id": observation.valid_mask_id,
                    "frame_payload_sha256": observation.frame_payload_sha256,
                    "valid_pixels": valid_count,
                    "sat1_valid_pixels": sat_count,
                    "sat1_fraction_of_valid": sat_count / valid_count if valid_count else None,
                    "artifacts": artifacts_by_id[observation.observation_id],
                })
            for mode in ("low_only", "high_only", "equal_weight"):
                fused = fuse_group(group, mode, evidence_cache=evidence_cache)
                stem = f"fusion_{specimen_key}_{mode}"
                npz_path = stage / f"{stem}.npz"
                arrays = {
                    "bright": fused.bright, "dark": fused.dark,
                    "source_direction": fused.source_direction, "source_role": fused.source_role,
                    "source_direction_bright": fused.source_direction_bright,
                    "source_direction_dark": fused.source_direction_dark,
                    "source_role_bright": fused.source_role_bright,
                    "source_role_dark": fused.source_role_dark,
                }
                for evidence in fused.direction_evidence:
                    prefix = evidence.direction
                    arrays[f"{prefix}_bright"] = evidence.bright
                    arrays[f"{prefix}_dark"] = evidence.dark
                    arrays[f"{prefix}_low_bright_contribution"] = evidence.low_bright
                    arrays[f"{prefix}_high_bright_contribution"] = evidence.high_bright
                    arrays[f"{prefix}_low_dark_contribution"] = evidence.low_dark
                    arrays[f"{prefix}_high_dark_contribution"] = evidence.high_dark
                    arrays[f"{prefix}_low_sat_fraction"] = evidence.sat_low
                    arrays[f"{prefix}_high_sat_fraction"] = evidence.sat_high
                    arrays[f"{prefix}_low_reliability"] = evidence.reliability_low
                    arrays[f"{prefix}_high_reliability"] = evidence.reliability_high
                    arrays[f"{prefix}_low_scale"] = evidence.scale_low
                    arrays[f"{prefix}_high_scale"] = evidence.scale_high
                np.savez_compressed(npz_path, **arrays)
                figure_path = stage / f"{stem}.png"
                _write_fusion_figure(fused, figure_path)
                rows.append({"group_id": raw_group["group_id"], "specimen_id": group["specimen_id"],
                             "pose_id": group["pose_id"], "input_status": "COMPLETE", "mode": mode,
                             "next_action": "REVIEW_EVIDENCE_AND_LABELS",
                             "reason": "Offline evidence only; candidate count does not select an exposure."})
                completed.append({"group_id": raw_group["group_id"], "specimen_id": group["specimen_id"],
                                  "pose_id": group["pose_id"], "mode": mode,
                                  "score_map": npz_path.name, "diagnostic_figure": figure_path.name,
                                  "score_max": float(np.max(fused.score)),
                                  "score_mean": float(np.mean(fused.score)),
                                  "source_direction_pixel_counts": {
                                      name: int(np.count_nonzero(fused.source_direction == i))
                                      for i, name in enumerate(fused.direction_names)},
                                  "inputs": input_summary})
        with (stage / "input_to_action_log.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=["group_id", "specimen_id", "pose_id",
                                                          "input_status", "mode", "next_action", "reason"])
            writer.writeheader()
            writer.writerows(rows)
        result = {
            "status": "BASELINES_COMPLETE_LABELS_REQUIRED",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "manifest_sha256": input_digest,
            "dataset_revision": manifest.get("dataset_revision"),
            "exposure_pair_status": manifest.get("exposure_pair_status"),
            "exposure_selection": "NOT_SELECTED",
            "weight_fit": "WAITING_FOR_REVIEWED_DEVELOPMENT_LABELS",
            "groups": completed,
            "note": "This is offline evidence fusion. It does not establish detection accuracy, an optimum exposure, or FPGA closed-loop operation.",
        }
        _write_json(stage / "run_status.json", result)
    _publish_new_directory(output_dir, write_complete)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="JSON manifest for one or more eight-frame groups")
    parser.add_argument("--output", required=True, help="new result directory")
    args = parser.parse_args(argv)
    return run_manifest(args.manifest, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
