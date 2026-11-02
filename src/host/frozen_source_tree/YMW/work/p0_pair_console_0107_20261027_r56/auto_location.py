"""Reuse the existing host locator on the already captured positioning image."""
from pathlib import Path
import plate_locator
import capture_backend as backend

def propose(png):
    png=Path(png)
    try:
        image=plate_locator.read_image(png);geometry,_=plate_locator.locate_plate(image)
        if geometry['status']=='auto_candidate_review_required':
            backend.polygon_mask(geometry['polygon'],(image.shape[1],image.shape[0]))
            points=geometry['polygon']
        else:points=[]
        return dict(status=geometry['status'],points=points,geometry=geometry,source_sha256=backend.sha(png),
            full_source_RGB_retained=True,ROI_crop_applied_to_formal_P0=False,
            note='Host geometry proposal only; operator confirmation still required. XDL P0 requests full1920x1080 source.')
    except Exception as exc:
        return dict(status='needs_manual_selection',points=[],error=str(exc))
