# 0106独立SDK：软件接入与验收边界

2026-10-25，r3.5补充：独立[0106操作人CLI与整轮归档](OPERATOR_USAGE.md)已接入并通过22项新软件检查；真实硬件门槛仍阻断。本页其余SDK验证为r3.4原证据。`sdk_transport.TransportExecutor`新增真实UDP网络执行库；本次只连接127.0.0.1软件设备，不是实板0106验证。原0105 SDK、09和638文件备份均未改动，旧0105固定八图CLI继续独立保留。

## 实现及源码对应

`generate_sdk_base.py`读取SHA固定的0105 SDK，输出`derived_sdk/acquisition_executor_0106_base.py`与变化清单。保留端点互斥、序号不重用、换端口/nonce、相机/ROI设置与回读、mask逐ACK及CRC封口、等待、超时/取消、退役、失败成本与隔离路径。原文件不改写。

派生基类只提供生命周期；公开网络类覆盖0106控制解析、能力/格式协商、严格接收及归档，并补充全部传输字段的稳定性比较。不是仅放宽旧固件白名单，不支持compat或0105回退。导入模块不创建socket。

请求先核对0106状态，绑定新nonce，再按本次协议查询能力、选择格式并再次查询；采集前还复核一次格式。FORMAT_SET是有不确定完成风险的状态修改，重试使用完全相同字节和seq；没有ACK即不启动CAP，执行器进入需要恢复状态。一次SDK实例的请求格式固定，数据集不在中途切换。

现有RTL在SESSION_BIND后清除valid和request_counter，**可能保留上一轮的无效identity及描述字段**。SDK此时只记录绑定ACK及计数清零，不声称读回了新nonce；首个CAP的实际身份必须匹配本次session/request、ACK frame_id、相机/ROI读回和固定参数。每次捕获前的计数须匹配本执行器拥有的计数。对应原始RTL包见[兼容性核对](verification/SDK_RTL_COMPATIBILITY.json)，包含独立发送命令清单的SHA；软件重连场景专门保留旧无效快照测试。

## 最终核验与原始数据

图片包收齐仍为provisional。执行器等待valid，再以独立seq查询第二次快照；相机原寄存器/代际和ROI再次读回后，第三次独立查询必须仍相同。三次的identity、bank、参数、ROI、H1/H2、RGB CRC、valid/error/mask/wait/FIFO，以及pixel_format/payload_bytes/payload_crc64都纳入稳定性比较。

最后用实际第三次查询的原包、实际发送seq及可信请求上下文调用StrictReceiver，重新检查真实负载CRC、完整DDR读数、等待计数和gray/SAT重算H1/H2。归档meta对象、原包和metadata_query_seq三者一致；不再保存第一次对象却附第三次原包。

`CaptureResult.raw_payload`是实际回传负载，`.validated`保留严格校验后的gray/SAT、原负载和原元数据包，可进入现有`fixed_eight.validate_eight`。不提供把灰度伪装成RGB565的兼容属性。

| 格式 | 实际负载与显示 | 共同保留 |
| --- | --- | --- |
| 1 RGB565 | `image.rgb565`、彩色`image.png` | `image.gray8`、`image.gray.png`、`image.sat1`、`image.sat.png` |
| 0x31 GRAY+SAT | `image.gray_sat`、灰度`image.gray.png` | 同上，不创建伪彩色`image.png`或`image.rgb565` |

`image.sat1`是**整平面**row-major位打包、bit7先，尾部低位补0，长度ceil(N/8)；它与线上8gray+1SAT的交错负载是两种清楚标记的布局。原负载字节完整保留。另存`metadata_packet.bin`、`board_mask.bin`、带查询seq及原回复字节的能力记录、各文件SHA、完整publication/相机读回/参数、源码与候选绑定、命令trace和实际成本。GRAY下RGB CRC仍保留原RGB语义，不能用灰度CRC替代。

成功目录原子发布，沿用冻结的Windows有限发布重试；不重新采集。若发布后最终检查失败，转入quarantined，结果改为provisional/FAILED，不留下被当作成功的committed目录。未知完成、错误或取消时保留outcome/trace与退役状态，未知物理成本不写0。

## API与软件复现

依赖现有Python、numpy、opencv和仓库相邻冻结依赖。在本目录运行：

```powershell
python -X utf8 -B generate_sdk_base.py
python -X utf8 -B run_sdk_verification.py --out verification/sdk_new
```

输出目录必须全新。验证程序强制socket绑定、连接和发送仅允许127.0.0.1；软件设备明确记录software_udp_peer。35项测试及源SHA见[最终凭证](verification/sdk_final_01/verification.json)。测试里的32/96像素模拟传感器仅作为明确的仿真钩子，real_board构造拒绝非1920×1080钩子。

执行器构造是显式网络动作。真实板调用除固件/能力检查外，须提供`candidate_binding`，含`candidate_source_commit`、实际存在的`bit_path`及匹配`bit_sha256`；当前期望RTL源码提交为`46f9d50`。这是调用方提供并由SDK校验本地文件的绑定，**不是板上bit SHA读回，也不是SDK独立证明该bit编译来源的凭证**。后续宿主还须核对对应构建、资格记录和实际候选文件，并在构造前取得现有operator_lock；本轮没有候选bit，不会构造实板连接。

每次调用前后检查SDK、严格解码、派生基类、整数参考、实际载入的协议源码等SHA；真实候选bit文件也在绑定中复核。可执行源码变化则拒绝或隔离结果。绑定与底层协议源码不是缺陷标签或检测质量证明。

批次宿主应在finally中显式调用`executor.lights_off()`并保存返回值，最后close；SDK不会将close等同于实体关灯。lights_off占用同一端点锁，独立记录命令、重试、ACK及成本；缺ACK不声称已关灯，也不清除之前未知完成造成的poison状态。底层close继续只关闭自身socket，不能关闭其他客户端。

## 测试范围与剩余工作

已验证双格式完整网络采集/文件对应、同一固定**软件输入**的gray/SAT等价、8请求/固定八图合同/mask复用/帧号及控制序号回绕、重连旧快照、版本/能力/seq/格式拒绝、FORMAT_SET未知完成、第二/第三次描述变化、负载CRC与H1/H2错误、缺包/冲突/乱序/重复、原相机/ROI后验、取消/未知退役、发布失败隔离、源码变化与关灯缺ACK。

没有实物新图、训练收益、置信度校准或新bit。SDK的同输入软件比较不能替代同一冻结输入的实板双格式诊断，也不能要求两个独立新DVP帧因噪声仍逐像素相等。

0106操作人宿主与完整批次打包现已接入，详见上述r3.5入口（0105独立CLI继续保留）；离线冻结字节核对也已实现。受控冻结输入实板诊断、窄时序余量、外部IO和CDC/DRC资格审查仍待完成。只有相应准入完成后才给YMW最小烧录/实物清单。XDL继续固定1倍、LED128的曝光选择/标注/训练，不等待灰度bit；400/800仍是合同和开发候选。
