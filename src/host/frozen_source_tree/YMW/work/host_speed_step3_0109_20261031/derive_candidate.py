"""Deterministic, narrowly patched copies of original host UI/control adapters."""
from pathlib import Path
import hashlib
import json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent/'final_board_0109_20261030'
RUNTIME=ROOT/'runtime'

def derive(source, target, edits):
    path=RUNTIME/source; raw=path.read_bytes(); text=raw.decode('utf-8-sig').replace('\r\n','\n')
    for before,after,count in edits:
        if text.count(before)!=count:raise ValueError('Unexpected source layout: '+source+' / '+before[:70])
        text=text.replace(before,after)
    header='# Derived independent host adapter; source SHA256 '+hashlib.sha256(raw).hexdigest()+'\n'
    (HERE/target).write_text(header+text,encoding='utf-8',newline='\n')
    return dict(source=str(path),source_sha256=hashlib.sha256(raw).hexdigest(),target=target,
                edits=[dict(before=a,after=b,count=c) for a,b,c in edits])

def main():
    anchor="HERE=Path("+repr(RUNTIME.as_posix())+")"
    recipes=[]
    recipes.append(derive('app.py','speed_ui_base.py',[
        ('import pipeline','import speed_pipeline as pipeline',1),
        ('HERE=Path(__file__).resolve().parent',anchor,1)]))
    recipes.append(derive('continuous_app.py','speed_app.py',[
        ('HERE=Path(__file__).resolve().parent',anchor,1),
        ('import app as stable_app','import speed_ui_base as stable_app',1),
        ('import pipeline','import speed_pipeline as pipeline',1),
        ('from continuous_capture import Controller,fresh_plan','from speed_capture import Controller,fresh_plan',1),
        ("super().__init__(root,hardware_mode='0109',**kwargs)","kwargs.setdefault('analysis_root',Path('E:/GuangjianData/UnifiedInspectionSpeed0109'))\n        super().__init__(root,hardware_mode='0109',**kwargs)",1),
        ('0109独立候选入口 v1.7','0109软件提速候选 v1.8',1),
        ('def verify_candidate():\n','def verify_candidate():\n    import bootstrap\n    bootstrap.verify()\n',1),
        ("print(json.dumps(dict(status='CONTINUOUS_UI_OFFLINE_READY'","print(json.dumps(dict(status='SPEED_UI_OFFLINE_READY'",1)]))
    recipes.append(derive('continuous_capture.py','speed_capture.py',[
        ('HERE=Path(__file__).resolve().parent',anchor,1),
        ('from verified_evidence import seal_live','from combined_evidence import seal_live',1),
        ('self.batch=SessionBatch(',"from bootstrap import candidate_sources\n        extra.update(candidate_sources())\n        self.batch=SessionBatch(",1)]))
    recipes.append(derive('pipeline.py','speed_pipeline.py',[
        ('    from integrity import verify\n    verify()','    from bootstrap import verify\n    verify()',1),
        ("validation_mode='reuse',capture_started=None):","validation_mode='reuse',capture_started=None,allow_fixture=False,cache_base=None,reference=False):",1),
        ("process=subprocess.Popen([str(executable),'-B','-u',str(HERE/('worker0109.py' if kind=='0109' else 'worker.py')),'--source',str(source),'--kind',kind,'--out',str(out),'--validation-mode',validation_mode]", "command=[str(executable),'-B','-u',str(HERE/('reference_worker.py' if reference else 'speed_worker.py') if kind=='0109' else HERE.parent/'final_board_0109_20261030/runtime/worker.py'),'--source',str(source),'--kind',kind,'--out',str(out),'--validation-mode',validation_mode]\n            if kind=='0109' and allow_fixture:command.append('--allow-fixture')\n            if kind=='0109' and cache_base:command.extend(['--cache-base',str(cache_base)])\n            process=subprocess.Popen(command",1)]))
    recipes.append(derive('worker0109.py','speed_worker.py',[
        ('import argparse,gzip,json,socket,sys,time','import bootstrap\nimport argparse,gzip,json,socket,sys,time',1),
        ('from hybrid import build_context','from combined_evidence import build_context',1),
        ("parser.add_argument('--allow-fixture',action='store_true');", "parser.add_argument('--allow-fixture',action='store_true');parser.add_argument('--cache-base',type=Path);",1),
        ('    from verified_evidence import load as load_evidence', '    from bootstrap import verify\n    verify()\n    from combined_evidence import load as load_evidence',1),
        ("x,validation_mode=load_evidence(a.source,mode=a.validation_mode,allow_fixture=a.allow_fixture)","x,validation_mode=load_evidence(a.source,mode=a.validation_mode,allow_fixture=a.allow_fixture,**({'base':a.cache_base} if a.cache_base else {}))",1),
        ("context,fused,provider=build_context(x['gray'],x['sat1'],x['board'],x['words'])","context,fused,provider=build_context(x)",1),
        ("host_residual_access='exact_native_tiles',host_tile_cache_peak_bytes=provider.peak_cache_bytes", "host_residual_access=x.get('residual_access','exact_native_tiles'),host_tile_cache_peak_bytes=getattr(provider,'peak_cache_bytes',0),host_optimization_id='combined-evidence-v1'",1)]))
    recipes.append(derive('worker0109.py','reference_worker.py',[
        ('import argparse,gzip,json,socket,sys,time','import bootstrap\nimport argparse,gzip,json,socket,sys,time',1),
        ("parser.add_argument('--allow-fixture',action='store_true');", "parser.add_argument('--allow-fixture',action='store_true');parser.add_argument('--cache-base',type=Path);",1),
        ('    from verified_evidence import load as load_evidence','    from bootstrap import verify\n    verify()\n    from verified_evidence import load as load_evidence',1),
        ("x,validation_mode=load_evidence(a.source,mode=a.validation_mode,allow_fixture=a.allow_fixture)","x,validation_mode=load_evidence(a.source,mode=a.validation_mode,allow_fixture=a.allow_fixture,**({'base':a.cache_base} if a.cache_base else {}))",1)]))
    native_source=(RUNTIME/'verified_evidence.py').read_text('utf-8-sig')
    unused_load=native_source[native_source.index('def load('):native_source.index('def seal_live(')]
    recipes.append(derive('verified_evidence.py','combined_evidence.py',[
        ("DEFAULT_CACHE=Path('E:/GuangjianData/VerifiedNative0109')","DEFAULT_CACHE=Path('E:/GuangjianData/VerifiedCombined0109')",1),
        ("SCHEMA='guangjian-verified-native0109-v2'","SCHEMA='guangjian-verified-combined0109-v3'",1),
        ("str(Path(archive.__file__).resolve()):archive.sha(archive.__file__)","str(Path(archive.__file__).resolve()):archive.sha(archive.__file__),str(Path(__file__).with_name('CANDIDATE_BINDING.json')):archive.sha(Path(__file__).with_name('CANDIDATE_BINDING.json'))",1),
        ("np.savez_compressed(temp/'native.npz',gray=x['gray'],sat1=x['sat1'],board=x['board'],words=x['words'])", "archive.need(x['residual_n'].dtype==np.int16 and x['residual_n'].shape==x['gray'].shape and x['valid'].dtype==bool and x['valid'].shape==x['gray'].shape,'Exact derivative arrays required')\n        np.savez(temp/'native.npz',gray=x['gray'],sat_bits=np.packbits(x['sat1'].reshape(-1),bitorder='big'),board_bits=np.packbits(x['board'].reshape(-1),bitorder='big'),words=x['words'],residual_n=x['residual_n'],valid_bits=np.packbits(x['valid'].reshape(-1),bitorder='big'))",1),
        ("with np.load(target/'native.npz',allow_pickle=False) as z:arrays={k:z[k].copy() for k in ('gray','sat1','board','words')}","with np.load(target/'native.npz',allow_pickle=False) as z:\n        shape=(8,r['roi'][3],r['roi'][2]);n=int(np.prod(shape));pixels=shape[1]*shape[2]\n        archive.need(set(z.files)=={'gray','sat_bits','board_bits','words','residual_n','valid_bits'},'Unexpected combined cache members')\n        def unpack(name,count,shape):\n            bits=z[name];archive.need(bits.dtype==np.uint8 and bits.ndim==1 and bits.size==(count+7)//8,'Packed evidence size/type differs')\n            return np.unpackbits(bits,bitorder='big',count=count).reshape(shape).astype(bool)\n        arrays=dict(gray=z['gray'].copy(),words=z['words'].copy(),residual_n=z['residual_n'].copy(),sat1=unpack('sat_bits',n,shape),board=unpack('board_bits',pixels,shape[1:]),valid=unpack('valid_bits',n,shape))\n        archive.need(arrays['residual_n'].dtype==np.int16 and arrays['residual_n'].shape==shape,'Cached residual shape/type differs')",1),
        (unused_load,'',1),
        ("qualification=str(qualification) if result['physical_hardware'] else None,records=records,source_hashes=hashes)","qualification=str(qualification) if result['physical_hardware'] else None,records=records,source_hashes=hashes,residual_n=np.stack([row['residual_n'] for row in rows]),valid=np.stack([row['valid'] for row in rows]))",1)]))
    with (HERE/'combined_evidence.py').open('a',encoding='utf-8') as stream:stream.write('''

def load(root,*,mode='reuse',base=DEFAULT_CACHE,allow_fixture=False,qualification=archive.QUALIFICATION):
    archive.need(mode in ('audit','reuse'),'Unknown validation mode')
    if mode=='reuse' and cache_path(root,base).exists():
        x=restore(root,base,allow_fixture=allow_fixture)
        for name in ('gray','sat1','board','words','residual_n','valid'):x[name].flags.writeable=False
        x['residual_access']='reused_engineering_H2_quality'
        return x,'COMBINED_VERIFIED_HASH_REUSE'
    import verified_evidence as legacy
    legacy_base=legacy.DEFAULT_CACHE if Path(base)==DEFAULT_CACHE else Path(base)/'legacy_native'
    x,label=legacy.load(root,mode=mode,base=legacy_base,allow_fixture=allow_fixture,qualification=qualification)
    x['residual_access']='exact_native_tiles_step1'
    return x,('FULL_STRICT_AUDIT' if mode=='audit' else 'LEGACY_NATIVE_REUSE_NO_DERIVATIVES:'+label)

def build_context(x):
    if 'residual_n' in x and 'valid' in x:
        from hybrid_resume import build_context as resume
        return resume(x['gray'],x['sat1'],x['board'],x['words'],valid=x['valid'],residual=x['residual_n'])
    from hybrid import build_context as original
    context,fused,_=original(x['gray'],x['sat1'],x['board'],x['words'])
    from bootstrap import HERE
    sys.path.insert(0,str(HERE.parent/'host_speed_step1_0109_20261031'))
    from cached_residual import PlannedResidualAccess
    provider=PlannedResidualAccess(x['gray']);context['planes']['residual_n']=provider
    return context,fused,provider
''')
    recipes.append(derive('hybrid.py','hybrid_resume.py',[
        ('HERE=Path(__file__).resolve().parent',anchor,1),
        ('def build_context(gray,sat,board,words):','def build_context(gray,sat,board,words,*,valid,residual):',1),
        ("valid=np.stack([assess_quality(frame)['valid_mask'] for frame in gray])","if valid.dtype!=bool or valid.shape!=gray.shape or residual.dtype!=np.int16 or residual.shape!=gray.shape:raise ValueError('Cached exact derivative arrays required')",1),
        ("unknown=~valid.any(0)","expected_residual=residual[index,yy,xx].copy();expected_residual[source==0]=0\n    if not np.array_equal(fused['residual_n'],expected_residual):raise ValueError('Selected-source residual differs from audited cache')\n    unknown=~valid.any(0)",1),
        ('provider=ResidualAccess(gray)','provider=residual',1)]))
    (HERE/'DERIVATION.json').write_text(json.dumps(recipes,ensure_ascii=False,indent=2)+'\n','utf-8')
    print('Derived',len(recipes),'host adapters; original source not modified')

if __name__=='__main__':main()
