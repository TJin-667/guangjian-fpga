"""Reopen and independently report final routed DCPs without altering them."""
import argparse,csv,subprocess,time
from pathlib import Path
from run_real_rtl import HERE,sha,dump

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('E:/GuangjianData/fpga_0108_20261028'));p.add_argument('--out',required=True,type=Path);a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);reports=[]
    for top,folder in [('fusion_axi_frame','synthesis_08'),('h2_scratch_writer','synthesis_06'),('fusion_group_guard','synthesis_09')]:
        checkpoint=a.root/folder/'build'/top/'routed.dcp';before=sha(checkpoint);audit=out/top
        cmd=['F:/Xilinx/Vivado/2018.3/bin/vivado.bat','-mode','batch','-source',str(HERE/'synth/audit_checkpoint.tcl'),
             '-log',str(out/(top+'.log')),'-journal',str(out/(top+'.jou')),'-tclargs',str(checkpoint),str(audit)]
        print('AUDIT_CHECKPOINT',top,flush=True)
        with (out/(top+'_console.txt')).open('w',encoding='utf-8') as log:r=subprocess.run(cmd,cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        row=dict(top=top,checkpoint=str(checkpoint),checkpoint_sha256=before,tool_returncode=r.returncode)
        if r.returncode or sha(checkpoint)!=before:raise RuntimeError('Checkpoint audit failed '+top)
        row['timing']=list(csv.DictReader((audit/'status.csv').open()))[0]
        if row['timing']['blackboxes']!='0':raise ValueError('Blackbox in checkpoint')
        if 'CHECKPOINT_AUDIT_COMPLETE' not in (out/(top+'_console.txt')).read_text('utf-8'):raise ValueError('Missing audit marker')
        row['reports_sha256']={f.name:sha(f) for f in audit.glob('*.rpt')};reports.append(row)
    dump(out/'VERIFICATION.json',dict(status='REOPEN_AUDIT_PASS_NOT_BOARD_QUALIFICATION',modules=reports,
        original_failed_tool_exits_not_erased=True,new_bit_generated=False,board_commands=0))
    print('CHECKPOINT_AUDIT_PASS',len(reports),flush=True)

if __name__=='__main__':main()
