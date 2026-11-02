> r4.2最新状态：[小ROI与原生全幅真实双格式传输已通过](NATIVE_TRANSPORT_REVIEW.md)，bit已生成且0106已上板。下文r3.5/r3.9为历史记录，其中“无bit/无实板”的表述不再代表当前。正式八图发布资格仍受同输入质量与IO/复位等缺项阻断，不能仅改状态字段放行。

# 0106独立操作入口与当前实板边界

> r3.9补充：[新0106实验bit](EXPERIMENTAL_BIT.md)已生成，`bit_generated=true`。正式八图入口仍受IO/CDC/DRC及发布资格阻断；本页r3.5关于“尚无bit/未确认0105”的记录仅描述当时状态。现用0105状态后来已确认，无需再做旧检查。新增工程只读入口为[RUN_NEW_0106_CHECK.cmd](RUN_NEW_0106_CHECK.cmd)，仅供新0106验证，尚无0106实板结果。

2026-10-25，r3.5。`operator_host.py`接入独立0106 SDK、固定四向低/高八请求和整轮ZIP。导入与prepare均不打开板卡socket，现用01～09、0105 SDK/bit及638文件备份保留。新入口在仓库中独立运行，没有覆盖安装或新增自动启动项。

## 当前可用范围

| 入口 | 已验证 | 当前限制 |
| --- | --- | --- |
| `board_probe.py` | 共享OS锁内只发STATUS_QUERY（命令3），按seq保留ACK/STATUS原包 | 实板两次无回复，固件版本未确认；不是采集或烧录 |
| `operator_host.py prepare` | 原02/03严格来源、同一快照预览、物理工件ID、姿态ID、固定曝光对、格式、完整计划SHA及源码/资格证据 | 旧02/03只作明确标识的0105历史定位来源；不是0106新图，使用前必须确认当前同件同姿态 |
| `operator_host.py capture` | 准入校验、共享OS锁、独立0106 SDK、逐帧原始数据复核、固定八图合同、关灯/关闭、整轮归档 | 当前0106资格为blocked，实板调用在socket创建前拒绝；仅回环设备走通全流程 |
| `frozen_diagnostic.py` | 冻结RGB字节与返回RGB/GRAY+SAT全像素、SAT、H1/H2一致及异常拒绝 | 只验证离线字节，不会冻结板上DDR，也不证明两次网络回传属于同一硬件帧 |

22项新增软件检查全部通过，其中17项宿主/只读查询与5项冻结字节检查；凭证为[operator_02](verification/operator_02/verification.json)。首轮15项有1项计划格式修改检查失败，现加入完整计划SHA，最终原日志保留于[operator_01](verification/operator_01/unittest.txt)。新增检查强制socket只允许127.0.0.1，不是实物照片。

## 离线准备与采集门槛

以下400/800只演示开发候选，不代表XDL已冻结最优曝光。在本目录、现有含numpy/opencv的Python环境运行，输出路径必须全新：

```powershell
python -X utf8 -B operator_host.py prepare --low 400 --high 800 --physical-specimen-id sample005 --pose-id sample005_A_development01 --pair-status development_trial --pair-reference "development candidate; pending XDL selection" --pixel-format 0x31 --out C:/BX72_0106_EXPERIMENT/plans/new_plan
```

prepare复用SHA固定的旧08/07来源审计，不运行旧自动曝光控制器。plan明确区分`source_initialization_firmware`与`capture_firmware`，保存原完整图/ROI图、mask、session/result的来源SHA，预览由同一原图和几何生成。物理工件ID与sample/pose分别记录，避免005制作前后被算成两块独立物理板。

真实采集入口是`capture --plan <plan.json> --out <new_round> --confirm-same-pose`。当前不能执行实板0106采集：`STATUS.json`仍为release_ready=false、bit_generated=false，外部IO/CDC/DRC审查未完成；原只读审计也明确未qualified。无命令行跳过开关，不用旧0105回退掩盖未满足条件。

后续正式准入还须保存实际候选bit、生成bit的原始构建记录及`guangjian-bit-from-qualified-checkpoint-v1`绑定凭证，将bit SHA绑定到已审查DCP SHA和固定RTL提交；宿主核对本地文件、来源与资格快照，SDK再独立复核实际bit文件。当前没有生成这份凭证。该绑定仍不是板上完整bit SHA读回，不能仅改一个ready字段放行。若更换RTL/DCP，必须重新构建、审查并更新源绑定。

## 八请求与失败归档

共享`.auto_exposure.lock`在SDK构造前取得，锁内再次读取来源、计划、源码和资格。固定CH1 low/high、CH2 low/high、CH3 low/high、CH4 low/high，LED128、gain16=16、settle1/discard3，一轮格式与session固定，无寻曝、补拍或整帧自动重试。SDK的相同命令/seq幂等重试继续记录成本。

每次请求后检查最终原metadata包、实际负载、SHA清单、gray8/SAT1、mask、读回参数/ROI/格式及身份前进，再发下一次。错误立即停止，保留已完成观测与失败outcome；第5次CRC失败只保留4个有效观测，不补成8个。只有全8图并通过`fixed_eight.validate_eight`后才生成数据合同。

finally中的显式关灯和close都在共享锁内完成。缺OFF ACK时保存`ACQUIRED_EIGHT_CLEANUP_REQUIRED`，不宣称灯已关闭。完整成功为`ACQUIRED_EIGHT_REVIEW_REQUIRED`，仍需人工光学/标签检查；不是检测质量合格或曝光最优。

整轮包含approved_plan、精确来源快照、资格证据、board_mask、observations、固定八图合同、全部SDK原始文件/trace/outcome和operator_summary。冻结归档函数对ZIP逐成员CRC/SHA重读，写清单、SHA侧附件及receipt；ZIP失败保留原目录和archive_error。记录每次尝试和关灯的网络成本，未知物理稳定/启动成本仍未知；历史02/03不计作本轮新图，初始主机准备和最终压缩不计入360秒采集预算，receipt另记完整主机耗时。

## 冻结输入诊断

```powershell
python -X utf8 -B frozen_diagnostic.py prepare --rgb565 C:/experiment/source.rgb565 --width 81 --height 21 --out C:/experiment/frozen_input
python -X utf8 -B frozen_diagnostic.py verify --frozen C:/experiment/frozen_input --rgb-payload C:/experiment/returned.rgb565 --gray-payload C:/experiment/returned.gray_sat --out C:/experiment/diagnostic.json
```

mask可显式用`--mask`提供保存域0/1平面；省略时评价全保存域。准备记录绑定输入RGB、mask和可执行参考SHA；验证要求返回RGB逐字节等于冻结输入，并逐像素核对gray/SAT、重算H1/H2，拒绝非零尾部padding。成功只写`OFFLINE_FROZEN_BYTES_EQUIVALENT`，硬件freeze及identity仍false。

尚需设计受控硬件测试源或同一冻结DDR银行的双格式回传和身份协议，当前不能用两个新DVP帧假称同一输入。真实曝光之间有噪声，不能要求两张新照片逐像素一致；此离线入口不会替代实板诊断准入。

## 本轮板卡只读检查

用户本轮明确允许使用已接通板卡。取得共享锁后发出两次独立尝试，每次仅一条命令3，均未收到ACK/STATUS：[默认路由](verification/board_status_20261025_01.json)、[仅此socket绑定实体网卡](verification/board_status_20261025_02.json)。因首条无回复，没有发同次计划中的第二条查询。

实体网卡192.168.0.3为Up/1Gbps，邻居表有192.168.0.2/MAC；系统对192.168.0.0/24优先使用Cisco AnyConnect虚拟网卡。固定实体网卡的单socket尝试仍无回复，不能据此认定VPN是唯一原因，也不能据邻居表认定0105已加载。没有改系统路由、VPN、曝光、灯光，没有发CAP或烧录。首次探针加入网卡绑定选项前的源码另存SHA对应历史副本。

### Cisco连接与本机独立检查（r3.5.1更正）

用户确认断开Cisco会使Codex无法工作，**保持Cisco连接以继续开发**。原“断开后由助手在线复测”的建议不适用，不再等待在线断开VPN，也不修改系统路由或VPN策略。

需要板测时，用户可在本机运行[RUN_LOCAL_STATUS.cmd](RUN_LOCAL_STATUS.cmd)：先关闭其他板卡客户端，临时断开Cisco，双击该入口，待窗口显示结果目录后恢复Cisco，再把结果交给助手。此入口及依赖均在本机，不依赖Codex在线；只发送命令3，不采集、改参数或烧录。输出保存于`C:/Users/yue/Documents/GuangjianBoardStatus/<时间_随机编号>/`，含board_status.json、console.txt、launcher_receipt.json；失败记录也保留。当前无需立即执行，离线软件工作继续。

脚本位于仓库实验目录，原LAB与01～09均未覆盖。PowerShell的`-CheckOnly`只校验探针SHA和本地冻结依赖，不打开socket；已通过该准备检查，实际断网运行仍待用户执行。首轮只读状态确认不要求工件或照片，后续采集再确认当前工件/姿态。

后续优先完成网络与原0105状态确认，再由现用RGB链路进行有当前工件/姿态确认的最小八图试采。新0106灰度板测须另完成上述资格；XDL不等待该灰度bit，继续固定1倍曝光选择、标注和融合训练。
