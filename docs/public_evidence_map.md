# 报告原来源与公开证据对应

46 页报告保持原字节，其中第 40 页和第 43 页保留了 8 个不同的原 Selfree 私有来源链接。原库继续私有，本页提供公开可读的对应材料。这里是必要材料的公开摘取和导航，不声称复制了原内部目录的全部内容。

| 报告原来源 | 本仓库入口 | 范围 |
| --- | --- | --- |
| `807c3f97ce` 工程与性能增量 | [指标表](../report/evidence/metrics.csv)、[资源对照](../report/evidence/resources.csv)、[旧任务 A/B](../report/evidence/history/system_ab_old_host.json)、[软件比较](../report/evidence/history/speed_software_compare.json) | 历史实测、软件区间和统计口径。 |
| `8c697e8695` XDL B1 集成 | [实际 vendor 执行树](../src/algorithm/vendor/xdl_b1)、[算法分工](architecture.md) | 按当前冻结依赖保留的执行源；不是原私有目录的全量镜像。 |
| `73a0cf3b12` 写作交接 | [完整 004 案例](../data/examples/portable004)、[离线复现](quickstart_offline.md) | 旧 0108 实拍输入及配对数学参考。 |
| `9969cb92e6` 最终写作包 | [证据索引](../report/evidence_index.md)、[真实协作记录](../report/ai_records/README.md)、[Skill](../skill/README.md)、[媒体](../report/media/README.md) | 公开选择的事实、记录和图源。 |
| `91c0f25e21` 报告 RTL 仿真 | [定向仿真结果](../report/evidence/rtl_simulation_result.json)、[新目录重跑](../board/results/simulation_verification.json)、[复跑方法](build_from_source.md) | 旧结果与新目录 VCD 分开标识，不作为物理 DDR 验证。 |
| `91c0f25e21` 原 route audit | [原约束与构建输入](../src/fpga/implemented)、[新资源报告](../board/results/utilization_routed.rpt)、[新时序报告](../board/results/timing_routed.rpt) | 新旧 checkpoint 身份不同；不把此次重建改写成原 bit 的新来源。 |
| `8e57494b9b` 报告审阅 | [唯一报告与实际哈希](../report/README.md)、[验证边界](validation.md) | 内部评审批注和私人过程材料不公开。 |
| `53c9c88b21` 报告配图复核 | [006 同组图及说明](../report/media/README.md)、[海报预览](../report/media/poster_zh.png) | 保留实际像素、组身份和曝光消融范围。 |

历史 JSON 内的原目录字符串用于追源，不是运行所需的目录。当前活动入口通过仓库相对路径和显式运行配置定位，不需要访问原私人电脑或原私有 Git 数据库。

原生历史证据： [0109 功能](../report/evidence/history/0109_acceptance.json)、[复位解码](../report/evidence/history/0109_reset_decoded.json)、[位流生成收据](../report/evidence/history/0109_bit_build_receipt.json)、[生成时资格](../report/evidence/history/0109_qualification.json)、[v1.8 真实组](../report/evidence/history/speed_live_acceptance.json)、[完整复检比对](../report/evidence/history/speed_live_review.json)、[主机区间](../report/evidence/history/pc_pl_host_only.json)。各材料按自身范围解释，不推导未测的整机加速或准确率。
