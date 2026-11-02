"""Read original implementation reports, including hierarchical utilization."""
import argparse,csv,hashlib,json,re
from pathlib import Path

def resources(report):
    text=report.read_text(encoding='utf-8')
    for line in text.splitlines():
        cells=[p.strip() for p in line.split('|')[1:-1]]
        if len(cells)==10 and cells[0]=='bx72_ddr_identity_top':
            return dict(LUT=int(cells[2]),FF=int(cells[6]),BRAM_36K_equivalent=int(cells[7])+int(cells[8])/2,DSP=int(cells[9]))
    result={}
    for key,label in [('LUT','Slice LUTs'),('FF','Slice Registers'),('BRAM_36K_equivalent','Block RAM Tile'),('DSP','DSPs')]:
        match=re.search(r'\|\s*'+re.escape(label)+r'\s*\|\s*([\d.]+)',text)
        if not match:raise ValueError('missing resource '+label)
        result[key]=float(match.group(1))
    return result

def audit(out,*,tool_returncode=None):
    out=Path(out);reports=out/'build/reports';status=out/'build/build_status.csv'
    result={'routed':(out/'build/routed.dcp').exists(),'timing_met':False,'bram_budget_met':None,'hardware_tested':False,'bit_generated':False,'release_ready':False,'tool_returncode':tool_returncode}
    if status.exists():
        rows=list(csv.DictReader(status.open()));assert len(rows)==1
        result.update(mode=rows[0]['mode'],wns_ns=float(rows[0]['wns_ns']),whs_ns=float(rows[0]['whs_ns']),timing_met=rows[0]['timing_met']=='1')
    utilization=reports/'utilization_routed.rpt'
    if utilization.exists():
        result['resources']=resources(utilization);result['bram_budget_met']=result['resources']['BRAM_36K_equivalent']<=108
    result['resource_and_timing_gate_passed']=result['routed'] and result['timing_met'] and result['bram_budget_met'] is True
    result['limits']=['No bitstream or physical operation.','Internal setup/hold and BRAM gate only; original external IO qualification gaps remain.']
    result['report_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in reports.glob('*.rpt')}
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();r=audit(a.out)
    path=a.out/'independent_report_audit.json'
    with path.open('x',encoding='utf-8') as f:json.dump(r,f,indent=2);f.write('\n')
    print(json.dumps(r,indent=2))
