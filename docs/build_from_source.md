# FPGA工程构建入口

**公开快照前置：** 本页的完整工程流程须先按[外部依赖说明](external_dependencies.md)合法取得并恢复原 IP、板级文件和工件。直接克隆的公开快照只保证独立离线胶囊入口；缺少外部文件时原完整性检查会拒绝运行。


目标器件为Artix-7 `xc7a100tfgg484-2`，板卡BX72-V1.1。工程使用Vivado 2018.3及包内四组原版IP输入，不自动升级IP或改时钟约束。

## 检查输入

```powershell
& ./.venv/Scripts/python.exe -B scripts/build_fpga.py --check-only
```

成功状态为`FPGA_BUILD_INPUTS_READY`。工具核对实现源码清单及包内完整性，不能把此状态当作已经完成综合或布线。

## 综合与布线

```powershell
& ./.venv/Scripts/python.exe -B scripts/build_fpga.py --vivado 'F:/Xilinx/Vivado/2018.3/bin/vivado.bat' --out E:/GJBuild/submission_01
```

请将`--vivado`替换为实际安装位置，输出目录必须尚未存在；建议使用较短英文路径。也可通过`VIVADO_BIN`或PATH提供Vivado入口。

工具先复制`src/fpga/implemented/`到新构建工作区，再调用原`source/synth/build_board.tcl`，避免Vivado生成文件写入冻结输入。输出包含`build/routed.dcp`、综合/布线资源与时序报告、日志及`rebuild_receipt.json`。只有实际进程成功退出并生成布线检查点时，记录`FPGA_REBUILD_COMPLETED`。

构建脚本不执行`write_bitstream`或板卡操作。交付bit为先前已验证检查点生成的文件；此次源码重建不替代该bit原有资格，也不要求重建检查点哈希与原位流检查点哈希相同。

## 报告对应的功能仿真

```powershell
& ./.venv/Scripts/python.exe -B scripts/run_sim.py --vivado-bin 'F:/Xilinx/Vivado/2018.3/bin' --out E:/GJBuild/simulation_01
```

工具使用包内原测试台和9×9输入，与当前实现的四个RTL模块逐文件核对并运行xvlog/xelab/xsim。完成标记为`H2_SCRATCH_ALL_PASS 2`和`MAXABS_REPORT_PASS 8`，新VCD和日志保存在输出目录。这验证数值、严格阈值、来源选择以及写应答/错误分支；DDR为边界模型，不作为实物DDR训练或外部IO签核。

## 输入分布

| 目录 | 内容 |
|---|---|
| `src/fpga/implemented/source/rtl` | 灰度、局部背景、融合、传输及状态控制RTL |
| `src/fpga/implemented/source/integration` | DDR、相机与顶层集成 |
| `src/fpga/implemented/source/constraints` | 引脚与跨时钟约束 |
| `src/fpga/implemented/ymw` | 原板级、相机及接口支撑 |
| `src/fpga/implemented/prebuilt_ip` | 原版PLL、FIFO和MIG输入及检查点 |
| `board/artifacts` | 既有bit、构建收据与工程资格 |

PL承担灰度/SAT、9×9背景残差和多观测最大有效响应等处理；PC保留全局强弱连接、受控弱段增强、复检提示及界面归档。PC与PL收益表述必须沿用实际计时范围，不能由综合时序或软件流程改善推导整机加速比。
