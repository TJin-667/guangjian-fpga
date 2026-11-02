# TJ电脑闭环适配（2026-10-15）

已把main的XDL/XDL_Software_Controller接到已有AcquisitionExecutor，实际运行软件UDP peer闭环。接口负责执行和证据；曝光选择、质量判据、确认/重试/停止仍由XDL controller-0.1决定，没有修改XDL源文件。当前交付不含新bit，未运行Vivado或连接板卡。

同轮[板级IO核对](../board_io_review_20261015/REVIEW.md)单独给出处、推导和待确认项，reviewed=false；供电/strap矛盾需要YMW确认。

## 固定来源

- main控制器：90c152bc702dd11c55d67c4761f426483fa43118，全部根Python文件逐字节SHA记录；状态/Decision逐项对照其独立fpga_reference。
- 采集SDK：2d69deeb169773c9cf54d4499b0c060a933af78e（PR #22中使用的源码；沿用PR #21/#20接口），原始文件由Git对象只读导出。
- XDL检测/整数基元及历史integrity：8e7dec0daaedb0f08ef80b707c83ba37de7e7002，继续使用XDL原load_algorithm核对七个检测源和整数基元的固定SHA。
- YMW wire-v1：de18e3b604158c1b53b87b08f22ddc59ed52cfe2。旧56文件完整manifest仍由原SDK验证。只读依赖副本在仓库外，不调用其RTL/XDC/Tcl。

SDK只有一项明确的软件执行增量：publication.py的bounded-windows-publish-1。加载时对固定原SDK的唯一目录发布语句应用一个受控覆盖；原始依赖文件不变，记录覆盖版本、覆盖后完整源码SHA和覆盖源文件SHA。它仅在Windows共享/访问错误下、有截止时间地重试已验证图像目录的原子重命名，不再采图、不覆盖既有目录、不改协议或XDL规则。永久失败/取消仍进入原SDK失败路径。第3轮真实Windows句柄锁验证了暂时锁、永久锁及发布期间取消；前两轮失败回执保留，未将它们算成通过。

## 一次完整流程

Controller.start/feed请求曝光 → acquire设置CH1/LED128/gain16=16/曝光及ROI → 执行确认/读回/等待/丢帧/组帧/身份与CRC验证 → 新调用的committed图片及实际参数 → 首帧共同区域/当前指标 → Controller.feed继续或停止。

ClosedLoop接受显式native mask或MaskProvider。首帧以自己的ROI和native mask在全坐标中建立共同区；不预读未来曝光图。后续区域像素和SHA冻结，只增加每个新来源及覆盖记录。当前native离开冻结区时停止复核；扩大但仍满足XDL覆盖条件时保留native/common不同分母。没有新增自动板面定位算法，实际mask/固定工件位置仍需现场核对。

## 可复跑命令

以下是本机实际环境；其他机器先填写自己的仓库/Python路径，输出目录必须全新。依赖不进入Git、不会生成bit。

```powershell
Set-Location 'C:/Users/30869/.codex/worktrees/tj-pc-closed-loop-20261015/fpga'
$tjPython='C:/Users/30869/Documents/ChatGPT/fpga/tmp/peer_upload_review_20261013/.venv/Scripts/python.exe'
$tjLoop='TJ/work/pc_closed_loop_20261015'
$tjDeps='C:/Users/30869/Documents/ChatGPT/fpga/tmp/tj_io_pc_loop_20261015/deps_r1'

# 新机器需要先取得固定Git对象。不会切换/合并main。
git fetch --no-tags --filter=blob:none origin 2d69deeb169773c9cf54d4499b0c060a933af78e 8e7dec0daaedb0f08ef80b707c83ba37de7e7002 de18e3b604158c1b53b87b08f22ddc59ed52cfe2
if ($LASTEXITCODE -ne 0) { throw '固定依赖获取失败' }
# 依赖尚未建立时才运行；已有deps_r1不得覆盖，重建请换新目录。
& $tjPython -B "$tjLoop/prepare_dependencies.py" --repository . --out $tjDeps
if ($LASTEXITCODE -ne 0) { throw '固定依赖导出失败' }

& $tjPython -B "$tjLoop/run_closed_loop.py" --dependencies $tjDeps --software-peer --out C:/tj_loop_peer_new
if ($LASTEXITCODE -ne 0) { throw '闭环未锁定或验收失败' }
& $tjPython -B "$tjLoop/audit_closed_loop.py" --dependencies $tjDeps --out C:/tj_loop_peer_new/loop
if ($LASTEXITCODE -ne 0) { throw '完整回执审计失败' }
& $tjPython -B "$tjLoop/run_verification.py" --dependencies $tjDeps --work C:/tj_loop_verification_new
if ($LASTEXITCODE -ne 0) { throw '测试失败；保留cases.csv与verification.json' }
```

也可通过start_pc_loop.ps1调用peer/verify/audit。peer是默认且只使用127.0.0.1软件peer。verify需要Windows，三项发布测试使用真实Win32文件句柄，失败不跳过算通过。

run_closed_loop退出码：0=规则LOCKED且审计通过；3=NEEDS_REVIEW；4=CAPTURE_FAILED；2=输入/接口/证据错误。run_verification与audit_closed_loop只在完整检查通过时返回0，否则非零。NEEDS_REVIEW属于合法策略停止，验收用例可预期它；不能把它标为现场图像成功锁定。

## XDL可导入的接口

```python
import sys
from pathlib import Path
sys.path.insert(0, r'C:/Users/30869/.codex/worktrees/tj-pc-closed-loop-20261015/fpga/TJ/work/pc_closed_loop_20261015')
from dependencies import load_dependencies
from closed_loop import ClosedLoop

dependencies = load_dependencies(Path('你的72文件依赖副本目录'))
config = dependencies.xdl.acquisition_control.ControllerConfig()
# 使用既有AcquisitionExecutor实例executor和bool native_mask：
adapter = ClosedLoop(dependencies=dependencies, executor=executor, config=config,
    output=Path('全新结果目录'), roi=(x, y, width, height),
    mask_provider=lambda request_index, exposure_lines: native_mask,
    sample_id='实际样件编号', pose='固定位置编号', settle_frames=1)
summary = adapter.run()
```

实例executor仍提供原acquire接口。strict以0x0105/schema1为前提，不把0x0104兼容结果送进控制器。任何确认、回退确认及错误后的新确认均调用新的acquire；像素相同可以是两个独立新观测，完整身份、request/publication和新调用记录必须不同。不能靠换文件名、重读旧图或改frame_id凑确认。

## 身份、统计与成本契约

- 完整session/config/request/DVP/publication/ROI/camera/light/frame_id加bank，从SDK诊断绑定到请求、原始RGB565、PNG、实际参数、读回和统计。返回的result/PNG必须属于本次新调用目录，CRC、SHA、逐像素PNG/RGB565及旧H1/H2整数统计再次核对。
- native_device_statistics是原十项设备统计；native_reference_statistics是XDL旧native基线；common_statistics是冻结共同区的新controller-statistics-1。各自单独保存，不把共同分母写回旧设备统计。
- XDLrequested/consumed/reserved/unfulfilled成本原样保留，仍是模型。cost_ledger另记每次实际API调用、UDP重传、等待/丢弃计划及设备报告、发布重试、失败、主机时长和未观测成本。默认一事务是1等待+3丢弃+1评估=5帧的请求预留，XDL模型仍为4帧；运输层预留会按max_frames额外限制，不静默修改XDL模型。
- 预留是请求内等待/丢弃/评估的容量，不是全系统物理成本上界。启动热身、未被观测的额外过渡帧、板上事件时长及光学生效未知。失败若已有完整验证快照和原图，仍计其已证明帧数；否则保留null及下界，不把失败成本记零。主机总耗时包括执行、重试、发布和统计计算。
- 需要外部恢复的错误及取消不自动重新连接/重置板卡；当前请求与未兑现确认都有成本/停止原因记录。没有实板物理稳定性或曝光生效声明。

## 输出与验收

每轮captures/<call_id>保存原SDK的图像、诊断/参数、outcome和frame_trace；loop目录有receipt、summary、cost_ledger、observations、transitions、冻结common mask、每次native mask、汇总frame_trace.jsonl。receipt给出完整输出SHA，审计独立重算统计、状态/动作、身份、成本和库存，拒绝删失/篡改。

本机最终第3轮47/47：34项软件UDP闭环、入口3项、审计否定8项、恢复与来源2项。34项合计70次API调用、44个可送入XDL的独立逻辑观测、111个完整独立规则转换；没有60张实图新回归或FPGA时序/板测声明。详见[实际运行报告](RESULTS_20261015.md)及evidence目录。

板级IO、候选bit构建及PHY现场读回由YMW继续。新bit和真实mask准备好后再调用CLI的显式真实端点模式，另记录bit下载身份、现场等待/丢帧校准及物理切换结果；本轮不执行这些动作。
