> 本页提出的全幅操作已完成并通过，见[全幅复核](NATIVE_TRANSPORT_REVIEW.md)。**不要重复运行03或04。** 下文保留r4.1阶段记录。

# 0106真实双格式小ROI已通过，全幅工程检查待执行

2026-10-26 r4.1。用户01:26的实板结果为 `ENGINEERING_TRANSPORT_VERIFIED`；两次逻辑CAP分别收到RGB565与GRAY8+SAT1，源码/bit绑定、相机读回、完整身份、最终metadata、实际负载CRC64、H1/H2和归档核验全部通过。见[独立复核凭证](verification/real_transport_20261026_01/verification.json)及[原始ZIP](verification/real_transport_20261026_01/archive/20261026_012615_2d0ad3.zip)。不是回环模拟数据。

| 真实小ROI结果 | RGB565 | GRAY8+SAT1 |
| --- | --- | --- |
| 诊断ROI | [896,496,81,21] | [896,496,81,21] |
| 图像负载字节 | 3402 | 1914 |
| 完整包数 | 3/3 | 2/2 |
| 丢包/重复包/外来包 | 0/0/0 | 0/0/0 |
| 命令重试/CAP传输 | 0/1 | 0/1 |
| FIFO排空像素 | 2073600 | 2073600 |
| gray_sum | 230380 | 230345 |
| H2 sum9_total | 18660629 | 18655650 |
| H2 residual_n_total | 151 | 2295 |
| 关灯命令ACK | 成功 | 成功 |

ROI共1701像素；灰度保留原饱和位后负载减少43.73898%，不含UDP头、控制命令、mask上传或磁盘PNG。两帧间DVP序号27682→27698、publish序号1→2、frame_id1→2，分别在新session中采集。灰度值不同符合两个新相机帧的性质，不能拿它们相减作为同一输入的等价证明。

助手离线从原字节独立实现CRC64、RGB565整数灰度/SAT解码、GRAY/SAT交错解码及9×9反射域81个移位求和，再核对H1/H2、保存平面和ZIP全部30个成员。原ZIP47905字节，SHA256 `dbf5c88b79db66a0feffff69e271dc5afa874624edcf185c52fcf860db7202b0`。执行器计时阶段2.297秒，至核验ZIP为2516毫秒；这不包含启动及来源预检，不是完整系统耗时。

本次覆盖奇数SAT尾组，但两帧SAT、near_black和near_white计数均为0。关灯有协议ACK，物理熄灯未测量。全1诊断mask不是板分割、标签或训练mask；未评价划痕识别质量、融合增益或置信度。独立复核器还有[7项离线检查](verification/native_prepare_01/verification.json)，包含CRC已知向量、颜色/SAT位序与非法尾位，以及全幅纯白H2超过32位的求和；这些向量是软件检查。

## 下一步只执行一次全幅检查

沿用相同0106 bit和严格SDK，仅将诊断域改为原生1920×1080，固定600行、1倍、CH1、LED128、settle1/discard3。RGB和GRAY各1次逻辑CAP，仍非训练采集。RGB负载4147200字节/3006包，GRAY+SAT为2332800字节/1691包，理论负载减少43.75%。每帧均须最终CRC、H1/H2、参数及身份通过，任何失败停止，锁内关灯并close、保留归档。程序不自动补拍。全幅有机会覆盖非零SAT和明暗分布，实际覆盖情况仍要读结果判断。

1. 保持当前0106和相机通电、现有工件不动，关闭旧09及其他板卡客户端；未断电无需重新下载bit。
2. 临时断开Cisco，本机双击 `C:/BX72_0106_EXPERIMENT/20261026_native_check01/04_check_full_RGB_GRAY.cmd` 一次。全幅每个session上传64800个mask字，可能数分钟；等最终RESULT DIRECTORY及退出码，不重复点击。每帧含配置与上传的超时上限300秒。
3. 完成后恢复Cisco，回复“全幅检查完成”。助手直接读取 `C:/Users/yue/Documents/Guangjian0106Native/` 最新结果，不需截图或上传。

失败同样恢复Cisco并交回结果，不反复重试。若板卡曾断电，才需要恢复同一0106实验bit。0106期间先不开旧0105的09；返回0105正式采集前恢复LAB原bit。原638文件、现用/回退bit和备份保留。

## 资格边界与复现

小ROI真实灰度负载已验证；全幅负载尚待实板验证，同一冻结硬件输入逐像素跨格式等价、划痕检测质量、外部IO/复位/CDC资格仍未完成。正式八图宿主发布门槛保持阻断，`release_ready=false`。BRAM81.5/135=60.37%、LUT18699、FF22647、DSP4及内部setup/hold +0.003/+0.007ns不变。没有生成新bit或修改RTL/DCP，助手本轮没有发送实体板卡命令。XDL继续模型、采集单与置信度；YMW采集、TJ协助标注，不能用这两张诊断图充当低高曝光训练组。

从GitHub复核时，将archive中的原ZIP解压到同名新目录，并把ZIP及`.zip.receipt.json`放在解压目录旁；在现有项目依赖环境执行 `review_engineering_capture.py --run <解压目录> --out <新的凭证.json>`。该命令从归档重算，不开socket；依赖来源仍须与原计划哈希一致。机器绝对来源路径保留原记录，不改写原始身份或旧SDK中的历史hardware_tested字段。
