# 0107：完整入口与同冻结输入的独立工程验收

已准备工程候选与单窗口入口，**尚未实板验收，现用09未切换，release_ready=false**。此轮不扩大FPGA图像算法；灰度转换器原源码和0106均保留。新版本只为补齐同一次冻结读取的RGB/灰度/SAT证据和完整入口验收。

- [一次最小实板操作单](MINIMUM_BOARD_WINDOW.md)：本机 `C:/BX72_0107_ACCEPTANCE/20261026_window01`，下载一次0107、运行一个CMD、按提示一次KEY2；最多10次工程CAP，不重做02/03、不计训练组。
- [候选bit](artifact/bx72_0107_acceptance_EXPERIMENTAL_NOT_RELEASED.bit)；SHA256 `4d1545266f83a6eb52327e4863658fa465448c04572b595cbe6dbc482850a01b`；固定RTL `baacb069b48436a739b5011f891bdd1883251be1`，来源清单见[新旧源码差异](derived/SOURCE_MANIFEST.json)、[软件派生](SOFTWARE_DERIVATION.json)和[运行绑定](FINAL_BUILD_BINDING.json)。
- [接口/复位资格边界](QUALIFICATION.md)、[真正缺失的厂家依据](INTERFACE_EVIDENCE_REQUEST.md)、[当前机器状态](STATUS.json)。

## 核验结果

| 项目 | 结果/边界 |
|---|---|
| BRAM | 81.5/135 = 60.37%，小于80%；原0106为81.5 |
| LUT / FF / DSP | 18818.0 / 22739.0 / 4.0 |
| 新精确DCP setup / hold | +0.126 / +0.008ns，内部约束通过；不代表外部IO预算已闭合 |
| RTL | 61项编码/分包/背压/复位，868项布局长度，18项板级模型及9个提交帧逐像素检查 |
| 完整软件入口 | 46项通过；实际严格SDK、关灯/ZIP、八图、导出、复位读回与重新配置；全部127.0.0.1，非实板 |
| 新DCP审查 | CDC 1099条，规则/源/目的/depth/严重性/exception变化0；完整DRC 336条及106引脚一致；[详细凭证](verification/qualification_01/verification.json)保留外部资格缺口 |
| 实板 | 本轮0命令/0采集/0下载；原0106已通过的小ROI及全幅四帧证据沿用 |
| 原软件/bit | 638个现用文件、原0106整个发布目录及备份ZIP均未改，见[保护核验](verification/PROTECTED_FILES.json) |

最终证据：[RTL](verification/rtl_unit_01/verification.json)、[板级/布局](verification/rtl_board_01/verification.json)、[软件](verification/software_a107sw07/verification.json)、[实现](verification/implementation_01/build_verification.json)、[DCP审查/bit](verification/checkpoint_01/verification.json)、[离线入口](verification/DELIVERY.json)。模型、DDR、PHY等模拟边界已分别标明；没有把软件回环称为实物采集。

## 入口与失败行为

`acceptance_operator.py`调用隔离的严格宿主/SDK，原09和0106生产gate没有放开。工程Runtime只接精确bit、源码和通过凭证，标记engineering_acceptance_only。全幅mask为全1诊断域，不冒充板面分割；所有导出training_data=false。

第一步0x32在一次CAP的一次冻结DDR读取中携带原RGB及灰度/SAT，逐像素对照并复算原RGB CRC、实际负载CRC及H1/H2；随后0x31跑四方向固定400/800行八请求、同session/mask复用、关灯和可搬移XDL输入。400/800仅工程配置，不是最优曝光。最后按KEY2；BIND前先用3/14/9读取空状态，新的nonce和mask重新配置后仅一张81×21恢复帧。

CRC失败立即停采；导出失败保留八张及ZIP，不自动重拍；OFF无ACK不导出；未真正复位不发恢复CAP。sw02/03发现复位失败状态仍为RESET_PENDING，已修正为FAILED，最终轮复核通过。[原失败/修正记录](verification/HISTORY.json)保留。当前实板、光学质量、置信度、外部IO及生产发布标志均未提前置true。

完整第三方硬件PDF、实现IP缓存/DCP、大型可再生向量和软件回环原图不重复上传。复现工具在本目录与tools；原0106/原实拍数据继续原位保留。XDL负责后续融合训练/置信度和正式采集单，YMW采集、TJ协助标注；007～010及背面仍保留。
