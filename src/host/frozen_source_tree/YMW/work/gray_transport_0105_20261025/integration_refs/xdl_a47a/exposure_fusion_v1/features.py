"""Polarity-separated image evidence using the frozen integer H2 residual."""

from dataclasses import dataclass

import numpy as np

from software.ymw_integer_reference import integer_h2


@dataclass(frozen=True)
class EvidenceMaps:
    bright: np.ndarray
    dark: np.ndarray
    reliability: np.ndarray
    scale: np.ndarray
    residual_n: np.ndarray
    saturation_fraction: np.ndarray


def _as_binary_mask(mask, name, shape):
    arr = np.asarray(mask)
    if arr.shape != shape:
        raise ValueError(f"{name} must have the same shape as gray8")
    if not np.isin(arr, (0, 1, False, True)).all():
        raise ValueError(f"{name} must contain only zero/one values")
    return arr.astype(bool, copy=False)


def extract_evidence(gray8, sat1, valid_mask, tile_size=32) -> EvidenceMaps:
    """Return continuous bright/dark evidence and tile reliability.

    The per-tile scale is a provisional 1.4826*MAD of unsaturated valid gray
    samples, floored at one gray level. It is a local-contrast proxy, not a
    calibrated camera-noise or SNR estimate. Saturation lowers a tile's
    reliability but does not zero the saturated pixels or the rest of that tile.
    """
    gray = np.asarray(gray8)
    if gray.dtype != np.uint8 or gray.ndim != 2 or min(gray.shape, default=0) < 9:
        raise ValueError("gray8 must be a uint8 2D image at least 9x9")
    if not isinstance(tile_size, int) or tile_size <= 0:
        raise ValueError("tile_size must be a positive integer")
    saturation = _as_binary_mask(sat1, "sat1", gray.shape)
    valid = _as_binary_mask(valid_mask, "valid_mask", gray.shape)
    residual_n = integer_h2(gray)["residual_n"].astype(np.int32)
    height, width = gray.shape
    scale = np.ones(gray.shape, dtype=np.float32)
    reliability = np.ones(gray.shape, dtype=np.float32)
    saturation_fraction = np.zeros(gray.shape, dtype=np.float32)

    for y0 in range(0, height, tile_size):
        y1 = min(height, y0 + tile_size)
        for x0 in range(0, width, tile_size):
            x1 = min(width, x0 + tile_size)
            tile = np.s_[y0:y1, x0:x1]
            use = valid[tile] & ~saturation[tile]
            samples = gray[tile][use].astype(np.float32)
            if samples.size:
                median = float(np.median(samples))
                mad = float(np.median(np.abs(samples - median)))
                local_scale = max(1.0, 1.4826 * mad)
            else:
                local_scale = 1.0
            valid_count = int(valid[tile].sum())
            sat_fraction = float((saturation[tile] & valid[tile]).sum() / valid_count) if valid_count else 0.0
            # Preserve a nonzero floor so saturation remains evidence with a risk tag.
            tile_reliability = max(0.15, 1.0 - sat_fraction)
            scale[tile] = local_scale
            reliability[tile] = tile_reliability
            saturation_fraction[tile] = sat_fraction

    normalized = residual_n.astype(np.float32) / (81.0 * scale)
    # Residual magnitudes are at most 255 gray levels after division by 81;
    # retain this range so exposure strength is not flattened by early clipping.
    bright = np.clip(np.maximum(normalized, 0.0), 0.0, 255.0) * reliability
    dark = np.clip(np.maximum(-normalized, 0.0), 0.0, 255.0) * reliability
    bright[~valid] = 0.0
    dark[~valid] = 0.0
    return EvidenceMaps(bright.astype(np.float32), dark.astype(np.float32), reliability,
                        scale, residual_n.astype(np.int16), saturation_fraction)
