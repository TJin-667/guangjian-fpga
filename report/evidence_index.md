# 证据与图表索引

本页把主要结论映射到随文档携带的材料和工程集成项。指标表为固定来源原字节副本；本轮没有新增实拍、位流或整机性能测量。原始工程收据由 YMW 随最终工程集成，TJ 内部来源登记保留其固定提交、路径和哈希。

<a id="ev01"></a>
## EV01 资源与内部时序

[metrics.csv](evidence/metrics.csv) 中 R01 行与 [resources.csv](evidence/resources.csv) 对应整板资源：0107/0108/0109 的 BRAM 均为 81.5/135，LUT/FF/DSP 和 DDR 条件分别保留。0109 WNS 0.079 ns、WHS 0.043 ns 为内部约束范围。新目录的[资源报告](../board/results/utilization_routed.rpt)、[时序报告](../board/results/timing_routed.rpt)、[DRC](../board/results/drc_routed.rpt)和[重建收据](../board/results/rebuild_verification.json)已随包提供；历史资格证据按对应来源解释；外部 IO 资格未完成。

<a id="ev02"></a>
## EV02 载荷与历史完整任务

指标表 A01 对应格式 50→49 同 ROI cold 接收应用载荷 25,005,698→11,373,958 B；含准备、协议、R32，排除线路头。B01/B02 为旧主机 12 组完整任务 A/B，cold PC/PL 中位 51.1125/56.1437 s，warm 25.4380/36.4607 s，PL 更慢。warm mask 命令为 0，但整个任务减少不能全部归因于 mask。

<a id="ev03"></a>
## EV03 软件交接与结果保持

H04/H07 对应三组各分支三次、共 18 次同输入比较，软件交接至完整导出下降 15.35%～17.05%。其起止点与排除项见[验证页](../docs/validation.md)。最终十数组、完整复检与分数保持一致，72 对导出图像逐像素一致。P01–P03 是独立 v1.8 一组 cold 功能闭环；C01 的 1.0328 仅属另一段主机延续比值，不表示新版整机加速。

<a id="ev04"></a>
## EV04 RTL 仿真

[rtl_simulation_result.json](evidence/rtl_simulation_result.json) 为固定 Vivado 仿真结果副本，记录生产模块 SHA、VCD SHA 和 PASS。定向 MaxAbs 涵盖严格强阈值、并列、符号和无效输入；9×9 输入有 81 像素比较及错误应答分支。`functional_RTL_only=true`、`physical_MIG=false`、`new_bit=false`，不代表物理 DDR、外部 IO 或速度验证。本次新目录重跑的[收据](../board/results/simulation_verification.json)、[H2 VCD](../board/results/simulation/h2/waves.vcd)及 [MaxAbs VCD](../board/results/simulation/maxabs/waves.vcd)另行保留，测试台和输入位于 `sim/fixtures/`。新旧 VCD 的哈希分别记录。

<a id="ev05"></a>
## EV05 样本与离线案例

开发回归 25 组 200 帧来自 003/004/005 三块板。便携 004 八帧身份为 `sample004_g1793337600415116700`，旧 0108、ROI `[576,160,864,864]`、格式 49、400/800 行、gain16=16、LED128；核心输入与十数组/复检/评分由最终 `data/examples/portable004` 和复现说明提供。006 两组来自一块冻结后新增工件，后态 M45 已确认非划痕，前态 H70 未裁决。

<a id="ev06"></a>
## EV06 曝光互补与海报图

[低曝光四方向](media/sample006_low.png)、[高曝光四方向](media/sample006_high.png)、[八帧融合](media/sample006_dual.png) 均来自 `sample006_g1793522156640254500`，ROI `[576,128,832,864]`，400/800 行、gain16=16、LED128，固定 B1 8/20。同一八帧灰度均值为显示底图，黄色为实际候选；它们不是三张单帧原片。青/紫局部用于观察代表性互补，不能推断整体准确率。

海报中 004 弱段消融来自 `sample004_A_v1_20261028_220937_87f02b`，复检三联来自另一组 `sample004_g1793416865712919600`，H45。不能将其与 006 曝光比较或其它 H50/M45 案例合并为同一组。[媒体说明](media/README.md)

<a id="ev07"></a>
## EV07 Skill 与 AI

[计时工具](../skill/README.md) 为标准库示例，其输出状态明确为 `EXAMPLE_ONLY_NOT_HARDWARE`。[协作记录](ai_records/README.md)区分原文摘录、概述、人工决定和工程验证；五条 YMW 消息及 TJ 本轮整理记录不代表全队完整开发日志。XDL 原始 AI 记录已列未交付项。

<a id="ev08"></a>
## EV08 唯一技术报告

采用 mask 存储修订后的 46 页稿，Word SHA-256 为 `1f5b2bbc84acb6fc3e72629160a4968bbeaa1349135aee89b4a3ffc67c688d6d`。同版 PDF 和 Word 的最终位置与身份见[报告说明](README.md)。旧 45/55 页审阅记录只保留为历史，不用其页号替代新稿。
