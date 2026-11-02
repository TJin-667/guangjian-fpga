set root [file normalize [file dirname [info script]]]
set project_dir [file join $root vivado_project]
set report_dir  [file join $root reports]
set bit_dir     [file join $root bit]
file mkdir $project_dir
file mkdir $report_dir
file mkdir $bit_dir

create_project -force BX72_FourLight_ROI $project_dir -part xc7a100tfgg484-2
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]

add_files [glob [file join $root src *.v]]
add_files [glob [file join $root src vendor *.v]]
add_files [list \
    [file join $root ip2018 sys_pll sys_pll.xci] \
    [file join $root ip2018 wr_ddr3_fifo wr_ddr3_fifo.xci] \
    [file join $root ip2018 rd_ddr3_fifo rd_ddr3_fifo.xci] \
    [file join $root ip2018 mig_7series_0 mig_7series_0.xci]]
add_files -fileset constrs_1 [file join $root bx72_1080p_udp.xdc]

set_property top bx72_1080p_udp_top [current_fileset]
update_compile_order -fileset sources_1

generate_target all [get_ips]
export_ip_user_files -of_objects [get_ips] -no_script -sync -force -quiet

launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property STATUS [get_runs synth_1]] ne "synth_design Complete!"} {
    error "Synthesis failed: [get_property STATUS [get_runs synth_1]]"
}

open_run synth_1
report_utilization -file [file join $report_dir utilization_synth.rpt]
report_timing_summary -file [file join $report_dir timing_synth.rpt]
close_design

launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {
    error "Implementation failed: [get_property STATUS [get_runs impl_1]]"
}

open_run impl_1
report_utilization -file [file join $report_dir utilization_impl.rpt]
report_timing_summary -file [file join $report_dir timing_impl.rpt]
report_drc -file [file join $report_dir drc_impl.rpt]
close_design

set generated_bit [file join $project_dir BX72_FourLight_ROI.runs impl_1 bx72_1080p_udp_top.bit]
file copy -force $generated_bit [file join $bit_dir BX72_1080P_4LIGHT_ROI.bit]
puts "BUILD_COMPLETE: [file join $bit_dir BX72_1080P_4LIGHT_ROI.bit]"
