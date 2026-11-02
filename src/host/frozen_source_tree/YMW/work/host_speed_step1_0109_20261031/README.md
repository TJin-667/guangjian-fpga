# 0109提速第一步：精确残差访问缓存

2026-10-31。**第一步软件候选验证通过：相同原片下，完整主机后处理和图文导出中位数缩短4.20%～5.49%，检测与复检结果精确一致。尚未接入现用窗口，不代表整机已加速。**

## 本步改动

冻结复检会在八帧、亮暗两种极性下重复访问同一条路径的整数坐标。新增访问器复用最近一组坐标的tile分组、局部下标和各帧已取值结果；坐标变化立即失效。索引按内容比较，返回独立可写数组，避免索引或返回值原位修改造成错误。

原64像素tile、256项LRU、精确`81×gray−sum9`及REFLECT101边界计算仍由原访问器承担。所有R32、质量和来源灰度核验保持。没有预计算八张完整残差来替代PL，没有改阈值、复检规则或冻结代码。

实现：[cached_residual.py](cached_residual.py)，具体范围和顺序：[PLAN.md](PLAN.md)。适配仅发生在本次独立上下文，未修改共享模块、旧程序或默认入口。

## 同输入对照

输入来自已独立验收的实板套件`E:/GuangjianData/SystemBenchmark0109/20261031_090644_5defee3a`。每个源组内的八张原片、mask和R32完全相同；两方法各运行三次，交替执行，每次重建上下文和缓存，OpenCV固定一线程。下面均为三次中位数，加载/输入核验和随后独立证明不计入该阶段。

| 测量区间 | 原片组标签 | 原访问器/s | 新访问器/s | 时间减少 |
|---|---|---:|---:|---:|
| 上下文＋冻结计算，不含导出 | 04_PL_warm_r1 | 12.3671 | 11.6587 | 5.73% |
| 上下文＋冻结计算，不含导出 | 08_PC_warm_r2 | 7.5710 | 7.2967 | 3.62% |
| 上下文＋冻结计算＋完整图文导出 | 03_PL_cold_r1 | 11.7403 | 11.2470 | 4.20% |
| 上下文＋冻结计算＋完整图文导出 | 12_PL_warm_r3 | 17.8443 | 16.8645 | 5.49% |

完整导出两组每次分别保留2个和6个复检窗口，没有减少窗口、跳过图片或关闭核验来换速度。首组完整导出中位数节省0.4934秒，另一组节省0.9798秒。

源组标签中的`PC/PL/cold/warm`是原采集身份；本步两个方法都执行原R32混合主机延续流程，**不是PC与PL整机对照**。08组使用原PC计算并已核验等价的R32字，其余三组使用保存的板端R32。每组独立比对，不把这些不同原片相互当作同输入。

全部24次正式回放中，十项检测数组、完整复检JSON和评分身份与相应实板存档均相同。原参数组合仍为`f09eb5885e1d`。

## 正确性、图文和内存核验

- [索引自检](verification/SELFTEST.json)：独立密集H2参考、四边反射、跨tile、广播、标量、空索引、坐标修改、返回值修改、LRU逐出、灰度输入别名及7类非法索引拒绝均通过。
- [完整导出二次核验](verification/EXPORT_AUDIT.json)：60对导出图片逐像素一致，360个本地链接存在，134项原0109资格源成员哈希不变，执行源码与回执相同。
- 保持原tile缓存上限。本次首个试跑组的7280次访问中，455次构造坐标计划、6825次复用计划、3640次复用已取值。该组额外计划数组峰值6400字节，原tile缓存峰值2,031,616字节。其他组的原始计数保留在结果回执中；该数值不是整个Python进程内存峰值。
- 原bit重新计算SHA256仍为`84530057679198ec1b7bd700c0bb9a97d803d605ac82db24b58f01161d4ac30e`。无RTL/SDK/冻结算法改动，无新CAP、烧录或板卡联系；也没有改Cisco、网卡或防火墙。

## 如何解读

收益属于原片已经在主机RAM、R32已经可读后的软件阶段。完整导出区间包含原冻结检测、弱段增强、复检、压缩数组、图片和报告；不含相机采集、mask上传、质量表上传、FUSE或R32 FETCH。

本次四组仍来自同一块004开发板，不是独立质量测试集，也不是多机器性能统计。三次重复用于核对稳定性，未声明统计显著性或全局最优。

此前[实板系统对照](../system_benchmark_0109_physical_review_20261031/README.md)的PC连续25.438秒、PL连续36.461秒保持原记录。不能从原整机时间简单减去本步节省值，生成一个未实测的整机加速比。`cProfile`结果只用于找开销，不能作为正式计时样本。

## 复现

使用原项目Python环境，输出为全新E盘目录。脚本禁止socket访问，原片和现用入口只读。

```powershell
python -B test_residual.py --out E:/GuangjianData/reviews/新的索引自检目录

python -B run_study.py --suite E:/GuangjianData/SystemBenchmark0109/20261031_090644_5defee3a --out E:/GuangjianData/reviews/新的计算对照目录 --groups 04_PL_warm_r1 08_PC_warm_r2 --repetitions 3

python -B run_study.py --suite E:/GuangjianData/SystemBenchmark0109/20261031_090644_5defee3a --out E:/GuangjianData/reviews/新的完整导出目录 --groups 03_PL_cold_r1 12_PL_warm_r3 --repetitions 3 --export

python -B verification/audit_exports.py --study E:/GuangjianData/reviews/新的完整导出目录 --out E:/GuangjianData/reviews/新的图文核验目录
```

完整新输出保存在`E:/GuangjianData/reviews/host_speed_step1_0109_20261031/`的`profile_01`、`selftest_01`、`pilot_01`、`full_export_01`和`export_audit_01`。Git只发布代码、原生计时/证明回执和索引，不重复上传原片或所有新图片。计时程序自身的执行哈希见[试跑源绑定](verification/PILOT_EXECUTED_SOURCES.json)和[导出源绑定](verification/FULL_EXECUTED_SOURCES.json)。

## 下一步

将本候选保留为第一步结果。下一步优先评估如何复用采集工程核验已生成的H2/质量中间结果，保持帧身份、来源绑定及全部检测/复检结果一致，避免后处理重复生成。之后再安排独立候选入口接入与整机复测；本步无需用户重拍或下载bit。
