"""Same archived eight inputs: exact PC core phases and local device services.

No camera commands. System speedup requires separate fair acquisition runs.
"""
import argparse,hashlib,json,statistics,sys,time
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent

def pc_maxabs_words(gray,residual,valid):
    shape=gray.shape[1:];source=np.zeros(shape,np.uint8);best=np.zeros(shape,np.int16);chosen=np.zeros(shape,np.uint8)
    magnitude=np.zeros(shape,np.int32)
    for i in range(8):
        amplitude=np.abs(residual[i].astype(np.int32));take=valid[i]&((source==0)|(amplitude>magnitude))
        source[take]=i+1;best[take]=residual[i][take];chosen[take]=gray[i][take];magnitude[take]=amplitude[take]
    present=source!=0
    words=best.view('<u2').astype(np.uint32)|(source.astype(np.uint32)<<16)|(((magnitude>648)&present).astype(np.uint32)<<20)|(((magnitude>1620)&present).astype(np.uint32)<<21)|(chosen.astype(np.uint32)<<22)
    return words

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--repetitions',type=int,choices=range(3,6),default=3);p.add_argument('--allow-fixture',action='store_true');a=p.parse_args()
    sys.path.insert(0,str(HERE/'runtime'));sys.path.insert(0,str(HERE/'host'))
    from archive0109 import load,read,sha,verify_profiles
    from integrity import verify
    from sdk_loader import load_sdk
    target=a.out.resolve();input_root=a.source.resolve()
    if target.is_relative_to(input_root) or input_root.is_relative_to(target) or target.is_relative_to(HERE) or HERE.is_relative_to(target):raise ValueError('Output overlaps input or source code')
    verify();x=load(a.source,allow_fixture=a.allow_fixture);sdk=load_sdk(qualification=x['qualification'])
    from hybrid import build_context
    build_context(x['gray'],x['sat1'],x['board'],x['words']) # verify/load exact pinned quality dependency
    from light_inspection.real_baseline import assess_quality
    source=read(x['root']/'RESULT.json');profiles=verify_profiles(source);rows=[]
    # All source bytes have passed strict validation first. These intervals start
    # with native planes in RAM and exclude validation/imports/disk/GUI.
    for repetition in range(a.repetitions):
        started=time.perf_counter();residual=np.stack([sdk.wire.reference.integer_h2(g)['residual_n'] for g in x['gray']]);h2=time.perf_counter()-started
        started=time.perf_counter();valid=np.stack([assess_quality(g)['valid_mask'] for g in x['gray']]);quality=time.perf_counter()-started
        started=time.perf_counter();words=pc_maxabs_words(x['gray'],residual,valid);fusion=time.perf_counter()-started
        differences=int(np.count_nonzero(words!=x['words']))
        if differences:raise ValueError('PC MaxAbs/R32 differs from saved device: '+str(differences))
        rows.append(dict(repetition=repetition+1,H2_eight_RAM_seconds=h2,PC_quality_eight_RAM_seconds=quality,MaxAbs_R32_eight_RAM_seconds=fusion,R32_word_differences=differences))
    medians={k:statistics.median(r[k] for r in rows) for k in ('H2_eight_RAM_seconds','PC_quality_eight_RAM_seconds','MaxAbs_R32_eight_RAM_seconds')}
    services=[]
    for stage in range(3):
        selected=[r for r in profiles if r['stage']==stage];frequency=125000000 if stage==0 else 100000000
        cycles=sum(r['service_cycles'] for r in selected)
        services.append(dict(stage=stage,clock_hz=frequency,eight_service_cycles=cycles,eight_service_seconds=cycles/frequency,
            frames=[dict(slot=r['slot'],service_cycles=r['service_cycles'],count0=r['count0'],count1=r['count1'],blocked_cycles=r['blocked_cycles']) for r in selected]))
    physical=x['physical_hardware']
    ratios=dict(H2_RAM_PC_over_device_inclusive_service=medians['H2_eight_RAM_seconds']/services[0]['eight_service_seconds'] if physical else None,
        MaxAbs_R32_RAM_PC_over_device_inclusive_service=medians['MaxAbs_R32_eight_RAM_seconds']/services[2]['eight_service_seconds'] if physical else None)
    if not all(sha(p)==digest for p,digest in x['source_hashes'].items()):raise ValueError('Input changed during comparison')
    result=dict(status='SAME_INPUT_PHASE_COMPARISON',group_id=x['group_id'],physical_hardware=physical,software_model=not physical,repetitions=a.repetitions,
        PC_samples=rows,PC_median_seconds=medians,device_local_services=services,phase_scope_ratios=ratios,
        system_speedup=None,FPGA_arithmetic_only_cycles=None,quality_upload_and_FETCH_excluded_from_core_phases=True,
        acquisition_E2E_comparison_complete=False,frozen_algorithm='f09eb5885e1d',new_CAP=0,
        scope='PC exact H2 and earliest-valid MaxAbs/R32 with native inputs in RAM vs actual device inclusive phase services. Includes device DDR/CDC; scratch listed separately. Not the whole detection or acquisition speedup. Domains overlap and must not be summed.',
        source_sha256=x['source_hashes'],benchmark_source_sha256=sha(Path(__file__)))
    target.mkdir(parents=True,exist_ok=False);(target/'SAME_INPUT_PHASES.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('SAME_INPUT_PHASES_COMPLETE',str(target), 'physical='+str(physical),flush=True)
if __name__=='__main__':main()
