"""Read-only validation for four-direction image capture manifests.

CSV values remain strings. Paths are resolved relative to the manifest and an
absolute image path plus the physical CSV line are attached to every parsed row.
Validation never modifies the CSV or its images.
"""

from __future__ import annotations

import csv
import hashlib
import math
import os
from pathlib import Path
import re

import cv2
import numpy as np


REQUIRED_COLUMNS = (
    "sample_id", "capture_id", "direction", "repeat_id", "image_path",
    "width", "height", "pixel_format", "exposure_us", "gain", "light_level",
    "config_version", "frame_status", "source_type", "annotation_status",
)
DIRECTIONS = ("E", "S", "W", "N")
_ENUMS = {
    "direction": DIRECTIONS,
    "source_type": ("real", "synthetic"),
    "pixel_format": ("GRAY8", "BGR8"),
    "frame_status": ("complete", "incomplete"),
    "annotation_status": ("pending", "normal", "defect", "uncertain"),
}
_SETTINGS = ("exposure_us", "gain", "light_level", "config_version")


def _positive_integer(value: str) -> int | None:
    if not re.fullmatch(r"[0-9]+", value):
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return number if number > 0 else None


def _validate_image(row: dict, dimensions: dict, errors: list[str]) -> None:
    prefix = f"Line {row['line']}"
    if not row["image_path"].strip() or not row["image_abspath"]:
        return
    image_path = Path(row["image_abspath"])
    try:
        if not image_path.is_file():
            errors.append(f"{prefix}: image is missing or is not a file: {image_path}")
            return
        encoded = np.fromfile(image_path, dtype=np.uint8)
        row["image_sha256"] = hashlib.sha256(encoded.tobytes()).hexdigest()
        image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED) if encoded.size else None
    except (OSError, ValueError, cv2.error) as exc:
        errors.append(f"{prefix}: image cannot be read: {image_path}: {exc}")
        return
    if image is None:
        errors.append(f"{prefix}: image is corrupt or cannot be decoded: {image_path}")
        return
    if image.dtype != np.uint8:
        errors.append(f"{prefix}: image must be uint8, found {image.dtype}")
    if image.ndim == 2:
        actual_format = "GRAY8"
    elif image.ndim == 3 and image.shape[2] in (1, 3):
        actual_format = "GRAY8" if image.shape[2] == 1 else "BGR8"
    else:
        errors.append(f"{prefix}: image must have one or three channels; shape={image.shape}")
        return
    if row["pixel_format"] in _ENUMS["pixel_format"] and row["pixel_format"] != actual_format:
        errors.append(
            f"{prefix}: pixel_format={row['pixel_format']} does not match image channels ({actual_format})"
        )
    actual = {"width": image.shape[1], "height": image.shape[0]}
    for field, expected in dimensions.items():
        if expected is not None and expected != actual[field]:
            errors.append(
                f"{prefix}: image dimension mismatch: {field}={expected}, actual {field}={actual[field]}"
            )


def _validate_row(row: dict, errors: list[str], warnings: list[str]) -> None:
    prefix = f"Line {row['line']}"
    for field in ("sample_id", "capture_id", "repeat_id", "config_version", "image_path", "light_level"):
        if not row[field].strip():
            errors.append(f"{prefix}: {field} must not be empty")
    for field, allowed in _ENUMS.items():
        if row[field] not in allowed:
            errors.append(f"{prefix}: invalid {field}={row[field]!r}; expected {', '.join(allowed)}")
    dimensions = {field: _positive_integer(row[field]) for field in ("width", "height")}
    for field, number in dimensions.items():
        if number is None:
            errors.append(f"{prefix}: {field} must be a positive integer")
    for field in ("exposure_us", "gain"):
        if row[field] == "unknown":
            continue
        try:
            value = float(row[field])
        except ValueError:
            value = math.nan
        if not math.isfinite(value) or value <= 0:
            errors.append(f"{prefix}: {field} must be finite and positive, or 'unknown'")
    for field in _SETTINGS:
        if row[field] == "unknown":
            warnings.append(f"{prefix}: {field} is unknown; comparability cannot be fully established")
    if row["frame_status"] == "incomplete":
        errors.append(f"{prefix}: incomplete frame cannot be used for comparison")
    _validate_image(row, dimensions, errors)


def _setting_key(field: str, value: str):
    # Numerically equal exposure/gain spellings represent the same setting.
    if field in ("exposure_us", "gain") and value != "unknown":
        try:
            number = float(value)
            if math.isfinite(number):
                return number
        except ValueError:
            pass
    return value


def _collect_groups(rows: list[dict], errors: list[str], warnings: list[str]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    sample_sources: dict[str, set[str]] = {}
    capture_lines: dict[str, int] = {}
    direction_lines: dict[tuple[str, str, str], int] = {}
    path_lines: dict[str, int] = {}
    hash_paths: dict[str, tuple[str, int]] = {}
    for row in rows:
        # resolve() handles relative aliases; normcase() also handles Windows
        # case aliases. Different filenames with identical bytes need review,
        # but may be legitimate captures and are therefore only warnings.
        path_key = os.path.normcase(row["image_abspath"])
        if path_key:
            if path_key in path_lines:
                errors.append(
                    f"Line {row['line']}: same image is referenced more than once; "
                    f"first seen on line {path_lines[path_key]}"
                )
            else:
                path_lines[path_key] = row["line"]
        digest = row["image_sha256"]
        if digest:
            if digest in hash_paths and hash_paths[digest][0] != path_key:
                warnings.append(
                    f"Line {row['line']}: image has identical file contents to line {hash_paths[digest][1]}; "
                    "verify that these are independent captures, not copied files"
                )
            else:
                hash_paths.setdefault(digest, (path_key, row["line"]))
        sample, repeat, capture = row["sample_id"], row["repeat_id"], row["capture_id"]
        if capture.strip():
            if capture in capture_lines:
                errors.append(
                    f"Line {row['line']}: duplicate capture_id={capture!r}; first seen on line {capture_lines[capture]}"
                )
            else:
                capture_lines[capture] = row["line"]
        if not sample.strip() or not repeat.strip():
            continue
        grouped.setdefault((sample, repeat), []).append(row)
        if row["source_type"] in _ENUMS["source_type"]:
            sample_sources.setdefault(sample, set()).add(row["source_type"])
        if row["direction"] in DIRECTIONS:
            key = (sample, repeat, row["direction"])
            if key in direction_lines:
                errors.append(
                    f"Line {row['line']}: duplicate (sample_id, repeat_id, direction)={key!r}; "
                    f"first seen on line {direction_lines[key]}"
                )
            else:
                direction_lines[key] = row["line"]
    for sample, sources in sample_sources.items():
        if len(sources) > 1:
            errors.append(
                f"Sample {sample!r}: mixed source_type real/synthetic is not allowed, including across repeats"
            )
    groups = []
    for (sample, repeat), members in grouped.items():
        directions = [direction for direction in DIRECTIONS if any(row["direction"] == direction for row in members)]
        missing = [direction for direction in DIRECTIONS if direction not in directions]
        sources = {row["source_type"] for row in members if row["source_type"] in _ENUMS["source_type"]}
        groups.append({
            "sample_id": sample,
            "repeat_id": repeat,
            "directions": directions,
            "missing_directions": missing,
            "source_type": next(iter(sources)) if len(sources) == 1 else "mixed" if sources else "unknown",
        })
        if missing:
            warnings.append(f"Sample {sample!r}, repeat {repeat!r}: missing directions {', '.join(missing)}")
        for field in _SETTINGS:
            values = {_setting_key(field, row[field]) for row in members}
            if len(values) > 1:
                warnings.append(
                    f"Sample {sample!r}, repeat {repeat!r}: {field} changes across directions; "
                    "comparability requires review of the calibrated per-direction settings"
                )
    return groups


def validate_manifest(path: str | Path) -> dict:
    """Return parsed rows, errors, warnings, and four-direction capture groups.

    Missing directions and unknown or changing acquisition settings are warnings.
    Invalid metadata, mixed source types within a sample, and unreadable or
    incompatible images are errors. Invalid manifests may contain partial rows;
    callers must inspect ``errors`` before using those rows for analysis.
    """
    result = {"rows": [], "errors": [], "warnings": [], "groups": []}
    rows, errors, warnings = result["rows"], result["errors"], result["warnings"]
    try:
        manifest_path = Path(path).resolve()
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            header = next(reader, None)
            if not header:
                errors.append("Manifest is empty: a CSV header and data rows are required")
                return result
            missing = [name for name in REQUIRED_COLUMNS if name not in header]
            if missing:
                errors.append(f"Missing required columns: {', '.join(missing)}")
            if len(set(header)) != len(header) or any(not name.strip() for name in header):
                errors.append("CSV column names must be nonempty and unique")
            if any(name in header for name in ("image_abspath", "image_sha256", "line")):
                errors.append("CSV columns image_abspath, image_sha256 and line are reserved for validation output")
            if errors:
                return result
            while True:
                line = reader.line_num + 1
                cells = next(reader, None)
                if cells is None:
                    break
                if len(cells) != len(header):
                    errors.append(
                        f"Line {line}: malformed CSV row has {len(cells)} fields; expected {len(header)}"
                    )
                    continue
                row = dict(zip(header, cells))
                row["line"] = line
                row["image_abspath"] = ""
                row["image_sha256"] = ""
                if row["image_path"].strip():
                    try:
                        image_path = Path(row["image_path"])
                        if not image_path.is_absolute():
                            image_path = manifest_path.parent / image_path
                        row["image_abspath"] = str(image_path.resolve())
                    except (OSError, ValueError, RuntimeError) as exc:
                        errors.append(f"Line {line}: invalid image_path: {exc}")
                rows.append(row)
                _validate_row(row, errors, warnings)
            if not rows:
                errors.append("Manifest is empty: no validly shaped data rows were found")
    except (OSError, UnicodeError, csv.Error, ValueError, RuntimeError) as exc:
        errors.append(f"Cannot read manifest: {exc}")
    result["groups"] = _collect_groups(rows, errors, warnings)
    return result
