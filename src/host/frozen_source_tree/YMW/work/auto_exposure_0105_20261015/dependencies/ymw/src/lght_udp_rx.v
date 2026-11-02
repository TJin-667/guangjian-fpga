`timescale 1ns/1ps
// Bounded streaming IPv4/UDP parser for untagged Ethernet, IHL=5, no fragments.
// Tentative payload is never a command commit until done && !error.
module lght_udp_rx #(
    parameter [47:0] LOCAL_MAC=48'h000a3501fec0,
    parameter [31:0] LOCAL_IP=32'hc0a80002,
    parameter [15:0] LOCAL_PORT=5000
)(
    input wire clk,reset,gmii_dv,gmii_er,
    input wire [7:0] gmii_data,
    output reg start,valid,done,error,
    output reg [7:0] data,
    output reg [47:0] peer_mac,
    output reg [31:0] peer_ip,
    output reg [15:0] peer_port
);
    reg [1:0] state;
    reg [3:0] preamble;
    reg [15:0] pos;
    reg [47:0] dst_mac;
    reg [31:0] dst_ip;
    reg [15:0] eth_type,ip_total,ip_frag,udp_length,dst_port,udp_checksum;
    reg [7:0] ip_vihl,ip_protocol,previous;
    reg bad;
    reg [31:0] ip_sum,udp_sum;
    wire [31:0] crc;
    wire crc_init=state==1 && gmii_dv && gmii_data==8'hd5 && preamble==7;
    crc32_d8 u_crc(.clk(clk),.reset_p(reset),.data(gmii_data),.crc_init(crc_init),
                  .crc_en(state==2 && gmii_dv),.crc_result(crc));
    function [15:0] fold;
        input [31:0] value;
        reg [16:0] s;
        begin s=value[15:0]+value[31:16];fold=s[15:0]+s[16];end
    endfunction
    wire [15:0] expected_size=(ip_total+18<64)?64:ip_total+18;
    always @(posedge clk)begin
        if(reset)begin
            state<=0;preamble<=0;pos<=0;start<=0;valid<=0;done<=0;error<=0;data<=0;
            peer_mac<=0;peer_ip<=0;peer_port<=0;dst_mac<=0;dst_ip<=0;eth_type<=0;
            ip_total<=0;ip_frag<=0;udp_length<=0;dst_port<=0;udp_checksum<=0;
            ip_vihl<=0;ip_protocol<=0;previous<=0;bad<=0;ip_sum<=0;udp_sum<=0;
        end else begin
            start<=0;valid<=0;done<=0;error<=0;
            case(state)
                0:if(gmii_dv && gmii_data==8'h55)begin state<=1;preamble<=1;end
                1:begin
                    if(!gmii_dv)state<=0;
                    else if(gmii_data==8'h55 && preamble<7)preamble<=preamble+1'b1;
                    else if(crc_init)begin
                        state<=2;pos<=0;start<=1;bad<=gmii_er;ip_sum<=0;udp_sum<=17;
                        peer_mac<=0;peer_ip<=0;peer_port<=0;dst_mac<=0;dst_ip<=0;
                        eth_type<=0;ip_total<=0;ip_frag<=0;udp_length<=0;dst_port<=0;
                        udp_checksum<=0;ip_vihl<=0;ip_protocol<=0;previous<=0;
                    end else state<=3;
                end
                2:begin
                    if(!gmii_dv)begin
                        done<=1;state<=0;
                        error<=bad || crc!=32'h2144df1c || pos!=expected_size || ip_total<28 || ip_total>1428 ||
                            eth_type!=16'h0800 || dst_mac!=LOCAL_MAC || dst_ip!=LOCAL_IP ||
                            ip_vihl!=8'h45 || ip_protocol!=17 || (ip_frag & 16'hbfff)!=0 ||
                            fold(ip_sum)!=16'hffff || udp_length<8 || udp_length!=ip_total-20 || dst_port!=LOCAL_PORT ||
                            (udp_checksum!=0 && fold(udp_sum)!=16'hffff);
                    end else begin
                        if(pos<2047)pos<=pos+1'b1;else bad<=1;
                        if(gmii_er)bad<=1;
                        previous<=gmii_data;
                        if(pos<6)dst_mac<={dst_mac[39:0],gmii_data};
                        if(pos>=6 && pos<12)peer_mac<={peer_mac[39:0],gmii_data};
                        if(pos==12 || pos==13)eth_type<={eth_type[7:0],gmii_data};
                        if(pos==14)ip_vihl<=gmii_data;
                        if(pos==16 || pos==17)ip_total<={ip_total[7:0],gmii_data};
                        if(pos==20 || pos==21)ip_frag<={ip_frag[7:0],gmii_data};
                        if(pos==23)ip_protocol<=gmii_data;
                        if(pos>=26 && pos<30)peer_ip<={peer_ip[23:0],gmii_data};
                        if(pos>=30 && pos<34)dst_ip<={dst_ip[23:0],gmii_data};
                        if(pos==34 || pos==35)peer_port<={peer_port[7:0],gmii_data};
                        if(pos==36 || pos==37)dst_port<={dst_port[7:0],gmii_data};
                        if(pos==38 || pos==39)udp_length<={udp_length[7:0],gmii_data};
                        if(pos==40 || pos==41)udp_checksum<={udp_checksum[7:0],gmii_data};
                        if(pos>=14 && pos<34 && pos[0])ip_sum<=ip_sum+{previous,gmii_data};
                        // Accumulate the pseudo-header as its bytes arrive.
                        // Avoid six cascaded adders on the final error path.
                        if(pos>=26 && pos<34 && pos[0])udp_sum<=udp_sum+{previous,gmii_data};
                        if(pos>=34 && (pos<42 || pos<34+udp_length))begin
                            // Length occurs in both UDP header and pseudo-header.
                            if(pos==39)udp_sum<=udp_sum+({16'b0,previous,gmii_data}<<1);
                            else if(pos[0])udp_sum<=udp_sum+{previous,gmii_data};
                            else if(pos==33+udp_length)udp_sum<=udp_sum+{gmii_data,8'b0};
                        end
                        if(pos>=42 && pos<34+udp_length)begin valid<=1;data<=gmii_data;end
                    end
                end
                3:if(!gmii_dv)state<=0;
            endcase
        end
    end
endmodule
