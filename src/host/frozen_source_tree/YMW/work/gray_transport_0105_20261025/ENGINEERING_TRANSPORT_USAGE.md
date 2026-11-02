> 本页小ROI操作已由YMW于2026-10-26 01:26完成并通过，以下保留当时方案。**不要再运行小ROI入口。** 最新证据和下一步一次全幅入口见[真实负载复核](REAL_TRANSPORT_REVIEW.md)。

# 0106首次真实双格式负载检查

2026-10-26。YMW运行新bit只读检查后，00:56:44（北京时间）的3份回包已独立重解码：固件0x0106、ready、busy=false、error=0；声明RGB565与GRAY8+SAT1、1380字节包负载及实际负载CRC64。见[握手凭证](verification/board_handshake_20261026_01/verification.json)和[原始记录](verification/board_handshake_20261026_01/raw/new_0106_check.json)。不用重复旧0105状态或重新下载未改动的bit。

## 这次检查内容

独立工程入口 `engineering_transport_check.py` 使用现有严格0106 SDK，固定RGB、GRAY各1次CAP；每次分别设置相机/ROI、绑定新session、检查参数读回、实际负载CRC64、完整帧身份、最终metadata与H1/H2。每次finally关灯并关闭socket，共享OS锁在全程持有，任一失败停在当前阶段，不自动补拍或进入另一格式。

两次是逻辑采集请求及最多两张保存图，不是传感器总帧数；设备仍执行settle/discard，同序号协议重发及实际成本由SDK逐次记录。

| 设置 | 固定值/意义 |
| --- | --- |
| ROI | [896,496,81,21]，仅诊断窗口，不是物理板分割或训练标签 |
| 掩膜 | 该ROI内全1；不评价划痕 |
| 相机/灯 | 600行、1倍、CH1、LED128，settle1/discard3 |
| RGB565 | 1701像素，3402字节、3包 |
| GRAY8+SAT1 | 1914字节、2包，覆盖不足8像素的尾部padding |
| DDR排空 | 每次仍要求1920×1080完整帧读数 |

以上参数只服务工程发送链路检查，不作为XDL的正式曝光对或训练采集指令。相机和灯保持连接，画面可有任意内容，不要求换/重制工件。RGB和GRAY是两个新DVP帧，存在噪声差异；每帧各自与其板上H1/H2对应，**不宣称逐像素跨格式等价**。同一冻结硬件输入的双格式质量验收仍待完成。

这项工程检查有固定的bit/SHA/握手证据、受测源码和2次CAP上限；没有修改 `operator_host.py` 的正式八图发布资格、现用0105程序或09。`release_ready=false`、外部IO/复位/CDC缺项和窄setup余量保持；通过小ROI检查也不直接放行完整检测。

## YMW一次执行

1. 保持当前0106板卡通电，关闭旧09/预览/其他板卡客户端；没有断电就不用再次下载bit。
2. 临时断开Cisco，在本机双击 `C:/BX72_0106_EXPERIMENT/20261026_transport_check01/03_check_RGB_GRAY.cmd`。本地程序不依赖Codex在线；等显示RESULT DIRECTORY后恢复Cisco。
3. 回复“双格式检查完成”。助手直接读取 `C:/Users/yue/Documents/Guangjian0106Transport/` 最新结果，不要求截图/手工上传。

若板卡已断电，RAM中的实验bit会失效，应仅重新下载原0106候选后执行。程序遇到非0106、CRC/H1/H2/参数错误、OFF缺ACK等情况停止，保留所有成功/失败原始记录；不用反复点击直至通过。0106运行时先不开旧0105的09；恢复正式0105采集前仍使用原LAB bit。

成功状态为 `ENGINEERING_TRANSPORT_VERIFIED`，表示两帧负载各自通过工程验证。保存每帧原payload、gray/SAT、PNG、最终metadata、trace/outcome、SDK配置、源码/bit绑定、关灯结果和逐成员核验的ZIP。原SDK记录中的旧 `hardware_tested=false` 不覆写；实际本次物理结果由外层证据另作判断。

## 新入口验证

[8项受保护回环检查](verification/engineering_operator_01/verification.json)通过：双格式真实字节及ZIP、首帧CRC失败停采、灰度CRC失败保留RGB、H2错误、OFF失败、源文件变化、旧固件拒绝、保存SAT被改。网络只准127.0.0.1，不是实板照片。真实计划准备在禁止创建socket的条件下通过，正式生产入口仍blocked。

首次外层prepare因原只读记录尚未拷入约定raw目录而失败；8项测试本身全部通过。补齐原字节后独立重做无socket准备及门槛检查通过，没有为此重跑未变测试；原问题另记于 [initial_prepare_failure.json](verification/engineering_operator_01/initial_prepare_failure.json)。

打包时Python子进程的Windows PowerShell环境未提供Get-FileHash函数，前两次只读准备日志保留。启动器改用.NET SHA256核对同一批来源，不改变或放宽哈希门槛；[最终准备凭证](verification/engineering_prepare_03/verification.json)与本机入口CheckOnly均通过，638个原软件文件未变。
