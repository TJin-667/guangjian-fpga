`timescale 1ns/1ps
module tb_report_maxabs;
reg [31:0] previous=0;
reg signed [15:0] residual_n=0;
reg [7:0] gray=100;
reg observation_valid=0;
reg [3:0] source=1;
wire [31:0] merged;
wire error;
wire signed [15:0] chosen_r=merged[15:0];
wire [3:0] chosen_source=merged[19:16];
wire weak_flag=merged[20],strong_flag=merged[21];
maxabs8_pixel dut(.*);
integer receipt;
task step(input integer s,input integer r,input integer valid,input integer want_r,input integer want_source);
begin
    source=s;residual_n=r;observation_valid=valid;
    #5;
    if(error || chosen_r!==want_r || chosen_source!==want_source || weak_flag!==(want_r>648||want_r< -648) || strong_flag!==(want_r>1620||want_r< -1620))$fatal(1,"maxabs mismatch source %0d",s);
    $fwrite(receipt,"%0t,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",$time,s,r,valid,chosen_r,chosen_source,weak_flag,strong_flag);
    #15;
end
endtask
initial begin
    receipt=$fopen("selection.csv","w");
    $fwrite(receipt,"time_ps,slot,input_residual,valid,chosen_residual,chosen_source,weak_flag,strong_flag\n");
    step(1,500,1,500,1);previous=merged;
    step(2,-900,1,-900,2);previous=merged;
    step(3,900,1,-900,2);previous=merged;
    step(4,1800,0,-900,2);previous=merged;
    step(5,1620,1,1620,5);previous=merged;
    step(6,1621,1,1621,6);previous=merged;
    step(7,-2100,1,-2100,7);previous=merged;
    step(8,2000,1,-2100,7);
    $fclose(receipt);$display("MAXABS_REPORT_PASS 8");$finish;
end
endmodule
