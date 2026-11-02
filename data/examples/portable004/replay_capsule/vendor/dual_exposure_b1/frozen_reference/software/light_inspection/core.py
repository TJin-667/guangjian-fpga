"""Floating-point local-background baseline, before any hardware quantization."""
from dataclasses import asdict, dataclass
import json
import math
from numbers import Real
from pathlib import Path

import cv2
import numpy as np

from .image_io import validate_image


@dataclass(frozen=True)
class AnalysisConfig:
    background_window: int = 9
    threshold: float = 20.0
    roi: tuple[int, int, int, int] | None = None

    def validate(self) -> None:
        k = self.background_window
        if type(k) is not int or k < 3 or k % 2 != 1:
            raise ValueError('background_window must be an odd integer >= 3.')
        if (isinstance(self.threshold, bool) or not isinstance(self.threshold, Real)
                or not math.isfinite(self.threshold) or not 0 <= self.threshold <= 255):
            raise ValueError('threshold must be a finite number from 0 to 255.')
        if self.roi is not None:
            if (not isinstance(self.roi, (tuple, list)) or len(self.roi) != 4
                    or any(type(v) is not int for v in self.roi)):
                raise ValueError('roi must contain four integers: x y width height.')
            x, y, w, h = self.roi
            if x < 0 or y < 0 or w <= 0 or h <= 0:
                raise ValueError('roi must have nonnegative origin and positive dimensions.')

    def to_dict(self) -> dict:
        return {'schema_version': 1, **asdict(self)}


def load_config(path: str | Path | None = None) -> AnalysisConfig:
    if path is None:
        return AnalysisConfig()
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ValueError(f'Cannot load configuration: {exc}') from exc
    if not isinstance(payload, dict):
        raise ValueError('Configuration must be a JSON object.')
    allowed = {'schema_version', 'background_window', 'threshold', 'roi'}
    if set(payload) - allowed:
        raise ValueError(f'Unknown configuration keys: {sorted(set(payload) - allowed)}')
    if type(payload.get('schema_version', 1)) is not int or payload.get('schema_version', 1) != 1:
        raise ValueError('Unsupported schema_version; expected 1.')
    values = {k: v for k, v in payload.items() if k != 'schema_version'}
    if isinstance(values.get('roi'), list):
        values['roi'] = tuple(values['roi'])
    config = AnalysisConfig(**values)
    config.validate()
    return config


def analyze_image(image: np.ndarray, config: AnalysisConfig) -> dict:
    validate_image(image)
    config.validate()
    gray_full = image.copy() if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray_full.shape
    k = config.background_window
    if k > min(width, height):
        raise ValueError('background_window exceeds input image dimensions.')
    x, y, w, h = config.roi if config.roi is not None else (0, 0, width, height)
    if x + w > width or y + h > height:
        raise ValueError('roi lies outside input image.')
    # Compute on the full image first: changing ROI does not change a pixel's background.
    background_full = cv2.blur(gray_full.astype(np.float32), (k, k),
                               borderType=cv2.BORDER_REFLECT_101)
    gray = gray_full[y:y + h, x:x + w].copy()
    background = background_full[y:y + h, x:x + w].copy()
    residual = gray.astype(np.float32) - background
    bright = np.maximum(residual, 0)
    dark = np.maximum(-residual, 0)
    mask = np.abs(residual) > config.threshold
    histogram = np.bincount(gray.ravel(), minlength=256)
    # Descriptive values only. These do not establish noise, defocus, or frame validity.
    lap = cv2.Laplacian(gray.astype(np.float32), cv2.CV_32F,
                        borderType=cv2.BORDER_REFLECT_101)
    metrics = {
        'interpretation': 'diagnostic_only', 'input_width': width, 'input_height': height,
        'roi': [x, y, w, h], 'analyzed_pixels': int(gray.size),
        'gray_mean': float(gray.mean()), 'gray_std': float(gray.std()),
        'gray_min': int(gray.min()), 'gray_max': int(gray.max()),
        'near_black_fraction': float(np.mean(gray <= 5)),
        'near_white_fraction': float(np.mean(gray >= 250)),
        'laplacian_variance': float(lap.var()),
        'candidate_pixels': int(mask.sum()), 'candidate_fraction': float(mask.mean()),
        'residual_min': float(residual.min()), 'residual_max': float(residual.max()),
    }
    return {'gray': gray, 'background': background, 'residual': residual,
            'bright': bright, 'dark': dark, 'mask': mask, 'histogram': histogram,
            'metrics': metrics}
