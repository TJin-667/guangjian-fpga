# GitHub交付说明（2026-10-25）

本目录现在随YMW分支和PR #23发布。[当前总入口](../../docs/project_route_20261025/README.md)为最新状态；[XDL完整交接](HANDOFF_TO_XDL.txt)为本轮算法任务单，[YMW FPGA交接](HANDOFF_TO_YMW_FPGA.txt)由YMW侧执行。README中格式/固件能力对齐的负责人统一为YMW侧，TJ不是本轮依赖；未发布早期HANDOFF_TO_TJ.txt。

PACKAGE_MANIFEST.json保留此前r2本地包的成员SHA，所列文件与本次GitHub文件字节相同。额外的本说明、.gitignore、.gitattributes和总交付索引不属于该旧ZIP成员。旧ZIP仍是历史快照，日后交接直接使用GitHub提交链接。package_handoff.py和verify.py中的本机路径用于原执行环境；他人复现需替换Python/Vivado及数据路径，不要求创建同名用户目录。

run_04、ooc_02是本次发布的最终证据。README所述run_01/02/03和ooc_01为本机保留的历史日志，没有作为当前通过凭证，也没有上传仿真数据库和实现缓存。最终OOC汇总hold仍负值，不能称为整板时序已通过；没有新bit、板卡测试或新融合质量结论。

原005 ZIP未重复上传，本目录context含审计与反馈；需原始图时索取已有原包，不能因此安排重拍。004用户确认的A/B/C归属已归档，精确中心线及端点仍须保留unknown。
