# 0106实验传输合同 v1

此协议仅由本目录候选实现。现用0105、09及SDK没有被替换。`0x0106 / schema2 / format0x31 / command14..15 / kind0x86`为本次隔离实验分配，不能只根据固件版本推断支持。调用方须核对源码/构建身份并完成能力查询；旧0105严格客户端应拒绝0106，不能静默降级。仓库既有可运行RTL/协议没有占用这些新增枚举，既有0106测试值是旧客户端拒绝未来版本的负例。

## 控制命令

沿用20字节LGHT wire-v1命令封装，`!4sBBHHHQ`，magic=LGHT、version=1、payload_length=10、reserved=0。命令8..13保持原有session、身份查询、mask写入/封口、等待策略与取消语义。

| 命令 | 参数与回复 |
| --- | --- |
| 14，TRANSPORT_QUERY | args=0；返回kind=0x86，32字节；其他参数返回原ACK错误2。查询可在busy时返回当时快照。 |
| 15，FORMAT_SET | args=1选择RGB565，args=0x31选择GRAY8+SAT1。须已绑定非零session且不busy；非法值错误2，busy错误3。返回原ACK，序号与命令必须匹配。 |

新session与复位恢复RGB格式。改变格式作废上次最终元数据并清空旧CAP重放缓存。每帧在capture接受时冻结格式；busy期间拒绝切换。重发相同FORMAT_SET是幂等的，不重新采图，不重用旧图。其余灯、相机、ROI寄存器及读回语义不变。

## 能力回复

前10字节为`!4sBBHH`：LGHT、1、0x86、请求seq、22。后22字节为`!BHBBBHHHQH`：

| 字段 | 固定值或含义 |
| --- | --- |
| schema / firmware | 1 / 0x0106 |
| selected_format | 1或0x31 |
| supported_mask | 3，bit0=RGB565，bit1=GRAY8+SAT1 |
| reserved | 0 |
| max_payload / max_width / max_height | 1380 / 1920 / 1080 |
| CRC polynomial | 0x42f0e1eba9ea3693，ECMA、init=0、无反射、xorout=0 |
| flags | 1，最终提交必须绑定真实传输负载CRC |

主机核对实际发送的查询序号，不从收到的包中自行取一个序号充当预期值。未知schema、枚举、保留位与不支持能力一律拒绝。

## 图像与最终元数据

图像20字节头仍是`!4sBBHHHHHHBB`，kind=0x90；格式1负载为RGB565大端，格式0x31为[既有GRAY8+SAT1合同](../gray_sat_0105_20261025/README.md)。最大负载1380；包数与最后一包长度按实际字节数计算。一个8像素组可跨行和UDP边界，不能在每行或每包重新开始SAT分组。

kind=0x85最终元数据仍为170字节、payload160字节；payload[0]=2，payload[4:6]=0x0106。前144字节的身份、参数、ROI、H1/H2和原RGB CRC字段布局保留；最后16字节（整个UDP应用包[154:170]）从原保留区变为`!BBHIQ`：format、reserved=0、reserved=0、实际payload_bytes、实际payload_crc64。

原RGB CRC继续表示保存RGB565序列，**不改成灰度CRC**。格式1的两个CRC必须相同；格式0x31新增CRC覆盖实际gray/SAT字节。只有完整DDR排空、H1/H2成功、编码尾部/CRC完成、最后一个图像包完成、reader STOP/ACK和owner release之后，last_valid才能发布。编码done或已收齐图像包均不等于检测采集成功。

主机保持所有数据为provisional，直到收到匹配查询序号的已提交元数据，再核对完整session/request/frame/配置代际、实际相机/灯参数、ROI/mask、等待计数、全帧FIFO读数、字节数、CRC及重新计算的H1/H2。缺包、冲突重复、超时、取消或任何不一致均拒绝并清空临时数据。上次已提交身份用于检查新出版计数前进；session重建须显式重新建立上下文。

本目录host_transport是无网络的严格解码/最终校验适配，要求调用者提供可信SDK请求和执行上下文；新增[sdk_transport网络执行库](SDK_USAGE.md)提供该上下文及最后一次原元数据包，目前只通过软件回环验证。元数据中的16位frame_id、CRC或图像哈希不单独证明物理曝光/灯光已经生效。板级姿态与物理新鲜度仍由现场操作、完整采集记录和后续验证负责。

新增executor保留原SDK的独立二次查询、采集后相机寄存器/代际及ROI读回核对，并在第三次最终查询后验证完整payload，format/payload_bytes/payload_crc64纳入所有稳定性比较。网络库不替代宿主的来源/构建核对与operator_lock，失败取消/退役及关灯ACK仍需完整批次记录。不能把离线StrictReceiver称为完整SDK；当前网络执行库也不等于现场应用已验收。上板前还须增加可明确标记的受控测试图或同一冻结输入诊断入口；本轮模拟受控输入不等于已有实板诊断开关。

## 固定八观测输入

`fixed_eight.validate_eight`检查四方向各low/high一张、固定1倍/LED128、冻结曝光对、同ROI/mask/session/姿态ID和向前身份。接收严格解码结果及原payload、metadata_packet，保留原字节以便SDK归档；不复用旧四base加两supplement预算，不执行自动寻曝、补拍、采集或训练。标签状态保持UNLABELED，可靠性/置信度保持NOT_EVALUATED，交XDL实际标注与训练。
