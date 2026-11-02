# LGHT 0109 增量协议

旧3/9/14返回固件0x0109；扩展0x88保持schema1、64字节头，revision为9。严格0108客户端拒绝revision9，严格0109客户端拒绝revision8。请求仍为20字节，同一排他socket/序列分配器；旧请求仅允许同一不可变内容重放。组内不旋转会话。

## 人工曝光

REG16原index0～5仍写group64/digest128；index6低曝光、index7高曝光。各项须为1～1116行；BEGIN17另检查低<高并锁存。已锁组内改REG返回3。新BIND/共同复位恢复400/800。SDK准备计划的digest包含完整曝光配置，正式CAP前核对CONFIG读回；ARM18检查实际曝光是否对应本slot。

CONFIG27要求args=0，成功载荷16字节，大端 `>4sHHHBBHBB`：magic GJC9、low、high、gain16=16、LED=128、feature_bits=3、maximum=1116、schema1、revision9。组内返回锁定值，组外返回待配置值。CRC32覆盖载荷。

## PROFILE26

args高32位为stage0/1/2，低32位为当前frame cookie。仅在锁组、对应slot成功FUSE并提交、没有工作在途时返回；cookie/slot/request/group/digest/ROI必须完全绑定。每帧FUSE后立即读取3页，再允许下一ARM覆盖本帧快照。无有效测量、溢出、过期或失败明确拒绝，不以零时间冒充成功。

成功载荷28字节，大端 `>4s6I`：GJP9、stage、clock_hz、inclusive_service_cycles、count0、count1、observed_blocked_cycles。CRC32覆盖载荷。SDK保留原始回复hex并解码再校验；归档再次对照原始wire与汇总值。

| stage | 本域 | 起止 | count0 | count1 | blocked |
|---|---|---|---|---|---|
| 0 H2 | NET125MHz | H2配置真实握手→analysis_done | H2已接受像素 | H2输出背压周期 | 同count1 |
| 1 scratch | UI100MHz | scratch配置握手→writer结果 | AXI W握手 | AXI B握手 | 观察到AW/W背压周期 |
| 2 fusion | UI100MHz | merger配置握手→结果握手 | AXI R握手 | AXI W握手 | 观察到R/W/AR/AW背压周期 |

P=ROI像素数，B=ceil(P/4)：stage0 count0=P；stage1 W=B、B响应=ceil(B/16)；stage2首帧R=B、后续R=2B，W=B。边缘部分beat仍计一个握手。

scratch描述符由ARM流程预置，可能先于实际采集/H2流到达；stage1因而可能包含等待采集、曝光稳定和数据抵达的空档。它是该写入服务的占用区间，不能当作DDR纯写入时间或纯H2运算时间。blocked只计所列接口的可见背压，不覆盖所有等待原因。

计数包含开始与完成边沿，单周期操作为1。32位饱和计数若继续增加则标溢出、测量无效；失败、重复start、共同reset等分支有独立测试。每段只用自己的时钟。当前上限约34.36秒(NET)/42.95秒(UI)；超限须拒绝，不回绕后报告很快。

UI计数通过原512位命令/256位回复mailbox读取，新增reply kind3；NET不得把kind3覆盖为普通UI工作状态。现有7条新增CDC mailbox保持宽度与DONT_TOUCH边界，route审计仍检查17条bus-skew及12条data bundle。

## 传输与性能解释

49/50格式、R32、原DDR地址布局、有效表、质量算法、融合数学及最早来源并列规则不变。PROFILE/CONFIG增加真实RPC字节与耗时，必须计入端到端记录。图像平面理论字节节省不能冒充整组传输或耗时节省。

三个服务区间有重叠和不同边界；只可分别列报，并与明确边界的PC同输入阶段比较。纯算术周期、完整PC-only采集端到端和实板加速比在未测得前保持null。
