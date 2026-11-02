"""Unicode-safe, explicit-depth image input. Never modify an input file."""
from pathlib import Path

import cv2
import numpy as np


def validate_image(image: np.ndarray) -> None:
    if not isinstance(image, np.ndarray) or image.size == 0:
        raise ValueError('Image is empty or not an array.')
    if image.dtype != np.uint8:
        raise ValueError('Only 8-bit input is supported; preserve and explicitly convert other depths.')
    if image.ndim != 2 and not (image.ndim == 3 and image.shape[2] == 3):
        raise ValueError('Expected GRAY8 or BGR8 image; alpha/multichannel input is unsupported.')


def read_image(path: str | Path) -> np.ndarray:
    path = Path(path)
    try:
        data = np.fromfile(path, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED) if data.size else None
    except (OSError, cv2.error) as exc:
        raise ValueError(f'Cannot read image {path}: {exc}') from exc
    if image is None:
        raise ValueError(f'Corrupt or unsupported image: {path}')
    validate_image(image)
    return image


def write_png(path: str | Path, image: np.ndarray) -> None:
    validate_image(image)
    path = Path(path)
    if path.suffix.lower() != '.png':
        raise ValueError('write_png requires a .png path.')
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise ValueError(f'Cannot encode PNG: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects any original or earlier output.
    with path.open('xb') as stream:
        stream.write(encoded.tobytes())
