# 外部依赖与本地恢复

用户确认没有另行取得 CrazyBingo 相机配置的公开再分发授权，因此将受限第三方材料作为外部依赖处理。公开文件不会通过改名、压缩、编码或 Git 历史携带这些原内容。

## 可以直接做什么

[独立离线回放](quickstart_offline.md)使用完整 004 样例和冻结数值源，禁止网络与硬件访问。该入口不需要恢复外部板级文件。

完整主机 API、GUI 和 FPGA 构建保留原完整性绑定，先恢复外部文件才可使用。缺件时原入口会拒绝运行，不把缺失改写成通过。

## 清单

`external_dependencies.json` 逐项记录 232 个相对路径、原字节数、SHA-256、来源类别和外置原因。210 项为 AMD/Xilinx 相关文件，19 项为 CoreCourse 参考或衍生文件，2 项为 CrazyBingo 相机配置及历史副本，另有 1 个含相关组件的既有 bit。原完整工程候选和原始文件由团队内部保留。

合法取得依赖包括取得适用的软件/IP 或源文件使用许可，并从权利人、板卡资料或已获合法使用权的工程材料获得正确版本。团队 MIT 不为这些组件新增授权。不要从不明来源凑同名文件；恢复器只接受清单约定的精确字节。

## 使用恢复器

先核对，默认不会复制文件：

```powershell
python -B scripts/prepare_external_dependencies.py --source 'D:/licensed_material/guangjian-fpga'
```

所有哈希匹配后，为本地使用恢复文件：

```powershell
python -B scripts/prepare_external_dependencies.py --source 'D:/licensed_material/guangjian-fpga' --apply
```

`--source` 也支持用户已合法取得的原完整交接 ZIP；它只按明确路径读取对应原件，不下载、不连接设备。成功状态为 `LICENSED_DEPENDENCIES_READY`，脚本没有授予许可。恢复文件已列入 `.gitignore`，不得因恢复成功就公开再分发。

恢复后按四份运行文档核对主机 API、GUI 或构建。原始数值核心、bit 身份、来源证明、时序资格和篡改检查仍有效。重新生成的 IP 文件若字节不同，不能擅自改哈希跳过来源校验，应作为另一个工程版本单独验证。

## 比赛交付范围

公开 RAR 与公开 Git 使用同一快照，包含本队源码和外部依赖清单，不包含上述受限原件。它是有明确第三方前置条件的公开源码包，不是所有硬件依赖随包自包含的工程。若赛方要求将这些外部原件一并交付，须先取得对应分发权并按赛方接受的方式处理；不以本库公开状态代替这一确认。

## MIG 副本与内容指纹

本修订补充两处 `ymw/mig_b.prj`，与原清单两处 `prebuilt_ip/.../mig_b.prj` 均为 11,262 字节，SHA-256 `dc9c15d3798d805251ac6509a7dabd2edee14b2e84a050e76064c609606b5954`。统一外置是沿用项目的保守分发策略，并非仅凭 XML 的哈希作出不可分发的法律认定。

`scripts/verify_public_release.py --for-publication` 按字节数和 SHA-256 检查所有公开路径；即使副本换名并被加入文件清单，也拒绝发布。`scripts/verify_public_history.py --all` 检查本地所有可达 Git 引用；正式远端须另用干净克隆核对。合法恢复的登记原件仅供本地检查使用，不因此允许重新公开。
