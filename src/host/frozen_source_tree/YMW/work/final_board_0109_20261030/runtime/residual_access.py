"""Exact on-demand H2 evidence from native gray; bounded host tile cache, no wire change."""
from collections import OrderedDict
import cv2
import numpy as np

class ResidualAccess:
    """Read-only logical[8,H,W] signed numerator plane for frozen review index calls."""
    def __init__(self,gray,*,tile_size=64,max_tiles=256):
        if gray.dtype!=np.uint8 or gray.ndim!=3 or gray.shape[0]!=8 or min(gray.shape[1:])<9:raise ValueError('Native eightGRAY8 planes required')
        if tile_size<1 or max_tiles<1:raise ValueError('Positive cache limits required')
        self.gray=gray.copy();self.gray.flags.writeable=False;self.shape=gray.shape;self.dtype=np.dtype('int16')
        self.tile_size=tile_size;self.max_tiles=max_tiles;self.cache=OrderedDict();self.computed_tiles=0;self.peak_cache_bytes=0
    @staticmethod
    def reflect(indices,size):
        period=2*(size-1);m=np.mod(indices,period);return np.minimum(m,period-m).astype(int)
    def tile(self,frame,ty,tx):
        key=(frame,ty,tx)
        if key in self.cache:self.cache.move_to_end(key);return self.cache[key]
        h,w=self.shape[1:];y0=ty*self.tile_size;x0=tx*self.tile_size;y1=min(h,y0+self.tile_size);x1=min(w,x0+self.tile_size)
        ys=self.reflect(np.arange(y0-4,y1+4),h);xs=self.reflect(np.arange(x0-4,x1+4),w)
        patch=self.gray[frame][np.ix_(ys,xs)]
        sums=cv2.boxFilter(patch,cv2.CV_32S,(9,9),normalize=False,borderType=cv2.BORDER_CONSTANT)[4:-4,4:-4]
        result=(81*self.gray[frame,y0:y1,x0:x1].astype('int32')-sums).astype('int16');result.flags.writeable=False
        self.cache[key]=result;self.computed_tiles+=1
        while len(self.cache)>self.max_tiles:self.cache.popitem(last=False)
        self.peak_cache_bytes=max(self.peak_cache_bytes,sum(v.nbytes for v in self.cache.values()))
        return result
    def __getitem__(self,key):
        if not isinstance(key,tuple) or len(key)!=3:raise IndexError('Use real frame,y,x native indices')
        frame,yy,xx=key
        if not isinstance(frame,(int,np.integer)) or not 0<=frame<8:raise IndexError('Invalid real frame')
        yy,xx=np.broadcast_arrays(np.asarray(yy),np.asarray(xx))
        if yy.dtype.kind not in 'iu' or xx.dtype.kind not in 'iu' or np.any(yy<0) or np.any(xx<0) or np.any(yy>=self.shape[1]) or np.any(xx>=self.shape[2]):raise IndexError('Native coordinates outside savedROI')
        shape=yy.shape;y=yy.ravel();x=xx.ravel();out=np.empty(y.size,'int16');tx=x//self.tile_size;ty=y//self.tile_size
        keys=ty*((self.shape[2]+self.tile_size-1)//self.tile_size)+tx
        for encoded in np.unique(keys):
            ids=np.flatnonzero(keys==encoded);row=int(ty[ids[0]]);column=int(tx[ids[0]]);values=self.tile(int(frame),row,column)
            out[ids]=values[y[ids]-row*self.tile_size,x[ids]-column*self.tile_size]
        return out.reshape(shape)
