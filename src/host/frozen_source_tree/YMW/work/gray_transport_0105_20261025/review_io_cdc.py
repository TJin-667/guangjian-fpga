"""Independently inventory native reports; no waivers or release approval."""
import argparse,collections,csv,hashlib,json,re
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
BASE=REPO/'TJ/work/fpga_image_pipeline/evidence/ymw_2018_20261015_final_lab/final_audit'
CHECKPOINT_SHA='175d82b777469cc1e94d4123ace9935ea25f8d47902476ee6f926ca47c30c947'
CDC_ROW=re.compile(r'^\s*\d+\s+(CDC-\d+)\s+(Info|Warning|Critical)\s+.*?\s+(\d+)\s+(Max Delay Datapath Only|False Path|None)\s+(\S+)\s+(\S+)\s*$')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def need(condition,message):
    if not condition:raise ValueError(message)

def cdc(text):
    rows=[];summary={};source_clock=destination_clock=None
    for line in text.splitlines():
        if m:=re.match(r'^(CDC-\d+)\s+(Info|Warning|Critical)\s+(\d+)\s+',line):summary[m[1]]=int(m[3])
        if line.startswith('Source Clock: '):source_clock=line.split(': ',1)[1]
        if line.startswith('Destination Clock: '):destination_clock=line.split(': ',1)[1]
        if m:=CDC_ROW.match(line):
            rule,severity,depth,exception,source,destination=m.groups()
            rows.append(dict(rule=rule,severity=severity,depth=int(depth),exception=exception,source=source,destination=destination,
                             source_clock=source_clock,destination_clock=destination_clock))
    need(dict(collections.Counter(row['rule'] for row in rows))==summary,'CDC detail count differs from native summary')
    need(len({(p['rule'],p['source'],p['destination']) for p in rows})==len(rows),'Duplicate CDC inventory key')
    return rows,summary

def drc(text):
    counts={m[1]:int(m[4]) for m in re.finditer(r'^\|\s+([A-Z][A-Z0-9]*-\d+)\s+\|\s+(Warning|Error|Critical Warning)\s+\|\s+([^|]+)\|\s+(\d+)\s+\|',text,re.M)}
    headers=list(re.finditer(r'^([A-Z][A-Z0-9]*-\d+)#(\d+)\s+(Warning|Error|Critical Warning)\s*$',text,re.M))
    rows=[]
    for i,m in enumerate(headers):
        row=dict(rule=m[1],index=int(m[2]),severity=m[3],detail=text[m.end():headers[i+1].start() if i+1<len(headers) else len(text)].strip())
        if row['rule'] in ('REQP-1839','REQP-1840'):
            n=re.search(r'has an input control pin (\S+) \(net: ([^)]+)\) which is driven by a register \(([^)]+)\)',row['detail'])
            need(n is not None,'Unparsed async RAM control')
            row.update(pin=n[1],net=n[2],driver=n[3],cell=n[1].rsplit('/',1)[0])
        rows.append(row)
    need(dict(collections.Counter(row['rule'] for row in rows))==counts,'DRC detail count differs from native summary')
    need(sum(counts.values())==int(re.search(r'Violations found:\s*(\d+)',text)[1]),'DRC total mismatch')
    return rows,counts

def review(audit,out,source_root):
    audit=Path(audit);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    receipt=json.loads((audit/'verification.json').read_bytes());reports=audit/'reports'
    need(receipt['completed'] and receipt['returncode']==0 and receipt['checkpoint_sha256']==CHECKPOINT_SHA,'Native audit incomplete/wrong checkpoint')
    for name,digest in receipt['reports_sha256'].items():need(sha(reports/name)==digest,'Changed native report '+name)
    need(sha(audit/'audit_script.tcl')==receipt['script_sha256'],'Native audit script changed')
    need(sha(HERE/'audit_io_cdc.tcl')==receipt['script_sha256'],'Native audit no longer matches current script')
    limit=(reports/'reporting_limit.txt').read_text()
    need('before=20' in limit and 'after=100000' in limit,'Expanded reporting not confirmed')
    current_path=HERE/'verification/postroute_03/native_audit/cdc.rpt'
    current,counts=cdc(current_path.read_text());baseline,base_counts=cdc((BASE/'inspection/cdc.rpt').read_text())
    prior=json.loads((BASE/'cdc_inventory.json').read_bytes())['paths']
    key=lambda p:(p['rule'],p['source'],p['destination'])
    need({key(p) for p in baseline}=={key(p) for p in prior},'Baseline native report and prior inventory differ')
    before={key(p):p for p in baseline};after={key(p):p for p in current}
    added=[p for k,p in after.items() if k not in before];removed=[p for k,p in before.items() if k not in after]
    changed=[dict(current=p,baseline=before[k]) for k,p in after.items() if k in before and any(p[f]!=before[k][f] for f in ('severity','depth','exception'))]
    warnings=collections.Counter()
    for row in current:
        if row['severity']=='Warning':
            group=re.sub(r'/held_data_reg.*','',row['source']) if '/held_data_reg' in row['source'] else row['rule']
            warnings[group]+=1
    bundles=list(csv.DictReader((reports/'bundle_paths.tsv').open(newline=''),delimiter='\t'))
    need(len(bundles)==5,'Expected five held-data mailboxes')
    for row in bundles:
        need(int(row['sources'])==int(row['destinations'])==warnings[row['bundle']],'Mailbox endpoints do not match CDC report')
        need(float(row['slack_ns'])>=0 and int(row['path_count'])==1,'Mailbox bound failed')
    xdc=(reports/'effective_timing.xdc').read_text()
    need('set_clock_groups' not in xdc,'Unexpected broad asynchronous clock-group exception')
    for row in bundles:
        need(any(row['bundle'] in line and line.startswith('set_max_delay -datapath_only') for line in xdc.splitlines()),'Mailbox max delay missing')
        need(any(row['bundle'] in line and line.startswith('set_bus_skew') for line in xdc.splitlines()),'Mailbox bus skew missing')
    all_drc,drc_counts=drc((reports/'drc_expanded.rpt').read_text())
    need('CHECK-3' not in drc_counts,'DRC reporting remains truncated')
    objects=list(csv.DictReader((reports/'violations.tsv').open(newline=''),delimiter='\t'))
    need(len(objects)==len(all_drc),'DRC object inventory differs from text')
    need(collections.Counter(v['violation'].split('#')[0] for v in objects)==drc_counts,'DRC object rules differ from text')
    async_ram=[p for p in all_drc if p['rule'] in ('REQP-1839','REQP-1840')]
    by_driver=collections.Counter(p['driver'] for p in async_ram)
    by_group=collections.Counter('u_source/packets' if p['pin'].startswith('u_source/packets/') else 'u_mask' if p['pin'].startswith('u_mask/') else 'u_source/analysis' if p['pin'].startswith('u_source/analysis/') else 'DDR_read_FIFO' if '/rd_ddr3_fifo/' in p['pin'] else 'DDR_write_FIFO' if '/wr_ddr3_fifo/' in p['pin'] else 'unclassified' for p in async_ram)
    need('unclassified' not in by_group,'Unclassified asynchronous RAM control')
    manifest_path=source_root/'input_manifest.json';manifest=json.loads(manifest_path.read_bytes())
    for name,digest in manifest['source_sha256'].items():need(sha(source_root/'source'/name)==digest,'Build source snapshot changed '+name)
    relevant=['rtl/cdc_snapshot_mailbox.v','rtl/reset_release_sync.v','rtl/frozen_frame_owner.v','rtl/axi4_to_fifo_epoch.v',
        'rtl/capture_identity_bridge.v','rtl/ov5640_manual_bridge_identity.v','rtl/board_mask_store.v',
        'rtl/transport_packet_store.v','constraints/tj_cdc_physical.tcl','constraints/pinned_board_pins.xdc']
    source_hashes={name:manifest['source_sha256'][name] for name in relevant}
    for name in relevant:
        if name in ('rtl/transport_packet_store.v','constraints/pinned_board_pins.xdc'):continue
        need(sha(REPO/'TJ/work/fpga_image_pipeline'/name)==source_hashes[name],'Reviewed RTL differs from built snapshot '+name)
    need(sha(HERE/'transport_packet_store.v')==source_hashes['rtl/transport_packet_store.v'],'Transport RAM source changed')
    result=dict(schema='guangjian-io-cdc-review-v1',status='REVIEWED_WITH_OPEN_QUALIFICATION_GAPS',checkpoint_sha256=CHECKPOINT_SHA,
        native_audit_completed=True,review_checks_passed=True,release_ready=False,hardware_contacted=False,new_physical_captures=0,
        CDC=dict(native_entries=len(current),counts=counts,baseline_counts=base_counts,added=added,removed=removed,changed=changed,
            warning_groups=warnings,mailbox_bounds=bundles,baseline_relation='Same rule/source/destination keys, depth, severity and exception; not proof of physical IO or reset qualification'),
        DRC=dict(expanded_total=len(all_drc),counts=drc_counts,report_cap_before=20,report_cap_after=100000,
            async_RAM_control_paths=len(async_ram),async_RAM_drivers=by_driver,async_RAM_groups=by_group,
            original_54_included_two_report_limit_notices=True,all_reported_severity_warning=all(p['severity']=='Warning' for p in all_drc)),
        source_snapshot_sha256=source_hashes,source_manifest_sha256=sha(manifest_path),reviewer_source_sha256=sha(Path(__file__)),
        evidence_sha256={str(current_path.relative_to(REPO)):sha(current_path),str((BASE/'inspection/cdc.rpt').relative_to(REPO)):sha(BASE/'inspection/cdc.rpt'),
            str((BASE/'cdc_inventory.json').relative_to(REPO)):sha(BASE/'cdc_inventory.json')},
        remaining=['Physical PHY identity/delay mode and board RGMII/DVP IO budgets',
            'SRCC V19 to MMCM routing override qualification',
            'MIG clock-buffer warning and reset/BRAM control operational qualification',
            'Controlled same-frozen-hardware-input RGB/GRAY diagnostic and actual candidate bit'])
    dump(out/'CDC_INVENTORY.json',dict(paths=current,added=added,removed=removed,changed=changed))
    dump(out/'DRC_INVENTORY.json',dict(paths=all_drc))
    dump(out/'verification.json',result)
    print(json.dumps({k:result[k] for k in ('status','review_checks_passed','release_ready','CDC','DRC')},ensure_ascii=False,indent=2))
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--audit',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--source-root',type=Path,default=Path('C:/bx72_ymw_0105_20261015/gray_transport_board_02'));args=p.parse_args()
    review(args.audit,args.out,args.source_root)

if __name__=='__main__':main()
