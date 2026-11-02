# B1精确计算规则与移植约定

本文件描述本包实际推荐调用链，不增加新检测规则。源版本固定于Selfree提交9326c12386134aa821a8eede30b20709fa030a34。7个核心文件使用相同Git blob，不重写、不改换行。

## 1. 灰度和9×9背景

BGR8整数灰度：

```text
gray = (9798*R + 19235*G + 3735*B + 16384) >> 15
```

乘加用至少uint32。输入GRAY8时复制原值。RGB565按R5/G6/B5位复制展开到8位：R8=(R5<<3)|(R5>>2)，G8=(G6<<2)|(G6>>4)，B8=(B5<<3)|(B5>>2)。原始RGB565文件字节序见decode_rgb565（big endian uint16）。

对整个已保存图像向四周pad4，np.pad(mode="reflect")，不重复边缘像素，等价OpenCV BORDER_REFLECT_101的镜像语义。每像素取包含自身的9×9和sum9，不先与工件mask相乘，不改变边界规则。

```text
R_n = 81*gray - sum9
```

sum9在[0,20655]，参考保存uint16；R_n保存有符号int16，最大允许范围[-20655,20655]。取绝对值、累计和时使用足够宽类型，参考积分图使用int64、融合先转int32。不先把背景平均数取整，不做归一化或响应加权。

## 2. 每帧有效性

assess_quality使用gray，默认QualityConfig固定：
tile_size=32，signal_floor=8，local_range_min=6，valid_frame_fraction=0.8，max_near_white_fraction=0.98。

从保存ROI左上角(0,0)开始按32×32分块，边缘用实际剩余尺寸。每块p01、p50、p99使用np.percentile默认linear插值。若移植，排序后对p对应索引(n-1)*p/100做相邻两值线性插值，保持比较精度。

```text
ordinary = (p50 >= 8)
dark_detail = (p99 >= 8) and (p99-p01 >= 6)
usable = (ordinary or dark_detail) and mean(gray >= 250) < 0.98
```

整块usable写入该帧valid_mask。使用灰度近白比例，不用SAT1替换，不按单像素最大码另作剔除。usable_tile_fraction是块数占比而非按像素面积加权；0.8仅决定帧诊断状态valid/locally_valid/review，不将局部有效块全部禁用。single_features直接使用quality["valid_mask"]。

## 3. 最大有效响应及并列

全局帧顺序固定：
1 CH1_low，2 CH1_high，3 CH2_low，4 CH2_high，5 CH3_low，6 CH3_high，7 CH4_low，8 CH4_high。

对每像素，只对valid=True的帧比较abs(R_n)，无效帧得分-1；取最大者的原始带符号R_n。并列使用顺序最早者，不因正负极性、曝光高低或质量分数重排。有效零响应仍选最早有效帧。

若均无效：unknown=True，residual_n=0，source_frame=0，其他来源为0。否则unknown=False，source_frame保留原八帧编号，direction=(frame-1)//2+1，exposure=(frame-1)%2+1。

先在(1,2)、(3,4)、(5,6)、(7,8)中取最大；四个中间结果再按CH1..CH4取最大。第二阶段读取中间residual_n、~unknown及source_frame，不读取中间mask/weak/strong。正因如此，最终可使用跨曝光、跨方向的原始弱响应形成连接。

绝对值并列按上述规则时，两阶段的响应和来源应与直接八帧最大完全相同。不要把来源编号重置为中间方向编号。

## 4. 严格阈值与连接

```text
weak = abs(selected_R_n) > 648 and selected_valid
strong = abs(selected_R_n) > 1620 and selected_valid
connected = weak的8邻域连通分量中至少含一个strong像素的所有像素
final_mask = connected AND board
```

等于648不是弱响应，等于1620不是强响应。亮暗极性均以绝对值连通，保留极性仅供追溯，不拆成正负两条独立连接通路。没有强种子时connected全False。

工件约束在连接之后执行，这是已验证原规则的一部分。不得提前将board外的响应/valid清零；那会改变可能经过board外的连接路径，破坏逐像素等价。weak、strong、connected_mask和residual_n保持未裁板的诊断形式；最终mask才裁板。

## 5. 工件mask与坐标

调用方直接提供已核对的同坐标bool board。若从全局凸多边形构造，冻结board_mask(shape, polygon, origin)按以下顺序：
先执行poly = np.asarray(polygon, np.float32)，再执行local = np.rint(poly - np.asarray(origin)).astype(np.int32)；保留该float32转换及np.rint的并列取偶规则，不能在移植中直接用float64多边形代替。随后cv2.fillConvexPoly填1；cv2.erode使用15×15全1核和原OpenCV默认边界；最后清除图像上下左右各4像素。非空结果转bool。
该步骤是原输入几何约束，不是本轮新增形态学补线。已有最终mask不要再做一次腐蚀，也不要把凹多边形直接交给凸多边形填充接口。

003六组已保存ROI为832×864（宽×高）、全局原点(576,160)，这只是已有数据实例，不是算法尺寸常量。全局坐标=(保存图坐标)+(ROI原点)。程序输出数组不带展示标题栏。

## 6. 保持与验收

不平均低高曝光，不用50%权重，不引入质量加权、SAT1额外门控、补线、小区删除或新阈值。逐帧阈值后的mask并集仅作辅助对照，不等于先融合原始响应再连接。

同一输入、坐标、有效性与mask下：
- 各单帧候选、低四向B1及高四向B1候选都应包含于最终候选。
- 两阶段与直接八帧的响应、来源、极性、unknown、强弱及最终mask应一致。
- 存在更多候选不自动代表更高准确率；unknown保留，区域数不作物理划痕计数。

本包未提供新的C++/RTL实现；如需移植，以本参考实现和以上逐像素性质为准，先用冻结实图回放验收，再评估资源、线程和延迟。
