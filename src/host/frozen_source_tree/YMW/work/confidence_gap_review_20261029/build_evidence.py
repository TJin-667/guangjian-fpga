"""Post-prediction figures/cards and development-only path comparison."""
import argparse,json,os,sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw
from gap_review import analyze
from run_study import read,write,sha,font,sheet

HERE=Path(__file__).resolve().parent;PRIOR=HERE.parent/'confidence_shadow_review_20261029';REPO=HERE.parents[2]

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True,type=Path);a=p.parse_args();root=a.run.resolve();inputs=read(root/'VERIFICATION.json')['input_files_sha256'];cards=root/'cards';cards.mkdir(exist_ok=False);indices=[]
    for rec in read(root/'RESULTS.json'):
        group=rec['group_id'];source=Path(rec['root'])/'arrays/original_eight_frames.npz';assert sha(source)==inputs[str(source)];summary=read(Path(rec['root'])/'summary.json');roi=summary['roi_xywh']
        with np.load(source,allow_pickle=False) as z:gray=z['gray'].copy()
        for gap in read(root/group/'GAP_REVIEWS.json'):
            if not gap['review']:continue
            x,y,w,h=gap['selected_probe']['bbox_xywh'];cx=x+w//2;cy=y+h//2;cw=min(gray.shape[2],max(80,w+28));ch=min(gray.shape[1],max(64,h+28));x0=max(0,min(gray.shape[2]-cw,cx-cw//2));y0=max(0,min(gray.shape[1]-ch,cy-ch//2));card=Image.new('RGB',(1200,660),'#eef2f7');d=ImageDraw.Draw(card);d.text((12,7),f'{rec["sample"]} G{gap["id"]}：八帧原片核对（未增强对比）',font=font(20),fill='#17314c');d.text((12,35),'缺口只是复检建议；两端检测像素不计入缺口证据；不自动补线',font=font(15),fill='#526374')
            for i,frame in enumerate((0,2,4,6,1,3,5,7)):
                panel=Image.new('RGB',(300,300),'white');dd=ImageDraw.Draw(panel);dd.text((8,8),f'CH{frame//2+1} '+('400行' if frame%2==0 else '800行'),font=font(18),fill='#17314c');im=Image.fromarray(gray[frame,y0:y0+ch,x0:x0+cw]).convert('RGB');scale=min(280/cw,240/ch);im=im.resize((int(cw*scale),int(ch*scale)),Image.Resampling.NEAREST);panel.paste(im,((300-im.width)//2,48+(240-im.height)//2));card.paste(panel,(i%4*300,60+i//4*300))
            name=f'{group}_G{gap["id"]:03d}';card.save(cards/(name+'.png'));meta=dict(id=name,group_id=group,gap_id=gap['id'],crop_native_xywh=[x0,y0,cw,ch],crop_full_saved_xywh=[x0+roi[0],y0+roi[1],cw,ch],best_fit=gap['selected_probe']['best_fit'],manual_class=None,manual_notes=None);write(cards/(name+'.json'),meta);indices.append(meta)
    write(root/'CARD_INDEX.json',indices)
    group='sample004_A_v1_20261028_220937_87f02b';ann=read(REPO/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json');xy=np.array(ann['path_points']);xs=xy[:,0].astype(int);ys=np.rint(xy[:,1]).astype(int)
    with np.load(root/group/'arrays.npz') as z:formal=z['formal_detector_mask'];new=z['supported_gap_sample_mask']
    with np.load(PRIOR/'results'/group/'confidence_reference_arrays.npz') as z:old=z['raw_validated_station_mask']
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7));hit=lambda m:cv2.dilate(m.astype('uint8'),kernel)[ys,xs]>0;missing=~formal[ys[:,None]+np.arange(-3,4),xs[:,None]].any(1);o=hit(old);n=hit(new);write(root/'SAMPLE004_COMPLEMENT_CHECK.json',dict(development_case_only=True,not_recall=True,uncovered=int(missing.sum()),prior_v4_near_raw=int((missing&o).sum()),gap_near_raw=int((missing&n).sum()),union_near_raw=int((missing&(o|n)).sum()),incremental_near_raw=int((missing&n&~o).sum()),formal_detector_not_changed=True))
    rec=next(r for r in read(root/'RESULTS.json') if r['group_id']==group)
    with np.load(Path(rec['root'])/'arrays/original_eight_frames.npz') as z:gray=z['gray'].copy()
    x0,x1=int(xs.min())-35,int(xs.max())+40;y0,y1=int(ys.min())-35,int(ys.max())+35;mean=np.rint(gray.astype('float32').mean(0)).astype('uint8');base=np.repeat(mean[:,:,None],3,axis=2);detected=base.copy();detected[formal]=[255,210,0];reference=base.copy();reference[old]=[255,55,175];reference[new]=[0,235,245];tiles=[]
    for name,image in [('原片CH2 800行',gray[3]),('原片CH4 800行',gray[7]),('正式检测保持不变',detected),('粉点上版；青点本轮缺口证据',reference)]:
        im=Image.fromarray(image[y0:y1,x0:x1]).convert('RGB');im=im.resize((im.width*2,im.height*2),Image.Resampling.NEAREST);tiles.append((name,im))
    sheet(tiles,root/'sample004_gap_evidence.png',columns=2,cell=(640,320))
    sys.path.insert(0,'E:/GuangjianData/software/analysis_dependencies_20261029');os.environ.setdefault('MPLCONFIGDIR',str(root/'matplotlib_cache'));import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont('C:/Windows/Fonts/msyh.ttc');plt.rcParams['font.family']=font_manager.FontProperties(fname='C:/Windows/Fonts/msyh.ttc').get_name();plt.rcParams['axes.unicode_minus']=False
    # Compare the real development gap to an explicitly synthetic empty break.
    from test_gap_review import scene
    synthetic=[]
    for continuous in (True,False):
        data=scene(continuous);result=analyze(*data,read(HERE/'PLAN.json'));g=result['gaps'][0]['selected_probe'];fit=next(f for f in g['fits'] if f['frame']==4 and f['polarity']==-1);synthetic.append(fit)
    g=next(g for g in read(root/group/'GAP_REVIEWS.json') if g['id']==44);real=g['selected_probe']['best_fit'];fig,ax=plt.subplots(figsize=(9,4.4));series=[('004实拍G44：CH2低曝、暗线',real,'#007a85'),('合成连续弱线（不是实拍）',synthetic[0],'#6666bb'),('合成空白断口（不是实拍）',synthetic[1],'#d47b21')]
    for label,fit,color in series:ax.plot([r['weak'] for r in fit['threshold_curve']],[r['fraction'] for r in fit['threshold_curve']],marker='o',label=label,color=color)
    ax.invert_xaxis();ax.set_ylim(-.03,1.04);ax.set_xlabel('残差阈值（灰度级）：从严到宽');ax.set_ylabel('缺口内有响应的采样比例');ax.set_title('只看缺口内部：阈值放宽是否出现连续弱细节');ax.grid(alpha=.22);ax.legend(fontsize=9,loc='upper left');fig.tight_layout();fig.savefig(root/'threshold_response_comparison.png',dpi=160);fig.savefig(root/'threshold_response_comparison.svg');plt.close(fig)
    svg=root/'threshold_response_comparison.svg';svg.write_text('\n'.join(line.rstrip() for line in svg.read_text('utf-8').splitlines())+'\n',encoding='utf-8')
    write(root/'RESPONSE_CURVES.json',dict(real_G44=real,synthetic_continuous=synthetic[0],synthetic_empty_break=synthetic[1],synthetic_not_physical_negative_validation=True))
    html=''.join(f'<figure><figcaption>{m["id"]}</figcaption><img src="cards/{m["id"]}.png"></figure>' for m in indices);(root/'cards.html').write_text('<!doctype html><meta charset="utf-8"><title>缺口八帧复核卡</title><style>body{font:17px system-ui;max-width:1250px;margin:30px auto;color:#17314c}img{max-width:100%}</style><h1>缺口复检：八帧原片</h1><p>8个建议可相互重叠，不是8条物理划痕；均未填入真伪标签。</p>'+html,encoding='utf-8')
    print('EVIDENCE_CARDS_READY',len(indices),'cards; complement',int((missing&(o|n)).sum()),flush=True)

if __name__=='__main__':main()
