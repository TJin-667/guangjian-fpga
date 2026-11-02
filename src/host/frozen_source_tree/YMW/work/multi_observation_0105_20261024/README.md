> **会后任务已更新**：先读[SCOPE_AFTER_MEETING.md](SCOPE_AFTER_MEETING.md)。以下保留10月24日实现范围，当前采用固定八图双曝光；不执行旧六图/最小补拍计划。

# 独立多观测采集实验版

2026-10-24，YMW。基础归档 `5fc156aa52771ba0f5f17d8f1e78b81858c71500`；XDL最新交付仍为 `ee34ff2f80fe9747c3afcb991a5e28506a78c5d1`。本目录仅新增电脑侧实验代码；现用06/07/08/09、冻结SDK、RTL、bit及原始数据均保持原状，没有安装或启动新在线程序。

## 已实现与验证范围

- 独立观测ID和文件目录，保留action/attempt/call/session/request/config/帧身份，允许重复方向和超过4个观测；base/probe/confirm/supplement分别记录。四方向base覆盖才允许STOP，正式supplement最多2张。
- 每请求自己的曝光、灯、ROI/mask绑定；1倍/LED128；软件实验档位400/500/600/700/800。gain16=32、3倍和LED搜索不准入。E800仅通过本轮软件契约测试，没有新增严格实物采集凭证。
- 校验原始曝光/增益/手动模式寄存器、请求/实际参数、可信SDK发布快照、保存PNG/raw实际哈希、包数、CRC64、逐像素解码、H1和直接81项求和H2。统计滤波域为整张保存ROI，沿用冻结整数灰度和648/1620严格阈值。
- 16位frame_id及相应32位计数器模前进；config/camera/light generation可以在同参数确认时不变，仍须与该请求可信SDK快照一致。跨session需显式重新建立上下文，当前拒绝自动拼接。被拒绝图的可信新身份仍更新水位，不能在重试时重新接受它。
- 单次逻辑请求最多一次同参数新请求重试；失败仍占请求和预留事务帧预算。初始化、策略分析、像素校验、图片保存、退出、归档都计入整次时间；预留退出时间。失败的未报告成本为unknown，预留5帧不冒称实际全部DVP帧。
- 可运行SDK接口适配器接收调用方明确提供的严格executor，核对冻结源码和独立发布快照。没有创建板卡连接的CLI/GUI。SDK接口形状经stub验证，尚未执行真实SDK在线采集。
- XDL策略接口为 `reset / consume / next_action / finalize`。当前仅提供scripted_offline动作注入，便于检查执行链。选参分数、局部质量/极性证据及多曝光融合仍由XDL后续参考实现对齐，未用无条件OR或跨参数MaxAbs代替。

最终离线套件：**52项测试通过**，其中有8个手写动作序列场景，错误字段组合另用subTest覆盖。测试禁止任何socket创建；SDK端口测试只运行stub，未实例化真实SDK。凭证见[verification/final/offline_tests.json](verification/final/offline_tests.json)与[完整测试输出](verification/final/unittest.txt)。

历史兼容复核：003的四方向600行、004的四方向500行，共8张真实历史保存图全部通过新逐请求校验器的PNG/raw、CRC64、H1及H2直接81项复算。这些图仅标为archive_replay，没有充当新请求后的图，也没有证明新逐方向策略或融合收益。见[003复核](verification/final_sample003_E600/archive_replay.json)、[004复核](verification/final_sample004_E500/archive_replay.json)。

## 模块入口

| 文件 | 用途 |
| --- | --- |
| `multiobs/contracts.py` | 上下文、参数档位、请求、观测集合、身份位宽、预算 |
| `multiobs/validation.py` | 单个严格已提交观测的实际字节/读回/整数统计核查 |
| `multiobs/ports.py` | 接收已显式创建的冻结SDK executor；从SDK发布状态获取请求绑定 |
| `multiobs/runner.py` | 逐请求、重试、总预算、取消、退出与归档；调用外部策略 |
| `demo_offline.py` | 生成可查看的software_fake多观测包，仅离线 |
| `replay_archive.py` | 读取已知SHA的原09 ZIP，以历史证据导入新容器 |
| `tests/golden_actions.json` | 8个执行层动作序列；决策为人工注入，不是图像策略黄金结果 |
| `XDL_INTERFACE.md` | 交接字段、API和下一步接入边界 |

依赖Python3.11.4、numpy1.26.4和opencv-python4.10.0.84，现有环境已具备。H1/H2纯参考从相邻的 `inspection_console_0105_20261022/vendor/software/ymw_integer_reference.py` 只读加载，校验固定SHA256；不需要拷贝或替换现用09。代码应保留在当前仓库目录结构中运行。

## 运行离线检查

在本目录运行。输出必须选择不存在的新目录，保留以往记录；下面的`recheck`与`demo_new`为新目录示例。命令不会创建板卡连接。

```powershell
$taskPython = 'C:/Users/yue/.codex/.chatgpt-projects/g-p-6aacf33115048191845c3025390bb3cd/output/BX72_FourLight_ROI_20261012/.venv_demo/Scripts/python.exe'
& $taskPython -B run_offline_tests.py --out verification/recheck
& $taskPython -B demo_offline.py --scenario weak_segment_local_supplements --out verification/demo_new
```

历史004复核示例，使用已有原ZIP，不解压覆盖原目录：

```powershell
& $taskPython -B replay_archive.py `
  --archive 'C:/bx72_ymw_0105_20261015/repo/YMW/data/0105_inspection_20261023/sample004_A_v1_auto_round01/raw/inspection_online_sample004_A_v1_20261023_212937_2b2391.zip' `
  --sha256 b05252b37b4255b2bf7559709b0d7d90006103fa975f50e78bdcf3caa04430f0 `
  --out verification/replay004_new
```

## 输出和成本口径

每个已接受观测有独立目录：PNG、RGB565、SDK结果、观测描述和审计结论。总包保存 `native_mask.bin`、`context.json`、`observations.json`、`events.jsonl`、`report.json`、`manifest.json` 和最后的 `completion.json`。

`completion.json`是最终状态/预算凭证，包含report及manifest实际哈希；manifest覆盖此前全部归档文件，自身和最后凭证除外。最终计时点覆盖report/manifest写入；最后时间凭证自身的写入未计入自身记录，明确保留此边界。超过整次时限、关灯未ACK或退出异常不会作为成功结束；安全退出仍会尝试执行，超限如实报告，不藏掉开销。

`report.budget.calls`按每次attempt保存SDK原成本；accepted/rejected都记录。相同图像哈希不自动判旧帧：静止工件的真实新帧可能字节相同，应以完整可信身份链和请求绑定裁决。关灯ACK仅表示指令确认，`physical_off_verified`始终false。

## 接续与实物边界

接下来以XDL冻结的选拍/局部质量/融合接口接入上述策略入口，继续004已有数据和错误分支验证。本目录没有自动选参或融合效果的验收结论，也不把质量冲突/无候选停止的注入场景写成实际算法判断。

未来在线宿主还需接上原02/03来源快照校验、用户同姿态确认、现用operator_lock、SDK创建/退出和界面；宿主必须在计时器启动后初始化，并保留原09回退。当前尚无新在线入口，先不发布实物采集清单。待XDL规则与必要未知量明确后，只给有样件/方向/曝光/重复数/预算/判据的最小清单，不执行旧16＋至少12张全扫描，也不因缺少派生图重拍。
