# 给采集端和XDL的0106灰度接口交接

2026-10-26。当前完成的是实验0106的81×21与1920×1080两种真实双格式传输检查，见[NATIVE_TRANSPORT_REVIEW](NATIVE_TRANSPORT_REVIEW.md)。这不是曝光对选定、模型训练、检测质量或正式发布验收。不重复XDL的模型实现，不要求YMW先采100组。

## 模型端保留的输入

灰度仍为与现用整数参考一致的8位像素，不在本轮向FPGA追加9×9背景相减、归一化、阈值化或有损压缩。SAT保留RGB565任一颜色通道达上限的信息；不能从灰度亮度阈值重建SAT。RGB565分支保留；0106灰度输入没有同帧RGB文件时，明确记录未保存RGB，禁止伪造/复制另一帧RGB来通过来源校验。

| 文件/字段 | 意义与校验 |
| --- | --- |
| image.gray_sat | 原始0x31负载，每8个gray字节后跟1个SAT字节，bit7为首像素；最后不足8像素仍附1个SAT字节，低padding必须0；长度N+ceil(N/8) |
| image.gray8 | N个row-major uint8像素，与同一原始payload解码逐字节一致 |
| image.sat1 | 整平面row-major打包位，bit7优先；这是拆出的SAT平面，不能把原交错payload当连续gray8 |
| board_mask.bin | 保存ROI内逐像素0/1有效域；正式数据须来自当次工件/姿态的有效mask，不得用本次诊断全1mask充当真实板分割 |
| metadata_packet.bin / result.json | schema2、固件0106、pixel_format49、payload_bytes/CRC64及参数/ROI/身份；严格提交记录，保留原字节 |
| identity | session/request_id/config_epoch/dvp_sequence/publish_sequence/roi_generation/camera_generation/light_generation/frame_id全部保存，跨组拒绝重复帧身份 |

采集端已有严格校验器host_transport及sdk_transport；对raw payload检查实际CRC64、整帧包数、最终metadata、参数读回、完整身份、H1/H2后才能提交平面。r4.3已核对XDL的a47aaf7代码：灰度/SAT来源摘要已经实现，不需要重复这项工作。新增gray_capture_bridge保留同帧raw/metadata并核对该摘要；saved_ROI输入保留真实全图原点，直接送入XDL数组接口，禁止补造全图或把ROI原点改成0。入口、27项新检查与坐标接入方式见[离线集成结果](OFFLINE_GRAY_INTEGRATION.md)。

## 分工和接入顺序

1. 助手保持现有0106及原09隔离，继续同输入逐像素一致性和采集宿主接入；正式资格未闭合前不修改release_ready绕过gate。后续同一pose的一轮应复用同一executor和mask，保留失败停采/关灯/完整ZIP。
2. XDL确认既有RGB解出gray/SAT的算法分支与上述输入合同，并给出模型规格、首批采集单和标注示例；高低曝光值、工件/pose/组数由XDL提出。本次600行不是最终曝光参数。XDL无需等待新灰度接口即可继续已有RGB数据的开发。
3. YMW按XDL采集单获取实物数据并确认物理划痕/unknown，TJ协助标注；前5个主面已完成，006待做、007～010整板冻结、B面保留。按物理板分组隔离，不把pose/面/重复/裁块当独立样本。

本次原始ZIP只用于工程解码和接口联调，没有正式训练标签/四向低高八观测，不应送入fit或冻结测试。下一次需要实物时再给一次完整最小清单；当前不用YMW重复已完成检查。
