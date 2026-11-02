"""Make bounded, reproducible comparison artifacts after inference has passed."""
import argparse,hashlib,json,shutil,zipfile
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont

HERE=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,obj):
    with Path(p).open('w',encoding='utf-8',newline='\n') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n')
def font(size):return ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',size)
def main():
    p=argparse.ArgumentParser();p.add_argument('--result',type=Path,required=True);p.add_argument('--equivalence-reference',type=Path);a=p.parse_args();root=a.result.resolve();receipt=read(root/'VERIFICATION.json')
    if receipt['status']!='PASS' or not all(sha(p)==h for p,h in receipt['source_sha256'].items()):raise ValueError('Unverified or changed inference source')
    evaluation=read(root/'sample004/ANNOTATION_EVAL.json');results=read(root/'RESULTS.json');annotation=read(HERE.parents[2]/'YMW/reviews/sample004_weak_line_threshold_20261029/annotation.json');path=np.asarray(annotation['path_points']);x0=int(path[:,0].min())-35;x1=int(path[:,0].max())+40;y0=int(path[:,1].min())-35;y1=int(path[:,1].max())+35
    names=[('protected','6/20保护层'),('loose','普通6/12'),('chain_raw','线形＋碎片关系'),('line_plus_raw','再加入原片线剖面')]
    tw,th=(x1-x0)*2,(y1-y0)*2+74;poster=Image.new('RGB',(tw*2,100+th*2),'white');pen=ImageDraw.Draw(poster)
    pen.text((12,5),'004弱段：固定弱6，保留6/20，分流6/12新增块',font=font(23),fill='#17314c')
    pen.text((12,39),'黄=6/20保护层；青=该实验保留的新增候选。未保留部分仍在橙色复检层，没有被当作背景删除。',font=font(15),fill='#17314c')
    pen.text((12,66),'标线支持是同x纵向±3px附近的位置数，非正式召回率；没有在间隙里补画确认像素。',font=font(15),fill='#17314c')
    for i,(name,title) in enumerate(names):
        row=next(r for r in results['sample004']['modes'] if r['mode']==name);score=evaluation['metrics'][name]['path_support_r3'];x=i%2*tw;y=100+i//2*th
        pen.text((x+8,y+3),f'{title} | 标线支持 {score}/268',font=font(19),fill='#17314c')
        pen.text((x+8,y+31),f'全板{row["candidate_pixels"]}px，新增{row["supplement_pixels"]}px，复检{row["review_pixels"]}px',font=font(16),fill='#17314c')
        image=Image.open(root/'sample004/full'/f'{name}.png').convert('RGB').crop((x0,y0+100,x1,y1+100)).resize((tw,th-74),Image.Resampling.NEAREST);poster.paste(image,(x,y+70))
    poster.save(root/'sample004/key_comparison.png')
    if a.equivalence_reference:
        previous=a.equivalence_reference.resolve();pngs=features=arrays=0
        if read(previous/'CONFIG.json')!=read(root/'CONFIG.json'):raise ValueError('Performance edit changed algorithm parameters')
        for sample in results:
            for p in (root/sample/'full').glob('*.png'):
                if sha(p)!=sha(previous/sample/'full'/p.name):raise ValueError('Performance edit changed PNG '+str(p));
                pngs+=1
            for name in ('FRAGMENT_RELATIONS.json','RAW_PROFILES.json'):
                if (root/sample/name).read_bytes()!=(previous/sample/name).read_bytes():raise ValueError('Performance edit changed component features '+sample+'/'+name)
                features+=1
            for p in (root/sample/'masks').glob('*.npz'):
                with np.load(p) as x,np.load(previous/sample/'masks'/p.name) as y:
                    if set(x.files)!=set(y.files) or any(not np.array_equal(x[k],y[k]) for k in x.files):raise ValueError('Performance edit changed arrays '+str(p))
                    arrays+=len(x.files)
        write(root/'PERFORMANCE_EQUIVALENCE.json',dict(status='PASS',reference=str(previous),full_PNGs_byte_identical=pngs,component_feature_JSONs_byte_identical=features,array_fields_equal=arrays,
            before_seconds=read(previous/'VERIFICATION.json')['runtime_seconds'],after_seconds=receipt['runtime_seconds'],algorithm_parameters_unchanged=read(previous/'CONFIG.json')==read(root/'CONFIG.json')))
    archive=root/'experiment_images_and_receipts.zip'
    entries=[p for p in root.rglob('*') if p.is_file() and p.suffix in ('.png','.html','.json','.csv') and 'source_snapshot' not in p.parts]
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in entries:z.write(p,p.relative_to(root).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('ZIP CRC failure')
        for p in entries:
            if hashlib.sha256(z.read(p.relative_to(root).as_posix())).hexdigest()!=sha(p):raise ValueError('ZIP member differs')
    write(root/'PACKAGE_RECEIPT.json',dict(status='PASS',zip_sha256=sha(archive),members_verified=len(entries),all_files_in_archive_byte_verified=True))
    evidence=HERE/'verification';evidence.mkdir(exist_ok=False)
    for name in ('VERIFICATION.json','CONFIG.json','RESULTS.json','SUMMARY.csv','PACKAGE_RECEIPT.json','PERFORMANCE_EQUIVALENCE.json'):
        if (root/name).is_file():shutil.copy2(root/name,evidence/name)
    gallery=HERE/'gallery';gallery.mkdir(exist_ok=False)
    for sample in results:
        target=gallery/sample;target.mkdir()
        for name in ('original','protected','loose','chain_raw','raw_profile','line_plus_raw'):
            shutil.copy2(root/sample/'full'/f'{name}.png',target/f'{name}.png')
        shutil.copy2(root/sample/'review/line_plus_raw.png',target/'review_layer.png')
        for name in ('METRICS.json','COMPONENTS.json','FRAGMENT_RELATIONS.json','RAW_PROFILES.json'):
            shutil.copy2(root/sample/name,evidence/(sample+'_'+name))
    for name in ('key_comparison.png','weak_line_comparison.png'):shutil.copy2(root/'sample004'/name,gallery/name)
    shutil.copy2(root/'sample004/ANNOTATION_EVAL.json',evidence/'sample004_ANNOTATION_EVAL.json');shutil.copy2(root/'three_board_comparison.png',gallery/'three_board_comparison.png')
    print('REVIEW_READY',root/'index.html',flush=True)
    for sample in results:
        for mode in ('original','protected','loose','line6','chain_raw','raw_profile','line_plus_raw'):
            row=next(r for r in results[sample]['modes'] if r['mode']==mode);print(sample,mode,row['candidate_pixels'],row['supplement_pixels'],row['review_pixels'],evaluation['metrics'][mode]['path_support_r3'] if sample=='sample004' else '-',flush=True)
if __name__=='__main__':main()
