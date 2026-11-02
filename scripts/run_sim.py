"""Run the report's unchanged two RTL fixtures from packaged inputs."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vivado-bin',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    from export_guard import verify
    verify()
    out=args.out.resolve()
    if out.exists():raise FileExistsError('Use a new simulation output directory')
    programs={name:args.vivado_bin/(name+('.bat' if os.name=='nt' else '')) for name in ('xvlog','xelab','xsim')}
    for p in programs.values():
        if not p.is_file():raise FileNotFoundError(p)
    out.mkdir(parents=True)
    rtl=ROOT/'src/fpga/implemented/source/rtl';fixtures=ROOT/'sim/fixtures'
    results={}
    cases=[('h2','tb_h2_scratch',['rgb565_gray.v','h2_background9.v','h2_scratch_writer.v'],
            'clk reset cfg_valid h2_valid h2_ready h2_x h2_y h2_gray h2_r h2_finish awvalid awready wvalid wready wlast bvalid bready bresp writer_valid writer_error pixels_written'.split(),'H2_SCRATCH_ALL_PASS 2'),
           ('maxabs','tb_report_maxabs',['maxabs8_pixel.v'],
            'source residual_n observation_valid previous merged error chosen_r chosen_source weak_flag strong_flag'.split(),'MAXABS_REPORT_PASS 8')]
    for name,top,modules,signals,marker in cases:
        folder=out/name;folder.mkdir()
        for p in (fixtures/name).iterdir():
            if p.is_file():shutil.copy2(p,folder/p.name)
        sources=[]
        for filename in modules:
            p=rtl/filename;target=folder/filename;shutil.copy2(p,target);sources.append(target)
        sources.append(folder/(top+'.sv'))
        (folder/'waves.tcl').write_text('open_vcd waves.vcd\n'+'\n'.join('log_vcd /'+top+'/'+signal for signal in signals)+'\nrun all\nclose_vcd\nquit\n',encoding='ascii')
        commands=[[str(programs['xvlog']),'-sv','-i',str(folder),*map(str,sources)],
                  [str(programs['xelab']),'--debug','typical','--timescale','1ns/1ps',top,'-s','report_sim'],
                  [str(programs['xsim']),'report_sim','-tclbatch','waves.tcl']]
        for i,command in enumerate(commands):
            log=folder/(str(i)+'_tool.log')
            with log.open('w',encoding='utf8') as stream:
                result=subprocess.run(command,cwd=folder,stdout=stream,stderr=subprocess.STDOUT,timeout=240)
            text=log.read_text(encoding='utf8',errors='replace')
            if result.returncode or 'ERROR:' in text or 'Fatal:' in text:raise RuntimeError('Simulation failed: '+str(log))
        if marker not in text:raise RuntimeError('Missing assertion completion marker: '+marker)
        results[name]=dict(status='PASS',assertion_completion=marker,VCD_sha256=sha(folder/'waves.vcd'),
                           source_sha256={p.name:sha(p) for p in sources})
    record=dict(status='PACKAGED_RTL_SIMULATION_PASSED',reports=results,functional_RTL_only=True,
                physical_MIG=False,new_bit=False,board_commands=0,production_RTL_modified=False)
    (out/'RESULT.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(status=record['status'],report=str(out/'RESULT.json'))),flush=True)
if __name__=='__main__':main()
