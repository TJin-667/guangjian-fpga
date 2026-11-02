// Included only in the independent directed-fault simulation.
task ack_receipt(input integer want);
    begin
        wait(receipt_valid);@(negedge clk);
        if(receipt_error!=want)$fatal(1,"receipt error got%0d want%0d",receipt_error,want);
        receipt_ready=1;tick();receipt_ready=0;
    end
endtask
task new_group(input integer gid);
    begin
        wait(begin_ready);@(negedge clk);begin_group=gid;width=9;height=9;begin_valid=1;tick();begin_valid=0;
        wait(active||receipt_valid);@(negedge clk);if(!active)$fatal(1,"failed to open fault group");
    end
endtask
task submit(input integer s,input integer req);
    begin
        wait(frame_ready);@(negedge clk);frame_group=begin_group;frame_digest=begin_digest;
        frame_slot=s;frame_request=req;frame_valid=1;tick();frame_valid=0;
    end
endtask
task good_slot(input integer s);
    reg [127:0] actual;integer bi,lane;
    begin
        $readmemh($sformatf("c0_s%0d_input.hex",s),scratch,0,20);
        $readmemh($sformatf("c0_s%0d_expected.hex",s),expected,0,20);
        submit(s,s);ack_receipt(0);
        if(completed!=s || published!=(s==8))$fatal(1,"bad successful fault-control slot");
        for(bi=0;bi<21;bi=bi+1)begin
            actual=published_base==30'h01000000 ? state1[bi] : state0[bi];
            for(lane=0;lane<4;lane=lane+1)if(bi*4+lane<81 && actual[32*lane+:32]!==expected[bi][32*lane+:32])$fatal(1,"retry changed result");
        end
    end
endtask
task abort_idle;
    begin @(negedge clk);abort_group=1;tick();abort_group=0;repeat(2)tick();if(active||published)$fatal(1,"abort idle failed");end
endtask
task common_reset;
    begin
        @(negedge clk);reset=1;force_ar_hold=0;force_aw_hold=0;force_w_hold=0;force_b_hold=0;
        abort_group=0;frame_valid=0;begin_valid=0;receipt_ready=0;release_valid=0;rresp=0;bresp=0;rid=8;bid=8;
        repeat(4)tick();reset=0;repeat(2)tick();
        if(published||fault||fence||!begin_ready)$fatal(1,"common reset leaked state");
    end
endtask
task pass_fault(input string name);
    begin passed=passed+1;$fwrite(receipt,"%s,PASS\n",name);$display("FAULT_PASS %s",name);end
endtask
initial begin: fault_run
    integer saved_reads,saved_writes;reg [127:0] saveword;
    wait(!reset);repeat(3)tick();
    new_group(1);saved_reads=read_commands;saved_writes=write_commands;
    submit(2,1);ack_receipt(2);
    frame_complete=0;submit(1,1);ack_receipt(2);frame_complete=1;
    @(negedge clk);frame_valid=1;frame_group=99;frame_digest=begin_digest;frame_slot=1;frame_request=1;tick();frame_valid=0;ack_receipt(2);
    @(negedge clk);frame_valid=1;frame_group=begin_group;frame_digest=0;frame_slot=1;frame_request=1;tick();frame_valid=0;ack_receipt(2);
    submit(1,0);ack_receipt(2);
    if(read_commands!=saved_reads || write_commands!=saved_writes || completed!=0 || published)$fatal(1,"metadata rejection touched DDR");
    pass_fault("reject_wrong_slot_incomplete_group_digest_request_without_DDR");
    good_slot(1);submit(1,1);ack_receipt(2);pass_fault("duplicate_committed_slot_rejected");abort_idle();

    new_group(2);$readmemh("c0_s1_input.hex",scratch,0,20);force_ar_hold=1;submit(1,1);wait(arvalid);@(negedge clk);
    abort_group=1;tick();abort_group=0;repeat(8)tick();if(!arvalid)$fatal(1,"abort withdrew stalled ARVALID");force_ar_hold=0;
    ack_receipt(3);if(active||published||completed!=0)$fatal(1,"aborted AR published");pass_fault("abort_stalled_AR_drains_no_commit");

    new_group(3);force_w_hold=1;submit(1,1);wait(wvalid);@(negedge clk);abort_group=1;tick();abort_group=0;
    repeat(8)tick();if(!wvalid)$fatal(1,"abort withdrew stalled WVALID");force_w_hold=0;ack_receipt(3);
    if(active||published||completed!=0)$fatal(1,"aborted W published");pass_fault("abort_stalled_W_drains_B_no_commit");

    new_group(4);force_b_hold=1;submit(1,1);wait(bdelay>0);@(negedge clk);abort_group=1;tick();abort_group=0;
    repeat(8)tick();if(receipt_valid||published)$fatal(1,"finished before outstanding B");force_b_hold=0;ack_receipt(3);
    pass_fault("abort_delayed_B_no_early_commit");

    new_group(5);rresp=2;submit(1,1);ack_receipt(4);rresp=0;
    if(completed!=0||published)$fatal(1,"RRESP committed");good_slot(1);pass_fault("RRESP_error_then_same_slot_retry_exact");abort_idle();

    new_group(6);bresp=2;submit(1,1);ack_receipt(5);bresp=0;
    if(completed!=0||published)$fatal(1,"BRESP committed");good_slot(1);pass_fault("BRESP_partial_target_then_retry_exact");abort_idle();

    new_group(7);scratch[0][25]=1;submit(1,1);ack_receipt(2);
    $readmemh("c0_s1_input.hex",scratch,0,20);scratch[0][15:0]=16'h8000;submit(1,1);ack_receipt(2);
    good_slot(1);pass_fault("reserved_and_out_of_range_record_rejected_then_retry");
    if(published_base==30'h01000000)begin saveword=state1[0];state1[0][19:16]=8;end
    else begin saveword=state0[0];state0[0][19:16]=8;end
    $readmemh("c0_s2_input.hex",scratch,0,20);submit(2,2);ack_receipt(2);
    if(completed!=1)$fatal(1,"corrupt history swapped bank");
    if(published_base==30'h01000000)state1[0]=saveword;else state0[0]=saveword;
    good_slot(2);pass_fault("future_source_history_rejected_no_bank_swap");
    for(integer s=3;s<=7;s=s+1)good_slot(s);
    if(published)$fatal(1,"seven frames published");pass_fault("seven_frames_cannot_publish");
    good_slot(8);release_group=999;release_valid=1;tick();release_valid=0;
    if(!published||begin_ready)$fatal(1,"wrong release accepted");pass_fault("publication_pinned_until_matching_release");
    release_group=7;release_valid=1;tick();release_valid=0;
    wait(begin_ready);begin_group=7;begin_valid=1;tick();begin_valid=0;ack_receipt(1);pass_fault("old_group_epoch_rejected");

    new_group(8);force_ar_hold=1;submit(1,1);wait(arvalid);repeat(75)tick();
    if(!arvalid||!fence||!fault||published)$fatal(1,"timeout did not fence while preserving ARVALID");
    force_ar_hold=0;wait(receipt_valid);if(receipt_error!=6)$fatal(1,"timeout result mismatch");
    receipt_ready=1;tick();receipt_ready=0;repeat(2)tick();
    if(begin_ready||frame_ready||cfg_ready)$fatal(1,"timeout reopened without external fence");pass_fault("timeout_holds_VALID_blocks_reuse_until_common_fence");
    common_reset();new_group(1);rid=9;submit(1,1);wait(fence);repeat(30)tick();
    if(!fault||published||cfg_ready)$fatal(1,"wrong RID not fenced");pass_fault("wrong_RID_requires_common_fence");
    common_reset();
    // Memory retains old words across reset. A fresh slot1 must ignore them.
    run_group(0,9,9);pass_fault("common_reset_retained_DDR_fresh_group_exact");
    $fclose(receipt);$display("FUSION_FAULTS_ALL_PASS %0d",passed);$finish;
end
