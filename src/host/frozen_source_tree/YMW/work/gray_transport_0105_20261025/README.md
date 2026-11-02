> 2026-10-26 r4.3：[同输入RTL及灰度采集接口接通](OFFLINE_GRAY_INTEGRATION.md)。真实留档全幅/奇数ROI像素、SAT和H1/H2一致；XDL六特征平面及两档阈值也一致。新增27项检查通过，采集后自动导出、失败保留不重拍；没有实体操作或新bit。板卡已按用户安排断电，当前无需补拍。

> 2026-10-26 r4.2：[原生1920×1080真实双格式回传通过](NATIVE_TRANSPORT_REVIEW.md)。RGB3006包、GRAY1691包全齐，零丢包/重试，CRC/H1/H2及非零SAT、64位H2独立复核一致；图像负载减少43.75%，BRAM仍60.37%。本阶段无需重复拍摄。后续[灰度接口](GRAY_INTERFACE_HANDOFF.md)与同输入质量验证继续，正式gate保持。

> 2026-10-26 r4.1：[小ROI真实双格式负载已通过，下一步全幅检查](REAL_TRANSPORT_REVIEW.md)。两帧实际CRC/H1/H2、身份及ZIP独立复核一致，零丢包/重试，灰度负载减少43.74%，关灯均有ACK；现用0106不变，BRAM60.37%。全幅只需运行新04入口一次；逐像素同输入质量与正式资格仍待验。

# GRAY/SAT发送链路集成候选

> 2026-10-26 r4.0：[新0106实板握手与双格式工程检查](ENGINEERING_TRANSPORT_USAGE.md)。用户00:56回包确认0106及RGB/GRAY+SAT能力，原始3包已重解码。下一步固定两帧小ROI实际负载CRC/H1/H2检查，8项新回环测试通过；正式采集资格不放宽，旧bit与638个软件文件保留。不需要再烧录未变化的0106或重复旧采集。

> 最新进展（2026-10-25 r3.9）：[新0106灰度实验bit与验证边界](EXPERIMENTAL_BIT.md)已交付。精确已审查DCP直接生成，BRAM60.37%、内部setup/hold +0.003/+0.007ns；未重新综合布线、未下载板卡或重复旧采集。仍为实验候选，正式采集资格保留阻断。助手继续FPGA，XDL负责融合训练与置信度。下方r3.6/r3.7段落保留对应阶段记录。

> 最新补充（2026-10-25 r3.7）：[已有硬件资料与29个引脚交叉核对](HARDWARE_REFERENCE_REVIEW.md)。15份原资料/22个清单成员哈希核对通过，PCB/PHY基础事实不再重复索取。外部IO及复位资格保持待验，资源、RTL和DCP不变。

2026-10-25，r3.6，继承[9c2fb8e交接](https://github.com/TJin-667/Selfree/commit/9c2fb8e05ee02a5c8f8024d31a3fd934f7107124)。本目录实现0106隔离候选，保留现用0105/09/SDK和原始数据；现用软件另作[638文件备份](../../backups/20261025_before_fixed_pair/README.md)。新增[0106独立八图操作入口与离线冻结诊断](OPERATOR_USAGE.md)，基于[0106独立UDP SDK](SDK_USAGE.md)完成22项软件检查。用户允许连接板卡后，两次仅STATUS查询均无回复；未生成bit、烧录或新采集。最新资源、时序及准入边界见[STATUS.json](STATUS.json)和[整板评估记录](IMPLEMENTATION_REVIEW.md)。

最新[IO/CDC/DRC复核](IO_CDC_REVIEW.md)：1099条CDC与0105逐键一致；展开DRC为336项，324条RAM控制路径已分类，资格缺项与原始明细均保留。没有修改RTL或DCP，也没有新增板卡查询。

## 已完成

- `transport_packet_store.v`：在原saved RGB分支接入灰度编码，使用一个1380字节包窗口，以原16位同步读取接口供应用发送。RGB565和GRAY8+SAT1各有真实负载CRC64；不申请整帧BRAM，不改变原H1/H2输入、阈值、反射域和DDR顺序排空。
- `generate_candidate.py`及`derived/`：从固定Git源码派生source、app、router和top，新增能力查询/格式选择、schema2最终描述。改变格式作废旧元数据；新session恢复RGB。原源码文件均未改动。
- `host_transport.py`：无网络的严格接收/最终校验适配，先保存临时包，最终校验请求、读回、完整身份、等待、FIFO全帧读数、实际负载CRC和重算H1/H2后才返回gray/SAT。保留原payload与元数据字节供后续SDK归档。
- `fixed_eight.py`：固定四向低/高八观测的数据合同校验，拒绝旧六图预算、错曝光/增益/光向、换姿态ID、旧身份和变更后的训练平面；不执行采集或自动选值。
- `sdk_transport.py`及`derived_sdk/`：独立0106网络执行库，保留原SDK生命周期、相机/ROI后验、失败退役与隔离；新增能力/格式协商、实际负载、第三次最终查询绑定、GRAY/SAT真实文件和显式关灯日志。不是原SDK白名单放宽；现已接入独立操作人宿主，0106实板资格与验证仍未完成。

- `operator_host.py`：来源/预览、完整计划SHA、构建与资格阻断、共享锁、真实0106 SDK、固定八图、失败停采、锁内关灯与close、整轮验证ZIP；当前硬件准入阻断，无跳过参数。`frozen_diagnostic.py`只做冻结字节核对，不冒充板上冻结输入。

## 验证证据

| 范围 | 证据 |
| --- | --- |
| 发送缓存28个RTL场景 | [final_01](verification/final_01/verification.json)：双格式65536颜色、1380字节边界前后、奇数尾部、背压、最终包等待分析、EOF、格式、取消和非法地址。 |
| 控制链路15个RTL场景 | [layout_board_01](verification/layout_board_01/verification.json)：实际app/router/owner/H1/H2/编码器，外围时钟/MIG/DDR/网口/SCCB寄存器为明确模型。 |
| 7张模拟帧逐字节审计 | [packet_audit](verification/layout_board_01/board/packet_audit.json)：5张RGB及2张GRAY/SAT，源图字节、CRC、重算H1/H2一致。是仿真数据，不是新增实物或融合收益。 |
| 22项主机与八观测检查 | [host_02](verification/host_02/verification.json)：18项接收器和4项固定八图检查；执行时禁止socket创建。 |
| 包布局计算 | [layout_unit_01](verification/layout_unit_01/verification.json)：579个有效向量，每个22拍；另含非法尺寸/格式、活动重启和取消检查。 |
| 0106操作人入口与冻结字节 | [operator_02](verification/operator_02/verification.json)：22项检查；全八图、第五次CRC失败、取消、文件改变、OFF缺ACK、ZIP失败、仅STATUS探针、冻结输入gray/SAT/H1/H2与尾padding；全为离线/回环。 |
| 0106网络SDK | [sdk_final_01](verification/sdk_final_01/verification.json)：35项离线/受保护回环测试，包括双格式、八请求合同、重连/回绕、协商和描述变化、CRC/H1/H2、取消/未知完成、隔离与源码变化；不连接实体板卡。 |
| 固定八请求后端与CLI | [fixed_pair_0105](../fixed_pair_0105_20261025/README.md)：现用0105严格RGB SDK适配，13项后端及12项宿主检查；真实SDK经本机回环设备测试，没有新增实拍或新GUI。 |
| 真实完整工程资源/时序 | 最新布局布线LUT18699、FF22647、BRAM81.5/135（60.37%）、DSP4；setup +0.003ns、hold +0.007ns。原始报告见[postroute_03](verification/postroute_03/verification.json)，完整资格边界见评估记录。 |

`run_01/02/03`及`board_01/02`保留开发失败记录，最终凭证以表格所列为准。中间发现并纠正了测试台握手/最终包断言，以及主机board_dark应使用原RTL的<=10而非全图near_black的<=5；该问题由实际RTL包与H1重算对照发现。原RTL阈值没有修改。仿真、实现缓存和旧轮重复黄金文件不入交付。

## 整板发现后的修正

首版将实际负载字节数直接组合除以1380，产生45级逻辑的header路径。`transport_layout.v`改为22拍移位除法，在采集开始后预先锁存包数与尾包长度；新头只有这些寄存器到发送口的路径。RGB模式恢复原包布局，复用原ROI像素数寄存器，移除重复几何乘法。未改变像素、饱和标志、H1/H2或阈值；新控制链路及579布局向量通过。

两次完整实现的setup分别为-17.897ns和-0.300ns，均保留失败报告。第二次的精确routed checkpoint继续物理优化，不改RTL、时钟周期或时序例外，第三轮达到+0.003ns。这个正余量很窄，且仍有外部IO约束资料缺项、CDC/DRC警告待审，因此只记录“当前约束下资源与内部时序通过”，不作为可烧录发布验收。

## 复现

依赖现有Python3.11、numpy、opencv和Vivado2018.3。保持仓库相邻目录结构，在本目录运行；输出目录须全新。

```powershell
python -B generate_candidate.py
python -B -m unittest -v test_host_transport test_fixed_eight
python -B run_verification.py --out verification/recheck --vivado-bin F:/Xilinx/Vivado/2018.3/bin
python -B build_candidate.py --out C:/bx72_gray_build_new --mode board --ymw-root C:/bx72_ymw_0105_20261015/board_2018_r5/ymw
```

`build_candidate.py`只拷贝固定依赖到新目录，使用实际sys_pll、MIG、读/写FIFO IP及原物理CDC约束；没有write_bitstream或硬件连接。新整板BRAM硬预算108个36Kb等效块（80%），布局布线后setup/hold均须闭合；资源通过不等于原外部IO资料缺项已自动补齐。不要把仿真边界模型用于综合。

## 尚未完成与下一步

0106 SDK、独立操作人CLI及整轮归档已完成软件接入；离线冻结字节验证入口已实现。同一硬件冻结输入双格式诊断、外部IO/CDC/DRC资格及新bit仍待完成，实板采集入口当前主动阻断。本轮两次授权只读STATUS均无回复，实体网卡Up/1Gbps但Cisco VPN路由优先；用户确认Codex依赖Cisco，保持连接继续开发。后续板测由用户在本机用[独立只读入口](RUN_LOCAL_STATUS.cmd)断网执行，恢复Cisco后交回结果，见[操作说明](OPERATOR_USAGE.md)。不能把无回复认定为唯一VPN原因或固件已确认。现用0105的[固定八请求CLI](../fixed_pair_0105_20261025/HOST_USAGE.md)已接入来源校验、共享锁和严格SDK，并通过本机回环测试；尚未安装新采集CMD或做现场验证。融合准备无需等待灰度bit。完成相应准入后才给YMW最小上板清单。现阶段不需要重拍004/005；XDL用现有RGB解出的gray/SAT推进标签、固定曝光与融合训练。

真实SDK后续改造及现场准入见[SDK_ADAPTATION_PLAN.md](SDK_ADAPTATION_PLAN.md)。

曝光400/800仅作合同测试值，尚未作为实物最优曝光冻结；测试用八观测也不是新增真实低高曝光组。完整协议见[PROTOCOL.md](PROTOCOL.md)，当前分工见[会后路线](../gray_sat_0105_20261025/MEETING_ROUTE_CONFIRMATION.md)。
