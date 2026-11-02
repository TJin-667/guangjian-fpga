# Independent read-only checkpoint audit after the original implementation.
# A successful audit does not erase an earlier failed tool exit or OOC hold gap.
if {$argc != 2} {error "Expected routed checkpoint and NEW audit output"}
set checkpoint [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
if {[file exists $out]} {error "Refusing overwrite"}
file mkdir $out
open_checkpoint $checkpoint
report_utilization -hierarchical -file [file join $out utilization.rpt]
report_timing_summary -report_unconstrained -file [file join $out timing.rpt]
report_drc -file [file join $out drc.rpt]
set launch [all_registers -clock [get_clocks core_clk] -output_pins]
set capture [all_registers -clock [get_clocks core_clk] -data_pins]
report_timing -from $launch -to $capture -delay_type max -max_paths 20 -file [file join $out internal_setup.rpt]
report_timing -from $launch -to $capture -delay_type min -max_paths 20 -file [file join $out internal_hold.rpt]
set setup [get_timing_paths -delay_type max -max_paths 1]
set hold [get_timing_paths -delay_type min -max_paths 1]
set isetup [get_timing_paths -from $launch -to $capture -delay_type max -max_paths 1]
set ihold [get_timing_paths -from $launch -to $capture -delay_type min -max_paths 1]
set f [open [file join $out status.csv] w]
puts $f "setup_ns,hold_ns,internal_setup_ns,internal_hold_ns,blackboxes,board_timing_qualified"
puts $f "[get_property SLACK $setup],[get_property SLACK $hold],[get_property SLACK $isetup],[get_property SLACK $ihold],[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]],false"
close $f
puts "CHECKPOINT_AUDIT_COMPLETE"
exit 0
