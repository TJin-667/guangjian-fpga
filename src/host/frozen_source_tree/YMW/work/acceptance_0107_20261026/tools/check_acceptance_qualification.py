"""Compare exact new native reports; never turn open IO gaps into approval."""
import argparse,collections,csv,hashlib,json,sys
from pathlib import Path
REPO=Path('C:/bx72_ymw_0105_20261015/repo')
OLD=REPO/'YMW/work/gray_transport_0105_20261025'
HERE=REPO/'YMW/work/acceptance_0107_20261026'
sys.path.insert(0,str(OLD))
from review_io_cdc import cdc,drc

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--finished',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    current_path=a.build/'build/reports/cdc_routed.rpt';prior_path=OLD/'verification/postroute_03/native_audit/cdc.rpt'
    current,counts=cdc(current_path.read_text());prior,old_counts=cdc(prior_path.read_text())
    key=lambda r:(r['rule'],r['source'],r['destination'])
    before={key(r):r for r in prior};after={key(r):r for r in current}
    added=[v for k,v in after.items() if k not in before];removed=[v for k,v in before.items() if k not in after]
    changed=[dict(before=before[k],after=v) for k,v in after.items() if k in before and any(v[f]!=before[k][f] for f in ('severity','depth','exception'))]
    drc_path=a.finished/'audit_reports/drc_expanded.rpt';paths,drc_counts=drc(drc_path.read_text())
    if any(r['severity']!='Warning' for r in paths) or 'CHECK-3' in drc_counts:raise ValueError('Blocking/truncated DRC')
    bundles=list(csv.DictReader((a.finished/'audit_reports/bundle_paths.tsv').open(),delimiter='\t'))
    if len(bundles)!=5 or any(float(r['slack_ns'])<0 or int(r['sources'])!=int(r['destinations']) for r in bundles):raise ValueError('Mailbox coverage')
    xdc=(a.finished/'audit_reports/effective_timing.xdc').read_text()
    if 'set_clock_groups' in xdc:raise ValueError('Broad clock group exception')
    for row in bundles:
        for command in ('set_max_delay -datapath_only','set_bus_skew'):
            if not any(line.startswith(command) and row['bundle'] in line for line in xdc.splitlines()):raise ValueError('Missing mailbox bound')
    # Compare pin assignments directly to the already reviewed native0106 IO.
    now=list(csv.DictReader((a.finished/'audit_reports/ports.tsv').open(),delimiter='\t'))
    old=list(csv.DictReader((OLD/'verification/io_cdc_native_02/reports/ports.tsv').open(),delimiter='\t'))
    if {r['port']:r for r in now}!={r['port']:r for r in old}:raise ValueError('Port/pin/IO standard changed')
    if added or removed or changed:raise ValueError('New/changed CDC requires review before packaging')
    result=dict(status='REVIEWED_WITH_OPEN_EXTERNAL_QUALIFICATION',review_checks_passed=True,
        CDC=dict(entries=len(current),counts=counts,old_counts=old_counts,added=added,removed=removed,changed=changed,bundles=bundles),
        DRC=dict(entries=len(paths),counts=drc_counts,all_reported_warning=True),
        IO=dict(assignments_unchanged=True,ports=len(now),external_IO_qualified=False),
        source_reports_sha256={str(p):sha(p) for p in [current_path,prior_path,drc_path,a.finished/'audit_reports/ports.tsv',a.finished/'audit_reports/effective_timing.xdc']},
        hardware_contacted=False,release_ready=False,
        remaining=['BX72-V1.1/251215 applicability and actual IO voltage','PHY actual delay registers and PCB RGMII budget',
                   'Current OV5640 DVP mode/cable/board budget','Original clock-route override/MIG reset warnings; hardware common-reset window pending'])
    (out/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'CDC_INVENTORY.json').write_text(json.dumps(current,indent=2)+'\n')
    (out/'DRC_INVENTORY.json').write_text(json.dumps(paths,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_reports_sha256','CDC')},indent=2))
if __name__=='__main__':main()
