# XDL Software Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在新XDL目录实现不改检测核心的有限预算曝光软件控制器，并完成真实数据离线回放与TJ整数/动作参考。

**Architecture:** 成像评价提供带分母的整数指标，纯状态机消费逐次观测并输出四状态，回放适配器负责输入身份与成本日志。原检测和整数基元只读加载；独立参考不调用主决策实现。真实回放、合成测试和成本模型各自标记，避免混淆。

**Tech Stack:** Python3.11；unittest；NumPy1.26.4、opencv-python-headless4.10.0.84、Matplotlib3.9.2（沿用现有依赖，无新模型、数据库或硬件接口）。

**Spec:** [DESIGN.md](D:/FPGA/XDL_Software_Controller/DESIGN.md)，用户2026-10-13确认。

状态：用户已确认按计划实施，选择逐任务子代理开发和审核；执行证据见XDL_Results/2026-10-13_software_controller_build/progress.md。

## Global Constraints

- 代码根目录D:\FPGA\XDL_Software_Controller；仅tests为代码子目录。结果根目录D:\FPGA\XDL_Results，按YYYY-MM-DD_software_controller_NN新建，拒绝覆盖。
- 固定CH1、LED128、gain16=16；允许曝光400/500/600/700行，初始600行；不是微秒。
- 原7个检测源码、六份历史结果、原图不修改，不复制第二套检测核心，不初始化D:\FPGA为Git仓库。
- 复用ymw_integer_reference.py；保存图滤波、REFLECT_101、sum9/81、严格>648与>1620、旧board mask/分母不变。共同评价统计另命名、另版本。
- 扫描数据7ccb753ffacff752a5cd65d4b3a13ff7be9875c6/revision=2，只用位置A四档CH1；原检测c5e4bea5cc39cd7b5b587847bce4547bdb3f0a88；已交参考8e7dec0daaedb0f08ef80b707c83ba37de7e7002。
- 重复数据de18e3b604158c1b53b87b08f22ddc59ed52cfe2，两块独立板各三张600行CH1，不作正常真值、不补作扫描A回退确认。
- common面积>=10000像素，且覆盖每帧native board面积>=95%；不足需复核，不偷偷缩小区域。
- 首版实验门槛：有效面积>=9000bp、过暗<=1000bp、灰度近白<=100bp；RGB风险>500bp提示，>1000bp为更高风险。候选更多不等于更好，RGB最大码不直接删除。
- 连续2个同设置独立观测才可离线锁定；灰度均值变化<=2、有效面积变化<=200bp、RGB风险变化<=50bp；变参清零确认计数。
- 最多8次请求/32帧/40000ms；每请求3丢弃+1评估，设置/等待1000ms、每帧模型1000ms，因此Cost(1,4,5000)；每档采集错误最多重试1次。
- 所有比较使用整数或交叉乘积；JSON严格禁止NaN，零分母记录null，新增累计uint64/交叉乘积不窄化到32位。
- 四结果CONTINUE_ADJUST、LOCKED、NEEDS_REVIEW、CAPTURE_FAILED；LOCKED仅离线策略意义，不宣称真实设置、光照生效或FPGA闭环。
- 模型请求/消耗/预留成本与历史实拍成本分栏；measured_live_control_cost=null。缺帧不复用原图假装新实拍。
- 不新增LED/增益搜索，不运行硬件，不报告准确率/正常误报率/最佳曝光/可靠噪声表。
- 本轮仅本地交付；后续明确要求上传时才更新XDL分支/PR15，不合并main。

## Review Focus

1. 重复内容但合法不同帧身份：按固定索引的来源身份判新观测，不靠像素差大小认定新帧；同来源重复/伪造身份不可增加确认。由任务3、5测试。
2. ROI混合全图/裁剪与评价面积缩水：统一全画面坐标，保持原滤波域，未覆盖或交集过小必须需复核。由任务2、6测试。
3. 未知采集时间、重叠累计日志：模型不是实测，001前缀不可相加，缺失日志不给零成本通过。由任务5、6测试。
4. 源码/配置/ZIP损坏或路径逃逸：默认拒绝未知键、bool充整数、非法ROI、哈希错误与压缩包越界；拒绝覆盖输入/结果。由任务1、5、6测试。
5. 回放提前看到未来、更换样件或终止后进图：适配器可预核验数据，主决策只能看到消费历史，跨位置/样件拒绝，终止后不能再动作。由任务3、6测试。

## File Structure and Shared Types

根目录新建config.json、capture_metrics.py、acquisition_control.py、fpga_reference.py、dataset_io.py、replay.py、run_tests.py、requirements.txt、README.md、repeat_regions.json。dataset_io.py是数据边界的小辅助文件，不增加目录或新功能范围；tests/各模块独立测试。

capture_metrics.py定义FrameInput（context_id、observation_id、sample_id、pose为str；exposure_lines、gain16、channel、led、saved_width、saved_height为int；roi为(x,y,width,height)四整数；png_sha256、rgb565_sha256、source_mode为str；source_metadata为dict，含文件/ZIP成员定位及不可变来源身份）、EvaluationArea（全画面共同bool mask、源/哈希/覆盖记录）、FrameMetrics（n、gray_sum、dark_count、near_white_count、rgb_max_count、effective_count、line_center_count、line_contrast_sum_n、background_count、background_activity_sum_n、baseline_candidate_count、native_reference_statistics、geometry记录）。

FrameMetrics所有计数为非负Python int，0<=计数<=对应分母，gray_sum<=255n，abs残差和<=20400×对应像素数；native_reference_statistics及geometry为dict，不替代公共整数指标。必须检查dark_count+near_white_count<=n、effective_count>=n-dark_count、background_count+line_center_count==n；灰度总和必须处在三个灰度分区计数给出的可达上下界内。background_count=0时背景均值为null，排序排在背景值已知的设置之后，不能补0获得优势。

acquisition_control.py定义ControllerConfig、Cost(attempts,frames,time_ms)、CaptureEvent(kind,context_id,observation_id,exposure_lines,metrics,error_code)、Decision(status,action_kind,next_exposure_lines,reason_codes,input_statistics,budget)、ControllerSnapshot。CaptureEvent.kind仅observation、capture_error、missing_data，metrics/error_code允许None。状态包含visited、seen_observation_ids、qualified历史、确认参考/次数、fallback_used、按档retry_count、pending_request、requested_cost和consumed_cost。

ControllerConfig字段固定为rule_version、threshold_status、cost_status、channel、led、gain16、exposures、initial_exposure_lines、min_area、min_coverage_bp、min_effective_bp、max_dark_bp、max_near_white_bp、rgb_warn_bp、rgb_review_bp、confirmations、max_mean_delta_gray、max_effective_delta_bp、max_rgb_delta_bp、max_attempts、max_frames、max_time_ms、discard_frames_per_request、frame_time_ms、settle_time_ms、retry_limit；默认值对应Global Constraints。JSON只接受这些字段，不允许私自添加动态硬件动作开关。

初始请求与后续请求先预留模型成本；成功观测/错误事件提交待处理请求成本，不双计。missing_data终止需复核并记录未兑现请求成本，不伪造真实消耗。状态机中next_exposure是下一请求参数，不代表已执行硬件写入。

## Task 1: 配置、依赖桥接和保留校验

**Files:** Create config.json、requirements.txt、run_tests.py；Create capture_metrics.py的依赖桥接和acquisition_control.py的ControllerConfig/Cost；Test tests/test_configuration.py。

**Interfaces:**
- ControllerConfig.from_dict(payload: dict) -> ControllerConfig；validate() -> None；request_cost -> Cost。
- load_algorithm(algorithm_root: Path, expected_results: Path) -> dict：返回integer_gray、integer_h2、integer_thresholds、board_mask、assess_quality、hysteresis_connect，先核验固定源码及整数基元哈希。
- preservation_snapshot(paths: list[Path]) -> dict[str,str]，只读SHA256，供最终对照。

- [ ] Step 1: 写测试default_values_exact、reject_unknown_key_bool_nan_bad_exposure、request_cost_exact、reject_changed_source、missing_algorithm_has_clear_error、snapshot_is_read_only。断言exposures==(400,500,600,700)、gain16==16、LED==128、request_cost==Cost(1,4,5000)，配置非法均抛ValueError，源码改变拒绝。
  首个红灯用例（其余测试按Step 1补全）：
  ```python
  def test_default_values_exact(self):
      cfg = ControllerConfig()
      cfg.validate()
      self.assertEqual(cfg.exposures, (400, 500, 600, 700))
      self.assertEqual((cfg.initial_exposure_lines, cfg.gain16, cfg.led), (600, 16, 128))
      self.assertEqual(cfg.request_cost, Cost(1, 4, 5000))
      with self.assertRaises(ValueError):
          ControllerConfig.from_dict({'initial_exposure_lines': 450})
  ```
- [ ] Step 2: 在新目录运行 `python -m unittest discover -s tests -p test_configuration.py -v`，确认因未实现接口失败，不把环境/语法错误当作有效红灯。
- [ ] Step 3: 只实现上述接口，写严格config.json并标记rule_version=controller-0.1、threshold_status=provisional、cost_status=modeled。依赖沿用三份精确版本；外部源码只读加载，不依赖工作目录或另设PYTHONPATH。
- [ ] Step 4: 同一命令应全通过；运行原software/run_tests.py，记录77项基线是否通过。
- [ ] Step 5: 记录本任务测试与源码快照检查点；当前非Git，不初始化/提交/上传。

## Task 2: 坐标一致的整数成像评价

**Files:** Extend capture_metrics.py；Test tests/test_capture_metrics.py。

**Interfaces:**
- build_common_area(frames: list[FrameInput], native_masks: list[np.ndarray], sensor_shape=(1080,1920)) -> EvaluationArea。
- line_centers(residual_n: np.ndarray, mask: np.ndarray) -> np.ndarray[bool]。
- compute_metrics(image_bgr: np.ndarray, frame: FrameInput, native_mask: np.ndarray, area: EvaluationArea, algorithm: dict) -> tuple[FrameMetrics,dict[str,np.ndarray]]。
- compare_repeats(records: list[tuple[FrameInput,FrameMetrics,dict]], area: EvaluationArea) -> dict。

- [ ] Step 1: 写full_and_crop_same_full_coordinates、intersection_cannot_shrink_silently、reflect_border_unchanged、strict_threshold_equality、rgbmax_is_counted_not_deleted、line_three_same_sign_no_wrap、different_sign_not_line、zero_union_iou_is_null、different_sample_or_setting_not_repeat。用gray=128常量断言sum9=10368、residual_n=0；±648不weak，±1620不strong。用独立手算的水平3点断言仅中心为线状见证；第一列不能与最后列连接。
  首个红灯用例：
  ```python
  def test_line_three_same_sign_no_wrap(self):
      residual = np.zeros((9, 9), dtype=np.int16)
      residual[4, 3:6] = 810
      found = line_centers(residual, np.ones((9, 9), dtype=bool))
      self.assertEqual(int(found.sum()), 1)
      self.assertTrue(found[4, 4])
      residual[:] = 0
      residual[4, [8, 0, 1]] = 810
      self.assertEqual(int(line_centers(residual, np.ones((9, 9), bool)).sum()), 0)
  ```
- [ ] Step 2: 跑 `python -m unittest discover -s tests -p test_capture_metrics.py -v`，看到正确断言/接口失败。
- [ ] Step 3: 实现同坐标mask交集、旧native统计和新common统计分栏。有效面积按gray>10或weak；线状四方向同符号三点；背景为非线状中心。旧候选在完整保存图按旧质量/连接计算后裁到评价mask，不提前删board外连接支撑。保存图滤波不随common区域变。
- [ ] Step 4: 同一测试命令全通过；用旧NPZ与黄金统计对照四档native H1/H2，不以common分母替代native分母。
- [ ] Step 5: 记录掩码/计数测试检查点和新增位宽范围。

## Task 3: 有限预算决策与确认/回退

**Files:** Extend acquisition_control.py；Create tests/fixtures.py；Test tests/test_acquisition_control.py。

**Interfaces:**
- Controller(config: ControllerConfig, context_id: str)；start() -> Decision；feed(event: CaptureEvent) -> Decision；snapshot() -> ControllerSnapshot。
- classify(metrics: FrameMetrics, config: ControllerConfig) -> dict；better_setting(left: dict,right: dict) -> bool。
- 测试fixture make_metrics(**overrides) -> FrameMetrics：默认n=10000、gray_sum=1000000、effective_count=10000、dark_count/near_white_count/rgb_max_count/line_center_count/line_contrast_sum_n/baseline_candidate_count=0、background_count=10000、background_activity_sum_n=0、native_reference_statistics={}、geometry为有效覆盖的来源记录；可显式覆盖完整字段名。
- 测试fixture make_frame(**overrides) -> FrameInput：默认context_id='scan_A'、observation_id='fixture-1'、sample_id='sample001'、pose='A'、曝光600、gain16=16、CH1、LED128、保存100×100、roi=(0,0,100,100)、source_mode='constructed_fixture'；source_metadata含固定dataset_id/capture_id/frame_id/member/hash身份，storage_root不参与身份；哈希字段为合法64位十六进制测试值。

- [ ] Step 1: 写normal_zero_candidates_locks_after_two、highlight_moves_down、dark_moves_up、dark_and_glare_reviews、threshold_equality_is_accepted、candidate_more_cannot_win、budget_reservation_not_double_counted、capture_error_retries_once、missing_confirmation_reviews、duplicate_source_rejected、distinct_verified_ids_with_identical_pixels_allowed、parameter_change_resets_streak、fallback_requires_new_frames_once、no_search_oscillation、wrong_context_rejected、terminal_feed_rejected。
  正常两帧断言动作confirm_current→LOCKED；从600行高光>500bp断言下一500；500行过暗>1000bp且低高光断言下一600。预算不足下一完整请求时不得发CONTINUE；missing_data不增加成功观测数。
  首个红灯用例：
  ```python
  def test_normal_zero_candidates_locks_after_two(self):
      controller = Controller(ControllerConfig(), 'normal_fixture')
      self.assertEqual(controller.start().next_exposure_lines, 600)
      first = CaptureEvent('observation', 'normal_fixture', 'r01', 600, make_metrics(), None)
      second = CaptureEvent('observation', 'normal_fixture', 'r02', 600, make_metrics(), None)
      self.assertEqual(controller.feed(first).action_kind, 'confirm_current')
      self.assertEqual(controller.feed(second).status, 'LOCKED')
      self.assertEqual(controller.snapshot().consumed_cost, Cost(2, 8, 10000))
  ```
- [ ] Step 2: 跑 `python -m unittest discover -s tests -p test_acquisition_control.py -v`，确认规则测试先失败。
- [ ] Step 3: 实现规格优先级和严格整数比较。dark_count>1000bp或effective_count<9000bp属于信号不足；rgb_max_count>500bp或near_white_count>100bp属于高光风险，两者同时存在需复核。RGB>1000bp附加高风险原因但不删候选。候选不进入最好设置排序；排序RGB风险低→有效面积高→背景低→曝光低。search每档一次，fallback最多一次；当前同档也可以明确fallback重启确认，不能复用旧确认。加入inconsistent_partition_counts_rejected及unknown_background_cannot_win测试。
- [ ] Step 4: 跑同一命令全通过，并核对全部事件的requested/consumed/pending成本。保存身份依据不可变来源记录，不接受调用者临时换UUID包装同一来源。
- [ ] Step 5: 保存四状态覆盖、动作覆盖和预算检查点。

## Task 4: 独立整数与动作对照

**Files:** Create fpga_reference.py；Test tests/test_fpga_reference.py。

**Interfaces:**
- scalar_metric_reference(gray: np.ndarray, residual_n: np.ndarray, rgb_max: np.ndarray, mask: np.ndarray) -> dict。
- reference_transition(snapshot: dict,event: dict,config: dict) -> tuple[dict,dict]：不得调用Controller.feed/classify/better_setting。
- verify_reference(cases: list[dict], actual: list[dict]) -> dict；export_golden(cases: list[dict], destination: Path) -> None。

- [ ] Step 1: 写scalar_matches_hand_count、vector_scalar_random_masks、reference_matches_all_rule_boundaries、reference_diff_is_detected、width_bounds_not_uint32、goldens_mark_source_type。对primary动作的下一档或reason篡改一项，独立对照必须失败。
  首个红灯用例：
  ```python
  def test_scalar_matches_hand_count(self):
      gray = np.full((9, 9), 128, dtype=np.uint8)
      residual = np.zeros((9, 9), dtype=np.int16)
      residual[4, 3:6] = 810  # 构造整数输入，不冒充gray的实测H2
      values = scalar_metric_reference(gray, residual, np.zeros((9, 9), bool), np.ones((9, 9), bool))
      self.assertEqual(values['line_center_count'], 1)
      self.assertEqual(values['line_contrast_sum_n'], 810)
      self.assertEqual(values['background_count'], 80)
      self.assertEqual(values['background_activity_sum_n'], 1620)
  ```
- [ ] Step 2: 跑 `python -m unittest discover -s tests -p test_fpga_reference.py -v`，确认先失败。
- [ ] Step 3: 独立逐点实现新增线状/背景统计；复用冻结H1/H2不另定灰度。独立按规格表进行事件转换，保留同参数确认和预算状态；黄金参考输入保留完整统计/配置/事件，而非仅保存主实现输出。
- [ ] Step 4: 同一命令全通过；报告计数、累计、交叉乘积所需位宽，所有边界整数精确相等。
- [ ] Step 5: 保存TJ人工构造统计向量、预期动作与独立核验检查点。

## Task 5: 原始数据适配与重复成本

**Files:** Create dataset_io.py、repeat_regions.json；Test tests/test_dataset_io.py。

**Interfaces:**
- load_scan_inputs(scan_root: Path, expected_results: Path) -> list[FrameInput]。
- load_repeat_inputs(repeat_root: Path, regions: Path) -> list[FrameInput]。
- read_frame(frame: FrameInput) -> np.ndarray。
- historical_cost(repeat_root: Path) -> dict；source_identity(frame: FrameInput) -> str。

- [ ] Step 1: 用临时目录/微型ZIP写reject_wrong_revision_pose_gain、verify_all_members、zip_member_escape_rejected、bad_crc_or_hash_rejected、duplicate_frame_provenance_rejected、three_repeats_per_board_separate、overlapping_session_prefix_not_added、missing_log_unknown_not_zero。匹配001完整接收884、002接收12、合计896；仅有重叠前缀不能相加为1536或伪造已知总量。
  首个红灯用例：
  ```python
  def test_storage_location_is_not_new_provenance(self):
      original = make_frame()
      moved = dataclasses.replace(original, source_metadata={**original.source_metadata, 'storage_root': 'other'})
      self.assertEqual(source_identity(original), source_identity(moved))
  ```
- [ ] Step 2: 跑 `python -m unittest discover -s tests -p test_dataset_io.py -v`，确认先失败。
- [ ] Step 3: 按索引原文件身份读取，禁止路径逃逸；扫描核验198成员，选取同位置A四档CH1。重复核验六ZIP/24成员和四份日志；优先内存读ZIP，避免增加一份原图副本。读回/帧号/配置代数按来源记录，不声称物理生效。
- [ ] Step 4: 实施时获取固定提交的新ZIP/索引/日志到D:\FPGA\YMW\ch1_repeat_defect_near_normal_20261013，读取YMW提供脚本内容但不自动执行未审查脚本。查看两块板各第一原帧，分别记录软件近似四边形、来源图哈希及manual_review_pending到repeat_regions.json；每组三帧固定同一多边形，不复用旧扫描位置或另块板区域。人工复核标志保留证据等级；覆盖不足/几何矛盾明确需复核，不声称自动定位通过。
- [ ] Step 5: 跑同一测试命令通过；验证两板各3张、600/16/128/CH1和PNG/RGB565一致。若数据取得失败，只交已完成部分并明确重复验证未完成，不用旧图替代。

## Task 6: 可追溯回放与结果日志

**Files:** Create replay.py；Test tests/test_replay.py。

**Interfaces:**
- replay_sequence(inputs: list[FrameInput], config: ControllerConfig, evaluate: Callable[[FrameInput],tuple[FrameMetrics,dict]]) -> dict：至少含decisions（逐事件dict）、final_decision（Decision字段dict）、consumed_observation_ids和modeled_control_cost。
- run_scan(inputs: list[FrameInput], config: ControllerConfig, algorithm: dict) -> dict。
- run_repeat_study(inputs: list[FrameInput], config: ControllerConfig, algorithm: dict) -> dict。
- sensitivity_runs(inputs: list[FrameInput], config: ControllerConfig, algorithm: dict) -> list[dict]。
- write_run(output: Path, payloads: dict) -> None；main(argv=None) -> int。

- [ ] Step 1: 写unseen_future_metrics_cannot_change_action、scan_missing_confirm_not_reused、repeat_not_scan_confirmation、three_cost_categories_separate、modeled_time_not_walltime、output_existing_or_inside_inputs_rejected、json_nan_rejected、bad_cli_nonzero、partial_evidence_not_passed、log_reconstructs_requested_consumed_pending。
  首个红灯用例：
  ```python
  def test_scan_missing_confirm_not_reused(self):
      result = replay_sequence([make_frame()], ControllerConfig(), lambda frame: (make_metrics(), {}))
      self.assertEqual(result['final_decision']['status'], 'NEEDS_REVIEW')
      self.assertIn('missing_fresh_confirmation', result['final_decision']['reason_codes'])
      self.assertEqual(len(result['consumed_observation_ids']), 1)
  ```
- [ ] Step 2: 跑 `python -m unittest discover -s tests -p test_replay.py -v`，确认先失败。
- [ ] Step 3: 实现按Controller pending档查找第一个尚未消费同context来源，缺失生成missing_data。允许预计算诊断表和mask，但不预装未来统计进Controller。分别运行scan_A、repeat_001、repeat_002，不混合数据或成本。没有缺陷候选也运行同一质量流程。
- [ ] Step 4: 导出frame_metrics.json/csv、decisions.json/csv、repeat_stability.json/csv、golden_actions.json、config/provenance/verification、mask和复核叠加图。JSON事件含输入统计→下一动作→停止原因、身份/版本和三类成本。敏感性至少9种组合（有效面积85/90/95%×RGB提示3/5/8%），逐组合记录动作依赖，不调优准确率。
- [ ] Step 5: 跑同一测试命令全通过；真实扫描即便输入只有各一图也必须如实缺确认停止。measured_live_control_cost始终null；source_mode区分实拍历史回放、合成图和构造统计。

## Task 7: 全量复跑、说明与交付审核

**Files:** Create README.md；Extend run_tests.py；Test tests/test_integration.py；Results only new dated directory.

**Interfaces:** README命令必须能独立使用；verification.json包含offline_verified、provisional_thresholds、hardware_validation_pending、source_unchanged、historical_results_unchanged及逐项证据，缺项不得passed=true。

- [ ] Step 1: 写cli_help_and_clean_cwd、full_scan_reference_counts_match、repeat_6_frames_completed、preservation_hashes_equal、commands_do_not_touch_hardware、every_golden_action_independently_matches。真实数据集成测试显式接收路径；若路径缺失可以跳过但验证总表必须列未完成，不能将跳过写成数据验收通过。
  首个红灯用例：
  ```python
  def test_cli_help_and_clean_cwd(self):
      entry = Path(__file__).resolve().parents[1] / 'replay.py'
      result = subprocess.run([sys.executable, str(entry), '--help'], capture_output=True, text=True)
      self.assertEqual(result.returncode, 0)
      self.assertIn('--algorithm-root', result.stdout)
      self.assertIn('--repeat-root', result.stdout)
  ```
- [ ] Step 2: 先运行集成测试，确认未实现入口/交付文件失败；没有数据导致skip不算有效红灯，也不计完成。
- [ ] Step 3: README写出安装、测试、复跑、目录说明、规则版本、整数契约、实验门槛/模型成本、缺确认帧及实板待验事项。run_tests.py发现tests/并用退出码反映失败。
- [ ] Step 4: 在controller目录运行以下全量命令（输出NN必须全新）：
```powershell
python -m pip install -r requirements.txt
python run_tests.py
python D:\FPGA\XDL_Algorithm\software\run_tests.py
python replay.py --algorithm-root D:\FPGA\XDL_Algorithm\software --scan-root D:\FPGA\YMW\YMW_manual_20261013 --expected-results D:\FPGA\XDL_Results\2026-10-13_manual_exposure_gain --repeat-root D:\FPGA\YMW\ch1_repeat_defect_near_normal_20261013 --regions repeat_regions.json --config config.json --output D:\FPGA\XDL_Results\2026-10-13_software_controller_01
```
  预期原77项及新测试通过；scan4、repeat6完整；独立统计/动作对照通过；输入哈希不变。需复核是合法回放结果，不是程序测试失败；缺失验证材料不是全量通过。
- [ ] Step 5: 复跑一次到_02，比较除墙钟/输出路径/时间戳外的稳定字段。检查Markdown文件入口、JSON/CSV行数、所有动作成本、无码生成文件混入交付、没有对相机/LED/FPGA的真实写入。
- [ ] Step 6: 全任务完成后使用requesting-code-review安排一次独立只读审核，针对上述Review Focus核对实物文件和结果；修正问题再重新验证，不为审核新开用户任务。
- [ ] Step 7: 本地交付README、新目录与运行结果链接，明确软件验证范围和实板未验范围。未经新上传要求，不改远程PR。

## Plan Self-Review

规格覆盖：身份/保留→任务1/5；共同ROI与指标→任务2；阈值/状态/预算/回退→任务3；独立参考→任务4；重复/历史成本→任务5；回放/日志/敏感性→任务6；原77项/新完整证据/说明→任务7。没有LED/增益/真实调参扩展。

类型与命名核对：后续任务共用FrameInput、EvaluationArea、FrameMetrics、ControllerConfig、CaptureEvent、Decision、ControllerSnapshot和Cost；统计字段保持n及明确count/sum，状态机接口只依赖已定义事件，不读未来帧。

五个Review Focus均有任务中的对应测试；原始文件身份、模型成本和物理证据等级分别处理，候选数不进入质量锁定门槛。没有以未知时间或缺帧补零通过的捷径。

执行方式推荐Native：由主代理在当前对话逐任务测试驱动实现，最后一次独立只读审核。模块依赖紧密，逐任务换实施代理增加接口交接成本。用户可改选逐任务子代理实施/审核，执行前需审阅本计划并选择方式。

