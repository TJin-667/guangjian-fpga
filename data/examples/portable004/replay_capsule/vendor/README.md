# B1四方向双曝光算法接入包

交付对象：YMW。版本：2026-10-27。用途：将已完成sample004/005及sample003六组验证的无训练B1算法接入现有程序。

整个文件夹可单独复制到程序中。运行时只需Python 3.10+、NumPy和OpenCV；不依赖仓库其他目录、原始数据集、标注、模型权重或离线报告工具。实际程序嵌入和硬件实时性能验证仍由接入方完成。

## 从这里开始

1. 读[接入说明](INTEGRATION.md)：内存调用、输入输出、坐标及质量mask。
2. 读[精确规则](ALGORITHM_SPEC.md)：灰度、背景、有效性、阈值、连接、并列规则与移植注意事项。
3. 看[可运行示例](examples/embed_example.py)。示例使用明确标为合成的八帧数组，不连接硬件、不读取采集目录。
4. 交付简述见[给YMW的纯文字说明](HANDOFF_TO_YMW.txt)；来源和逐文件哈希见[PROVENANCE.json](PROVENANCE.json)。

在本文件夹打开终端：

```powershell
python -m pip install -r requirements.txt
python -B -m unittest discover -s tests -v
python -B examples/embed_example.py
```

嵌入时将本文件夹放到Python模块搜索路径，使用：

```python
from dual_exposure_b1.fusion import FRAME_ORDER, single_features, fuse_two_stage
```

不需要运行原离线run.py，也不需要exposure_fusion_v1或报告脚本。请先按INTEGRATION.md检查冻结模块的导入位置，避免宿主已有同名模块覆盖冻结版本。

## 文件职责

| 路径 | 用途 |
|---|---|
| dual_exposure_b1/fusion.py | 已验证的双曝光/四方向最大有效响应融合，原字节保留 |
| dual_exposure_b1/frozen_reference/ | 原09整数灰度、9×9背景、有效性及强弱连接所需冻结依赖，原字节保留 |
| dual_exposure_b1/frozen_reference_manifest.json | 原冻结文件SHA-256记录，路径相对dual_exposure_b1 |
| tests/test_fusion.py | 原8项融合性质测试，原字节保留 |
| examples/embed_example.py | 合成八帧调用、输出合同及两阶段/直接八帧对照 |

冻结依赖中包含历史浮点分析和M1工具函数，以保持来源文件完整；本包唯一推荐调用链是single_features → fuse_two_stage。不要改用analyze_image、tile_quality或M1代替B1核心。

## 本包保持的规则

- 顺序：CH1_low、CH1_high、CH2_low、CH2_high、CH3_low、CH3_high、CH4_low、CH4_high。
- 先同方向低/高最大绝对有效响应，再四方向最大绝对有效响应；绝对值并列优先上述顺序中较早帧。
- 保留带符号原始残差及来源；严格弱阈值>648、强阈值>1620；8邻域连接后再与工件mask相交。
- 中间候选只展示；最终输入始终是原始响应及有效性。
- 不训练、不平均曝光、不加权、不新增补线、小区域删除或归一化。

曝光数值由采集元数据传入展示/归档，算法内没有固定300/400/800参数。现阶段优先验证高曝800行，300/800和400/800并列保留；尚未冻结普适最佳曝光。RGB饱和标志SAT1可保留作诊断，本B1核心不以SAT1额外剔除像素。

已有结果不在本接入包重复上传：
[003六组结果](../result/2026-10-27_sample003_six_exposure_groups/README.md)；
[004/005结果](../result/2026-10-27_dual_exposure_b1_maxabs/README.md)。

本次仅整理独立接入资料，不修改现用09、YMW程序、采集、SDK或RTL。检测输出是候选像素，unknown仍需保留；连通区域数不代表物理划痕条数。
