"""Separate offline review entry and reproducible scoring of the existing23 groups."""
from __future__ import annotations
import os
for _env in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[_env] = '1'
import argparse
import csv
import gzip
import html
import importlib.util
import json
import shutil
import socket
import sys
import time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from priority import attach_scores, file_sha, verify_frozen, TERMS

HERE = Path(__file__).resolve().parent
for _folder in ('seeded_component_tuning_20261029', 'joint_threshold_tuning_20261029',
                'confidence_large_gap004_20261029'):
    sys.path.insert(0, str(HERE.parent / _folder))
from sleeve_runtime import load_sealed, predict, verify_inputs
from large_gap import analyze_large_gaps
_spec = importlib.util.spec_from_file_location('_frozen_large_gap_window_utilities', HERE.parent/'confidence_large_gap004_20261029/run.py')
_utilities = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_utilities)
windows_for = _utilities.windows_for

def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))

def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', 'utf-8')

def csv_write(path, rows):
    if not rows:
        Path(path).write_text('group_id,window_id,human_decision,notes\n', 'utf-8-sig')
        return
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)

def font(size):
    return ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', size)

STYLE = '''body{font:17px system-ui;color:#20334b;background:#f4f6fa;margin:0 auto;padding:24px;max-width:1500px}
a{color:#125caa}img{max-width:100%;height:auto}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:white;border:1px solid #dae1ea;border-radius:10px;padding:18px;margin:18px 0}
p{line-height:1.7}.pill{display:inline-block;background:#fff0d8;padding:5px 10px;border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:15px}td,th{padding:9px;border-bottom:1px solid #ddd;text-align:left}
button,select,textarea,input{font:inherit;padding:9px;margin:5px}textarea{width:90%;min-height:55px}
.sticky{position:sticky;top:0;background:#f4f6fa;padding:10px;z-index:2;border-bottom:1px solid #ccc}
.small{font-size:14px;color:#53677e}@media(max-width:900px){.grid{grid-template-columns:1fr}}'''

def page(title, body, script=''):
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>' + html.escape(title) + '</title><style>' + STYLE + '</style><body>' + body + script + '</body></html>'

def render_group(target, record, arrays, formal, scored):
    gray = arrays['gray']
    base = np.repeat(np.rint(gray.mean(0)).astype('uint8')[:, :, None], 3, axis=2)
    detector = base.copy(); detector[formal] = [255, 210, 0]
    orange = Image.fromarray(detector); draw = ImageDraw.Draw(orange)
    for window in scored['windows']:
        x0, y0 = max(0, window['x0']), max(0, window['y0'])
        x1, y1 = min(formal.shape[1]-1, window['x1']), min(formal.shape[0]-1, window['y1'])
        draw.rectangle((x0, y0, x1, y1), outline='#ff9100', width=2)
        label = f'R{window["id"]} {"H" if window["review_priority"] == "high" else "M"} {window["evidence_support_score"]}'
        draw.text((x0, max(0, y0-20)), label, font=font(15), fill='#e57700', stroke_width=1, stroke_fill='#fafafa')
    top = Image.new('RGB', (formal.shape[1], formal.shape[0]+94), 'white')
    top.paste(orange, (0, 94)); draw = ImageDraw.Draw(top)
    for y, text, size in [(5, f'{record["sample"]} | {record["low"]}/{record["high"]}行 | 固定检测 + 复检提示', 19),
                          (34, 'H/M：复检优先级；数字：证据支持分，不是正确概率', 16),
                          (62, record['group_id'], 12)]:
        draw.text((8, y), text, font=font(size), fill='#20334b')
    top.save(target/'priority_review.png')
    Image.fromarray(detector).save(target/'formal_detector.png')
    cards = []
    human_rows = []
    for window in sorted(scored['windows'], key=lambda r: r['view_order']):
        evidence = window['representative_evidence']; source = evidence['source']
        frame = source['frame'] - 1
        x0, y0 = max(0, window['x0']-12), max(0, window['y0']-12)
        x1, y1 = min(formal.shape[1], window['x1']+13), min(formal.shape[0], window['y1']+13)
        original = Image.fromarray(gray[frame].astype('uint8')).convert('RGB')
        original.save(target/f'R{window["id"]}_source_frame.png')
        support = Image.fromarray(detector); d = ImageDraw.Draw(support)
        d.rectangle((window['x0'], window['y0'], window['x1'], window['y1']), outline='#ff9100', width=2)
        for x, y in evidence['joint_supported_native_xy']:
            d.point((x, y), fill='#00cde2')
        tiles = [('同一原片，未增强', original), ('正式检测，保持原像素', Image.fromarray(detector)), ('橙框 + 同帧实际支持点', support)]
        tile_w = max(220, min(550, (x1-x0)*2))
        tile_h = max(110, min(380, round((y1-y0)*tile_w/max(1, x1-x0))))
        comparison = Image.new('RGB', (3*tile_w, tile_h+40), 'white'); cd = ImageDraw.Draw(comparison)
        for i, (name, image) in enumerate(tiles):
            cd.text((i*tile_w+6, 5), name, font=font(16), fill='#20334b')
            comparison.paste(image.crop((x0, y0, x1, y1)).resize((tile_w, tile_h), Image.Resampling.NEAREST), (i*tile_w, 40))
        comparison.save(target/f'R{window["id"]}_comparison.png')
        actual_exposure = record['low'] if source['exposure']=='low' else record['high']
        human_rows.append(dict(group_id=record['group_id'], sample=record['sample'], low=record['low'], high=record['high'],
                               window_id=window['id'], bbox_xyxy=json.dumps([window[k] for k in ('x0','y0','x1','y1')]),
                               review_priority=window['review_priority'], evidence_support_score=window['evidence_support_score'],
                               largest_visual_gap_px=round(evidence['largest_visual_gap_px'],2),
                               source_frame=source['frame'], source_direction=source['direction'], source_exposure_lines=actual_exposure,
                               polarity='暗线' if source['polarity']==-1 else '亮线', human_decision='未复核', notes=''))
        terms = ''.join('<tr><td>'+html.escape(TERMS[k])+'</td><td>'+str(round(v,3))+'</td></tr>' for k,v in evidence['terms'].items())
        cards.append(f'<article class="card" id="R{window["id"]}"><h2>R{window["id"]} · {"高" if window["review_priority"]=="high" else "中"}优先 · 证据支持 {window["evidence_support_score"]}/100</h2>'
                     f'<p>最大视觉缺口 {evidence["largest_visual_gap_px"]:.1f}px；CH{source["direction"]} / {actual_exposure}行 / '+('暗线' if source['polarity']==-1 else '亮线')+'</p>'
                     f'<a href="R{window["id"]}_source_frame.png">打开实际来源整帧</a>'
                     f'<p>{html.escape("；".join(evidence["reasons"]))}</p><img src="R{window["id"]}_comparison.png"><table>{terms}</table></article>')
    body = f'<h1>{html.escape(record["sample"])} {record["low"]}/{record["high"]}行</h1><p>{html.escape(record["group_id"])}</p>'
    body += '<p>黄色为正式检测；橙框为人工复检建议；青点为所选同一原片在最大缺口内的实际支持。支持分是规则刻度，不表示缺陷概率或整板检出完整度。</p>'
    body += '<p><a href="../index.html">全部结果</a> · <a href="../人工复核.html">填写人工复核</a> · <a href="REVIEW_PRIORITY.json">完整评分与证据</a></p>'
    body += '<img src="priority_review.png">' + (''.join(cards) if cards else '<div class="card">本通路未触发复检提示；请继续查看原片，当前系统不自动放行。</div>')
    if (target/'original8_preview.jpg').exists():
        body += '<h2>同组八帧预览</h2><img src="original8_preview.jpg">'
    (target/'index.html').write_text(page('局部复检证据 '+record['group_id'], body), 'utf-8')
    return human_rows

def overview(out, records, rows):
    all_cards=[]; groups=[]
    for record in records:
        gid = record['group_id']; scored = read(out/gid/'REVIEW_PRIORITY.json')
        groups.append(f'<div class="card"><h2><a href="{gid}/index.html">{record["sample"]} {record["low"]}/{record["high"]}行</a> · {scored["review_window_count"]}个框</h2><p class="small">{gid}</p><a href="{gid}/index.html"><img loading="lazy" src="{gid}/priority_review.png"></a></div>')
        for row in [r for r in rows if r['group_id']==gid]:
            key = gid+'/R'+str(row['window_id'])
            all_cards.append(f'<section class="card" data-key="{key}"><h2>{record["sample"]} {record["low"]}/{record["high"]}行 · R{row["window_id"]}</h2>'
                             f'<p>{"高" if row["review_priority"]=="high" else "中"}优先 / 证据支持分 {row["evidence_support_score"]} / 缺口 {row["largest_visual_gap_px"]}px</p>'
                             f'<p class="small">{gid}；CH{row["source_direction"]}，{row["source_exposure_lines"]}行，{row["polarity"]}</p>'
                             f'<img loading="lazy" src="{gid}/R{row["window_id"]}_comparison.png">'
                             f'<p><a href="{gid}/R{row["window_id"]}_source_frame.png">实际来源整帧</a> · <a href="{gid}/index.html#R{row["window_id"]}">分项证据</a></p>'
                             '<label>人工判断<select class="decision"><option>未复核</option><option>含真实漏段</option><option>仅背景响应</option><option>不确定</option></select></label><br>'
                             '<textarea class="notes" placeholder="可记录漏段位置、油污边缘、不确定端点等"></textarea></section>')
    body = f'<h1>局部复检收敛版：{len(records)}组 / {len(rows)}个橙框</h1><p>黄色检测与橙框准入规则冻结。证据分采用短板规则、5分一档，尚未进行概率校准；同一实体板不同曝光仍属于同一块板。</p><p><a href="人工复核.html">开始人工逐框复核</a> · <a href="人工复核模板.csv">CSV模板</a> · <a href="SUMMARY.json">本轮摘要</a></p><div class="grid">'+''.join(groups)+'</div>'
    (out/'index.html').write_text(page('置信度复检收敛版', body), 'utf-8')
    model = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c')
    script = '''<script>
const initial=__ROWS__, storeKey='guangjian-review-priority-v1:'+initial.map(r=>r.group_id+':'+r.window_id).join('|');
let saved={};try{saved=JSON.parse(localStorage.getItem(storeKey)||'{}')}catch(e){}
const cards=[...document.querySelectorAll('[data-key]')];
function collect(){return initial.map(r=>{const key=r.group_id+'/R'+r.window_id,c=cards.find(c=>c.dataset.key===key);return {...r,human_decision:c.querySelector('.decision').value,notes:c.querySelector('.notes').value}})}
function save(){saved={rows:Object.fromEntries(collect().map(r=>[r.group_id+'/R'+r.window_id,{human_decision:r.human_decision,notes:r.notes}])),reviewer:document.getElementById('reviewer').value,missed:document.getElementById('missed').value};try{localStorage.setItem(storeKey,JSON.stringify(saved));document.getElementById('state').textContent='已记录 '+collect().filter(r=>r.human_decision!=='未复核').length+'/'+initial.length+'；请导出文件作为正式记录'}catch(e){document.getElementById('state').textContent='浏览器不允许本地保存，请及时导出文件'}}
for(const c of cards){const v=(saved.rows||{})[c.dataset.key];if(v){c.querySelector('.decision').value=v.human_decision;c.querySelector('.notes').value=v.notes||''}c.addEventListener('change',save);c.addEventListener('input',save)}
document.getElementById('reviewer').value=saved.reviewer||'';document.getElementById('missed').value=saved.missed||'';document.getElementById('reviewer').addEventListener('input',save);document.getElementById('missed').addEventListener('input',save);
function exportJSON(){const data={schema:'human-orange-window-review-v1',reviewer:document.getElementById('reviewer').value,exported_at:new Date().toISOString(),rows:collect(),unprompted_missing_notes:document.getElementById('missed').value,not_independent_test:true};const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='光鉴_人工复核_'+new Date().toISOString().replace(/[:.]/g,'-')+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
document.getElementById('export').addEventListener('click',exportJSON);save();
</script>'''.replace('__ROWS__', model)
    body = '<h1>人工逐框复核</h1><p>先看实际来源整帧，再判断框内是否含真实漏段。框内可同时存在背景；请选择“含真实漏段”，并在备注指出位置。复核框外显眼漏段也请记录。</p><div class="sticky"><label>复核人<input id="reviewer"></label><button id="export">导出人工复核JSON</button><span id="state"></span></div>'
    body += '<div class="card"><label>未被橙框提醒的显眼漏段、额外说明<textarea id="missed"></textarea></label><p>未触发提示的组也需要抽查。真实断口、油污边缘等负例请注明组ID和位置。</p></div>' + ''.join(all_cards)
    (out/'人工复核.html').write_text(page('光鉴人工复核', body, script), 'utf-8')
    csv_write(out/'人工复核模板.csv', rows)

def process_record(record, out, base_plan, core_plan, previous=None):
    start=time.monotonic(); target=out/record['group_id']; target.mkdir()
    x=load_sealed(record['root']); gray=x['planes']['gray'].astype('float32'); arrays={**x['planes'], 'gray':gray}
    previous_hashes={}
    if previous is not None:
        old=previous/record['group_id']
        for name in ('GAP_REVIEWS.json.gz','REVIEW_WINDOWS.json','arrays.npz'):
            previous_hashes[str(old/name)]=file_sha(old/name)
        with gzip.open(old/'GAP_REVIEWS.json.gz','rt',encoding='utf-8') as stream: evidence=json.load(stream)
        windows=read(old/'REVIEW_WINDOWS.json')
        with np.load(old/'arrays.npz',allow_pickle=False) as z: formal=z['formal_detector_mask'].copy()
        frozen_path=Path(read(HERE.parent/'confidence_large_gap_batch_20261029/PLAN.json')['formal_masks'])/record['group_id']/'masks.npz'
        with np.load(frozen_path,allow_pickle=False) as z:
            if not np.array_equal(z['candidate'],formal):raise ValueError('Formal baseline mask differs')
        if (old/'original8_preview.jpg').exists():shutil.copyfile(old/'original8_preview.jpg',target/'original8_preview.jpg')
    else:
        result=predict(x,read(HERE.parent/'joint_threshold_tuning_20261029/FROZEN_SLEEVE_CONFIG.json')['selected']['config'])
        formal=result['candidate'].copy()
        evidence=analyze_large_gaps(formal,gray,arrays['valid'],arrays['board'],arrays['residual_n'],base_plan,core_plan)
        windows=windows_for(evidence['gaps'])
        np.savez_compressed(target/'formal_arrays.npz',**result)
        with gzip.open(target/'GAP_REVIEWS.json.gz','wt',encoding='utf-8') as stream:json.dump(evidence,stream,ensure_ascii=False,allow_nan=False)
    before=formal.tobytes()
    scored=attach_scores(evidence,windows,gray,arrays['valid'],arrays['board'],arrays['residual_n'],base_plan,core_plan)
    for old_w,new_w in zip(windows,scored['windows']):
        if any(new_w[k]!=v for k,v in old_w.items()):raise ValueError('Frozen review window changed')
    if len(windows)!=len(scored['windows']) or before!=formal.tobytes():raise ValueError('Frozen output changed')
    scored.update(group_id=record['group_id'],sample=record['sample'],low=record['low'],high=record['high'],formal_config_id='4c0be2d44fdd')
    write(target/'REVIEW_PRIORITY.json',scored)
    rows=render_group(target,record,arrays,formal,scored)
    verify_inputs(x)
    if not all(file_sha(p)==v for p,v in previous_hashes.items()):raise ValueError('Previous evidence modified')
    write(target/'RECEIPT.json',dict(status='PASS',group_id=record['group_id'],previous_evidence=previous_hashes,
                                    formal_mask_unchanged=True,orange_windows_unchanged=True,frames=8,
                                    score_semantics='rule_based_development_index',calibrated_probability=False,
                                    automatic_pass=False,runtime_seconds=time.monotonic()-start))
    print('DONE',record['sample'],f'{record["low"]}/{record["high"]}',len(windows),'windows',round(time.monotonic()-start,1),'s',flush=True)
    return rows,scored

def finalize(out, records, rows, start, own_sources):
    overview(out,records,rows)
    write(out/'SUMMARY.json',dict(status='VERIFYING'))
    import re
    links=0
    for path in out.rglob('*.html'):
        for ref in re.findall(r'(?:href|src)="([^"#]+)"',path.read_text('utf-8')):
            if not (path.parent/ref.split('#')[0]).is_file():raise ValueError('Broken local link '+ref)
            links+=1
    verify_frozen()
    if not all(file_sha(HERE/name)==digest for name,digest in own_sources.items()):raise ValueError('Scoring sources changed during run')
    summary=dict(status='PASS',groups=len(records),frames=8*len(records),physical_boards=len(set(r['sample'] for r in records)),
                 windows=len(rows),high_priority=sum(r['review_priority']=='high' for r in rows),medium_priority=sum(r['review_priority']=='medium' for r in rows),
                 scores=[r['evidence_support_score'] for r in rows],all_formal_masks_unchanged=True,all_orange_windows_unchanged=True,
                 html_links_checked=links,human_acceptance='PENDING',probability_calibrated=False,automatic_pass=False,
                 new_captures=0,FPGA_changed=False,TJ_model_overwritten=False,runtime_seconds=time.monotonic()-start,
                 group_results=[dict(group_id=r['group_id'],sample=r['sample'],low=r['low'],high=r['high'],
                                     windows=read(out/r['group_id']/'REVIEW_PRIORITY.json')['review_window_count']) for r in records])
    write(out/'SUMMARY.json',summary)
    print('REVIEW_PRIORITY_COMPLETE',len(records),'groups',len(rows),'windows',round(time.monotonic()-start,1),'s',flush=True)

def main():
    parser=argparse.ArgumentParser()
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--from-batch',type=Path)
    source.add_argument('--detection-root',type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    cv2.setNumThreads(1)
    def denied(*a,**k):raise RuntimeError('Offline review prohibits sockets')
    socket.socket=denied
    binding=verify_frozen(); base_plan=read(HERE.parent/'confidence_gap_review_20261029/PLAN.json'); core_plan=read(HERE.parent/'confidence_large_gap004_20261029/PLAN.json')
    own_sources={p.name:file_sha(p) for p in HERE.glob('*.py')}
    out=args.out.resolve(); out.mkdir(parents=True,exist_ok=False); start=time.monotonic()
    if args.from_batch:
        previous=args.from_batch.resolve(); records=read(previous/'DATASETS.json')
        prior=read(previous/'VERIFICATION.json')
        if not prior['all_formal_masks_byte_identical'] or prior['status']!='PASS':raise ValueError('Previous batch was not verified')
    else:
        previous=None; root=args.detection_root.resolve(); summary=read(root/'summary.json')
        # Exposure values are taken from the actual exported frame identity, never a folder name.
        frames=list(csv.DictReader((root/'frame_inputs.csv').open(encoding='utf-8-sig')))
        exposures=[int(r['exposure_lines']) for r in frames]
        record=dict(group_id=summary['group_id'],sample=summary['group_id'].split('_')[0],low=exposures[0],high=exposures[1],root=str(root))
        if len(frames)!=8 or len(set(exposures[::2]))!=1 or len(set(exposures[1::2]))!=1:raise ValueError('Incomplete real exposure identity')
        records=[record]
    write(out/'DATASETS.json',records); write(out/'FROZEN_DEPENDENCIES.json',binding)
    rows=[]; summaries=[]
    for record in records:
        items,result=process_record(record,out,base_plan,core_plan,previous)
        rows+=items; summaries.append(dict(group_id=record['group_id'],sample=record['sample'],low=record['low'],high=record['high'],windows=result['review_window_count'],status=result['status']))
    finalize(out,records,rows,start,own_sources)

if __name__=='__main__':main()
