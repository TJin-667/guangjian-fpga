# 已有硬件资料接收与交叉核对

2026-10-25，r3.7。已完整读取本机`C:/BX72_HARDWARE_REFERENCE/START_HERE.md`及`TO_NEXT_CHAT.txt`，继续固定1倍增益、LED128、低高曝光配对与训练主线。原件和历史照片此前已经由YMW提供，部分在10/22清理C盘时转存D盘；不再把旧路径失效写成用户没有提供资料，不重新索要整包资料、背面照或PHY基础型号。

## 本次验证

- [接收凭证](verification/hardware_reference_01/verification.json)：FILE_INDEX的15份文件、9,956,483字节逐项大小/SHA256一致；MANIFEST的22个成员也全部一致。这是当前复制件对交接清单的核对，不冒称重算过整个3GB归档。
- 六份PDF均可解析，共13/2/28/1/177/66页；XLSX的Sheet1可读，三个历史照片已查看。没有无法读取的文件。PDF只对下表有关页面作视觉核对，没有声称逐页人工审阅所有手册。
- [引脚核对](verification/hardware_reference_01/PIN_CROSSCHECK.json)：相机14个、以太网15个实际端口在厂家表、固定XDC及精确DCP原生`ports.tsv`中全部一致，差异0。每条保留Sheet1的B/C单元格坐标。表中ENET0_INT_N/W17未用于当前顶层，单独记录，不算差异。
- [来源记录](verification/hardware_reference_01/source_records/)保留交接文字、文件索引、事实及历史照片接收凭证原字节。第三方PDF、原XLSX、原照片、提取全文与渲染图只在本机，未再次上传。

复现只读核对需要Python及openpyxl；输出目录必须全新：

```powershell
python -X utf8 -B verify_hardware_reference.py --reference-root C:/BX72_HARDWARE_REFERENCE --pin-xdc C:/bx72_ymw_0105_20261015/gray_transport_board_02/source/constraints/pinned_board_pins.xdc --native-audit verification/io_cdc_native_02 --out verification/hardware_reference_new
```

## 已确认信息，后续直接使用

PCB为**BX72-V1.1**；U25为Motorcomm，用户逐行读出的丝印为**YT8531C / VDUJ18927 / 1400310c**；没有焊接或更改硬件、电压跳线。基础PHY型号已经确认，CA订货后缀没有单独确认。历史相机背面原图可见**OV5640V5.0、ID=0X78**及针序。

旧照片接收凭证中的`full_phy_marking_confirmed=false`、`phy_base_model_confirmed=true`和`phy_ca_suffix_confirmed=false`保留原值。r3.6的[PHY_REFERENCE.json](verification/io_cdc_review_02/PHY_REFERENCE.json)是当轮审查范围的历史记录；其中实物基础型号未确认、原理图未在当轮材料中找到的限制，现由本接收补充覆盖，不重新签署或改写旧原包。

## 原件直接支持的结论

本机根目录为`C:/BX72_HARDWARE_REFERENCE/documents/`。页码均为PDF物理页；更完整的来源、视觉核对范围见[DOC_REVIEW.json](verification/hardware_reference_01/DOC_REVIEW.json)。

| 原件与定位 | 本次直接核实 | 适用边界 |
| --- | --- | --- |
| BX72_schematic_251215.pdf，第1、2页 | 以太网与SCCB在Bank14，DVP数据/同步/时钟在Bank16；网络和相机引脚与表格/候选一致。V19标为SRCC。 | 不消除现有MMCM配对/专用时钟路由覆盖问题。 |
| 同文件，第4页 | 图纸VCC3P3经FB20到VCCIO14。 | 是图纸连接；不是当前V1.1电压实测。 |
| 同文件，第10页 | U25标YT8531C-CA；RXD0/RXDLY、RXD1/TXDLY经R107/R108的4.7k上拉至VCCIO14。 | 支持strap接法假设；不等于实际装配、复位采样与寄存器读回。不能直接据此填入某个ns。 |
| 同文件，第12页 | P3的3/4为SCLK/SDA、5/6为VSYNC/HREF、7/8为PCLK/XCLK；9～16为D7～D0交错排列；17 RESET上拉、18 PWDN下拉。 | 不改变已验证的接线或电压；不由图纸假装已取得当前排线长度/偏斜。 |
| BX72_assembly.pdf，第1、2页 | 装配位置可用于定位U25、R107/R108、P3；第1页明显标为BX72-V1.0。 | 与已确认实物V1.1存在版本标记差异，必须向厂家核对适用范围；不能用此图追认实物全部等价。 |
| BX72_pins_V2_1.xlsx，Sheet1 B26:C39、B41:C56 | 使用中的29个相机/网口端口全部匹配XDC与原生DCP导出。 | 仅引脚对应，不是时序、电压或整板资格通过。 |
| ACM5640_V5_user_manual.pdf，第7～9页 | 给出行/帧格式与8位DVP上RGB565每像素两拍的说明。 | 不提供当前连接下可直接采用的完整电气输出延迟上下界；不凭通用说明更改已验证字节顺序。 |
| ACM5640_V5_schematic.pdf，第1页 | 参考图传感器DOVDD为2.8V；P1的9/10标为传感器D9/D8，继续至15/16的D3/D2。 | 用户历史模块图在相应位置标D7/D6至D1/D0，两者编号语义需区分。可能是8位接口重编号，不能认定接错或要求改线；当前实物器件/电压对应尚未证明。 |
| OV5640_sensor_datasheet_v2_01.pdf，第93页，Table6-6 | 0x4740定义PCLK/HREF/VSYNC极性；0x4745含DVP数据位序选项。 | 需要结合实际初始化写表及读回，不能采用手册默认值冒充当前状态。 |
| 同文件，第94页，Figure6-7/Table6-7；第166页，Table8-4/8-5 | 前者是随寄存器变化的行帧时序；后者包含PCLK频率、时钟输入边沿与稳定时间说明。 | 其中PLL旁路4～5ns脚注描述输入时钟到输出时钟，不能拿来替代DVP数据相对PCLK的tCO预算；96MHz上限也不是实际PCLK测量。 |

候选依赖的`I2C_OV5640_RGB565_1080P_Config.v`已能定位，尾部设置含0x4740=0x01以及PLL/DVP分频配置；头部旧VGA注释不是最终1080p状态。源码值仍不是本轮传感器读回，本次未改该文件、PCLK约束或0～2ns输入延迟。

## 真正剩余的问题及处理顺序

以下是证据工作清单，**不是要求YMW立即全部补交**。先利用已有资料完善诊断，再按具体板测窗口给最小清单。原004/005数据、XDL标注和融合训练继续推进。

| 问题 | 由助手先准备 | 后续最小外部证据 |
| --- | --- | --- |
| V1.1与251215图纸、V1.0装配图的适用关系 | 把差异限定到U25 strap、Bank14/16供电和P3，不再询问已确认的版本字符串。 | 厂家对V1.1修订差异、BOM/默认电压的说明；必要时仅补对应正面区域照片，不要求重拍已有全部照片。 |
| RGMII外部时序 | 基于YT8531手册准备只读寄存器清单、MDIO诊断及双边沿预算模板；保留现用常1的MDC/MDIO限制。 | 实际PHY ID/延迟配置读回、厂家clock/data走线偏斜或可追溯测量；STATUS_QUERY无法提供这些值。 |
| DVP接口时序与电平 | 对初始化末次写值、极性、8位引出和接收边沿作静态核对，不擅自改线、阈值或延迟。 | 当前线缆长度/连接及与模式对应的输出电气界限；仅在需要测量时请求相应电压/PCLK/数据测点。 |
| 当前原0105通信状态 | 已有独立本机只读STATUS入口，命令3、保存JSON/console/receipt；两次旧NO_REPLY保留。 | 用户选择板测窗口后本机独立运行的新结果。Cisco在线开发保持连接；不要求断开后等待在线助手操作。 |
| 0106功能与复位资格 | 继续受控硬件输入双格式诊断及复位/BRAM有效数据规则验证，使用精确DCP和既有CDC/DRC库存。 | 准备完成后的一次受控上板验收，不能由资料找回自动标为通过。 |

当前资源仍为BRAM81.5/135（60.37%），内部setup +0.003ns、hold +0.007ns；没有重新构建相同候选。`external_IO_qualified=false`、`release_ready=false`保留，没有新bit、烧录、板卡命令、采集或网络配置改动。现用09、0105/回退及638文件备份保持原样。
