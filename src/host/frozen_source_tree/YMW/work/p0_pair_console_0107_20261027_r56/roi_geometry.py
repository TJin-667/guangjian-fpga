"""Axis-aligned native sensor ROI; no deskew, warp, resizing or interpolation."""
import math
import numpy as np

GRID=32
MIN_MARGIN=16

def build(points,sensor_size,margin_px=16):
    if type(margin_px) is not int or not MIN_MARGIN<=margin_px<=256:raise ValueError('板外余量请输入16～256的整数像素')
    width,height=map(int,sensor_size);p=np.asarray(points,dtype=np.float64)
    if p.shape!=(4,2) or not np.isfinite(p).all():raise ValueError('Select four finite board corners')
    if min(width,height)<9 or (p<0).any() or (p[:,0]>=width).any() or (p[:,1]>=height).any():raise ValueError('Board corners outside sensor')
    low=np.floor(p.min(axis=0)).astype(int)-margin_px
    high=np.ceil(p.max(axis=0)).astype(int)+margin_px+1
    x=max(0,math.floor(int(low[0])/GRID)*GRID);y=max(0,math.floor(int(low[1])/GRID)*GRID)
    right=min(width,math.ceil(int(high[0])/GRID)*GRID);bottom=min(height,math.ceil(int(high[1])/GRID)*GRID)
    roi=[x,y,right-x,bottom-y]
    if min(roi[2:])<9:raise ValueError('ROI too small')
    return dict(schema='guangjian-native-axis-ROI-v1',sensor_size=[width,height],points_xy=p.tolist(),
        roi_xywh=roi,source_origin_xy=[x,y],requested_margin_px=margin_px,tile_grid_px=GRID,
        requested_margin_clipped_by_sensor=bool((low<0).any() or high[0]>width or high[1]>height),
        pixels_resampled=False,deskew=False,RGB_pixel_payload_fraction=roi[2]*roi[3]/(width*height))
