"""First-frame location of a near-axis-aligned rectangular metal plate.

No image resizing, perspective warp or enhancement is applied to exported pixels.
This pilot assumes one fully visible rectangular plate brighter than its surround.
"""
from dataclasses import dataclass, asdict
import cv2
import numpy as np


@dataclass
class LocatorConfig:
    margin: int = 16
    min_edge_contrast: float = 8.0
    min_area_fraction: float = 0.08
    max_area_fraction: float = 0.80
    max_edge_slope: float = 0.10
    min_bright_percentile: float = 12.0


def read_image(path):
    image = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Cannot decode image: {path}")
    return image


def write_image(path, image):
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise ValueError('PNG encoding failed')
    encoded.tofile(str(path))


def _peaks(values, gap, count=8):
    work = np.asarray(values).copy()
    peaks = []
    for _ in range(count):
        index = int(work.argmax())
        peaks.append((index, float(work[index])))
        work[max(0, index-gap):index+gap+1] = 0
    return peaks


def _pair(values, span, config):
    values = np.asarray(values).copy()
    guard = max(16, int(.04*span))
    values[:guard] = 0
    values[-guard:] = 0
    peaks = _peaks(values, max(12, span//40))
    options = []
    for i, (a, sa) in enumerate(peaks):
        for b, sb in peaks[i+1:]:
            distance = abs(a-b)
            if 0.15*span < distance < 0.85*span and min(sa, sb) >= config.min_edge_contrast:
                options.append((sa+sb, min(a, b)+3, max(a, b)+3))
    if not options:
        raise ValueError('two reliable opposing edges not found')
    _, a, b = max(options)
    return a, b


def _fit_edge(gray, axis, guess, start, end, sign, config):
    positions = np.arange(start+12, end-12, 3)
    signed = gray[:, 6:] - gray[:, :-6] if axis == 'x' else gray[6:] - gray[:-6]
    picked, strength = [], []
    for pos in positions:
        lo, hi = max(3, guess-32), min((gray.shape[1] if axis == 'x' else gray.shape[0])-4, guess+33)
        values = signed[pos, lo-3:hi-3] if axis == 'x' else signed[lo-3:hi-3, pos]
        index = int(np.argmax(sign*values))
        picked.append(lo+index)
        strength.append(float(sign*values[index]))
    picked, strength = np.asarray(picked), np.asarray(strength)
    keep = strength >= max(3.0, config.min_edge_contrast/2)
    if keep.sum() < max(10, len(positions)//2):
        raise ValueError('plate edge has insufficient contrast/support')
    for _ in range(4):
        slope, intercept = np.polyfit(positions[keep], picked[keep], 1)
        error = np.abs(picked-(slope*positions+intercept))
        bound = max(2.5, 3*float(np.median(error[keep])))
        revised = keep & (error <= bound)
        if revised.sum() < 10:
            raise ValueError('edge fit unstable')
        keep = revised
    if abs(slope) > config.max_edge_slope:
        raise ValueError('rotation exceeds current locator support')
    return slope, intercept, float(keep.sum()/len(positions))


def _intersection(vertical, horizontal):
    # x = a*y+b; y = c*x+d
    a, b = vertical[:2]
    c, d = horizontal[:2]
    x = (a*d+b)/(1-a*c)
    return [x, c*x+d]


def geometry_from_polygon(polygon, shape, margin):
    if type(margin) is not int or margin < 4:
        raise ValueError('margin must be an integer >=4 for the 9x9 filter halo')
    h, w = shape[:2]
    points = np.asarray(polygon, np.float32)
    if points.shape != (4, 2) or not np.isfinite(points).all() or not cv2.isContourConvex(points):
        raise ValueError('four ordered convex plate corners required')
    if (points[:, 0] < 0).any() or (points[:, 0] >= w).any() or (points[:, 1] < 0).any() or (points[:, 1] >= h).any():
        raise ValueError('plate extends beyond the image; preserve full frame')
    # Export box encloses subpixel edge estimates, then adds a configurable halo.
    x0, y0 = np.floor(points.min(axis=0)).astype(int)-margin
    x1, y1 = np.ceil(points.max(axis=0)).astype(int)+margin+1
    clipped = x0 < 0 or y0 < 0 or x1 > w or y1 > h
    roi = [max(0, int(x0)), max(0, int(y0)), min(w, int(x1))-max(0, int(x0)), min(h, int(y1))-max(0, int(y0))]
    # Approximate geometric mask, independent of exposure validity or defects.
    mask = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(mask, np.rint(points).astype(np.int32), 255)
    return roi, mask, bool(clipped)


def locate_plate(first_image, config=None):
    config = config or LocatorConfig()
    h, w = first_image.shape[:2]
    base = dict(locator_version='rectangular_plate_v1', config=asdict(config),
                image_size=[w, h], status='needs_review', first_frame_only=True,
                contour_type='four fitted edges; approximate rectangular plate mask')
    gray = cv2.cvtColor(first_image, cv2.COLOR_BGR2GRAY)
    base['gray_p99'] = float(np.percentile(gray, 99))
    if base['gray_p99'] < config.min_bright_percentile:
        return dict(base, reason='first_frame_too_dark_to_locate', roi=[0, 0, w, h], polygon=None, margin_clipped=False), None
    smooth = cv2.GaussianBlur(gray.astype(np.float32), (9, 9), 0)
    try:
        dx = np.abs(smooth[:, 6:]-smooth[:, :-6])
        # Pilot prior: plate edges span much of the frame height. Not fixed x/y.
        rows = slice(int(.12*h), int(.93*h))
        # A narrow edge band tolerates slight rotation without fixing its origin.
        dx_band = cv2.dilate(dx, np.ones((1,17), np.uint8))
        x0, x1 = _pair(np.quantile(dx_band[rows], .5, axis=0), w, config)
        dy = np.abs(smooth[6:]-smooth[:-6])
        dy_band = cv2.dilate(dy, np.ones((17,1), np.uint8))
        y0, y1 = _pair(np.quantile(dy_band[:, x0+12:x1-12], .5, axis=1), h, config)
        left = _fit_edge(smooth, 'x', x0, y0, y1, +1, config)
        right = _fit_edge(smooth, 'x', x1, y0, y1, -1, config)
        top = _fit_edge(smooth, 'y', y0, x0, x1, +1, config)
        bottom = _fit_edge(smooth, 'y', y1, x0, x1, -1, config)
        polygon = np.array([_intersection(left, top), _intersection(right, top),
                            _intersection(right, bottom), _intersection(left, bottom)], np.float32)
        fraction = float(cv2.contourArea(polygon)/(w*h))
        if not config.min_area_fraction <= fraction <= config.max_area_fraction:
            raise ValueError('plate area outside configured range')
        roi, mask, clipped = geometry_from_polygon(polygon, first_image.shape, config.margin)
        return dict(base, status='auto_candidate_review_required', reason=None,
                    roi=roi, polygon=polygon.round(3).tolist(), margin_clipped=clipped,
                    plate_area_fraction=fraction, edge_support=[left[2], right[2], top[2], bottom[2]]), mask
    except (ValueError, np.linalg.LinAlgError) as exc:
        return dict(base, reason=str(exc), roi=[0, 0, w, h], polygon=None, margin_clipped=False), None


def crop_pixels(image, roi):
    x, y, w, h = roi
    if min(x,y) < 0 or min(w,h) <= 0 or x+w > image.shape[1] or y+h > image.shape[0]:
        raise ValueError('out-of-bounds ROI')
    return image[y:y+h, x:x+w].copy()


def overlay(image, geometry):
    display = image.copy()
    x, y, w, h = geometry['roi']
    cv2.rectangle(display, (x,y), (x+w-1,y+h-1), (0,255,0), 3)
    if geometry['polygon'] is not None:
        cv2.polylines(display, [np.rint(geometry['polygon']).astype(np.int32)], True, (0,255,255), 3)
    label = 'ROI with margin / plate boundary' if geometry['polygon'] is not None else 'LOCATION FAILED - FULL FRAME RETAINED'
    cv2.putText(display, label, (20,45), cv2.FONT_HERSHEY_SIMPLEX, .85, (0,0,255), 2, cv2.LINE_AA)
    return display
