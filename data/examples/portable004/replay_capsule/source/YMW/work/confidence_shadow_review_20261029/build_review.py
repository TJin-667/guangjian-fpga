"""Combine five fixed-exposure groups and prepare unlabelled manual cards."""
import json,re
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from evidence import distance_to
from run_study import read,write,csv_write,sheet,font,sha

HERE=Path(__file__).resolve().parent;ROOT=Path('E:/GuangjianData/reviews/confidence_shadow_review_20261029')
def main():
    out=ROOT/'review_04';out.mkdir(exist_ok=False);records=[];source_for={};receipts=[]
    for name in ('dev_04','pose_04'):
        receipts.append(read(ROOT/name/'VERIFICATION.json'))
        for r in read(ROOT/name/'RESULTS.json'):
            if r['group_id'] in source_for:raise AssertionError('Duplicate group')
            source_for[r['group_id']]=ROOT/name/r['group_id'];records.append(r)
    if len(records)!=5:raise AssertionError('Expected five unique400/800 groups')
    cards=out/'cards';cards.mkdir();label_rows=[];all_card_data=[];tiles=[];sections=[];features=[]
    for r in records:
        group=r['group_id'];source=source_for[group];windows=read(source/'REVIEW_REGIONS.json');summary=read(Path(r['root'])/'summary.json');roi=summary['roi_xywh'];review=Image.open(source/'review_regions.png').copy();tiles.append((r['sample']+' '+('主组' if r['role']=='development' else '旧姿态'),review));limit=len(windows)
        with np.load(Path(r['root'])/'arrays/original_eight_frames.npz',allow_pickle=False) as z:gray=z['gray'].copy()
        raw_sources=[v for v in summary['gallery'] if v.get('kind')=='raw']
        for win in windows[:limit]:
            width=min(gray.shape[2],max(64,win['x1']-win['x0']+24));height=min(gray.shape[1],max(64,win['y1']-win['y0']+24));cx=(win['x0']+win['x1'])//2;cy=(win['y0']+win['y1'])//2;x0=max(0,min(gray.shape[2]-width,cx-width//2));y0=max(0,min(gray.shape[1]-height,cy-height//2));label_id=group+f'_R{win["id"]:02d}';tt=[]
            for frame in (0,2,4,6,1,3,5,7):
                crop=Image.fromarray(gray[frame,y0:y0+height,x0:x0+width]).convert('RGB');crop.thumbnail((288,240),Image.Resampling.NEAREST)
                if width<144 and height<120:crop=crop.resize((crop.width*2,crop.height*2),Image.Resampling.NEAREST)
                panel=Image.new('RGB',(300,300),'white');d=ImageDraw.Draw(panel);d.text((7,5),f'CH{frame//2+1} | '+('400行' if frame%2==0 else '800行'),font=font(19),fill='#17314c');d.text((7,34),'封存灰度局部；未增强对比度',font=font(13),fill='#596b7b');panel.paste(crop,((300-crop.width)//2,60+(240-crop.height)//2));tt.append(panel)
            card=Image.new('RGB',(1200,660),'#eef2f7');d=ImageDraw.Draw(card);d.text((10,8),f'{r["sample"]} 复检窗口{win["id"]} | '+win['priority'],font=font(21),fill='#17314c');d.text((10,35),'先看原片再填写：真实漏段／边界变化／油污反光／其他原痕／不确定；当前均未自动标真伪',font=font(15),fill='#526374')
            for index,panel in enumerate(tt):card.paste(panel,(index%4*300,60+index//4*300))
            card.save(cards/(label_id+'.png'));metadata=dict(label_id=label_id,group_id=group,formal_config_id=r['formal_config_id'],region_native_xyxy=[win['x0'],win['y0'],win['x1'],win['y1']],region_full_saved_xyxy=[roi[0]+win['x0'],roi[1]+win['y0'],roi[0]+win['x1'],roi[1]+win['y1']],crop_native_xywh=[x0,y0,width,height],evidence=win['evidence'],source_raw=[dict(frame=summary['frame_order'][i],path=v['path'],sha256=v['sha256']) for i,v in enumerate(raw_sources)],manual_class=None,manual_notes=None)
            write(cards/(label_id+'.json'),metadata);all_card_data.append(metadata);label_rows.append(dict(label_id=label_id,group_id=group,sample=r['sample'],region_id=win['id'],evidence_priority=win['priority'],manual_class='',manual_notes='',card=label_id+'.png'))
        sections.append(f'<section><h2>{r["sample"]} · {r["role"]} · {r["review_windows"]}个复检窗口</h2><a href="../{source.parent.name}/{group}/overview.png"><img src="../{source.parent.name}/{group}/overview.png"></a><p><a href="../{source.parent.name}/{group}/review_regions.png">复检框原尺寸</a> · <a href="../{source.parent.name}/{group}/SHADOW_COMPARISONS.json">轻度放宽对照统计</a></p></section>')
        for name,m in r['shadows'].items():features.append(dict(group_id=group,sample=r['sample'],profile=name,**m))
    sheet(tiles,out/'five_group_review.png',columns=5,cell=(330,400));write(out/'RESULTS.json',records);csv_write(out/'SUMMARY.csv',[{k:v for k,v in r.items() if k not in ('shadows','duplicate_result_folders')} for r in records]);csv_write(out/'SHADOW_FEATURES.csv',features);csv_write(out/'MANUAL_LABELS_TEMPLATE.csv',label_rows);write(out/'MANUAL_CARD_INDEX.json',all_card_data)
    html=''.join(f'<figure><figcaption>{v["label_id"]}</figcaption><a href="cards/{v["label_id"]}.png"><img src="cards/{v["label_id"]}.png"></a></figure>' for v in all_card_data)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>置信度参考v4：五组与人工复核卡</title><style>body{font-family:system-ui;background:#eef2f7;color:#17314c;margin:24px}main{max-width:1700px;margin:auto}img{max-width:100%;height:auto}section,figure{background:white;padding:14px;margin:18px 0}p{line-height:1.7}</style><main><h1>参数轻放宽＋原片连续线证据：复检参考</h1><p>只改变复检证据，不改变冻结检测。5组来自三块实体工件；窗口不是划痕条数，未标定为正确率。无告警也不等于自动通过。</p><p><a href="../dev_04/sample004_case_comparison.png">004已确认弱线开发案例</a> · <a href="SUMMARY.csv">五组汇总</a> · <a href="SHADOW_FEATURES.csv">扰动分项指标</a> · <a href="MANUAL_LABELS_TEMPLATE.csv">空白人工标注表</a></p>'+''.join(sections)+'<h1>人工复核卡：先看八帧原片</h1>'+html+'</main>',encoding='utf-8')
    refs=re.findall(r'(?:src|href)="([^"#]+)"',(out/'index.html').read_text('utf-8'));missing=[v for v in refs if not (out/v).is_file()]
    if missing:raise AssertionError('Missing review assets '+repr(missing))
    sources={}
    for v in receipts:sources.update(v['input_files_sha256'])
    if not all(sha(p)==v for p,v in sources.items()):raise AssertionError('Input changed')
    write(out/'VERIFICATION.json',dict(status='PASS',groups=5,unique_frames=40,physical_boards=3,input_unique_files=len(sources),formal_masks_unchanged=True,manual_cards=len(label_rows),manual_labels_prefilled=False,html_asset_references=len(refs),missing_assets=[],independent_validation=False,calibrated_probability=False))
    (ROOT/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>光鉴置信度参考实验</title><style>body{font:18px system-ui;max-width:1100px;margin:50px auto;color:#17314c;line-height:1.8}a{display:block;padding:14px;background:#eef2f7;margin:12px 0}</style><h1>置信度参考实验：检测不变，另给复检证据</h1><p>FPGA部署已后置。本轮无采集、无烧录；不输出已校准正确率，不改正式参考掩膜。</p><a href="review_04/index.html">当前v4：五组对照、分项指标与人工复核卡</a><a href="dev_04/sample004_case_comparison.png">004已确认漏段的原片与复检证据</a><a href="dev_01/index.html">v1：保留失败案例记录，漏段未被提醒</a><a href="dev_02/index.html">v2：记录容量限制，不作为有效覆盖证明</a><a href="dev_03/index.html">v3：取样仍过稀，未覆盖已知漏段</a>',encoding='utf-8')
    print('REVIEW_BUNDLE_READY',len(records),'groups',len(label_rows),'unlabelled cards',flush=True)
if __name__=='__main__':main()
