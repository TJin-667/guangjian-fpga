"""Exact H1/H2 reference operations for the revision-2 YMW handoff."""
from pathlib import Path

import cv2
import numpy as np


def integer_gray(image):
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.size == 0:
        raise ValueError('Expected a nonempty uint8 image.')
    if image.ndim == 2:
        return image.copy()
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('Expected grayscale or three-channel BGR.')
    values = image.astype(np.uint32)
    return ((9798 * values[:, :, 2] + 19235 * values[:, :, 1]
             + 3735 * values[:, :, 0] + 16384) >> 15).astype(np.uint8)


def integer_h2(gray):
    if not isinstance(gray, np.ndarray) or gray.dtype != np.uint8 or gray.ndim != 2:
        raise ValueError('Expected a uint8 gray matrix.')
    if min(gray.shape, default=0) < 9:
        raise ValueError('Saved image dimensions must be at least 9.')
    padded = np.pad(gray, 4, mode='reflect').astype(np.int64)
    integral = np.pad(padded.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    sums = integral[9:, 9:] - integral[:-9, 9:] - integral[9:, :-9] + integral[:-9, :-9]
    numerator = gray.astype(np.int32) * 81 - sums
    return {'sum9': sums.astype('<u2'), 'residual_n': numerator.astype('<i2')}


def integer_thresholds(residual_n):
    values = np.abs(np.asarray(residual_n).astype(np.int32))
    return values > 648, values > 1620


def board_mask(shape, polygon, origin):
    poly = np.asarray(polygon, np.float32)
    if poly.ndim != 2 or poly.shape[1] != 2 or len(poly) < 3 or not np.isfinite(poly).all():
        raise ValueError('Expected a finite board polygon.')
    local = np.rint(poly - np.asarray(origin)).astype(np.int32)
    mask = np.zeros(shape, np.uint8)
    cv2.fillConvexPoly(mask, local, 1)
    mask = cv2.erode(mask, np.ones((15, 15), np.uint8))
    mask[:4] = mask[-4:] = 0
    mask[:, :4] = mask[:, -4:] = 0
    if not mask.any():
        raise ValueError('Board mask is empty.')
    return mask.astype(bool)


def save_arrays(path, arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        np.savez_compressed(stream, **arrays)


def decode_rgb565(path, width, height):
    words = np.fromfile(path, dtype='>u2')
    if words.size != width * height:
        raise ValueError('RGB565 length does not match saved dimensions.')
    words = words.reshape(height, width)
    red, green, blue = (words >> 11) & 31, (words >> 5) & 63, words & 31
    return np.stack(((blue << 3) | (blue >> 2), (green << 2) | (green >> 4),
                     (red << 3) | (red >> 2)), axis=2).astype(np.uint8)
