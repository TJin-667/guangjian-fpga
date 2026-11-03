# 审查修订与比赛提交状态

本说明回应 2026-11-03 的独立审阅，逐项对照实际文件。工程检查通过、公开范围一致和赛方允许的最终交付方式分别记录。

| 审查项 | 本修订的处理 | 状态 |
| --- | --- | --- |
| 完整 RAR 与公开 RAR 的用途 | 公开包只包含自研及明确可分发内容、离线案例和外部清单；完整本地包含第三方原件，不由本库授予上传权。 | 范围已区分；平台接收方式待确认。 |
| MIG 相同字节副本 | 两处额外 `ymw/mig_b.prj` 与原外置配置相同，统一外置，清单为 232 个路径；添加工作树及可达 Git blob 的内容指纹检查。 | 当前修订已处理；旧公开历史及资产须按发布处置记录检查。 |
| 历史大写路径 | 保留冻结导入、Tcl、参数与来源绑定；列出实际路径清单，未把推荐目录可调整解释为大小写豁免。 | 是否接受例外尚未获得赛方确认。 |
| 仓库链接与复现环境 | 当前名称为 `guangjian-fpga`；首页使用规范直链；公开与完整本地包的回放均说明 Prescott 环境。 | 已处理。 |

## 两种代码包

`guangjian_source_v1.0.1.rar` 对应公开 Git 固定版本，不含 232 项外部原件。它不能在未确认时冒充依赖随包齐全的“全部代码”。

独立审阅提到的 `guangjian_all_code_20261103.rar` 是团队内部完整本地包：80,810,948 字节，SHA-256 为 `04be69bb05f1029eba47e603939fe4de704b4c3f21dbf4aa605fc1b5ef94b68f`。它包含第三方原件和既有 bit，不在本公开仓库或 Release 分发。以上身份须与实际包核对，不能从本机可用推定获得赛事平台交付权。

CrazyBingo 未取得额外公开再分发授权；AMD/Xilinx IP、板级参考和既有位流分别适用原条件。尚无比赛方书面确认接受“自研代码＋外部依赖清单”的材料，也没有证明完整包所有组件均可上传的新增授权。当前状态为 **待确认**。确认后将依据及适用范围补入本说明，不虚构许可或赛事答复。

## 完整本地包的异机精确回放

合法取得并在私有目录解包后，在启动 Python 前使用：

```powershell
$env:OPENBLAS_CORETYPE = 'Prescott'
& ./.venv/Scripts/python.exe -B scripts/replay_example.py --out _work/capsule_replay_new
& ./.venv/Scripts/python.exe -B scripts/replay_host_example.py --out _work/host_replay_new
```

虚拟环境和锁定依赖见[离线说明](quickstart_offline.md)。此补充不修改既有完整 RAR 或其哈希；重做完整包时必须更新其文档、清单和验证收据。公开版先按[恢复说明](external_dependencies.md)合法恢复所需原件，才可使用完整主机 API、GUI 或 FPGA 输入检查。

## 命名的待确认范围

指南 §3.3.5.4 的目录映射与小写文字要求是两件事。当前项目含 `YMW`、`CASE.json` 等历史名称；[实际命名清单](path_naming_inventory.json)统计全部公开路径、大小写冲突和建议的小写形式。该清单不是赛方豁免，也没有执行批量改名。

若赛方不接受冻结路径例外，需要单独制作规范化快照，并验证全部导入、约束、原始字节映射和回放。不能直接批量改名再改哈希放行。

## 旧版本与发布处置

v1.0.0 含两份本应按现有策略外置的 MIG 配置，不再推荐使用。v1.0.1 修正公开范围，不移动旧 Tag 来伪装原发布；如撤下旧 Release/Tag 并清理公开历史，应先保存内部备份、说明提交号变化，并核对所有远端分支和标签。

可达历史检查不等于删除 GitHub 缓存、第三方克隆或 fork。GitHub 对改写历史及缓存的范围有[官方说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)。成员接续时从修订后的公开版本重新克隆，勿合并旧历史将已外置副本带回。

本修订不新增采集、接板、综合或 bit 生成。最终 MP4、签署授权书和 XDL 原始 AI 记录仍按各自实际交付状态处理。
