# YMW程序接入说明

## 运行环境与接入位置

Python 3.10+，依赖numpy、opencv-python。若宿主已安装提供cv2的OpenCV发行包，请沿用同一个cv2环境，不同时安装多个OpenCV发行包。本包保持参考代码及其导入方式，未改写为C++或RTL。

将整个b1_dual_exposure_integration文件夹复制/取出后，将其根目录加入宿主模块搜索路径。只复制fusion.py会缺少冻结依赖。推荐在采集事务完整确认、八帧元数据校验通过后，在后台计算线程或独立计算进程调用。参考实现会计算全图连通域及中间结果；尚未测实时延迟或内存上限。

冻结源文件会将包内software目录加入sys.path，并使用顶层模块名ymw_integer_reference和light_inspection。宿主若已经导入同名模块，Python可能复用它们。应在首次加载前确认名称冲突；若宿主必须使用不同版本的同名库，使用独立计算进程。可在首次导入后核对：

```python
from pathlib import Path
import dual_exposure_b1.fusion as b1
import ymw_integer_reference
import light_inspection.real_baseline as baseline

expected = Path(b1.__file__).resolve().parent / "frozen_reference" / "software"
assert Path(ymw_integer_reference.__file__).resolve().parent == expected
assert Path(baseline.__file__).resolve().parent == expected / "light_inspection"
```

## 输入合同

frames_by_name是八帧字典，键必须恰好为FRAME_ORDER中的八个名称，不按文件名排序、不按到达顺序猜测曝光。

每帧为原生保存坐标下的uint8二维GRAY8或uint8三通道BGR数组，尺寸一致且宽高至少9。若来源是RGB，先正确调整通道顺序；若来自RGB565，沿用冻结decode_rgb565的位复制展开。GRAY8必须是已核对的同一整数灰度公式输出，不用其他灰度近似替代。

board是同一保存坐标下非空bool二维工件几何mask。它不是每帧quality valid_mask。八帧必须使用同一个工件mask、同一ROI原点和同一姿态；不得在此处再次裁剪已保存ROI、缩放或插值配准。若需要从全局凸多边形生成mask，沿用ALGORITHM_SPEC.md中的board_mask；已有最终mask直接使用，不重复腐蚀。

采集元数据由宿主保留：组ID、实体样品/姿态、CH方向、低高角色、实际曝光行、增益、LED、帧/请求/会话身份、ROI原点和mask校验。数组函数本身无法从像素证明这些身份。缺帧或校验失败时不要复制另一帧补齐，也不要把未完成事务交给八帧算法。

## 最小内存调用

以下代码放在已有八帧数组和board变量的处理位置：

```python
import numpy as np
from dual_exposure_b1.fusion import FRAME_ORDER, single_features, fuse_two_stage

if set(frames_by_name) != set(FRAME_ORDER):
    raise ValueError("需要恰好八帧，并按方向和低高曝光命名")
if not isinstance(board, np.ndarray) or board.dtype != np.bool_ or board.ndim != 2 or not board.any():
    raise ValueError("需要非空bool工件mask")
for name in FRAME_ORDER:
    frame = frames_by_name[name]
    if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8
            or frame.shape[:2] != board.shape or min(board.shape) < 9
            or not (frame.ndim == 2 or (frame.ndim == 3 and frame.shape[2] == 3))):
        raise ValueError("八帧必须是同坐标、同尺寸的GRAY8或BGR8")

features = [single_features(frames_by_name[name]) for name in FRAME_ORDER]
residuals = np.stack([feature["residual_n"] for feature in features])
valid = np.stack([feature["valid"] for feature in features])
result = fuse_two_stage(residuals, valid, board=board)
final = result["final"]
candidate_mask = final["mask"]
direction_candidates = [direction["mask"] for direction in result["directions"]]
unknown_on_board = final["unknown"] & board
```

single_features返回gray、sum9、residual_n、valid以及单帧weak/strong/mask。
fuse_two_stage返回directions（CH1至CH4的四个结果）和final。
它们不负责文件归档、UI或硬件请求；不要使用文件展示图上的红色像素作为下一轮算法输入。

## 若已有H2响应

可直接将八帧原始带符号residual_n和逐帧质量有效性传给fuse_two_stage，省去single_features。residuals形状为(8,H,W)，signed整数且值在[-20655,20655]；valid必须是同形状bool，不能用0/255图片代替，也不能传已经筛选的候选掩膜。

只有gray和SAT1时，沿用包内integer_h2及assess_quality计算；不需要伪造BGR。SAT1不进入本B1最大响应选择，保留其诊断及追溯用途。已有valid必须与冻结质量规则逐像素一致，不能临时换成几何board。

## 输出合同

所有平面均为(H,W)，没有标题边框或缩放。

| 字段 | 类型与解释 |
|---|---|
| residual_n | int16，选择后的带符号81倍残差，保留阈值以下弱响应 |
| source_frame | uint8，1..8按FRAME_ORDER；全帧无效时为0 |
| source_direction | uint8，1..4为CH；0无有效来源 |
| source_exposure | uint8，1=low、2=high；0无有效来源；不是曝光行数 |
| polarity | int8，-1暗、0零响应、+1亮 |
| unknown | bool，八帧在此像素均无有效观测 |
| weak / strong | bool，严格阈值后结果；尚未裁工件mask |
| connected_mask | bool，8邻域含强种子的弱连通区域；尚未裁工件mask |
| mask | bool，connected_mask与board相交后的最终候选 |

有效但响应为0的像素仍有非零来源，polarity为0；它不等于unknown。
工件mask外不自动标unknown；UI/统计在board内解释。
保存二值PNG时可显式转换为uint8×255。推荐归档residual_n、source_frame、source_direction、source_exposure、polarity、unknown、mask及采集元数据，保留原始八帧响应供复核。

## 可选对照与接入验收

```python
from dual_exposure_b1.fusion import maxabs_connect

direct = maxabs_connect(residuals, valid, source_ids=np.arange(1, 9), board=board)
low4 = maxabs_connect(residuals[0::2], valid[0::2],
                     source_ids=np.array([1, 3, 5, 7]), board=board)
high4 = maxabs_connect(residuals[1::2], valid[1::2],
                      source_ids=np.array([2, 4, 6, 8]), board=board)
for key in final:
    np.testing.assert_array_equal(final[key], direct[key])
assert not np.any(low4["mask"] & ~final["mask"])
assert not np.any(high4["mask"] & ~final["mask"])
for feature in features:
    assert not np.any((feature["mask"] & board) & ~final["mask"])
```

先运行包内8项测试和合成示例，再以已有003/004/005的原片、相同mask及保存响应作逐像素对照；要求最终响应、来源、unknown、候选一致，差异位置单独输出。分辨率/ROI变化后tile锚点、边界和mask必须重新对齐，不能拿重采照片要求逐像素相等。

本包交付核验记录在VERIFICATION.json。历史003的794项输出检查、004/005的687项检查属于已有离线实验，不代表本包已经接入YMW GUI、SDK或硬件实时链路。现场曝光参数仍需由实际对照决定。
