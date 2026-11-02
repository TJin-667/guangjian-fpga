# Distinguish real FF-to-FF module paths from placeholder OOC I/O budgets.
# Does not change constraints or turn a failed full timing report into a PASS.
if {$argc != 2} {error "Expected routed checkpoint and NEW report directory"}
set checkpoint [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
if {[file exists $out]} {error "Refusing overwrite"}
file mkdir $out
open_checkpoint $checkpoint
set launch [all_registers -clock [get_clocks core_clk] -output_pins]
set capture [all_registers -clock [get_clocks core_clk] -data_pins]
report_timing -from $launch -to $capture -delay_type max -max_paths 20 -file [file join $out internal_setup.rpt]
report_timing -from $launch -to $capture -delay_type min -max_paths 20 -file [file join $out internal_hold.rpt]
set setup [get_timing_paths -from $launch -to $capture -delay_type max -max_paths 1]
set hold [get_timing_paths -from $launch -to $capture -delay_type min -max_paths 1]
set f [open [file join $out internal_status.csv] w]
puts $f "internal_setup_ns,internal_hold_ns,board_timing_qualified"
puts $f "[get_property SLACK $setup],[get_property SLACK $hold],false"
close $f
exit 0
