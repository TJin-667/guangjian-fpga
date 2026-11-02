# 独立0105固定八图宿主

`paired_host.py`使用现用0105 RGB通路，不依赖新灰度bit。计划命令只读文件；capture命令由操作人显式执行才会连接板卡。未把新宿主加入现用09，也没有自动运行实体采集。此文是软件使用说明，当前还不是已通过现场验证的发布单。

## 计划与来源复核

以下命令在本目录运行，使用带numpy、opencv的现有Python；Windows原环境需用现有CMD中记录的Python解释器替换`python`。源码和相邻依赖保持仓库目录结构。

```powershell
python -X utf8 -B paired_host.py prepare --lab-root C:/BX72_0105_LAB --low 400 --high 800 --physical-specimen-id sample005 --pose-id pose005_pair_trial01 --pair-status development_trial --pair-reference "development candidate only; not an XDL frozen optimum" --out C:/BX72_pair_plan_new
```

这个例子是候选曝光，不是最优值。使用已存在的本轮02完整图和最新03确认，核对原严格实拍记录、样件/ROI/mask、原相机参数、PNG/raw SHA、bit/runtime/SDK/vendor来源。最新失败来源不回退到旧来源。只有仍为同一工件、同一摆放时，已有02/03才继续有效；本软件无法从文件验证眼前摆放是否移动。

输出`plan.json`和从同一已核验快照生成的`source_preview.png`。先核对样件编号、物理工件ID及预览轮廓。physical_specimen_id用于按实物划分数据；005的v0/v1应沿用同一物理ID，pose_id只区分本轮摆放，不能增加独立工件数。初始02/03不算这次低高曝光八张观测。

## 显式启动与输出

操作人确认工件、相机和灯位仍一致，检查预览并关闭预览/其他采集客户端后，才执行：

```powershell
python -X utf8 -B paired_host.py capture --plan C:/BX72_pair_plan_new/plan.json --out C:/BX72_0105_LAB/results/fixed_pair_sample005_new --confirm-same-pose
```

输出路径及同名ZIP/附件必须均不存在。命令先重新构建计划，再取得与现用07/08/09共用的operator_lock，持锁后再次复核来源；随后才创建真实严格SDK。顺序固定为CH1低/高、CH2低/高、CH3低/高、CH4低/高，1倍增益、LED128、1等待+3丢弃。不自动寻曝、补拍或重新执行失败观测。SDK幂等控制包重试仍保留实际成本。

默认采集阶段预算360秒、单次60秒；包括持锁复核、SDK初始化、八请求、关灯/关闭、后端封档。初始主机预检和最终ZIP时间另计；ZIP receipt记录从这次capture开始到验证归档发布的主机时间。更早02/03的成本不包含其中，不能把八张正式图的40个已验证事务帧当成总传感器帧数。

每张保留raw RGB565、PNG、SDK原结果、可信publication和独立CRC/H1/H2检查；所有SDK命令、失败与退役日志归档。02/03的原图、几何、mask和记录也以已核验字节快照保存。退出时保持锁直到关灯ACK与SDK关闭。Ctrl+C走取消和清理分支；ACK只表示协议确认，尚不表示实体灯光状态经观测确认。

结束生成目录、ZIP、`.zip.sha256`和`.zip.receipt.json`。沿用现有冻结归档器，重新读取ZIP逐文件验证；失败时保留原目录，不覆盖同名结果。外层`output_manifest.json`覆盖完整最终包，包括后端manifest/completion及SDK子日志；后端manifest只描述后端完成时已经存在的文件。

状态`ACQUIRED_EIGHT_REVIEW_REQUIRED`表示八张均通过采集数据合同、来源未变化、关灯已ACK并已归档，仍需看真实图像。失败/取消包也会保存证据，其status不作为可训练的完整配对组。保存八张不代表融合/检测准确率或曝光最优已经验收；physical_freshness_verified、外部IO资格和融合质量标志保持false。

## 已验证与后续

25项本目录检查由13项后端检查和12项宿主检查组成。宿主包含原SDK在明确127.0.0.1设备上的完整八图和第五次CRC错误分支；测试套件阻止非回环socket绑定/发送，没有连接192.168.0.2。现场相机噪声、曝光效果及实板新流程仍未验证。

0106的真实SDK协商/归档、同一冻结输入双格式实板诊断和外部IO资格审查继续独立推进。本CLI可先承接现用0105的配对数据准备。操作人尚未收到XDL冻结值时，候选组必须保留development_trial标签，不自行标记XDL_frozen。
