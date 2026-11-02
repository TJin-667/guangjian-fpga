# 无板卡离线复现

公开快照保留完整 004 八帧案例及冻结数值胶囊，可直接复算输入、融合、十类掩膜、完整复检与评分，不需要外部板级依赖。样例来自旧 0108 的真实采集，不计为新 0109 板测或独立准确率评估。

## 环境与直接回放

已在 Windows/Python 3.11.4、NumPy 1.26.4、opencv-python-headless 4.10.0.84、Pillow 12.3.0 下执行。仓库根目录：

```powershell
py -3.11 -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements-offline.txt
& ./.venv/Scripts/python.exe -B scripts/replay_example.py --out _work/capsule_replay_01
```

输出目录必须尚未存在。成功状态为 `PASS_RELOCATABLE_FROZEN_REPLAY`；结果中十项融合字段、选中灰度、最终十类掩膜差异均为 0，完整复检证据和评分一致。禁止网络、设备与子进程，读取范围限制在胶囊、Python 环境和新输出目录。

## 完整当前主机 API 与迁移检查

先按[外部依赖](external_dependencies.md)合法恢复原文件，再执行：

```powershell
& ./.venv/Scripts/python.exe -B scripts/replay_host_example.py --out _work/host_replay_01
& ./.venv/Scripts/python.exe -B scripts/check_export.py
```

前者成功状态为 `PACKAGED_HOST_REPLAY_PASSED`；后者运行带空格目录、隐藏 GUI、SDK/CRC、八帧重算和异常分支，成功状态为 `RELOCATED_EXPORT_CHECKS_PASSED`。它们依赖原完整工程的来源资格检查，不在缺少外部原件时冒充可运行。

2026-11-03，TJ 已在新虚拟环境对恢复前的完整候选执行全部 12 项检查，并在外置后另行执行公开胶囊回放，均通过。前者见[完整候选回执](../board/results/tj_export_verification.json)，后者见[公开快照回执](../board/results/tj_public_replay.json)。均未接板或运行 Vivado。

## 公开快照检查

```powershell
& ./.venv/Scripts/python.exe -B scripts/verify_public_release.py
```

该检查核对公开文件清单、链接及外部依赖范围，不把它当作 FPGA 构建或实板结果。证据支持分供人工复检排序，不是概率。
