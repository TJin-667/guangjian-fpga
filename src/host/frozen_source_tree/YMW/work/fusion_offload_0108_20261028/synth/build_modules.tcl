# Standalone implementation gates, NOT a board build and never a bitstream.
# Usage: vivado -mode batch -source build_modules.tcl -tclargs SOURCE_ROOT NEW_OUT
if {$argc < 2} {error "Expected source root and NEW output root; optional top list"}
set root [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
if {[file exists $out]} {error "Refusing to overwrite evidence"}
file mkdir $out
set_param general.maxThreads 2
set tops {fusion_axi_frame h2_scratch_writer fusion_group_guard}
if {$argc>2} {set tops [lrange $argv 2 end]}
foreach top $tops {
    if {$top ni {fusion_axi_frame h2_scratch_writer fusion_group_guard}} {error "Unexpected top"}
    set target [file join $out $top]
    file mkdir $target
    create_project -in_memory -part xc7a100tfgg484-2
    foreach file {maxabs8_pixel.v fusion_axi_frame.v h2_scratch_writer.v fusion_group_guard.v} {
        read_verilog -sv [file join $root rtl $file]
    }
    synth_design -top $top -part xc7a100tfgg484-2 -mode out_of_context
    create_clock -name core_clk -period 8.000 [get_ports clk]
    # Representative OOC clock-buffer origin. This is not the board's actual
    # clock placement and must be replaced/rechecked in the final board build.
    set_property HD.CLK_SRC BUFGCTRL_X0Y0 [get_ports clk]
    set_input_delay -clock core_clk -max 2.000 [get_ports -filter {DIRECTION == IN && NAME != clk}]
    set_input_delay -clock core_clk -min 0.200 [get_ports -filter {DIRECTION == IN && NAME != clk}]
    set_output_delay -clock core_clk -max 2.000 [all_outputs]
    set_output_delay -clock core_clk -min 0.200 [all_outputs]
    report_utilization -hierarchical -file [file join $target utilization_synth.rpt]
    write_checkpoint [file join $target synthesized.dcp]
    opt_design
    place_design
    phys_opt_design -directive AggressiveExplore
    route_design
    phys_opt_design -hold_fix
    route_design
    write_checkpoint [file join $target routed.dcp]
    report_utilization -hierarchical -file [file join $target utilization_routed.rpt]
    report_timing_summary -report_unconstrained -file [file join $target timing_routed.rpt]
    report_drc -file [file join $target drc_routed.rpt]
    set setup [get_timing_paths -delay_type max -max_paths 1]
    set hold [get_timing_paths -delay_type min -max_paths 1]
    set wns [get_property SLACK $setup]
    set whs [get_property SLACK $hold]
    set launch [all_registers -clock [get_clocks core_clk] -output_pins]
    set capture [all_registers -clock [get_clocks core_clk] -data_pins]
    report_timing -from $launch -to $capture -delay_type max -max_paths 20 -file [file join $target internal_setup.rpt]
    report_timing -from $launch -to $capture -delay_type min -max_paths 20 -file [file join $target internal_hold.rpt]
    set isetup [get_timing_paths -from $launch -to $capture -delay_type max -max_paths 1]
    set ihold [get_timing_paths -from $launch -to $capture -delay_type min -max_paths 1]
    set iwns [get_property SLACK $isetup]
    set iwhs [get_property SLACK $ihold]
    set f [open [file join $target status.csv] w]
    puts $f "top,wns_ns,whs_ns,timing_met,internal_setup_ns,internal_hold_ns,internal_timing_met,board_build,bit_generated"
    puts $f "$top,$wns,$whs,[expr {$wns>=0 && $whs>=0}],$iwns,$iwhs,[expr {$iwns>=0 && $iwhs>=0}],false,false"
    close $f
    puts "MODULE_ROUTED $top WNS=$wns WHS=$whs"
    # Leave the final in-memory design open for normal process shutdown. The
    # installed 2018.3 can crash while explicitly closing a routed OOC project.
    if {$top ne [lindex $tops end]} {close_project}
}
exit 0
