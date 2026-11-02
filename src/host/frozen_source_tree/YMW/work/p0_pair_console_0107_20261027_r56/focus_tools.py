"""Relative manual-focus metric, matching the old PIL Gaussian/Laplacian method."""
import math
import numpy as np
from PIL import ImageFilter

def rectangle(start,end,image_size,min_side=9):
    width,height=image_size
    values=tuple(float(v) for point in (start,end) for v in point)
    if not all(math.isfinite(v) for v in values):raise ValueError('Nonfinite focus rectangle')
    xa,ya,xb,yb=values
    x0=max(0,min(width,math.floor(min(xa,xb))));x1=max(0,min(width,math.ceil(max(xa,xb))))
    y0=max(0,min(height,math.floor(min(ya,yb))));y1=max(0,min(height,math.ceil(max(ya,yb))))
    if x1-x0<min_side or y1-y0<min_side:raise ValueError('Focus rectangle must be at least9x9 original pixels')
    return x0,y0,x1-x0,y1-y0

def measure(image,roi=None):
    if roi is None:roi=(0,0,image.width,image.height)
    x,y,width,height=roi
    if any(type(v) is not int for v in roi) or min(width,height)<9 or min(x,y)<0 or x+width>image.width or y+height>image.height:raise ValueError('Focus ROI outside source pixels')
    crop=image.crop((x,y,x+width,y+height))
    gray=np.asarray(crop.convert('L').filter(ImageFilter.GaussianBlur(1.0)),dtype=np.float32)
    laplace=4*gray[1:-1,1:-1]-gray[:-2,1:-1]-gray[2:,1:-1]
    laplace-=gray[1:-1,:-2]+gray[1:-1,2:]
    original=np.asarray(crop.convert('L'))
    return dict(score=float(laplace.var()),dark_percent=float(np.mean(original<=5))*100,
        bright_percent=float(np.mean(original>=250))*100,clipped_percent=float(np.mean((original<=5)|(original>=250)))*100,
        width=width,height=height,metric='PIL_GaussianBlur_sigma1_then_4_neighbor_Laplacian_variance',calibrated_probability=False)

class Tracker:
    def __init__(self):self.reset()
    def reset(self):self.key=None;self.best=None;self.current=None;self.best_record=None
    def accept(self,metric,key,record=None):
        if key!=self.key:self.reset();self.key=key
        self.current=metric['score']
        if self.best is None or self.current>self.best:self.best=self.current;self.best_record=record
        return self.best

def anchored_scroll(old_scale,new_scale,old_left,old_top,mouse,image_size,viewport_size):
    """Preserve the image pixel below the pointer, except at scroll boundaries."""
    image_x=(old_left+mouse[0])/old_scale;image_y=(old_top+mouse[1])/old_scale
    total_w=image_size[0]*new_scale;total_h=image_size[1]*new_scale
    left=min(max(0,image_x*new_scale-mouse[0]),max(0,total_w-viewport_size[0]))
    top=min(max(0,image_y*new_scale-mouse[1]),max(0,total_h-viewport_size[1]))
    return left,top
