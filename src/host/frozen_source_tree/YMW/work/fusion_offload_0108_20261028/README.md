# 0108独立部署：保留现用模式，逐步下沉核心计算

用户于2026-10-28授权开始新的FPGA部署，并要求保留目前满意的检测效果。TJ独立负责置信度，本目录不修改他的实现。现用09、0107、r5.6采集入口和独立检测入口均不切换。

本目录是**正在实现的新候选，不是已完成整板部署或可下载固件**。本阶段完成的是H2到DDR的写入、八帧DDR融合、组事务和PC结果解码；真实MIG仲裁、板级控制/网络协议、质量表上传与板端精确质量判定仍待接入。已完成与待完成以[STATUS.json](STATUS.json)及[VERIFICATION.json](VERIFICATION.json)为准。

## 保留什么，什么条件才允许切换

固定400/800行、gain16=16、LED128及原B1数学定义。低高曝光/四方向按最大有效绝对响应融合，保留符号和最早来源；严格`abs(R_n)>648/1620`。上位机继续在**整个保存ROI**做8邻域强弱连接，再与board相交。不得提前丢弃board外、阈值下或单曝光独有证据。

算法参考：XDL固定提交`8c697e86954270714d7ea45146d1e8f4bf262355`。数学不等价时先修实现、地址、有效域与事务，不调阈值掩盖差异。新模式的验收要求同一冻结输入的响应、来源、unknown、weak/strong、连接结果和最终mask逐像素一致；随后才做新bit的最少实物验证。

旧模式备份：`E:/GuangjianData/backups/before_0108_20261028/working_mode_before_0108.zip`，2188个文件，解压前字节总量33,822,595。包内成员已逐SHA256验证；归档SHA256为`1fe1622edf1da84616e9e117b5046a6903f75d69d7b2762dab58a53eec4e0bb9`。同目录有完整`BACKUP_MANIFEST.json`、恢复说明、Python包版本。原始采集/检测数据仍在E盘原位，Python虚拟环境原位保留；不把这份程序备份说成整盘或全部原始数据备份。

旧源码基线`ca70dafe9b15432be68823aecef91e6d54bfac31`；0107 bit仍为`4d1545266f83a6eb52327e4863658fa465448c04572b595cbe6dbc482850a01b`。09另需它原来的0105 LAB bit，不能与0107协议混用。没有改原启动器或要求用户重下旧bit。

## 已实现的计算与事务

| 文件 | 实际职责 |
|---|---|
| `rtl/h2_scratch_writer.v` | 接原H2的R16、gray、精确valid；64像素缓冲、128位AXI突发，正确尾部WSTRB；等H2成功和全部B应答后才提交scratch |
| `rtl/maxabs8_pixel.v` | signed残差扩位取绝对值；最早槽位并列优先；有效零响应仍保留非零来源；严格阈值和32位结果打包 |
| `rtl/fusion_axi_frame.v` | 每次处理一个已提交帧；突发读scratch/旧状态，四像素并行更新，写非活动bank；全部B应答完成才报告成功 |
| `rtl/fusion_group_guard.v` | 绑定组ID、128位配置摘要、几何、请求及1～8槽顺序；逐帧成功才换bank，完整八槽才发布整组；旧结果需匹配释放 |
| `host/result_codec.py` | 严格校验32位结果字段；原上位机B1连接后再裁board，恢复原有10项结果字段 |
| `host/prepare_quality.py` | 过渡版离线生成精确32×32 tile表并绑定原帧身份/哈希；**没有冒称板卡已支持上传命令** |

H2原模块与RGB565灰度转换直接复用TJ已冻结源码，没有改其灰度、9×9反射边界或残差单位。融合核心与写入模块的组合路径经综合发现问题后已增加寄存级/预存字节使能；不是放宽时钟或改数学。

第一阶段质量表仍来自冻结PC规则。不能将其写成“上位机已经只做连接”或“FPGA已完成质量判定”。最终目标才是在严格等价验证后将精确tile质量下沉；SAT1不作为额外一票否决。

## 当前内存与结果约定

建议共用MIG UI时钟域运行新算法和AXI主机，控制描述符通过已验证的CDC机制传递。**当前模块没有跨时钟接口，不允许直接把125MHz net域信号接到异步MIG AXI。** 单独125MHz实现检查也不是实际整板时钟/IO资格证明。

本机固定MIG配置是`TimePeriod=2500ps`、`PHYRatio=4:1`，旧0107时序报告的`clk_pll_i`为100MHz；旧网络域则为125MHz。新算法拟接MIG UI域，不能把这两域直接等同。本轮8ns/125MHz是独立模块的较严检查，没有修改原系统时钟。OOC的时钟来源、接口预算和上层上下文需单独核验，参见[AMD OOC约束说明](https://docs.amd.com/api/khub/documents/Z2EXIopH3XyqVKZTNw53kQ/content)和[时钟延迟建模说明](https://docs.amd.com/r/en-US/ug1387-acap-hardware-ip-platform-dev-methodology/Clock-Latency-at-the-Source)。完整OOC端口hold不通过时仍记录为未通过，不能只展示内部路径的正裕量。

| DDR字节范围 | 用途 |
|---|---|
| 0～4MiB、4～8MiB | 保留现有两个raw bank地址 |
| 8～16MiB | fusion0，32位/像素 |
| 16～24MiB | fusion1，32位/像素 |
| 24～32MiB | 本阶段scratch，32位/像素 |

scratch字：bit0～15为signed R_n，16～23为gray，24为精确valid，25～31保留0。最终字：bit0～15为signed R_n，16～19来源0/1～8，20弱、21强、22～29选中来源gray、30～31保留0；均按低字节在前落盘。source=0必须全字为0，代表unknown。

本阶段为保存gray和valid采用32位scratch，因此概念布局从前期R16暂存评估的28MiB变成32MiB，新增4MiB来自外部DDR，不是BRAM。该布局尚未接入真实MIG，也尚无新DDR带宽实测。八张原图长期留档、TJ额外证据、方向中间图和上一组额外快照必须另计，不能用两bank假装无限保留。

AXI目前为128位、最多16 beat、4KiB对齐的独占帧更新。所有写应答都返回后才交换状态。取消保留已经assert的VALID并排空已发行事务；超时/ID/长度错误要求公共AXI fence/reset，不能复用仍可能接收旧写入的地址。该责任必须在新板级控制器中落实，不能仅复位本地状态机。

## 验证与复跑

测试大文件/日志/检查点放在`E:/GuangjianData/fpga_0108_20261028/`。仓库只发布源码和小型验证凭据。

使用现有项目Python，下面每个`--out`必须为不存在的新目录：

```powershell
# $python指向原项目.venv_demo/Scripts/python.exe
& $python -B YMW/work/fusion_offload_0108_20261028/make_vectors.py --out E:/GuangjianData/fpga_0108_recheck/vectors
& $python -B YMW/work/fusion_offload_0108_20261028/run_fault_rtl.py --vectors E:/GuangjianData/fpga_0108_recheck/vectors --out E:/GuangjianData/fpga_0108_recheck/faults
& $python -B YMW/work/fusion_offload_0108_20261028/run_real_rtl.py --vectors E:/GuangjianData/fpga_0108_recheck/vectors --out E:/GuangjianData/fpga_0108_recheck/fusion
& $python -B YMW/work/fusion_offload_0108_20261028/run_h2_rtl.py --out E:/GuangjianData/fpga_0108_recheck/h2
& $python -B YMW/work/fusion_offload_0108_20261028/host/test_result_codec.py
& $python -B YMW/work/fusion_offload_0108_20261028/run_synthesis.py --out E:/GuangjianData/fpga_0108_recheck/synthesis
```

真实输入读取终版400/800冻结清单中的003、004、005本机结果，未使用007～010，没有新拍照片。XSim的DDR/FIFO边界是模型，原H2与新计算/控制模块是真实RTL；不把模型PASS写成实板PASS。完整原图、NPZ与源数据未重复上传GitHub，异机复跑需要先取得索引所指的原始文件。

后续直接按[NEXT_IMPLEMENTATION.md](NEXT_IMPLEMENTATION.md)接入整板。现用程序继续使用；新候选完成同输入实板对照、资源与内部时序门槛后才提供独立新bit验收入口。
