# 0106灰度回传实验bit（2026-10-25 r3.9）

> 2026-10-26补充：用户已下载并运行新0106只读检查，版本/状态/双格式声明通过，见[真实回包和下一步工程检查](ENGINEERING_TRANSPORT_USAGE.md)。下文“未上板”描述10/25生成时状态；实际灰度负载和质量资格仍待验。

已从现有、已审查的布线结果生成新的0106实验bit，并核对文件头、芯片型号、SHA及固定RTL来源。本轮没有重新综合或布局布线，没有下载板卡、改动现用软件或重复004/005采集。当前为 `EXPERIMENTAL_NOT_RELEASED`，尚无0106实板验收结论。

- [实验bit文件](verification/experimental_bit_01/artifact/bx72_0106_gray_EXPERIMENTAL_NOT_RELEASED.bit)，3,825,906字节。
- SHA-256：`9d3b8566fa1909969c711b0bcb3122fd9d8e059344adcdb6e080b5240e18e1b0`。
- [独立复核凭证](verification/experimental_bit_01/INDEPENDENT_REVIEW.json)、[原生成日志](verification/experimental_bit_01/vivado.log)、[原执行凭证](verification/experimental_bit_01/verification.json)。
- RTL：`46f9d50cf2d854f2e9f31bf8b0dddfe9b2025c07`；精确DCP：`175d82b777469cc1e94d4123ace9935ea25f8d47902476ee6f926ca47c30c947`，生成前后SHA一致。
- 器件：`xc7a100tfgg484-2`；工具Vivado2018.3；bit头生成时间2026-10-25 20:47:08。

## 部署范围与资源

板端新增RGB565到既定整数灰度的转换、饱和标志及对应负载CRC64发送。支持原RGB565与GRAY8+SAT1两种回传；DDR和原H1/H2统计仍使用原RGB链路。它没有部署融合模型或置信度模型。

| 项目 | 结果 |
| --- | ---: |
| LUT | 18,699 / 63,400（29.49%） |
| FF | 22,647 / 126,800（17.86%） |
| BRAM，36Kb等效 | 81.5 / 135（60.37%） |
| DSP | 4 / 240（1.67%） |
| Setup / Hold | +0.003 / +0.007ns |
| 布线错误 | 0 |
| 生成前DRC | 336项Warning；无Error/Critical Warning |

资源与时序来自这份bit对应的同一DCP。BRAM低于80%预算，但setup余量仅3ps；已有IO/复位/CDC资格缺项仍保留。`release_ready=false`、`hardware_tested=false`，正式八图采集入口的资格门槛没有放宽。

同ROI且像素数可被8整除时，单张GRAY8+SAT1纯图像负载是RGB565的56.25%；8张灰度加饱和标志合计是原4张RGB565的112.5%。不包含UDP头、重试、等待及丢弃帧，不能据此推算整轮耗时。这个格式保留原灰度/SAT合同，实板质量仍需对照验证。

## 后续集中验证范围

只针对新的0106推进，已有bit修复、0105状态和004/005旧采集不重复。助手负责新bit与严格灰度接收链路，XDL负责曝光融合训练、标注与置信度；用户已转交的三项算法修正继续由XDL处理。

工程验证依次覆盖：0106版本及传输能力、GRAY/SAT包长与实际CRC、参数/ROI/请求身份、H1/H2重算、失败停采与关灯。逐像素质量验收还需要同一冻结硬件输入的RGB/GRAY对照；两个新拍帧存在噪声，不能当作同一输入。现有离线冻结字节检查不替代这项实板证据。

已准备[新0106只读检查入口](RUN_NEW_0106_CHECK.cmd)，并通过[受保护回环验证](verification/experimental_probe_01/verification.json)。它仅发送一次命令3和一次命令14，核对0106及双格式能力，不设置曝光/灯光、不采图、不烧录。输出到 `C:/Users/yue/Documents/GuangjianNew0106/`。检查成功只证明新协议握手，不证明灰度图验收或板上完整bit SHA读回。

此入口用于新的0106下载后检查，现阶段不用反复运行。保持Cisco连接继续开发；需要离线板测时，集中窗口在本机独立执行并保存结果，再恢复Cisco。无需为本轮生成bit移动工件、补拍旧数据或重做02/03。

## 生成与复核复现

`emit_experimental_bitstream.py`只接受上述精确DCP和来源清单，输出目录必须全新；不调用任何硬件API。原 `build_candidate.py`继续保留仅实现、不生成bit的职责。源码/约束不变时不必重跑综合布局布线。

原Vivado正常退出并生成bit。首次Python后验解析未接受布线报告的点填充标签，因此原执行凭证保留 `candidate_verified=false` 及解析错误。修正报告解析后，`verify_emitted_bitstream.py`直接复核原bit、原报告、执行源码快照、DCP和Git固定源码，写入独立PASS凭证；没有重建bit或覆盖失败凭证。当前结论以独立复核凭证为准。

现用0105 bit SHA仍为 `f9aa14f03d15e687a905104f1a9a30b615b456bc6b6488df3e841ed7285a29fe`；原01～09及[638文件备份](../../backups/20261025_before_fixed_pair/README.md)保留。

用户要求完成后再自检。本轮[最终离线自检](verification/experimental_selfcheck_01/verification.json)通过：精确DCP与7份固定RTL、bit及原日志、状态绑定、受保护回环证据、无socket准备、PowerShell语法、638份现用文件和原备份ZIP均核对；未验证的实板项目逐项保留。
