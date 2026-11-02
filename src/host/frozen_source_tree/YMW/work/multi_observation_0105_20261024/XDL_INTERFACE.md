> **会后任务已更新**：先读[SCOPE_AFTER_MEETING.md](SCOPE_AFTER_MEETING.md)。以下保留10月24日实现范围，当前采用固定八图双曝光；不执行旧六图/最小补拍计划。

# XDL对接：多观测执行接口已具备，选拍和融合继续独立冻结

基础：ee34ff2及2026-10-24最新完整交接。现用09不变。本文件未发送给队友。

## 实际API

策略对象提供以下方法：

```python
policy_id: str
reset(context: Context, output_root: Path, profile: Profile) -> None
consume(observation: Observation) -> None
next_action(observations: ObservationSet, budget: dict) -> CaptureRequest | Stop
finalize(status: str, observations: tuple[Observation, ...], budget: dict) -> dict
```

`reset`建立固定样件/姿态/ROI/mask上下文及输出位置；`consume`只接收已通过逐请求审计、文件已保存的观测副本。可从output_root和相对files路径读取实际图像，计算局部质量和保极性证据。派生输出放独立algorithm子目录，以observation_id、源文件SHA、算法/配置SHA关联；在finalize返回JSON索引，执行器统一归档。consume不能更改执行器的有效观测历史。

`next_action`只能基于实际已接受观测、历史与剩余预算决策；不能输入人工划痕路径/编号/真值。`Stop('STOP', reason)`允许可靠无候选结束，但执行器仍核查四方向基础覆盖与退出ACK。`Stop('REVIEW', reason)`保留质量冲突等原因。finalize返回的算法报告不能覆盖执行器的预算或身份结论。

请求例：`CaptureRequest('unique_action', 1, 800, 'supplement', 'local evidence request')`。LED128/gain16=16固定。action_id每次逻辑动作唯一；一次失败重试沿用action_id，但attempt_id、SDK调用和真实新帧必须独立。base/probe/confirm/supplement均保留图和成本；同方向重复观测合法。

执行入口：`run(context, limits, policy, open_port, out, profile=..., cancel=...)`。默认只在软件fake中验证。`open_port`在总计时启动之后调用；工厂返回前若初始化失败，应由工厂清理已持有资源。返回后由执行器负责关灯与关闭。未来在线宿主负责SDK创建、原operator_lock、02/03来源和实物同姿态确认；当前没有在线CLI。

## 观测字段与融合边界

每个Observation记录：

- 独立observation/action/attempt/call ID；channel及direction；role。
- 实际绑定的exposure_lines、gain16、brightness、light_mask、settle/discard。
- session、request_id、config_epoch、dvp/publish、ROI/camera/light generation、frame_id。
- PNG/raw实际SHA与文件路径、来源evidence、执行模式；camera_readback、H1 statistics和H2 features。
- analysis中的quality/polarity/evidence目前明确为pending_XDL；不能冒称已有新策略分数。共享context给ROI、mask字节/SHA与物理样件/姿态身份。

融合必须按观测ID追踪来源，方向只是观测属性；同方向E400和E800既不能互相覆盖，也不能伪装成不同方向。来源表示应支持N个观测，不能沿用只有4方向的uint8位语义。基础图可靠证据、补充图可靠增量、冲突和unknown分别输出。这里没有实现OR或跨参数原幅值MaxAbs融合。

## 与ee34ff2规则的对齐

| 事项 | 当前实现 | 尚待XDL/联调冻结 |
| --- | --- | --- |
| 1倍/LED128、逐向独立请求 | 已支持 | 在线曝光档位；E800仅软件准入 |
| 同向多观测、4基础＋最多2正式补充 | 已支持容器/执行/成本 | 何时补、补哪档、哪些局部接受 |
| 同参数新帧确认 | 可请求并审计，成本独立 | 原草案额外2张是否保留及稳定判据；不能由执行器擅自删减 |
| 错回读/旧帧/缺帧 | 拒绝，最多一次同参数新请求重试 | 重置类故障必须停，不能不断重开session躲避 |
| config_epoch | 从该次SDK可信发布快照绑定 | 不把初次上下文epoch永久固定 |
| 帧水位 | 16位回绕/完整请求链；被拒图也更新可信水位 | 不接受普通大于或仅不等判断 |
| 选参分数 | 未新增 | 局部质量、背景代理、保极性证据及真实重复校准 |
| 总预算 | 参数显式必填、确认/失败/重试均扣预算，退出/归档计时 | 实机总时间与动作上限；测试的12请求/60预留帧/20秒是假时钟fixture，不是产品指标 |

旧A16＋B至少12扫描不是本接口默认任务。8个固定动作场景只验证执行语义，不是XDL新策略黄金结果。请提供新策略实现/配置/动作黄金序列后，再作同预算固定补拍和实物验收；没有净收益保留负结果和可靠09。
