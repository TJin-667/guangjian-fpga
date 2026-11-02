"""Engineering workaround for0109 BEGIN seeing last-capture ROI geometry.

One strict native ROI preparation frame is kept outside the eight observations.
The existing SDK/RTL, formal slots, fusion and detector remain unchanged.
"""
def executor_class(implementation):
    sdk=implementation.sdk
    class ROIPreparedExecutor(implementation.EngineeringExecutor):
        _preparing_native_roi=False
        def acquire_roi_preparation(self,**kwargs):
            if self._off_group_live or self._off_slot or self._preparing_native_roi:raise ValueError('ROI preparation must precede group BEGIN')
            self._preparing_native_roi=True
            try:return sdk.TransportExecutor.acquire(self,**kwargs)
            finally:self._preparing_native_roi=False
        def _capture(self,*,strict=True):
            if self._preparing_native_roi:return sdk.TransportExecutor._capture(self,strict=strict)
            return super()._capture(strict=strict)
        def _publish_verified(self,meta,after,rectangle):
            if self._preparing_native_roi:return sdk.TransportExecutor._publish_verified(self,meta,after,rectangle)
            return super()._publish_verified(meta,after,rectangle)
    return ROIPreparedExecutor
