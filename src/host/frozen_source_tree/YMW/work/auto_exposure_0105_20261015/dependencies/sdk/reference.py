"""tj-image-v1 integer oracle and original-pixel ROI, without illumination judgments."""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Config:
    width: int
    height: int
    x: int
    y: int
    roi_width: int
    roi_height: int
    black: int = 5
    white: int = 250

    def validate(self):
        values = vars(self)
        if any(type(v) is not int for v in values.values()):
            raise ValueError('integer parameters required')
        if not (1 <= self.width <= 1920 and 1 <= self.height <= 1080):
            raise ValueError('input geometry outside 1920x1080 capacity')
        if not (self.x >= 0 and self.y >= 0 and self.roi_width > 0 and self.roi_height > 0
                and self.x+self.roi_width <= self.width and self.y+self.roi_height <= self.height):
            raise ValueError('empty or out-of-bounds ROI')
        if not 0 <= self.black < self.white <= 255:
            raise ValueError('require 0 <= black < white <= 255')


def expand_rgb565(words):
    v = np.asarray(words, dtype=np.uint32)
    r, g, b = v >> 11, (v >> 5) & 63, v & 31
    return np.stack(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)), axis=-1).astype(np.uint8)


def gray_rgb565(words):
    rgb = expand_rgb565(words).astype(np.uint32)
    return ((9798*rgb[...,0]+19235*rgb[...,1]+3735*rgb[...,2]+16384) >> 15).astype(np.uint8)


def crop_and_stats(words, config):
    config.validate()
    if words.shape != (config.height, config.width) or words.dtype.kind != 'u' or words.dtype.itemsize != 2:
        raise ValueError('expected full-frame uint16 RGB565 array')
    region = np.s_[config.y:config.y+config.roi_height, config.x:config.x+config.roi_width]
    crop = words[region].copy()
    gray = gray_rgb565(words)[region]
    stats = dict(pixel_count=int(gray.size), gray_sum=int(gray.sum(dtype=np.uint64)),
                 near_black=int((gray <= config.black).sum()), near_white=int((gray >= config.white).sum()),
                 gray_min=int(gray.min()), gray_max=int(gray.max()),
                 dynamic_range=int(gray.max())-int(gray.min()))
    return crop, gray, stats


def payloads(words, payload_bytes=1380):
    if payload_bytes <= 0 or payload_bytes % 2:
        raise ValueError('positive even packet capacity required')
    raw = np.asarray(words, dtype='>u2').tobytes()
    return [raw[i:i+payload_bytes] for i in range(0,len(raw),payload_bytes)]
