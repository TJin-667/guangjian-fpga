"""Low/high exposure and four-direction evidence baselines."""

from dataclasses import dataclass

import numpy as np

from .features import extract_evidence
from .models import DIRECTIONS, observation_dicts, validate_group


@dataclass(frozen=True)
class DirectionEvidence:
    direction: str
    bright: np.ndarray
    dark: np.ndarray
    low_bright: np.ndarray
    high_bright: np.ndarray
    low_dark: np.ndarray
    high_dark: np.ndarray
    sat_low: np.ndarray
    sat_high: np.ndarray
    reliability_low: np.ndarray
    reliability_high: np.ndarray
    scale_low: np.ndarray
    scale_high: np.ndarray


@dataclass(frozen=True)
class FusionResult:
    bright: np.ndarray
    dark: np.ndarray
    source_direction: np.ndarray
    source_role: np.ndarray
    source_direction_bright: np.ndarray
    source_direction_dark: np.ndarray
    source_role_bright: np.ndarray
    source_role_dark: np.ndarray
    direction_names: tuple[str, ...]
    role_names: tuple[str, ...]
    direction_evidence: tuple[DirectionEvidence, ...]
    mode: str
    high_weight: float

    @property
    def score(self):
        """Polarity-preserving summary used only for path scoring."""
        return np.maximum(self.bright, self.dark)


def _take_observation(observations, direction, role):
    return next(o for o in observations if o.direction == direction and o.exposure_role == role)


def prepare_evidence(group):
    """Calculate immutable per-frame evidence once for several fusion modes."""
    validate_group(group)
    prepared = {}
    for observation in observation_dicts(group):
        if any(getattr(observation, key) is None for key in ("gray8", "sat1", "valid_mask")):
            raise ValueError(f"missing gray8/sat1/valid_mask image arrays for {observation.observation_id}")
        prepared[observation.observation_id] = extract_evidence(
            observation.gray8, observation.sat1, observation.valid_mask)
    return prepared


def fuse_group(group, mode="equal_weight", high_weight=0.5, evidence_cache=None) -> FusionResult:
    """Fuse one complete group; annotations are deliberately not accepted here."""
    if mode not in {"low_only", "high_only", "equal_weight", "weighted"}:
        raise ValueError("mode must be low_only, high_only, equal_weight, or weighted")
    if not np.isfinite(high_weight) or not 0.0 <= high_weight <= 1.0:
        raise ValueError("high_weight must be between zero and one")
    if mode == "equal_weight" and high_weight != 0.5:
        raise ValueError("equal_weight requires high_weight exactly 0.5; use weighted for other values")
    validate_group(group)
    observations = observation_dicts(group)
    direction_evidence = []
    mode_weight = 0.0 if mode == "low_only" else 1.0 if mode == "high_only" else high_weight
    if evidence_cache is None:
        evidence_cache = prepare_evidence(group)
    for direction in DIRECTIONS:
        low = _take_observation(observations, direction, "low")
        high = _take_observation(observations, direction, "high")
        try:
            low_maps, high_maps = evidence_cache[low.observation_id], evidence_cache[high.observation_id]
        except KeyError as exc:
            raise ValueError(f"evidence cache is missing observation {exc.args[0]}") from exc
        b_low, b_high = low_maps.bright * (1.0 - mode_weight), high_maps.bright * mode_weight
        d_low, d_high = low_maps.dark * (1.0 - mode_weight), high_maps.dark * mode_weight
        if mode == "low_only":
            b_low, d_low = low_maps.bright, low_maps.dark
            b_high, d_high = np.zeros_like(b_low), np.zeros_like(d_low)
        elif mode == "high_only":
            b_low, d_low = np.zeros_like(high_maps.bright), np.zeros_like(high_maps.dark)
            b_high, d_high = high_maps.bright, high_maps.dark
        direction_evidence.append(DirectionEvidence(
            direction, b_low + b_high, d_low + d_high,
            b_low, b_high, d_low, d_high,
            low_maps.saturation_fraction, high_maps.saturation_fraction,
            low_maps.reliability, high_maps.reliability, low_maps.scale, high_maps.scale))

    bright_stack = np.stack([d.bright for d in direction_evidence])
    dark_stack = np.stack([d.dark for d in direction_evidence])
    source_direction_bright = bright_stack.argmax(axis=0).astype(np.uint8)
    source_direction_dark = dark_stack.argmax(axis=0).astype(np.uint8)
    bright = bright_stack.max(axis=0).astype(np.float32)
    dark = dark_stack.max(axis=0).astype(np.float32)
    has_bright = bright > 0
    has_dark = dark > 0
    source_direction_bright[~has_bright] = 255
    source_direction_dark[~has_dark] = 255
    selected = [direction_evidence[i] for i in range(len(DIRECTIONS))]
    source_role_bright = np.full(bright.shape, 255, dtype=np.uint8)
    source_role_dark = np.full(dark.shape, 255, dtype=np.uint8)
    for index, item in enumerate(selected):
        chosen_bright = (source_direction_bright == index) & has_bright
        chosen_dark = (source_direction_dark == index) & has_dark
        source_role_bright[chosen_bright & (item.low_bright > item.high_bright)] = 0
        source_role_bright[chosen_bright & (item.high_bright > item.low_bright)] = 1
        source_role_dark[chosen_dark & (item.low_dark > item.high_dark)] = 0
        source_role_dark[chosen_dark & (item.high_dark > item.low_dark)] = 1
    use_bright = bright >= dark
    source_direction = np.where(use_bright, source_direction_bright, source_direction_dark).astype(np.uint8)
    source_role = np.where(use_bright, source_role_bright, source_role_dark).astype(np.uint8)
    no_evidence = ~(has_bright | has_dark)
    source_direction[no_evidence] = 255
    source_role[no_evidence] = 255
    return FusionResult(bright, dark, source_direction, source_role,
                        source_direction_bright, source_direction_dark,
                        source_role_bright, source_role_dark, DIRECTIONS, ("low", "high"),
                        tuple(direction_evidence), mode, mode_weight)
