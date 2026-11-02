# 0106离线同输入验证及灰度采集数据接入

2026-10-26 r4.3。用户已将板卡断电休息，本轮全部在离线文件、RTL仿真及仅允许127.0.0.1的软件设备上完成，没有新拍摄、烧录、改网络、覆盖原09或新建训练标签。

## 本轮完成

| 工作 | 结果 | 证据 |
| --- | --- | --- |
| 已有真实RGB作为固定输入，经过精确实现源中的编码器RTL | 全幅2073600像素及81×21裁剪，各gray像素、SAT位、H1/H2完全一致；输入停顿/输出背压、SOF/EOF及奇数尾组同时检查 | [RTL凭证](verification/same_input_rtl_01/verification.json) |
| 固定输入的XDL算法接口对照 | 原RGB参考与RTL回放输出进入XDL原版extract_evidence，bright/dark/reliability/scale/residual_n/saturation_fraction共6平面逐元素一致，648/1620两档阈值掩膜也一致 | [真实留档接入检查](verification/gray_bridge_real_02/verification.json) |
| 独立灰度输入桥接 | 原payload、metadata、gray/SAT/mask、PNG、身份及SHA严格复核，原子导出可搬移数据包；23项新检查通过 | [23项凭证](verification/gray_bridge_02/verification.json) |
| 采集→完整归档→自动导出模型输入 | 保留原发布准入，采集失败不导出，导出失败保留原ZIP且不重新CAP；4项新受限回环检查通过 | [4项凭证](verification/gray_workflow_03/verification.json) |
| 原程序和bit保护 | 638个现用文件及原bit再次核对未变；实验0106 bit SHA不变，BRAM仍60.37% | [最终自检](verification/offline_gray_integration_02/verification.json) |

RTL输入来自01:51全幅RGB留档的原字节，SHA为b8aa4c34f924d56ba7fe030dea17919b6570d2a1d20b90b065f5c73a323306f0。编码器逐字节核对固定实现提交46f9d50，未修改RTL。全幅与奇数裁剪输出均与冻结参考一致；用另一张真实GRAY相机帧替代同输入输出时，验证器正确拒绝。大数组只存在于testbench，不进入综合，也不占板上BRAM。

**这建立了同一真实留档输入的RTL/数字算法接口一致性，不等于在板上冻结同一DDR银行后回传两种格式。** 现有0106协议仍会在格式切换时作废metadata并释放帧，没有假称已实现硬件重放。也未用本轮结果宣称标注后的识别率、最优融合比例、置信度或外部IO/复位资格。

## 已接通的软件入口

`gray_capture_bridge.py`是无网络模块，可由采集宿主在严格SDK提交后调用。独立用法如下（输出目录必须全新）：

```powershell
python -B gray_capture_bridge.py frame --record <原committed/result.json> --out <新单帧目录>
python -B gray_capture_bridge.py batch --batch <完整八观测原批次目录> --out <新八观测目录>
python -B gray_capture_bridge.py verify --frame <单帧数据包目录>
```

每包保留原committed文件，并提供uint8 gray8/sat1/valid_mask NPY、绝对传感器ROI原点、完整帧身份及XDL兼容的gray/SAT绑定摘要。摘要明确在离线校验导出时计算，不能伪称原SDK早已记录它；同帧来源由保留的原wire payload、实际CRC64和metadata继续核对。SAT不从灰度亮度推断，也不伪造同帧RGB。

`gray_acquisition_workflow.py`已把原固定八请求宿主与自动导出连接起来。它先检查原计划/来源及候选准入，再复用原host/strict SDK采集、关灯、ZIP，最后才导出。失败保留原批次与错误收据；无整轮重拍。没有CLI绕过资格参数。本轮用明确的软件姿态测试实际现有candidate gate会在socket创建前阻断；未要求重做历史02/03去满足一个离线测试。

正式入口当前仍受原release/IO等准入阻断，不给用户一个现在就运行的真实八图命令。原09完整保留；XDL照常用已采RGB开展训练，无需等待灰度入口发布。

## XDL接口已经核对，剩余坐标差异有明确处理

PR27核对头仍为a47aaf7。其源码已经有gray_sat_payload_sha256和灰度源SAT绑定，不重复要求他重做。只读引用6个精确Git blob用于兼容检查，见[integration_refs快照](integration_refs/xdl_a47a/SNAPSHOT.json)，没有改XDL模型。另验证了XDL已先从自身工作区导入同版模块的情况：只有加载的接口源码Git blob完全一致才复用其类型，防止重复类导致接入失败；不同代码仍拒绝。

原生全幅的真实RGB/GRAY输入导出后，XDL原文件读取器均可复核。FPGA只保存ROI的输入则带真实saved_origin_xy，不能对一个ROI PNG再次按全图坐标裁剪；原文件读取器对此会正确报错。新桥接读取器从同帧raw+metadata重建数组，保留全局ROI，直接构造XDL ObservationGroup，23项测试已通过低曝光、高曝光、等权三个现有基线的完整软件八观测输入；这是接口测试，不是新的训练数据或融合收益。

```python
from gray_capture_bridge import load_group
from exposure_fusion_v1.fusion import fuse_group

group = load_group(portable_group_folder, purpose="interface_test")
result = fuse_group(group, mode="equal_weight")
```

数据桥接当前只允许interface_test，导出标签为UNLABELED、training_data=false，不能直接塞进fit冒充已审核数据。XDL下一步把此已验证的saved-ROI入口接入其训练驱动，继续按原标注/有效mask/物理板分组规则审核；不改融合公式来迁就坐标。一个[可直接读取的真实小ROI样包](verification/gray_bridge_real_02/small_31/frame.json)完整随库提供；全幅导出与RTL大向量在本机生成，避免再上传同一批原图，原全幅ZIP已在上一阶段入库。

## 验证范围与后续

本轮新增27项检查（23+4）、2个真实留档RTL场景、4个已有真实帧的导出复核。最终通过轮次的29次CAP全为受保护的软件设备（历史轮次另有43次，也全为软件请求），不计实物采集或训练样本。首次workflow测试的Windows长路径及旧02/03耦合问题仅调整测试夹具，失败原日志/源码保留，最终4项通过；没有放宽SDK、来源或发布准入。

目前不需要YMW拍摄或操作板卡。助手后续继续集成与资格缺项；XDL给出MODEL_SPEC、首批NEXT_BATCH和标注示例，YMW负责采集，TJ协助标注；不提前下100组任务，不消耗007～010冻结板或B面。需要下一次实板时再集中给最小清单。板卡已断电，下次验证0106时需恢复同一实验bit到RAM；这不意味着本轮生成了新bit，也不要求现在操作。
