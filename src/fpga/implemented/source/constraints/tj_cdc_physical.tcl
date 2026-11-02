# Apply after synthesis. No clock-group or clock-to-clock false path is allowed:
# it would override the mailbox datapath bounds (AMD UG903).
proc tj_pins {expression} {
    return [get_pins -hier -regexp $expression]
}
proc tj_first_stage {expression} {
    set pins [tj_pins $expression]
    if {[llength $pins] == 0} {error "Missing CDC first stage: $expression"}
    set_false_path -to $pins
}
proc tj_bundle {source_expression destination_expression} {
    set sources [tj_pins $source_expression]
    set destinations [tj_pins $destination_expression]
    if {[llength $sources] == 0 || [llength $destinations] == 0} {
        error "Missing held bundle: $source_expression -> $destination_expression"
    }
    set cells [get_cells -of_objects $destinations]
    set clocks [get_clocks -of_objects [get_pins -of_objects $cells -filter {REF_PIN_NAME == C}]]
    if {[llength $clocks] != 1} {error "Bundle does not have one destination clock"}
    set period [get_property PERIOD $clocks]
    # Three toggle synchronizer stages precede capture; one destination period
    # is a conservative bound, leaving at least two edges of settling margin.
    # A flop Q pin is NOT a valid timing startpoint (UG903 Path Segmentation).
    # Use the owning registers so Vivado retains the C->Q arcs and selects
    # valid launch clock pins. Keep the same destination-period bound.
    set launch_registers [get_cells -of_objects $sources]
    set_max_delay -datapath_only $period -from $launch_registers -to $destinations
    set_bus_skew $period -from $launch_registers -to $destinations
    puts "TJ_BUNDLE $source_expression -> $destination_expression budget_ns=$period"
}
foreach instance {u_capture/requests u_capture/cancellations u_capture/published u_manual/requests u_manual/responses} {
    tj_first_stage [format {%s/(request_sync|ack_sync)_reg\[0\]/D} $instance]
    tj_bundle [format {%s/held_data_reg\[[0-9]+\]/Q} $instance] [format {%s/dst_data_reg\[[0-9]+\]/D} $instance]
}
foreach expression {
    {u_capture/(enable_sync|fatal_sync)_reg\[0\]/D}
    {u_capture/camera/done_sync_reg\[0\]/D}
    {u_source/owner/(ack_sync|seen_sync)_reg\[0\]/D}
    {u_ddr3/fifo_axi4_adapter_inst/axi4_to_fifo_inst/ctrl_sync_reg\[0\]/D}
    {u_ddr3/fifo_axi4_adapter_inst/wr_bank_sync_reg\[0\]/D}
    {(camera_ready_sync|ddr_ready_sync|sda_sync|scl_sync)_reg\[0\]/D}
    {rd_fault_sync_reg\[0\]/D}
    {u_light/u_rx/rx_meta_reg/D}
} {tj_first_stage $expression}
tj_bundle {u_source/owner/(active_bank|reader_ctrl_bank|reader_ctrl_enable)_reg/Q} \
    {u_ddr3/fifo_axi4_adapter_inst/axi4_to_fifo_inst/held_(bank|enable)_reg/D}
# Async assertion is intentional only for the reset synchronizer registers;
# downstream synchronous reset/recovery paths remain timed. Synchronizer-local
# shift paths remain timed as well: these exceptions end at CLR/PRE, never D.
set reset_controls [tj_pins {(u_sys_reset|u_net_reset|u_manual/nr|u_manual/cr)/pipe_reg\[[0-9]+\]/(CLR|PRE)}]
if {[llength $reset_controls] == 0} {error "Missing reset synchronizer controls"}
set_false_path -to $reset_controls
set_false_path -to [tj_pins {camera_reset_sync_reg\[[0-9]+\]/CLR}]
# Dedicated forwarded clocks, not an invented data IO delay budget.
create_generated_clock -name rgmii_tx_forwarded -source [get_pins u_net_out_buf/O] \
    -divide_by 1 [get_ports rgmii_tx_clk]
create_generated_clock -name camera_xclk_forwarded -source [get_pins u_cam_out_buf/O] \
    -divide_by 1 [get_ports cam_xclk]

# New0108 immutable control/data CDC paths. All domains share coherent reset.
foreach instance {u_off_commands u_off_replies u_off_result_data u_off_h2_bridge/u_cfg u_off_h2_bridge/u_records u_off_h2_bridge/u_finish u_off_h2_bridge/u_result} {
    tj_first_stage [format {%s/(request_sync|ack_sync)_reg\[0\]/D} $instance]
    tj_bundle [format {%s/held_data_reg\[[0-9]+\]/Q} $instance] [format {%s/captured_data_reg\[[0-9]+\]/D} $instance]
    # Physical DSP optimizations must not clone a CDC capture register into
    # a new endpoint outside its deliberately bounded data-bundle constraint.
    set held_regs [get_cells -hier -regexp [format {%s/held_data_reg\[[0-9]+\]} $instance]]
    set capture_regs [get_cells -hier -regexp [format {%s/captured_data_reg\[[0-9]+\]} $instance]]
    if {[llength $held_regs]==0 || [llength $capture_regs]==0} {error "Missing0108 preserved mailbox boundary"}
    set_property DONT_TOUCH TRUE $held_regs
    set_property DONT_TOUCH TRUE $capture_regs
}
tj_first_stage {off_fault_sync_reg\[0\]/D}
set new_reset_pins [tj_pins {(u_ddr3/u_offload_reset|u_off_net_reset|u_off_ui_reset|u_off_h2_bridge/u_net_reset|u_off_h2_bridge/u_ui_reset)/pipe_reg\[[0-9]+\]/(CLR|PRE)}]
if {[llength $new_reset_pins]==0} {error "Missing0108 coherent reset synchronizers"}
set_false_path -to $new_reset_pins
