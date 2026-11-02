"""Offline eight-photo browser. Source copies are byte-identical; no board access."""
import argparse,hashlib,html,json,shutil,uuid
from pathlib import Path
from urllib.parse import quote
import numpy as np
from PIL import Image,ImageDraw,ImageFont

FOLDER='eight_compare'
FULL='01_八张原片总览.png'
CROP='02_工件区域八张对照.png'
RAW='原片_8张'
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def write(p,data):Path(p).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def need(ok,message):
 if not ok:raise ValueError(message)
def inside(root,name):
 p=Path(name);need(not p.is_absolute(),'Relative source path required')
 result=(root/p).resolve();need(result.is_relative_to(root),'Source path escapes paired data')
 return result
def default_output(pair):
 pair=Path(pair).resolve()
 return pair.parent/FOLDER if pair.name=='pair' else pair.with_name(pair.name+'_'+FOLDER)
def font(size):
 for name in ['C:/Windows/Fonts/msyh.ttc','C:/Windows/Fonts/arial.ttf','DejaVuSans.ttf']:
  try:return ImageFont.truetype(name,size)
  except OSError:pass
 return ImageFont.load_default()

def create(pair,out=None):
 pair=Path(pair).resolve();manifest=pair/'XDL_manifest.json';doc=read(manifest)
 need(len(doc.get('groups',[]))==1,'Exactly one paired group is required')
 group=doc['groups'][0];observations=group['observations']
 need(len(observations)==8,'Eight real observations are required; no padding')
 slots={};identities=set();images={};mask=None;origin=None
 for o in observations:
  key=(o['direction'],o['exposure_role'])
  need(key[0] in ['CH1','CH2','CH3','CH4'] and key[1] in ['low','high'],'Unknown observation slot')
  need(key not in slots,'Duplicate direction/exposure slot')
  identity=(str(o.get('session_id')),str(o.get('frame_id')))
  need(identity not in identities,'Duplicate source frame identity');identities.add(identity)
  path=inside(pair,o['source_path']);need(digest(path)==o['source_sha256'],'Source image SHA mismatch: '+str(key))
  image=Image.open(path);image.load();image=image.convert('RGB')
  mpath=inside(pair,o['valid_mask_path']);need(digest(mpath)==o['valid_mask_sha256'],'Valid mask SHA mismatch')
  current=np.load(mpath,allow_pickle=False).astype(bool)
  need(current.shape==(image.height,image.width),'Mask/source dimensions differ')
  here=tuple(o.get('source_origin_xy',[0,0]))
  if mask is None:mask=current;origin=here;size=image.size
  else:need(image.size==size and here==origin and np.array_equal(current,mask),'Group geometry differs between observations')
  for field in ['exposure_lines','gain16','led','frame_id']:need(isinstance(o[field],int) and o[field]>=0,'Invalid actual parameter: '+field)
  slots[key]=dict(o);images[key]=image
 need(len(slots)==8 and len({o['source_path'] for o in observations})==8,'Eight distinct source paths required')
 yy,xx=np.where(mask);need(len(xx)>0,'Valid board mask is empty')
 box=(max(0,int(xx.min())-32),max(0,int(yy.min())-32),min(size[0],int(xx.max())+33),min(size[1],int(yy.max())+33))
 out=Path(out).resolve() if out is not None else default_output(pair)
 need(not out.is_relative_to(pair),'Compare output must be outside sealed pair directory')
 for p in [out,*out.parents]:need(not (p/'output_manifest.json').exists(),'Compare output is inside a sealed raw archive')
 mh=digest(manifest)
 if out.exists():
  saved=read(out/'COMPARE_MANIFEST.json');need(saved['source_manifest_sha256']==mh,'Existing comparison belongs to another manifest')
  for name,sha in saved['files_sha256'].items():need(digest(inside(out,name))==sha,'Existing comparison file changed: '+name)
  return dict(status='READY',directory=str(out),index=str(out/'index.html'),reused=True,source_manifest_sha256=mh)
 out.parent.mkdir(parents=True,exist_ok=True);temp=out.with_name(out.name+'.building_'+uuid.uuid4().hex[:8]);temp.mkdir()
 (temp/RAW).mkdir();records=[]
 for role in ['low','high']:
  for channel in ['CH1','CH2','CH3','CH4']:
   o=slots[(channel,role)];name=f'{channel}_{role}_{o["exposure_lines"]}lines_gain16-{o["gain16"]}_LED{o["led"]}_frame{o["frame_id"]}.png'
   target=temp/RAW/name;shutil.copyfile(inside(pair,o['source_path']),target);need(digest(target)==o['source_sha256'],'Copied source differs')
   records.append(dict(direction=channel,exposure_role=role,exposure_lines=o['exposure_lines'],gain16=o['gain16'],led=o['led'],
    frame_id=o['frame_id'],session_id=o.get('session_id'),source_path=o['source_path'],source_sha256=o['source_sha256'],copy_path=(Path(RAW)/name).as_posix(),
    original_dimensions=list(size),source_origin_xy=list(origin),native_pixels_resampled=False))
 for cropped,name in [(False,FULL),(True,CROP)]:
  w,h=(box[2]-box[0],box[3]-box[1]) if cropped else size
  scale=min(480/w,480/h);pw,ph=round(w*scale),round(h*scale);tilew=max(pw,460);tileh=ph+76
  canvas=Image.new('RGB',(4*(tilew+12)+12,2*tileh+144),'#edf2f7');draw=ImageDraw.Draw(canvas)
  title=f'{group["specimen_id"]} {group.get("specimen_variant","")} · '+('工件区域八张对照' if cropped else '八张原片总览')
  draw.text((18,10),title,font=font(27),fill='#18324b')
  draw.text((18,50),'每列CH1～CH4；上排低曝光，下排高曝光。参数取自本组清单实际记录。',font=font(19),fill='#354f65')
  note=f'显示裁区源坐标{list(box)}，仅对比预览裁切；原片文件保持完整。' if cropped else f'原片{size[0]}×{size[1]}；全图原点{list(origin)}；只缩小总览显示，不修改单张源图。'
  draw.text((18,81),note,font=font(16),fill='#506477')
  for r,role in enumerate(['low','high']):
   for c,ch in enumerate(['CH1','CH2','CH3','CH4']):
    o=slots[(ch,role)];x=12+c*(tilew+12);y=120+r*tileh
    draw.text((x+5,y),f'{ch} · '+('低曝光' if role=='low' else '高曝光')+f' · {o["exposure_lines"]} 行',font=font(23),fill='#007c98' if role=='low' else '#a65b00')
    draw.text((x+5,y+34),f'增益{o["gain16"]/16:g}×  LED{o["led"]}  帧{o["frame_id"]}',font=font(17),fill='#354f65')
    im=images[(ch,role)].crop(box) if cropped else images[(ch,role)]
    shown=im.resize((pw,ph),Image.Resampling.LANCZOS);canvas.paste(shown,(x+(tilew-pw)//2,y+65))
  draw.text((18,canvas.height-22),'原色显示，无提亮/划痕标注/取正；100%查看请打开“原片_8张”或index.html。',font=font(15),fill='#506477')
  canvas.save(temp/name)
 esc=html.escape;cards=[]
 for o in records:
  role='低曝光' if o['exposure_role']=='low' else '高曝光';url=quote(o['copy_path']);label=f'{o["direction"]} · {role} · {o["exposure_lines"]} 行'
  cards.append(f'<article><h2>{esc(label)}</h2><p>增益{o["gain16"]/16:g}× · LED{o["led"]} · 帧{o["frame_id"]}</p><a href="{url}" target="_blank"><img src="{url}" alt="{esc(label)}"></a><p>点击打开完整原片，可在浏览器放大查看</p></article>')
 page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>光鉴八张原片对比</title><style>body{background:#edf2f7;color:#18324b;font:16px "Microsoft YaHei",sans-serif;margin:20px}h1{font-size:26px}nav{display:flex;gap:18px;margin:20px 0}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}article{background:white;padding:12px;border-radius:8px}h2{font-size:19px}p{font-size:13px}img{width:100%;height:330px;object-fit:contain;background:#171b20}@media(max-width:1000px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}</style>'
 page+=f'<h1>{esc(group["specimen_id"])} {esc(group.get("specimen_variant",""))} · 八张原片对比</h1><p>组ID：{esc(group["group_id"])}。每行CH1～CH4，上排低曝光，下排高曝光；具体曝光以每张标题为准。</p><p>源图尺寸{size[0]}×{size[1]}，全图原点{list(origin)}。本页只浏览，不连接板卡。</p>'
 page+=f'<nav><a href="{quote(FULL)}">八张原片总览</a><a href="{quote(CROP)}">工件区域八张对照</a><a href="{quote(RAW)}/">八张单独原片</a></nav><div class="grid">'+''.join(cards)+'</div></html>'
 (temp/'index.html').write_text(page,encoding='utf-8')
 (temp/'使用说明.txt').write_text('双击index.html同时看八张；每列CH1～CH4，上排低曝光，下排高曝光。\n01为完整源图总览；02只对照显示裁区，没有改动八张原片。\n原片_8张中的文件与采集源PNG逐字节相同，文件名标出实际曝光/增益/LED/帧号。\n这是同一组的浏览副本，不是新采集、训练标签或新的独立样本。\n',encoding='utf-8')
 files={p.relative_to(temp).as_posix():digest(p) for p in temp.rglob('*') if p.is_file()}
 write(temp/'COMPARE_MANIFEST.json',dict(schema='eight-raw-photo-compare-v1',group_id=group['group_id'],specimen_id=group['specimen_id'],
  source_pair=str(pair),source_manifest_sha256=mh,source_origin_xy=list(origin),source_size_xy=list(size),display_crop_source_xyxy=list(box),
  observations=records,files_sha256=files,display_only=True,source_images_modified=False,new_physical_CAP=0,hardware_contacted=False))
 need(not out.exists(),'Comparison destination appeared during generation; preserved temporary output')
 temp.rename(out)
 return dict(status='READY',directory=str(out),index=str(out/'index.html'),reused=False,source_manifest_sha256=mh)

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--pair',type=Path,required=True);parser.add_argument('--out',type=Path)
 args=parser.parse_args();print(json.dumps(create(args.pair,args.out),ensure_ascii=False,indent=2))
