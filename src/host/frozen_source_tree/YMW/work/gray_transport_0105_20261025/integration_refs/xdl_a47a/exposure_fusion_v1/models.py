"""Strict observation contract for one four-direction, two-exposure capture."""

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np

from .provenance import hardware_frame_identity


DIRECTIONS = ("CH1", "CH2", "CH3", "CH4")
ROLES = ("low", "high")


@dataclass(frozen=True)
class Observation:
    observation_id: str
    specimen_id: str
    pose_id: str
    direction: str
    exposure_role: str
    exposure_lines: int
    gain16: int
    led: int
    frame_id: str | int
    session_id: str
    hardware_identity: Mapping[str, int]
    source_sha256: str
    gray8_sha256: str
    sat1_sha256: str
    valid_mask_sha256: str
    roi_xywh: tuple[int, int, int, int]
    valid_mask_id: str
    frame_payload_sha256: str | None = None
    gray8: Any = None
    sat1: Any = None
    valid_mask: Any = None

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "Observation":
        values = dict(item)
        values["roi_xywh"] = tuple(values["roi_xywh"])
        return cls(**{key: values[key] for key in cls.__dataclass_fields__ if key in values})


@dataclass(frozen=True)
class ObservationGroup:
    specimen_id: str
    pose_id: str
    observations: tuple[Observation, ...]

    @classmethod
    def from_mapping(cls, group: Mapping[str, Any]) -> "ObservationGroup":
        obs = tuple(o if isinstance(o, Observation) else Observation.from_mapping(o)
                    for o in group["observations"])
        return cls(group["specimen_id"], group.get("pose_id", group.get("physical_pose_id")), obs)


def observation_dicts(group: Mapping[str, Any] | ObservationGroup) -> tuple[Observation, ...]:
    if isinstance(group, ObservationGroup):
        return group.observations
    if not isinstance(group, Mapping) or "observations" not in group:
        raise ValueError("group must be a mapping with observations")
    try:
        return tuple(o if isinstance(o, Observation) else Observation.from_mapping(o)
                     for o in group["observations"])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"malformed observation record: {exc}") from exc


def validate_group(group: Mapping[str, Any] | ObservationGroup) -> None:
    """Validate completeness, acquisition identity, fixed settings and image shapes."""
    obs = observation_dicts(group)
    if len(obs) != 8:
        raise ValueError("group must contain exactly eight observations")
    specimen_id = group.specimen_id if isinstance(group, ObservationGroup) else group.get("specimen_id")
    pose_id = group.pose_id if isinstance(group, ObservationGroup) else group.get(
        "pose_id", group.get("physical_pose_id"))
    if not specimen_id or not pose_id:
        raise ValueError("group requires specimen_id and pose_id")
    if any(o.specimen_id != specimen_id for o in obs):
        raise ValueError("specimen_id mismatch within group")
    if any(o.pose_id != pose_id for o in obs):
        raise ValueError("pose_id mismatch within group")

    slots = [(o.direction, o.exposure_role) for o in obs]
    expected = {(d, r) for d in DIRECTIONS for r in ROLES}
    if len(set(slots)) != 8 or set(slots) != expected:
        raise ValueError("group requires one observation in each CH1-CH4 low/high slot")
    if any(o.gain16 != 16 for o in obs):
        raise ValueError("gain16 must remain fixed at 16 (1x)")
    if any(o.led != 128 for o in obs):
        raise ValueError("LED must remain fixed at 128")
    if any(not isinstance(o.exposure_lines, int) or o.exposure_lines <= 0 for o in obs):
        raise ValueError("exposure_lines must be positive integers")

    low_levels = {o.exposure_lines for o in obs if o.exposure_role == "low"}
    high_levels = {o.exposure_lines for o in obs if o.exposure_role == "high"}
    if len(low_levels) != 1 or len(high_levels) != 1 or max(low_levels) >= min(high_levels):
        raise ValueError("all directions must use the same low/high exposure levels with low < high")

    for attr, label in (("roi_xywh", "ROI"), ("valid_mask_id", "valid mask")):
        if len({getattr(o, attr) for o in obs}) != 1:
            raise ValueError(f"{label} mismatch within group")
    for attribute in ("source_sha256", "gray8_sha256", "sat1_sha256", "valid_mask_sha256"):
        if any(not isinstance(getattr(o, attribute), str) or len(getattr(o, attribute)) != 64
               or any(c not in "0123456789abcdefABCDEF" for c in getattr(o, attribute)) for o in obs):
            raise ValueError(f"{attribute} must contain 64 hexadecimal characters")
    if len({o.valid_mask_sha256.lower() for o in obs}) != 1:
        raise ValueError("valid mask digest mismatch within group")
    if any(not o.observation_id or not o.session_id or o.frame_id is None for o in obs):
        raise ValueError("observation, session, and frame identity are required")
    if len({o.session_id for o in obs}) != 1:
        raise ValueError("session_id mismatch within group")
    identities = [hardware_frame_identity(o.session_id, o.frame_id, o.hardware_identity)
                  for o in obs]
    if len(set(identities)) != 8:
        raise ValueError("duplicate hardware frame identity within group")
    if len({o.observation_id for o in obs}) != 8:
        raise ValueError("duplicate observation_id within group")
    shapes = set()
    masks = []
    for o in obs:
        present = [o.gray8 is not None, o.sat1 is not None, o.valid_mask is not None]
        if any(present) and not all(present):
            raise ValueError("gray8, sat1, and valid_mask must be provided together")
        if all(present):
            shape = tuple(getattr(o.gray8, "shape", ()))
            if len(shape) != 2:
                raise ValueError("gray8 must be a two-dimensional array")
            if tuple(getattr(o.sat1, "shape", ())) != shape or tuple(
                    getattr(o.valid_mask, "shape", ())) != shape:
                raise ValueError("gray8, sat1, and valid_mask must have the same shape")
            sat = np.asarray(o.sat1)
            valid = np.asarray(o.valid_mask)
            if not np.isin(sat, (0, 1, False, True)).all():
                raise ValueError("SAT1 arrays must contain only 0/1")
            if not np.isin(valid, (0, 1, False, True)).all():
                raise ValueError("valid mask arrays must contain only 0/1")
            roi_x, roi_y, roi_w, roi_h = o.roi_xywh
            if roi_w <= 0 or roi_h <= 0 or shape != (roi_h, roi_w):
                raise ValueError("image dimensions must match the declared ROI width and height")
            shapes.add(shape)
            masks.append(np.asarray(o.valid_mask, dtype=bool))
    if len(shapes) > 1:
        raise ValueError("observation image dimensions mismatch within group")
    if len(masks) == 8 and not np.asarray(masks[0], dtype=bool).any():
        raise ValueError("valid mask must include at least one valid pixel")
    if len(masks) == 8 and any(not np.array_equal(masks[0], mask) for mask in masks[1:]):
        raise ValueError("valid mask contents mismatch within group")
