# 0106候选的IO、CDC与DRC复核

> 2026-10-25 r3.7补充：[已有硬件原件与实物事实已接收核对](HARDWARE_REFERENCE_REVIEW.md)。原理图已找回，基础PHY和PCB版本沿用用户此前确认；29个相机/网口引脚与表格、XDC和原生DCP一致。以下r3.6的原始报告/凭证保留，实物延迟、版本等价与外部IO资格仍待闭合。

2026-10-25，r3.6。结论为**已完成本轮清点与结构复核，外部接口及复位运行资格仍有缺项**。新灰度通路相对0105未新增CDC报告路径；五组握手总线有实际跨域延迟约束且余量为正。展开DRC后完整数量为336项，需继续审查时钟布线及异步控制。`release_ready=false`保留，本轮没有新bit、烧录、网络配置改动或采集，Cisco保持连接。

## 证据与复现

审查使用最终routed DCP，SHA256：`175d82b777469cc1e94d4123ace9935ea25f8d47902476ee6f926ca47c30c947`，对应RTL提交`46f9d50`。审查前后DCP哈希一致；没有改RTL、时钟周期、例外、布线、DRC严重性或waiver。此前LUT18699、FF22647、BRAM81.5/135（60.37%）、DSP4、setup +0.003ns、hold +0.007ns结果保持原版本含义。

- [原生审查](verification/io_cdc_native_02/verification.json)：Vivado2018.3重新打开精确DCP，导出完整DRC对象、实际时序约束、IO、时钟及五组握手路径。
- [独立复核](verification/io_cdc_review_02/verification.json)：逐报告SHA、CDC明细/汇总、原基线报告/库存、DRC明细/原生对象、构建源码清单与源码内容交叉核对。
- [1099条CDC库存](verification/io_cdc_review_02/CDC_INVENTORY.json)、[336项DRC库存](verification/io_cdc_review_02/DRC_INVENTORY.json)、[IO分类](verification/io_cdc_review_02/IO_REVIEW.json)。清点通过不等于全部资格已通过。

在本目录运行，输出目录必须全新：

```powershell
python -X utf8 -B run_io_cdc_audit.py --checkpoint C:/bx72_ymw_0105_20261015/gray_transport_postroute_03/implementation/build/routed.dcp --out C:/bx72_io_audit_new
python -X utf8 -B review_io_cdc.py --audit C:/bx72_io_audit_new --out verification/io_review_new
```

首轮原生脚本在导出IO时用了2018.3不存在的`get_input_delays`命令，未完成；[日志与原脚本](verification/io_cdc_native_01/verification.json)保留。改为本版本支持的`write_xdc -type timing`后，第二轮完成。该错误属于审查脚本，不改变DCP或候选逻辑。

## CDC：路径与0105一致，逐组核对协议与约束

1099条路径与现用0105原生报告及独立库存逐键对照，rule/source/destination、severity、depth、exception均一致，新增/缺失/变化为0。数量分布：CDC-3为34、CDC-9为4、CDC-15为1058、CDC-17为2、CDC-8为1，无Critical。

CDC-15集中在五组`cdc_snapshot_mailbox`。源码中源域在valid/ready时锁存payload与request toggle，收到同步ack前不再覆盖；目的域经3级request同步，锁存数据后置pending，消费前保持数据；ack只在目的域消费时更新。共同复位要求仍是协议前提。[AMD UG906](https://www.xilinx.com/support/documents/sw_manuals/xilinx2022_1/ug906-vivado-design-analysis.pdf)说明CE/MUX类CDC的功能正确性需要设计者验证，结构识别本身不能替代它。

| 总线 | 实现后有效位数 | max-delay预算 | 本次最差setup余量 |
| --- | ---: | ---: | ---: |
| u_capture/requests | 312 | 10ns | +8.411ns |
| u_capture/cancellations | 192 | 10ns | +8.345ns |
| u_capture/published | 396 | 8ns | +6.477ns |
| u_manual/requests | 27 | 20ns | +18.954ns |
| u_manual/responses | 131 | 8ns | +6.600ns |

这些是优化后保留的位数，不是接口声明WIDTH。五组位数合计1058，与CDC-15明细一一相符。实际导出的XDC保留每组`set_max_delay -datapath_only`与`set_bus_skew`；未出现全时钟组异步切断。前轮10条bus skew的最小余量仍为+6.348ns。上述总线余量不是整板setup最差余量，整板仍仅+0.003ns。

两条CDC-17为读银行/enable命令的held_bank、held_enable。接收端3级同步toggle，额外登记command_arrived后锁存两位；源端等待ack后才发下一命令，STOP还等待旧AXI读排空。实际XDC对此组合保留10ns最大延迟和bus skew。该结构复核支持原有握手解释，不能证明现场PHY时序或任意独立复位都可安全进行。

唯一CDC-8位于MIG生成IP的IDELAYCTRL reset链。已核对实际生成源码：在参考时钟边沿移位释放、异步置位，缺少ASYNC_REG属性；该路径与0105相同。不能只把库存reviewed改true或批量加属性视为完成IP复位资格，仍需按IP结构/约束和实际复位条件评估。

## DRC：提高报告上限后为336项

原报告54项包含REQP-1839/1840各20项及两条CHECK-3“报告上限”。本次读取工具实际参数`drc.maxLimitREQP1839and1840=20`，仅将本次会话的报告上限提高到100000，再运行原规则。新报告无CHECK-3，336条文本明细与336个原生violation对象、规则计数一致。没有改变规则严重性。

| 规则 | 完整数量 | 本轮判读与剩余事项 |
| --- | ---: | --- |
| BUFC-1 | 4 | MIG DQS宏内输入缓冲无负载，保留IP上下文，不能仅凭名字删掉缓冲。 |
| DPOP-1 / DPOP-2 | 2 / 4 | DSP流水性能建议；当前时序余量窄。加流水会改变控制时序，需新实现/回归后评估。 |
| PLCK-23 | 1 | 网口V19为SRCC引脚；当前MMCM配对位置仍触发专用路径检查，原`CLOCK_DEDICATED_ROUTE FALSE`使报告为Warning。仍需评估专用路径可行位置或实际布线/抖动边界。 |
| REQP-1709 | 1 | MIG PLL各输出缓冲类型不一致的相位提示，需结合生成IP的用途与时钟树判断。 |
| REQP-1839 | 276 | RAMB36异步控制影响路径，逐项保留，见下表。 |
| REQP-1840 | 48 | RAMB18异步控制影响路径，逐项保留，见下表。 |

324条RAM控制警告不是324块BRAM：同一个存储器可对多个控制pin和上游寄存器分别报告。按使用位置归类为mask256、原H1/H2分析缓存42、发送包缓存24、DDR读FIFO2。315条关联`u_net_reset/pipe_reg[2]`，另外9条关联原UDP发送FSM的异步复位状态寄存器。新灰度发送包缓存也在24条范围内，不能把这些警告全部归为无关IP。

共同复位会使session、mask-valid、缓存ready及发布状态失效，这为后续重填提供了协议边界；仍须确认时钟稳定、FIFO wr/rd_rst_busy、复位持续时间及重填顺序。FIFO XCI确为异步复位并开启内部复位同步，不能将“有同步器”等同于BRAM所有异步控制风险已消除。本轮未增加false path、降低DRC级别、修改IP或切换复位方案。需进一步针对这些位置设计复位资格验证，不能用CRC成功的一次采集证明复位过程全部安全。

## IO：无delay与已有数值依据分别列出

| 接口 | 当前证据 | 仍需的依据/处理 |
| --- | --- | --- |
| RGMII RX的5条数据/控制线 | 双沿IDDR，8ns输入时钟；无input delay | 基础PHY型号已由用户确认YT8531C；仍需实际延迟模式、时钟与数据PCB偏斜，分别推导两边沿预算。 |
| RGMII TX的5条数据/控制线 | 同边沿ODDR数据与转发时钟；无output delay | 实际PHY输入要求/内部延迟与PCB预算；同边沿输出不能自行证明接收窗口满足。 |
| cam_sda/cam_scl | 开漏IOBUF，3级输入同步，例外只到首级D | 同步结构已核对；电气电平、上拉和总线时序仍按SCCB/I2C性质验证。 |
| UART RX/TX | RX首级同步例外，异步串行协议 | 不能套用RGMII同步采样delay；后续核对电平/波特率和真实灯控运行。 |
| reset_n | 本地释放链及MIG复位路径 | 共同复位、时钟锁定、最小持续与忙状态资格。 |
| ddr3_reset_n | MIG生成逻辑 | 结合MIG与DDR器件初始化规范；不是随意填一个output delay。 |
| led[0:1] | 状态输出 | 不作为图像采样同步接口，保留用途说明。 |
| cam_xclk / rgmii_tx_clk | 已定义转发时钟 | 仍要与对应器件及数据路径的外部时序配对。 |
| DVP data[7:0]/href/vsync | 已有min0/max2ns，cam_pclk约束10ns | 本轮未取得当前相机模块/排线/模式对应的延迟来源，数字已填不代表IO资格已通过。 |

原check_timing的9个输入、11个输出无delay以及2个转发时钟提示仍保留。DVP这10个已有delay的输入也单列为“依据待核”，不会因不出现在no_input_delay列表就忽略。

## PHY资料核对与读取边界

原Motorcomm V1.00/2023-04-03手册已重新从[LCSC厂家资料入口](https://www.lcsc.com/datasheet/C22472312.pdf)取得，1,882,440字节、66页，SHA256与TJ历史记录一致：`11528125260ef4c63793c7f71205524cb45a3e7238273e3c79bba02567c9bdb9`。不是新修订声明。浏览器文本工具不能读取直链PDF后，本地下载、pypdf提取和Poppler渲染均成功；已查看物理页28/29/58/59，含Table14/15/94/95/96，未重复上传完整手册或页面。

Table14/15将RX延迟使能与RX/TX延迟档位分别定义，档位为典型/近似步长；Table94/95又区分带延迟/不带延迟模式。因此必须先取得实际寄存器与板级关系，不能把手册默认值或典型步长直接写成实板ns预算。详细来源、页码及SHA见[PHY_REFERENCE.json](verification/io_cdc_review_02/PHY_REFERENCE.json)。

r3.6审查时未在当轮工作材料中找到BX72-251215原理图原件。r3.7已从用户整理的永久目录直接取得，并核对第1/2/4/10/12页；PCB为BX72-V1.1、PHY基础型号为YT8531C及未改硬件/跳线的事实均沿用已确认记录，不再索取。仍缺的是V1.1与251215图纸/V1.0装配图适用关系、电压实证、PHY实际延迟读回、PCB偏斜及当前模块/排线DVP电气时序依据，详见[接收补充](HARDWARE_REFERENCE_REVIEW.md)。上述缺项与004/005图像和XDL派生图无关，现有图像分析继续使用。

## 后续工作

1. 继续准备明确标记的受控测试图/冻结硬件输入诊断，保留真实身份及双格式CRC/gray/SAT/H1/H2核对；光学数据仍用现用0105 RGB通路推进。
2. 对网口时钟覆盖、MIG时钟及324条RAM控制路径建立有边界的资格验证，涉及实际RTL/约束变更时单独生成候选并重新实现，不改现用09/0105。
3. 需要本机板测时用已准备的独立只读入口，用户断开Cisco执行后再重连交回结果；当前不要求断开Cisco、重拍004/005或重新烧录原bit。

XDL PR #25本轮只读确认仍为`aa5669d`，没有新交付；400/800仍是开发候选。保持固定1倍、LED128双曝光标注/训练主线，灰度板端资格不会改变本阶段质量优先的目标。
