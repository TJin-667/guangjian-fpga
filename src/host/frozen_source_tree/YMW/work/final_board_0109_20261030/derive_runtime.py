"""Derive a separate 0109 operator entry; original 0108 UI and math stay pinned."""
import hashlib,json,re,subprocess
from pathlib import Path
from derive_candidate import HERE,replace

REPO=HERE.parents[2]
PARENT='73a0cf3b12242a02fe0fbf96adbf25d380db6822'
sources={}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def original(path):
    member=HERE.parent/path
    raw=subprocess.check_output(['git','show',PARENT+':'+member.relative_to(REPO).as_posix()],cwd=REPO)
    if raw!=member.read_bytes():raise ValueError('Parent changed: '+str(member))
    sources[member.relative_to(REPO).as_posix()]=sha(member)
    return raw.decode('utf-8').replace('\r\n','\n')
def rebase(s):
    if 'HERE.parent' in s:
        s=re.sub(r'HERE\.parent(?!s)', 'WORK',s)
        s=replace(s,'HERE=Path(__file__).resolve().parent','HERE=Path(__file__).resolve().parent\nWORK=HERE.parents[1]')
    return s
def write(name,s):
    (HERE/'runtime'/name).write_text(s,encoding='utf-8')

def main():
    out=HERE/'runtime';out.mkdir(exist_ok=True)
    for name in ('app','archive0108','contracts','engineering0108','focus0108','frozen_algorithm','hybrid','location0108','performance','pipeline','residual_access','roi_prepare0108','verified_evidence','worker','worker0108'):
        s=rebase(original('final_system_20261029/'+name+'.py'))
        # Do not rename the immutable numerical kernel folders.
        s=s.replace('0108','0109').replace('fusion_offload_0109_20261028','fusion_offload_0108_20261028')
        if name=='archive0108':
            s=replace(s,"HOST=WORK/'fusion_board_0109_20261028/host'","HOST=HERE.parent/'host'")
            s=replace(s,"E:/GuangjianData/fpga_0109_board_20261028/engineering_bit_01/QUALIFICATION.json","E:/GuangjianData/final_board_0109_20261030/engineering_bit_01/QUALIFICATION.json")
            s=s.replace("r['firmware']==264","r['firmware']==265")
            s=replace(s,"    roi=result['roi'];raw=", "    low,high=result['low_lines'],result['high_lines'];need(type(low) is int and type(high) is int and 1<=low<high<=1116,'Invalid frozen pair')\n    roi=result['roi'];raw=")
            s=s.replace('(400 if slot%2 else 800)','(low if slot%2 else high)')
            s=replace(s,'physical_hardware=physical,source_hashes=source_hashes,','low=low,high=high,physical_hardware=physical,source_hashes=source_hashes,')
            s=replace(s,"    need(len(result['frames'])==8", "    verify_profiles(result)\n    need(len(result['frames'])==8")
            s+='''
def verify_profiles(result):
    sys.path.insert(0,str(HOST))
    from device_profiles import validate
    return validate(result)
'''
        elif name=='engineering0108':
            s=replace(s,'def prepare_native(roi,source,sample,pose,destination,*,pixel_format=50):','def prepare_native(roi,source,sample,pose,destination,*,pixel_format=50,low=400,high=800):')
            s=replace(s,'out=destination,pixel_format=pixel_format)','out=destination,pixel_format=pixel_format,low_lines=low,high_lines=high)')
            s=s.replace("group_board=board,result_directory=root/'fusion',", "group_board=board,group_low=plan['low_lines'],group_high=plan['high_lines'],result_directory=root/'fusion',")
            s=s.replace('exposure_lines=400 if slot%2 else 800',"exposure_lines=plan['low_lines'] if slot%2 else plan['high_lines']")
            s=s.replace('exposure_lines=400,gain16',"exposure_lines=plan['low_lines'],gain16")
        elif name in ('focus0108','location0108'):
            s=s.replace('required_firmware=264','required_firmware=265').replace("meta['firmware']==264","meta['firmware']==265")
        elif name=='contracts':s=s.replace("SYSTEM_VERSION='v1.5'","SYSTEM_VERSION='v1.7-candidate'")
        elif name=='performance':
            s=replace(s,"    end=path.parent/'END_TO_END.json'", "    if (path.parent/'DEVICE_SERVICE.html').is_file():rows.append('<h2>器件分段计数</h2><p><a href=\"DEVICE_SERVICE.html\">逐帧服务周期、握手计数及范围说明</a></p>')\n    end=path.parent/'END_TO_END.json'")
        elif name=='verified_evidence':
            s=replace(s,"    source=archive.read(root/'RESULT.json')", "    source=archive.read(root/'RESULT.json');archive.verify_profiles(source)")
            s=replace(s,"    gray=[];sat=[];records=[];hashes=", "    archive.verify_profiles(result)\n    gray=[];sat=[];records=[];hashes=")
            s=s.replace("record['firmware']==264","record['firmware']==265").replace("r['firmware']==264","r['firmware']==265")
            s=s.replace('(400 if slot%2 else 800)',"(result['low_lines'] if slot%2 else result['high_lines'])")
            s=s.replace("sample=x['sample'],roi=x['roi'],", "sample=x['sample'],low=x['low'],high=x['high'],roi=x['roi'],")
            s=s.replace("sample=r['sample'],roi=r['roi'],", "sample=r['sample'],low=source['low_lines'],high=source['high_lines'],roi=r['roi'],")
            s=s.replace("sample=sample,roi=roi,gray=np.stack(gray)","sample=sample,low=result['low_lines'],high=result['high_lines'],roi=roi,gray=np.stack(gray)")
        elif name=='worker0108':
            s=replace(s,"parser.add_argument('--validation-mode'", "parser.add_argument('--allow-fixture',action='store_true');parser.add_argument('--validation-mode'")
            s=s.replace("load_evidence(a.source,mode=a.validation_mode)","load_evidence(a.source,mode=a.validation_mode,allow_fixture=a.allow_fixture)")
            s=s.replace('low=400,high=800',"low=x['low'],high=x['high']").replace('low_lines=400,high_lines=800',"low_lines=x['low'],high_lines=x['high']")
            s=s.replace('physical_hardware=True',"physical_hardware=x['physical_hardware']").replace('physical_hardware_input=True',"physical_hardware_input=x['physical_hardware']")
            s=s.replace("exposure_role='FORMAL_400_800'","exposure_role='FORMAL_400_800' if (x['low'],x['high'])==(400,800) else 'DEVELOPMENT_MANUAL_PAIR'")
            s=replace(s,"    capture_profile=x['root'].parent/'CAPTURE_PERFORMANCE.json'", "    from device_performance import export\n    export(x,a.out)\n    capture_profile=x['root'].parent/'CAPTURE_PERFORMANCE.json'")
        elif name=='app':
            s=s.replace('0109工程模式：调焦、单张定位和8帧流程已完成实板功能对照；接口/复位发布资格仍待收尾。','0109独立候选：新增人工曝光配置和器件分段计数；尚待本版实板验收。')
            s=s.replace('两种模式都保留八帧gray/SAT证据；候选灰度模式先做一组实板确认。默认保留RGB审计。','两种模式都保留八帧gray/SAT证据。正式默认400/800；其他曝光作为开发对照。')
        write(name.replace('0108','0109')+'.py',s)

    for name in ('session_batch','continuous_capture','continuous_app'):
        s=original('performance_followup_0108_20261030/'+name+'.py').replace('0108','0109')
        if name=='session_batch':
            s=s.replace("Path(__file__).resolve().parent.parent/'final_system_20261029'","Path(__file__).resolve().parent")
            s=replace(s,"need((self.low_lines,self.high_lines)==(400,800),'Current0109 fusion firmware requires400/800; no CAP issued for unsupported exposure')", "need(type(self.low_lines) is int and type(self.high_lines) is int and 1<=self.low_lines<self.high_lines<=1116,'Legal ordered manual exposure pair required')")
            s=replace(s,'group_id=plan.group,group_digest=plan.digest,group_roi=plan.roi,','group_id=plan.group,group_digest=plan.digest,group_roi=plan.roi,group_low=plan.low_lines,group_high=plan.high_lines,')
            s=replace(s,'e._off_group=plan.group;e._off_digest=plan.digest;e._off_roi=plan.roi','e._off_pair=(plan.low_lines,plan.high_lines)\n        e._off_group=plan.group;e._off_digest=plan.digest;e._off_roi=plan.roi')
            s=s.replace('exposure_lines=400 if slot%2 else 800','exposure_lines=plan.low_lines if slot%2 else plan.high_lines')
            s=s.replace('FPGA_core_cycles=None,FPGA_core_speedup=None,release_ready=False','device_profiles=actual[\'device_profiles\'],FPGA_core_speedup=None,release_ready=False')
        else:
            s=replace(s,"STABLE=HERE.parent/'final_system_20261029'","STABLE=HERE")
        if name=='continuous_capture':
            s=replace(s,"need((low,high)==(400,800),'当前0109融合bit仅支持400/800；自定义曝光尚未支持，本次没有发出CAP。')","need(type(low) is int and type(high) is int and 1<=low<high<=1116,'曝光需为1～1116行整数，且低曝光小于高曝光。')")
            s=replace(s,'target,pixel_format=pixel_format)','target,pixel_format=pixel_format,low=low,high=high)')
            s=replace(s,"schema')=='0109-engineering-capture-plan-v1'", "schema')=='0109-engineering-capture-plan-v1'")
        elif name=='continuous_app':
            start=s.index('def verify_candidate():');end=s.index('\n\nclass ContinuousApp',start)
            s=s[:start]+'''def verify_candidate():
    result=stable_app.verify_dependencies()
    from archive0109 import HOST,QUALIFICATION
    sys.path.insert(0,str(HOST))
    from qualification import validate
    validate(QUALIFICATION)
    return result
'''+s[end:]
            s=replace(s,"        if (settings.low,settings.high)!=(400,800):\n            self.status.set('当前0109融合bit只支持400/800行；自定义曝光待最终bit支持。本次没有发出CAP。');return", "        if not 1<=settings.low<settings.high<=1116:\n            self.status.set('低、高曝光须为1～1116行整数，且低值小于高值。');return")
            s=s.replace('连续采集实验入口 v1.6','0109独立候选入口 v1.7')
            s=s.replace('现0109融合bit支持400/800；其他曝光组合会在CAP前拒绝，等待最终bit支持。','默认400/800行；可人工设置下一组曝光。组内锁定，逐帧核对实际写入与读回。')
            s=s.replace('current_firmware_exposure=[400,800]','default_exposure=[400,800],manual_exposure_range=[1,1116],device_service_cycles_enabled=True')
        write(name+'.py',s)

    s=original('fusion_board_0108_20261028/host/engineering_capture.py').replace('0108','0109').replace('_off108','_off109')
    s=replace(s,'+math.ceil(4*w*h/1024)+32','+math.ceil(4*w*h/1024)+64')
    s=replace(s,'    qualification,proofs=validate(args.qualification)',"    require(type(args.low_lines) is int and type(args.high_lines) is int and 1<=args.low_lines<args.high_lines<=1116,'Legal ordered manual exposure pair required')\n    qualification,proofs=validate(args.qualification)")
    s=s.replace('low_lines=400,high_lines=800','low_lines=args.low_lines,high_lines=args.high_lines').replace('low_high=[400,800]','low_high=[args.low_lines,args.high_lines]')
    s=s.replace('group_roi=roi,group_board=board,',"group_roi=roi,group_board=board,group_low=plan['low_lines'],group_high=plan['high_lines'],")
    s=s.replace('exposure_lines=400 if slot%2 else 800',"exposure_lines=plan['low_lines'] if slot%2 else plan['high_lines']")
    s=s.replace("a.add_argument('--pixel-format'","a.add_argument('--low-lines',type=int,default=400);a.add_argument('--high-lines',type=int,default=800)\n    a.add_argument('--pixel-format'")
    (HERE/'host/engineering_capture.py').write_text(s,encoding='utf-8')
    s=original('fusion_board_0108_20261028/host/qualification.py').replace('0108-engineering-candidate','0109-engineering-candidate').replace('0108-route-verification','0109-route-verification').replace('0108 engineering qualification','0109 engineering qualification')
    (HERE/'host/qualification.py').write_text(s,encoding='utf-8')
    s=original('fusion_board_0108_20261028/common.py')
    (HERE/'route_common.py').write_text(s,encoding='utf-8')
    s=original('fusion_board_0108_20261028/audit_candidate.py').replace('from common import','from route_common import')
    (HERE/'audit_candidate.py').write_text(s,encoding='utf-8')
    s=original('fusion_board_0108_20261028/finish_engineering_candidate.py').replace('from common import','from route_common import')
    start=s.index("    for path in [*(HERE/'rtl')");end=s.index("    proof=json.loads",start)
    s=s[:start]+'''    for path in [*(HERE/'generated/rtl').glob('*.v'),*(HERE/'generated/integration').glob('*.v'),*(HERE/'rtl').glob('*.v')]:
        folder='integration' if path.parent.name=='integration' else 'rtl'
        if sha(path)!=sha(build/'source'/folder/path.name):raise ValueError('Current RTL differs from actual route '+path.name)
    run=json.loads((build/'TOOL_RUN.json').read_text('utf-8'))
    if run['returncode']!=0 or run['source_unchanged'] is not True:raise ValueError('Incomplete implementation')
    for name,source_digest in inputs['candidate_source_sha256'].items():
        if sha(name)!=source_digest:raise ValueError('Implementation source changed '+name)
'''+s[end:]
    s=s.replace('guangjian-0108-route','guangjian-0109-route').replace('guangjian-0108-engineering','guangjian-0109-engineering').replace('bx72_0108_fusion_', 'bx72_0109_fusion_').replace('EMIT0108','EMIT0109')
    (HERE/'finish_engineering_candidate.py').write_text(s,encoding='utf-8')
    s=original('reset_acceptance_0108_20261030/reset_window.py').replace('0108','0109').replace('0x108','0x109').replace('_reset108','_reset109').replace('RESET108','RESET109')
    s=replace(s,"HOST = WORK / 'fusion_board_0109_20261028/host'", "HOST = HERE / 'host'")
    s=replace(s,"RUNTIME = WORK / 'final_system_20261029'", "RUNTIME = HERE / 'runtime'")
    s=replace(s,"E:/GuangjianData/software/FinalSystem_20261029/candidate0109/QUALIFICATION.json", "E:/GuangjianData/final_board_0109_20261030/engineering_bit_01/QUALIFICATION.json")
    s=s.replace("HERE / 'TOOL_BINDING.json'", "HERE / 'RESET_TOOL_BINDING.json'")
    s=s.replace("HERE/'TOOL_BINDING.json'","HERE/'RESET_TOOL_BINDING.json'")
    (HERE/'reset_window.py').write_text(s,encoding='utf-8')
    (HERE/'RUNTIME_DERIVATION.json').write_text(json.dumps(dict(parent_commit=PARENT,parent_files_sha256=sources,changes='Isolated109 firmware/protocol, rebased imports, explicit per-group manual exposure, exact frozen f09 unchanged'),indent=2)+'\n',encoding='utf-8')
    print('DERIVED0109_RUNTIME',len(list(out.glob('*.py'))),flush=True)
if __name__=='__main__':main()
