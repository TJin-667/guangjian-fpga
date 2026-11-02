# XDL 软件控制器：离线回放与 TJ 整数参考

本地交付版本：2026-10-14。规则 `controller-0.1`；统计 `controller-statistics-1`；共同区域 `common-evaluation-1`；独立参考 `tj-independent-reference-1`。这是保存图像上的软件数值与策略验证。`LOCKED` 仅表示离线规则确认成立；真实曝光写入、LED 光照生效、相机新帧与 FPGA 闭环均待实板验证。

## 环境与安装

固定使用已有 Python 3.11 环境。以下 PowerShell 命令不依赖启动目录，可以整段独立执行；依赖锁定在 requirements.txt 中，已安装时安装命令仅检查现有包。

```powershell
& 'D:\FPGA\XDL_Algorithm\.venv\Scripts\python.exe' -B -m pip install -r 'D:\FPGA\XDL_Software_Controller\requirements.txt'
```

数据、检测核心和历史参考都留在原位置，控制器没有第二套检测核心。全量验收依赖以下实物材料；任一缺失、原始哈希不匹配或验证不完整，都不能标记全量通过：

| 材料 | 路径 / 不可变身份 |
| --- | --- |
| 已有检测与整数基元 | `D:\FPGA\XDL_Algorithm\software`；检测提交 `c5e4bea5cc39cd7b5b587847bce4547bdb3f0a88` |
| 扫描图 | `D:\FPGA\YMW\YMW_manual_20261013`；提交 `7ccb753ffacff752a5cd65d4b3a13ff7be9875c6`，revision=2，只用位置 A 四档 CH1 |
| 历史结果 | `D:\FPGA\XDL_Results\2026-10-13_manual_exposure_gain` |
| 已交付数组参考 | `D:\FPGA\XDL_Results\2026-10-13_integer_reference_01`；参考提交 `8e7dec0daaedb0f08ef80b707c83ba37de7e7002` |
| 两块板各三帧重复资料 | `D:\FPGA\YMW\ch1_repeat_defect_near_normal_20261013`；提交 `de18e3b604158c1b53b87b08f22ddc59ed52cfe2` |
| 保护基线16项 | `D:\FPGA\XDL_Results\2026-10-13_software_controller_build\preservation_before.json`；SHA256 `69cb3f1515a7ef1786bd44ea41f195c08e51c9c69b738c9be644156c462f0f4b` |
| 下载凭证20项 | `D:\FPGA\XDL_Results\2026-10-13_software_controller_build\repeat_download_receipt.json`；SHA256 `c48282b5e65f063dea6e93e8b321241111a0fbe9077deb8b904daacebe1c5824` |

两个审计 JSON 是明确的外部依赖，CLI 默认使用表中路径，也允许显式指定相同字节的副本；程序校验固定 SHA256，不信任任意改写的基线。16项包括7个原检测源、整数基元、参考导出器，以及6份历史交付结果和 analysis_inputs.json。额外核对历史结果/数组参考目录和扫描/重复输入目录的运行前后完整文件清单及哈希；忽略 Python 缓存目录。原输入不会被提取到控制器目录或改写。

## 测试

以下命令发现 tests/ 全部测试，并显式把实际数据路径交给集成测试。所有路径均有以脚本位置确定的默认值，因此下列两个命令可从任意工作目录分别执行。第一条还会从独立临时工作目录运行一次完整 CLI，保留一个全新的日期结果目录。

```powershell
& 'D:\FPGA\XDL_Algorithm\.venv\Scripts\python.exe' -B 'D:\FPGA\XDL_Software_Controller\run_tests.py'
```

```powershell
& 'D:\FPGA\XDL_Algorithm\.venv\Scripts\python.exe' -B 'D:\FPGA\XDL_Algorithm\software\run_tests.py'
```

控制器测试末行 JSON 的 `acceptance_complete` 只有在完整发现、没有失败/错误/跳过时才为 true。真实材料缺失允许集成测试说明原因并跳过，但全量命令返回非零、列出未完成项；跳过不算数据验收通过。`--pattern test_replay.py` 等参数只做局部诊断，即使通过仍是 `acceptance_complete=false`。直接使用 unittest 发现的局部结果不能替代此全量验收。

I1–I4修正后当前完整控制器套件166项（含九项确定性最终回归），原检测77项均通过；全量验收产生独立新目录06。最终回归另覆盖合格观测后重试耗尽、第二次不稳定、首次回退预算不足、真实空native mask、完整配置域边界及低复核门槛敏感性实验。

需要更换材料路径时，对 run_tests.py 使用与下方 replay.py 相同的路径参数；完整路径不会依赖当前目录。

## 全量复跑

下面命令明确指定全部外部依赖和配置。省略 `--output` 时自动选择本地当天 `D:\FPGA\XDL_Results\YYYY-MM-DD_software_controller_NN` 的下一个未使用目录，重复执行同一段即可完成第二次复跑。程序拒绝覆盖已有目录；不得为了复跑删除旧结果。可用 `--output` 指定该结果根下的全新日期目录。

```powershell
& 'D:\FPGA\XDL_Algorithm\.venv\Scripts\python.exe' -B 'D:\FPGA\XDL_Software_Controller\replay.py' --algorithm-root 'D:\FPGA\XDL_Algorithm\software' --scan-root 'D:\FPGA\YMW\YMW_manual_20261013' --expected-results 'D:\FPGA\XDL_Results\2026-10-13_manual_exposure_gain' --reference-root 'D:\FPGA\XDL_Results\2026-10-13_integer_reference_01' --repeat-root 'D:\FPGA\YMW\ch1_repeat_defect_near_normal_20261013' --regions 'D:\FPGA\XDL_Software_Controller\repeat_regions.json' --config 'D:\FPGA\XDL_Software_Controller\config.json' --preservation-baseline 'D:\FPGA\XDL_Results\2026-10-13_software_controller_build\preservation_before.json' --repeat-receipt 'D:\FPGA\XDL_Results\2026-10-13_software_controller_build\repeat_download_receipt.json'
```

```powershell
& 'D:\FPGA\XDL_Algorithm\.venv\Scripts\python.exe' -B 'D:\FPGA\XDL_Software_Controller\replay.py' --help
```

CLI 返回0表示完整离线证据通过；验证不完整返回1，配置/输入/路径校验错误返回2。`NEEDS_REVIEW` 是合法策略停止，不是测试失败。全量应包含 scan4、repeat6、重复对照6对、敏感性27组、构造15场景/42完整转换/4种预期拒绝，及当前147个完整 state+Decision 独立对照。

## 实际回放结论与待验事项

首版固定 CH1、LED128、gain16=16（1×），曝光400/500/600/700**行**，初始600行。扫描 A 的实际动作是600→500→400→请求新的400行确认帧；资料中没有第二张新400行图，结果 `NEEDS_REVIEW`，理由 `missing_fresh_confirmation`、`unfulfilled_modeled_request`，不能重读旧图凑确认。

repeat_001 和 repeat_002 是两块独立板。各自先消费第一张600行图，因风险请求500行；该重复实验只有600行数据，因此各自 `NEEDS_REVIEW`，理由 `missing_requested_data`、`unfulfilled_modeled_request`。各板三张600行图全部用于另外的稳定性统计，不能跨板混合，也不能补作扫描 A 的确认。002不作为严格正常真值，不计算正常误报率。所有掩码人工复核标志保留。

扫描共同面积602230；两板分别599427和596266。I1–I4修正后的两次最终输出见 [第一次修正源验证](D:/FPGA/XDL_Results/2026-10-14_software_controller_07/verification.json)、[第二次修正源验证](D:/FPGA/XDL_Results/2026-10-14_software_controller_08/verification.json)，成本/终止见 [修正源摘要](D:/FPGA/XDL_Results/2026-10-14_software_controller_07/summary.json)。完整RED/GREEN、当前源码哈希、保护证据和稳定字段对照见 [最终修正报告](D:/FPGA/XDL_Results/2026-10-13_software_controller_build/final-fix-report.md)。旧01/02是修正前Task7正式证据，03–05、10/11也保留为修正前验证记录，不能代替当前修正源复跑；[Task7审计报告](D:/FPGA/XDL_Results/2026-10-13_software_controller_build/task-7-report.md)保留原阶段结论。

当前修正源码SHA256：fpga_reference.py=`052f62fbf09fe5da72e36b23d8e89751bafd81c3ed0581f4faf1a26101e99f34`；replay.py=`4e81407fcc77d2080e8932c4f439833ae9ec69be80282e86879529898cb18a2a`。最终07/08的provenance.json记录全部六个根Python模块哈希；主控制器/统计模块及固定源保护基线不变。

需要TJ/YMW实板另验：设置与图像关联、相机/光照确实生效、丢弃帧数量和等待时序标定、同参数独立新帧/回退确认、人工板面几何、阈值泛化，以及 FPGA 资源与时序。现有历史读回只能证明保存资料中的记录。没有实时控制成本测量、准确率、最佳曝光或可靠噪声表。

## 整数契约、实验门槛与成本

保存图上复用原 ymw_integer_reference.py：REFLECT_101、sum9为81像素精确和、residual_n=81gray−sum9，weak严格 `abs(residual_n)>648`，strong严格 `>1620`。不拉伸保存图、不先重建全画面滤波；原board mask/侵蚀/边缘排除和 native 分母保持原样。控制器另在全坐标共同区域统计，面积至少10000且覆盖各 native board 至少95%，不足则需复核。

`native_reference_statistics` 保留旧基线；新的 `controller_statistics` 使用共同分母。dark是gray≤10，near_white是gray≥250，RGB风险是任一RGB8通道=255；effective是gray>10或weak。line_center需要四方向中某方向的中心和两侧同符号weak；背景是共同区域其余像素。线状/背景残差和只是成像代理，候选数不参加选优，RGB最大码不直接删除候选。

计数/灰度与残差和均非负整数，检查灰度分区可达范围、dark+near_white≤n、effective≥n−dark和background+line_center=n。新累计使用uint64/Python int；交叉乘积不窄化成32位。零分母记录null；未知背景不能补0占排序优势；JSON禁止NaN。比例以basis points（10000=100%）交叉相乘比较；百分数显示不参与决策。

实验门槛：effective≥9000bp、dark≤1000bp、near_white≤100bp；RGB>500bp提示，>1000bp更高风险。确认需连续2个同设置、独立未用观测，均值变化≤2、effective变化≤200bp、RGB变化≤50bp；变参清零。搜索不重复访问档位，允许一次有新帧的回退确认，每档采集错误最多重试1次。敏感性导出effective85/90/95% × RGB提示3/5/8%，不从这27组对照挑“最佳准确率”。

采集错误超过该档重试上限后直接以`CAPTURE_FAILED` / `retry_exhausted`停止；先前有合格观测也不会增加一次采集错误回退。确认不稳定时才可使用一次明确回退（搜索耗尽时仍按既定规则处理）；首次选择回退立即清空旧确认，即使预算不足以支付回退请求。回退已使用后的第二次不稳定以`NEEDS_REVIEW` / `fallback_exhausted`停止，保留最后reference/count作为历史快照，pending_request为null，不代表仍有活动确认。

共同区域真实为空时，`coverage_denominator=null`、均值等零分母比值为null；metric→controller→独立参考→replay正常返回`NEEDS_REVIEW`及几何/面积理由，不伪造比例。可用几何的非法分母类型仍属于`ValueError`。独立参考接受完整、规范化配置，独立验证与`controller-0.1`主配置相同的固定值、整数类型、最小面积10000、覆盖9500bp及预算/范围限制。

自定义RGB复核门槛低于800bp时，自动敏感性实验对全部九个变体统一使用研究专用复核门槛`max(用户rgb_review_bp,800)`，保证提示300/500/800bp都有效。用户基准配置和动作不变。每个变体保留完整已验证config、`requested_rgb_review_bp`、`sensitivity_rgb_review_bp`、`sensitivity_review_threshold_adjusted`、`baseline_config`及`baseline_comparison`；后者明确列出改变的配置字段及复核门槛是否也不同。因此该情况下相对用户基准的动作差异同时包含复核门槛变化，不能解读为只隔离有效面积/风险提示门槛的影响。默认复核1000bp保持不变。

预算最多8请求/32帧/40000ms。每请求3丢弃+1评估，模型设置等待1000ms、每帧1000ms，即Cost(1,4,5000)。请求先预留，观测或错误提交一次，缺资料记未兑现，逐轴保持requested=consumed+reserved+unfulfilled。

扫描模型 requested/consumed/unfulfilled 为(4,16,20000)/(3,12,15000)/(1,4,5000)；每块重复板为(2,8,10000)/(1,4,5000)/(1,4,5000)，reserved均0。重复实验历史人工接收896帧（001完整预览884、002三次单拍12）；505/514/517是重叠前缀不能相加。扫描历史总成本未聚合，明确null；历史时间也是null。`compute_walltime_ms` 是软件计算时间，`measured_live_control_cost` 始终null，二者都不是请求模型时间。

## 文件与结果入口

根目录扁平，仅tests为代码子目录。capture_metrics.py负责整数统计与区域；acquisition_control.py负责有限状态/预算；dataset_io.py负责原始文件/ZIP/session边界；replay.py负责三个独立实验及导出；fpga_reference.py提供独立逐点统计/决策/位宽。config.json记录实验规则，repeat_regions.json记录两板各自来源绑定的人工区域；[设计](D:/FPGA/XDL_Software_Controller/DESIGN.md) 是规则权威。

每个全新结果目录有35个文件：12个JSON/CSV配置与日志文件、3个common mask、10个native mask和10张复核叠加图。frame_metrics.json/csv有10帧；decisions.json/csv是3实验的11条动作日志；repeat_stability.json/csv为2板记录，各含3对；golden_actions.json含147转换；sensitivity.json含3板/场景×9配置。CSV嵌套字段是严格JSON，保留整数和null。

verification.json明确给出 `offline_verified`、`provisional_thresholds`、`hardware_validation_pending`、`source_unchanged`、`historical_results_unchanged`、`inputs_unchanged` 及逐项哈希/数量证据。数值、独立决策或保护证据缺项不能通过。provenance.json记录输入身份/源码哈希/三个来源提交/配置/外部路径、模型与历史成本；实拍回放、synthetic_image和constructed_statistics标记不同。叠加图绿色是共同区域边界、黄色是线状中心、红色是保留旧候选，均不作为缺陷真值。

## TJ 独立参考入口

优先读取当前修正源结果 [黄金动作](D:/FPGA/XDL_Results/2026-10-14_software_controller_07/golden_actions.json)、[逐帧整数指标](D:/FPGA/XDL_Results/2026-10-14_software_controller_07/frame_metrics.json)、[完整动作与历史](D:/FPGA/XDL_Results/2026-10-14_software_controller_07/decisions.json)。每个golden记录保留input与独立expected，验证完整state和Decision，包括四个预期ValueError拒绝；拒绝不被伪造成采集失败。默认仍为15个构造场景/42转换/四拒绝，总147完整转换，新增最终回归单列于tests，不任意改变黄金库存。

以下只读命令独立生成并核对15个构造场景/42转换，同时打印新增位宽契约，不写任何文件、不连接硬件：

```powershell
& 'D:\FPGA\XDL_Algorithm\.venv\Scripts\python.exe' -B -c "import sys,json; sys.path.insert(0,r'D:\FPGA\XDL_Software_Controller'); from replay import constructed_validation; from fpga_reference import verify_reference,bit_width_contract; cases,actual=constructed_validation(); print(json.dumps({'verification':verify_reference(cases,actual),'bit_widths':bit_width_contract()},allow_nan=False))"
```

核心接口：scalar_metric_reference(gray,residual_n,rgb_max,mask)独立逐点对照；reference_transition(snapshot,event,config)独立规则转换；verify_reference(cases,actual)比较全部序列化字段；bit_width_contract()输出累计/交叉乘积量程。PC connectedComponents、旧质量百分位和浮点组件诊断不属于首版板端决策必须实现的算法。此交付没有RTL、资源/时序达标或物理闭环声明。

本轮只在本地交付。未经后续明确上传要求，不操作XDL远程分支/PR15，也不合并main。
