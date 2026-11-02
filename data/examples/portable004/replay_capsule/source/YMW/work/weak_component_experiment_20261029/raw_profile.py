"""Same-observation raw line profiles around fragments; no annotation access."""
import math
import cv2
import numpy as np

CONFIG=dict(tangent_samples=13,orientation_count=8,normal_flank_offset_px=3.,center_strip_offsets_px=[-.5,0,.5],
    same_polarity_contrast_floor=1.,min_support_fraction=.65,min_mean_two_sided_contrast=2.,
    all_samples_require_board_and_same_frame_validity=True,geometry_gap_pixels_added=False)

def inspect_profile(center,gray,valid,board):
    best=dict(evidence_margin=0.,accepted=False,frame=0,orientation_degrees=0.,polarity=0,support_fraction=0.,mean_two_sided_contrast=0.,valid_fits_tested=0)
    h,w=board.shape;valid_fits=0
    for orientation in range(CONFIG['orientation_count']):
        theta=orientation*math.pi/CONFIG['orientation_count'];tangent=np.array([math.cos(theta),math.sin(theta)]);normal=np.array([-tangent[1],tangent[0]])
        positions=np.asarray(center,dtype=float)[None,:]+np.arange(-6,7)[:,None]*tangent
        paths=[positions+offset*normal for offset in [-.5,0,.5,3.,-3.]]
        indices=[];inside=True
        for points in paths:
            x=np.floor(points[:,0]).astype(int);y=np.floor(points[:,1]).astype(int)
            if (x<0).any() or (y<0).any() or (x+1>=w).any() or (y+1>=h).any():inside=False;break
            indices.append((y,x))
        if not inside:continue
        for frame,image in enumerate(gray):
            okay=True
            for y,x in indices:
                for dy,dx in ((0,0),(0,1),(1,0),(1,1)):
                    if not np.all(valid[frame,y+dy,x+dx]&board[y+dy,x+dx]):okay=False;break
                if not okay:break
            if not okay:continue
            valid_fits+=1
            values=[cv2.remap(image.astype('float32',copy=False),points[:,0].astype('float32')[None,:],points[:,1].astype('float32')[None,:],cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT).ravel() for points in paths]
            center_value=.25*values[0]+.5*values[1]+.25*values[2];p,m=values[3:]
            for polarity,contrast in ((1,np.minimum(center_value-p,center_value-m)),(-1,np.minimum(p-center_value,m-center_value))):
                fraction=float(np.mean(contrast>=CONFIG['same_polarity_contrast_floor']));mean=float(contrast.mean());margin=min(fraction/CONFIG['min_support_fraction'],mean/CONFIG['min_mean_two_sided_contrast'])
                if margin>best['evidence_margin']:
                    best=dict(evidence_margin=margin,accepted=margin>=1.,frame=frame+1,orientation_degrees=float(theta*180/math.pi),polarity=polarity,support_fraction=fraction,mean_two_sided_contrast=mean,valid_fits_tested=0)
    best['valid_fits_tested']=valid_fits
    return best

def raw_profile_gate(protected,loose,gray,valid,board,retained_supplement):
    if gray.shape!=(8,*board.shape) or valid.shape!=gray.shape:raise ValueError('Eight actual native observations required')
    gray=gray.astype('float32',copy=False)
    new=loose&~protected;n,labels,stats,centroids=cv2.connectedComponentsWithStats(new.astype('uint8'),connectivity=8)
    admitted=[];rows=[]
    for label in range(1,n):
        evidence=inspect_profile(centroids[label],gray,valid,board);rows.append(dict(component=label,centroid_xy=centroids[label].tolist(),bbox_xywh=stats[label,:4].tolist(),area=int(stats[label,4]),**evidence))
        if evidence['accepted']:admitted.append(label)
    raw=np.isin(labels,admitted)&new
    result={}
    for mode,supplement in [('raw_profile',raw),('line_plus_raw',raw|retained_supplement)]:
        candidate=protected|supplement;review=new&~supplement
        if (protected&~candidate).any() or (candidate&~loose).any() or not np.array_equal(supplement|review,new):raise AssertionError('Profile partition contract failed')
        result[mode]=dict(candidate=candidate,line_supplement=supplement,review=review)
    return result,dict(config=CONFIG,components=rows,accepted_components=len(admitted))
