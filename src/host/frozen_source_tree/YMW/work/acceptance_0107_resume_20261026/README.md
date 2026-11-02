# 0107入口进度修复与接续

原启动器在采集、mask配置、归档期间没有过程输出；用户看到空窗口，但程序已实际工作。旧原始结果保留，没有把中断写成板卡故障。

现已更新同一处本机CMD：`C:/BX72_0107_ACCEPTANCE/20261026_window01/RUN_ACCEPTANCE_0107.cmd`。启动即显示STARTED，每5秒显示阶段/已提交灰度帧/最新mask字进度，先确认关灯；复用已通过的同冻结对照。无需重烧bit。操作见[更新清单](local_launchers/START_HERE.md)，旧入口已在本机launcher_backup_e40c960备份。

## 已取得的实板证据

- [同冻结独立复核](verification/real_frozen_review.json)：1920×1080共2073600像素，RGB/gray/SAT来自一次冻结读取；灰度及SAT差异0，独立整数H1/H2、原RGB/实际负载CRC、身份、全DDR读数、原OFF ACK和ZIP均通过。[原ZIP](verification/real_frozen_01/same_frozen.zip)按字节保存，不重复上传解压图。
- [灰度部分序列复核](verification/PARTIAL_RUN_REVIEW.json)：同一会话的前5张已COMMITTED，逐帧负载、平面和H1/H2重新计算一致，mask命令64801→0→0→0→0，传输异常为0。第6次停在相机配置后、CAP之前。后一次启动已用新nonce，因此不能沿用旧5张冒充同会话八请求。
- 新入口只重启严格八请求序列并完成KEY2恢复，最多新增9次工程CAP，已经通过的同冻结全幅不再采。旧5张保留为部分序列证据，不拼接/伪造session，不修改原八请求校验器，不用于训练。

## 修复与验证

新resume_acceptance.py调用原0107严格SDK/宿主/导出器，原RTL、bit及229份发布源文件/凭证保持原字节。进度线程只读新输出目录，不发板卡命令，不修改旧capture/committed文件。启动和最终结果目录即时可见，运行前先落STARTED回执；KEY2输入说明完整换行显示。

[8项新回环检查](verification/r107resume_verification02.json)全部通过，覆盖完整接续且不重拍旧冻结帧、八帧仍在单session、篡改拒绝、第五CRC失败停采、OFF丢失不采集、未复位不发恢复CAP、导出失败保留八图、进度读半行/无ACK；只允许127.0.0.1，未做新实拍。首轮缺少binding时错误类型处理已修正，原失败日志和源码见verification/history_test01。

[本机入口自检](verification/INSTALL.json)通过；外部IO/完整八请求实板及KEY2恢复仍待完成，release_ready=false、现用09未切换。本轮助手0实体命令/0CAP/0烧写/0网络改动，未联系XDL/TJ。
