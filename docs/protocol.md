# 主机与FPGA数据接口

本提交运行固件0x0109及扩展revision9，默认应用端点见`configs/runtime.json`。主机不会自动修改操作系统网络。下面给出当前接口入口；保留目录中的旧阶段README是来源归档，不作为当前功能状态或性能结论。

## 图像和算法数据

- 传感器全幅1920×1080，ROI为原图坐标下的`x,y,width,height`，不做取正或重采样。板面mask是几何约束，不是划痕标注。
- 格式49：GRAY8和SAT1；格式50：同一冻结帧的RGB565及灰度/SAT视图。主机核对元数据、身份、CRC与实际曝光/增益/光源读回，不能通过复制旧帧构成新八帧。
- PL保留`R_n=81×gray−sum9`的signed整数分子，9×9反射边界与PC参考相同。质量有效表由PC冻结规则生成，按32×32 tile打包后上传。
- R32为每像素32位、小端：bit0～15 signed残差，16～19来源0/1～8，20弱标志，21强标志，22～29选中来源灰度，30～31保留0。来源0表示unknown且整字为0。
- 基础弱/强标志使用严格`abs(R_n)>648/1620`。这些是8/20基础B1字段；最终弱段增强仍由PC依据冻结配置执行，不能把R32标志当成最终检测输出。
- 八槽顺序为CH1低/高、CH2低/高、CH3低/高、CH4低/高。同幅响应保留更早来源。新帧写入非活动bank，完整成功后才提交；整组八槽完成后才发布。

## 组控制及计数

请求为20字节；扩展回复类型0x88，固定头部64字节，schema1/revision9。请求、扩展回复与旧采集命令共用同一排他socket和序列分配器。组ID、128位摘要、ROI、slot、请求及帧cookie共同约束归属，修改类失败不自动重发为新的动作。

| 操作 | 作用 |
|---|---|
| REG16、BEGIN17 | 配置组身份和人工低/高曝光，BEGIN锁定本组 |
| ARM18、STATUS19 | 顺序准备并核对当前槽 |
| QWORD20、QSEAL21 | 上传并确认精确质量有效表 |
| FUSE22、FETCH23 | 增量融合并读取R32结果 |
| RELEASE24、ABORT25 | 释放结果或终止组事务 |
| PROFILE26、CONFIG27 | 读取本域服务计数及实际锁定曝光配置 |
| CAPABILITIES31 | 核对固件能力 |

低、高曝光均为1～1116行整数且低值小于高值；gain16=16、LED128。推荐默认400/800，允许组间人工调整；不执行自适应曝光或最小补拍策略。

PROFILE分H2的NET125MHz、scratch写入和融合的UI100MHz三段，记录包含DDR等待及背压的服务周期。三个区间可能重叠，不能跨域直接相加，或用“减背压”冒充纯算术时间。性能结论以对应实测收据及其边界为准。

## 精确编码的源码入口

- [扩展报文与质量表编码](../src/host/frozen_source_tree/YMW/work/final_board_0109_20261030/host/offload_wire.py)
- [图像传输与元数据](../src/host/frozen_source_tree/YMW/work/final_board_0109_20261030/derived_sdk/host_transport_0109.py)
- [R32解码及连接](../src/host/frozen_source_tree/YMW/work/fusion_offload_0108_20261028/host/result_codec.py)
- [原增量协议详细规格](../src/host/frozen_source_tree/YMW/work/final_board_0109_20261030/PROTOCOL.md)

源码中的保留位、长度、CRC、失败分支及身份断言是接口的一部分。提交适配只改变位置与来源检查方式，未改变报文语义或冻结数值核心。
