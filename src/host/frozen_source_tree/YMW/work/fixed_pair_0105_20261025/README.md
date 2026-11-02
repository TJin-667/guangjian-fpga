# 现用0105的固定八请求执行适配

2026-10-25，r3.3。为高低曝光融合准备固定八请求后端和独立CLI宿主，使用现用0105的严格RGB SDK，独立于0106灰度候选。不修改、不替换、不启动现用09。开发与测试未连接物理板卡。

`fixed_pair_runner.run_fixed_eight`按CH1低/高、CH2低/高、CH3低/高、CH4低/高执行，固定gain16=16、LED128、settle1/discard3。曝光显式传入并冻结在本轮，不自动寻曝、不补拍、不做整观测重试。SDK自身幂等控制报文重试仍记录在各attempt实际成本中。

调用方必须先使用现有02/03来源校验、提供同姿态确认及原生ROI/mask哈希，再提供取得现有operator_lock的guard_factory；只有持锁后才创建SDK端口，并保持到关灯ACK及SDK关闭。真实调用构造已有`multiobs.ports.SdkPort`，它核对冻结SDK源码和可信publication快照；不接受另写一个自称sdk_adapter的端口绕过该检查。`paired_host.py`已接入独立prepare/capture命令，尚无新GUI或真实板卡验证。

每次SDK返回均复核原寄存器、完整session/request/配置/帧身份、实际参数、mask、PNG/raw、CRC、H1及直接81项H2；允许同方向重复和相同像素的新身份。新目录保存八个独立观测、所有attempt成本、错误与未完成项，最后才写completion。第五张失败即整组失败，保留前四张并关灯/关闭；缺关灯ACK、超时、取消或源码变化均不作成功。实际未知DVP成本保留unknown，不把40个已验证事务帧写成总传感器帧数。

`development_trial`表示开发曝光试验，`XDL_frozen`须附XDL实际冻结依据；400/800只在离线测试中用作合同值，尚未认定最优。原600行四向005不能被标成此类真实低高组。当前仍保持完整RGB565，可供XDL解gray/SAT并保留颜色信息。

来源绑定必须明确physical_specimen_id，与sample/pose标签分开。同一005工件的v0/v1都归同一物理ID，不能因组名不同而增加独立工件数或分入训练、测试两侧。

13项离线场景见[verification/final_04/verification.json](verification/final_04/verification.json)：完整八图（包括绑定SDK子目录中的manifest/completion）、同像素不同身份、16位frame_id回绕、第五张失败、错误寄存器/旧身份、来源/姿态缺失、旧输出目录、取消、初始化计时、关灯缺ACK及非法成本。测试端口为software_fake且禁止socket创建，不是实物采集，不证明相机参数光学效果。

```powershell
python -B -m unittest -v test_fixed_pair_runner
```

主机接入的12项检查见[verification/host_02/verification.json](verification/host_02/verification.json)：真实02/03来源检查禁止socket；软件完整/失败归档；源码/来源变化；确认、旧目录与取消门控；冻结真实SDK在127.0.0.1模拟设备上的八次成功及第五次CRC失败停采。初轮测试传感器尺寸小于17×17偏移ROI，SDK正确拒绝INPUT_INVALID；只修正模拟传感器为32×32，保留[初轮日志](verification/host_01/unittest.txt)。没有用兼容模式或放宽SDK门槛通过。

使用步骤与状态口径见[HOST_USAGE.md](HOST_USAGE.md)。现用软件已另作[638文件备份](../../backups/20261025_before_fixed_pair/README.md)。目前没有安装新CMD、生成/烧录新bit或执行真实八图采集。待操作人确认摆放和开发曝光后，再做最小现场验证；XDL冻结值尚未收到，400/800仍为开发候选。

灰度候选尚未通过全部准入前，配对采集保留现用RGB通路；完整八张RGB纯图像字节数为原四张的两倍，不能按GRAY/SAT的112.5%口径计算。

真实端口factory应将原SDK output_root设为本轮out/sdk_calls，保留每条命令及失败退役日志；后端会核对该位置，SDK日志随整组manifest一起归档。
