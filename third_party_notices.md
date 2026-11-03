# 许可范围与第三方材料

团队有权授权的自研代码采用根目录 [MIT](LICENSE)。第三方代码、工具生成 IP、标识和素材保留各自权利与条件，不被根 MIT 重新授权。

## 来源与许可

| 组件 | 实际版本或位置 | 适用说明 |
| --- | --- | --- |
| 团队 RTL、PC 主机、冻结算法 | 0109、独立 v1.8、冻结 `f09eb5885e1d`；发布清单绑定具体文件 | 自研贡献 MIT；保留文件内实际作者及上游声明。 |
| NumPy | 1.26.4；通过 requirements 安装 | BSD 及所列第三方条款，见 [原许可](LICENSES/numpy.txt)。仓库不分发 wheel 或虚拟环境。 |
| opencv-python-headless | 4.10.0.84；通过 requirements 安装 | [主许可](LICENSES/opencv-python.txt)与[依赖条款](LICENSES/opencv-bundled.txt)；不将 OpenCV 当作本队原创。 |
| Pillow | 12.3.0；通过 requirements 安装 | MIT-CMU 及随分发记录的第三方条款，见 [原许可](LICENSES/pillow.txt)。 |
| Python / Tkinter | 原环境 Python 3.11.4；GUI 使用 Tkinter | 由使用者安装并按相应 Python/Tcl/Tk 条款使用，不打包解释器。 |
| Easics CRC32 参考 | `src/fpga/implemented/ymw/src/crc32_d8.v` 及相应历史副本 | 原头部明确允许使用和分发，条件是保留版权、衍生作品声明和免责声明。原文保留，不改为本队原创。 |
| Xilinx PLL、FIFO、MIG | `sys_pll`、`wr_ddr3_fifo`、`rd_ddr3_fifo`、`mig_7series_0`，原 XCI/HDL/DCP | 受 AMD/Xilinx 原许可约束，限相应器件与许可范围；不是 MIT。2018.3 EULA 对源/网表接收方设有软件许可条件，不能将免费 IP 等同于无限制开源。 |
| 芯路恒 CoreCourse 板级参考 | GMII/RGMII、校验和、UDP 等原文件及衍生实现 | 保留原头部和实际来源；完整公开再分发授权仍须核实。 |
| CrazyBingo 相机配置 | `I2C_OV5640_RGB565_1080P_Config.v` 及历史副本 | 原头部写明 CONFIDENTIAL，并要求按 CrazyBingo 许可使用。没有以团队 MIT 替代该许可；公开前须取得相应授权或采用外部依赖方式。 |
| 预览 CRC 本地 DLL | 对应目录含 C 源和构建收据 | Windows 本地构建产物，原源码与 CRC64 自检记录随工程保留。 |
| 原理图和厂商手册 | 内部交接参考区 | 不随公开仓库整包复制。只整理已核实的硬件事实。 |
| 实拍图、检测图、中英文海报 | `report/media/`，保留来源字节与组身份 | 用于项目展示；校徽与其它第三方标识不授予通用 MIT 权利。署名和校徽按用户确认保留。 |
| AI 可见消息节选 | `report/ai_records/` | 仅选择的项目相关可见消息；原始文本、摘录和概述各自标注，不公开完整私人会话。 |

## 当前公开状态

完整技术候选已完成集成与离线检查。受限或未明确获得公开再分发权的 232 项原件已外置，不在公开 Git 或公开 RAR 内；详见[外部依赖清单与恢复方法](docs/external_dependencies.md)。其余团队有权授权的自研部分采用 MIT，Easics 等已明确允许分发的参考保留原条款。公开快照与恢复后的完整本地工程分别记录验证范围。

许可依据：[AMD Licensing FAQ](https://www.amd.com/en/products/software/adaptive-socs-and-fpgas/licensing-faq.html)；本项目实际 2018.3 EULA 和原文件头部作为内部核对来源保留。文档说明不能替权利人授予额外授权。
