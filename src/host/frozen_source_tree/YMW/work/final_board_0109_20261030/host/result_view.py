"""Native original PNGs plus a local eight-frame/result comparison page."""
from html import escape
import hashlib,json
import cv2
import numpy as np
def png(path,value):
    okay,encoded=cv2.imencode('.png',value)
    if not okay:raise OSError('PNG encoding failed '+str(path))
    path.write_bytes(encoded.tobytes())
def build(folder,rows,result,chosen_gray,wire):
    originals=folder/'originals';originals.mkdir();items=[]
    for index,row in enumerate(rows):
        capture=row['capture'];meta=capture.metadata;diag=meta['diagnostic'];params=meta['actual_parameters'];h,w=row['gray'].shape
        if meta['pixel_format']==50:
            raw,_,_=wire.dual_view.decode(capture.raw_payload,w,h,codec=wire.codec)
            words=np.frombuffer(raw,dtype='>u2').reshape(h,w).astype(np.uint32);r,g,b=words>>11,(words>>5)&63,words&31
            image=np.stack(((b<<3)|(b>>2),(g<<2)|(g>>4),(r<<3)|(r>>2)),axis=2).astype(np.uint8)
            if not np.array_equal(wire.codec.planes(image)[0],row['gray']):raise ValueError('Original RGB PNG does not reproduce the same frozen gray')
        elif meta['pixel_format']==49:image=row['gray']
        else:raise ValueError('Engineering comparison requires49/50')
        label=f"CH{index//2+1} {'低' if index%2==0 else '高'}曝光 {params['exposure_lines']}行 · {params['gain16']/16:g}倍 · LED{params['brightness']}"
        filename=f'{index+1:02d}_CH{index//2+1}_{"low" if index%2==0 else "high"}_{params["exposure_lines"]}lines.png';png(originals/filename,image)
        items.append(dict(slot=index+1,label=label,png='originals/'+filename,png_sha256=hashlib.sha256((originals/filename).read_bytes()).hexdigest(),identity=diag['identity'],parameters=params))
    overlay=np.repeat(chosen_gray[:,:,None],3,axis=2);overlay[result['mask']]=(0,0,255);png(folder/'overlay.png',overlay)
    sample=escape(str(rows[0]['capture'].metadata.get('sample_id','unknown')))
    cards=''.join(f'<figure><figcaption>{escape(item["label"])}</figcaption><a href="{item["png"]}"><img src="{item["png"]}"></a></figure>' for item in items)
    text='<!doctype html><meta charset="utf-8"><title>0109 同输入验收</title><style>body{font-family:system-ui;margin:24px;background:#f3f5f8;color:#15243a}main{max-width:1500px;margin:auto}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}figure{margin:0;background:white;padding:12px}figcaption{padding-bottom:8px;font-weight:600}img{width:100%;height:auto}p{line-height:1.6}a{color:#175bb6}</style><main><h1>'+sample+' · 0109工程同输入核对</h1><p>每行同一方向，左为本组实际低曝光、右为实际高曝光（数值见各图标题）。点击图片查看原尺寸；彩色图按同帧RGB565精确展开，灰度模式显示原生gray8。融合核对是计算一致性，不代表独立准确率或置信度验收。</p><div class="grid">'+cards+'</div><h2>最终候选</h2><p>红色为最终mask，底图为所选来源gray，仅用于溯源显示。<a href="comparison.json">逐字段比较</a> · <a href="RESULT.json">组身份与八帧索引</a></p><a href="overlay.png"><img src="overlay.png"></a></main>'
    (folder/'index.html').write_text(text,encoding='utf-8');(folder/'ORIGINALS.json').write_text(json.dumps(items,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
