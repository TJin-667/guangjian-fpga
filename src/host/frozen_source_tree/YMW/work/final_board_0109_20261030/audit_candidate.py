"""Read-only routed IO/CDC/DRC inventory, never emit or program a bit."""
import argparse,json,subprocess,time
from pathlib import Path
from route_common import HERE,REPO,sha,dump,pinned,replace
def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    checkpoint=a.checkpoint.resolve();digest=sha(checkpoint);out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    source=pinned('YMW/work/gray_transport_0105_20261025/audit_io_cdc.tcl').decode('utf-8').replace('\r\n','\n')
    extra='u_off_commands u_off_replies u_off_result_data u_off_h2_bridge/u_cfg u_off_h2_bridge/u_records u_off_h2_bridge/u_finish u_off_h2_bridge/u_result'
    source=replace(source,'foreach instance {u_capture/requests u_capture/cancellations u_capture/published u_manual/requests u_manual/responses}',
        'foreach instance {u_capture/requests u_capture/cancellations u_capture/published u_manual/requests u_manual/responses '+extra+'}')
    source=replace(source,'%s/dst_data_reg\\[[0-9]+\\]/D','%s/(dst_data|captured_data)_reg\\[[0-9]+\\]/D')
    source=replace(source,'exit 0', '''check_timing -verbose -file [file join $out check_timing.rpt]
report_cdc -details -file [file join $out cdc.rpt]
report_route_status -file [file join $out route_status.rpt]
report_bus_skew -file [file join $out bus_skew.rpt]
report_timing_summary -report_unconstrained -file [file join $out timing.rpt]
report_timing -delay_type max -max_paths 30 -file [file join $out setup_paths.rpt]
report_timing -delay_type min -max_paths 20 -file [file join $out hold_paths.rpt]
report_utilization -file [file join $out utilization.rpt]
set f [open [file join $out audit_gate.csv] w]
set unexpected 0
set inventory [open [file join $out new_mailbox_fanout.tsv] w]
puts $inventory "mailbox\\theld\\tcaptured\\tunexpected_endpoints"
foreach instance {u_off_commands u_off_replies u_off_result_data u_off_h2_bridge/u_cfg u_off_h2_bridge/u_records u_off_h2_bridge/u_finish u_off_h2_bridge/u_result} {
    set held [get_cells -hier -regexp [format {%s/held_data_reg\\[[0-9]+\\]} $instance]]
    set captured [get_cells -hier -regexp [format {%s/captured_data_reg\\[[0-9]+\\]} $instance]]
    if {[llength $held]==0 || [llength $captured]==0} {error "Missing preserved RTL mailbox boundary $instance"}
    set bad [list]
    foreach endpoint [all_fanout -flat -endpoints_only -from [get_pins -of_objects $held -filter {REF_PIN_NAME == Q}]] {
        if {[lsearch -exact $captured [get_cells -quiet -of_objects $endpoint]]<0} {lappend bad $endpoint;incr unexpected}
    }
    puts $inventory "$instance\\t[llength $held]\\t[llength $captured]\\t$bad"
}
close $inventory
set blocking 0
foreach violation [get_drc_violations -name expanded] {
    if {[get_property SEVERITY $violation] in {Error {Critical Warning}}} {incr blocking}
}
puts $f "wns_ns,whs_ns,blackboxes,unexpected_new_mailbox_endpoints,blocking_DRC,hardware_tested"
puts $f "[get_property SLACK [get_timing_paths -delay_type max -max_paths 1]],[get_property SLACK [get_timing_paths -delay_type min -max_paths 1]],[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]],$unexpected,$blocking,false"
close $f
exit 0''')
    script=out/'audit.tcl';script.write_bytes(source.encode('utf-8'))
    command=['F:/Xilinx/Vivado/2018.3/bin/vivado.bat','-mode','batch','-source',str(script),'-log',str(out/'vivado.log'),'-journal',str(out/'vivado.jou'),'-tclargs',str(checkpoint),str(out/'reports')]
    dump(out/'INPUTS.json',dict(checkpoint=str(checkpoint),checkpoint_sha256=digest,script_sha256=sha(script),read_only=True,bit_generated=False))
    start=time.monotonic();print('READONLY0108_AUDIT_STARTED',flush=True)
    with (out/'console.txt').open('w') as log:r=subprocess.run(command,cwd=out,stdout=log,stderr=subprocess.STDOUT)
    if sha(checkpoint)!=digest:raise ValueError('Checkpoint changed')
    dump(out/'TOOL_RUN.json',dict(tool_returncode=r.returncode,wall_seconds=time.monotonic()-start,checkpoint_unchanged=True,read_only=True,bit_generated=False))
    if r.returncode:raise SystemExit(r.returncode)
    print('READONLY0108_AUDIT_TOOL_PASS',flush=True)
if __name__=='__main__':main()
