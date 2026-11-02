# v1.5职责更新：计算核心不变

PL/PC算法分工及f09数学保持不变。v1.5在主机加入计时包装和原生证据复用：完整CRC/metadata/H1/H2及同输入审计先完成，随后可凭源/SDK/资格/loader绑定和原始planes逐字节核对，避免采后重复计算整图CRC/H2。完整audit模式保留；采集阶段原工程金标准仍在运行。

49/50仅改变图像传输格式，正式8gray/SAT及R32证据保留；默认50，49仍待本次实板确认。无新RTL/bit。PERFORMANCE使用主机墙钟，嵌套不可累加，FPGA纯周期/加速比未测字段为null。当前普通“offload0108”发布gate仍未放开。

详见[性能与精确复用交付](../performance_closure_20261030/README.md)。下文的核心数据流继续适用。

---

# Final system architecture and interface v1.5

Status: frozen engineering algorithm f09eb5885e1d is installed in both the stable0107 PC path and the0108 archive/native-plane path. Existing0108 has real same-input functional evidence; interface/reset release qualification is still pending. This update changes host parameters via the immutable frozen API, with no bit or RTL change.

## Fixed algorithm and responsibilities

Parameter combination `f09eb5885e1d`, detector `387cfeac0426`; original review/scoring core `9a2a91e` with frozen raw-support55% and endpoint-line28% overrides. Detection supplement thresholds are5.2/12; its own line gate remains60%. Formal exposure is400/800 sensor lines, gain16=16, LED128. Other exposures are explicitly marked experimental replay. Both workers call `final_parameter_check_20261030/frozen_runtime.py:process`; the integration layer does not implement a second detector or change scoring mathematics.

| Function | Target owner | Reason |
|---|---|---|
| Sensor/light sequencing, ROI, frame ownership, DDR and transport | PL | Existing deterministic acquisition path |
| Exact RGB565 gray, SAT and REFLECT_101 signed9x9 residual | PL | Reusable fixed-point local computation |
| Exact32x32 validity table | PC in final v1 | Preserve frozen percentile semantics; upload sealed table tied to actual frame |
| Eight-observation max-valid-absolute response, signed value and earliest source | PL | Shared pixel core, incremental DDR state |
| Whole-ROI8-connected hysteresis, board mask, seeded supplements and constrained endpoints | PC | Global topology and frozen geometric/raw-profile checks |
| Large-gap review, evidence support score, UI, archive | PC | Full eight-frame gray evidence, exact on-demand per-frame residual access and inspectable reasons |

Stable0107 performs the same mathematical preprocessing/fusion on PC. Both backends must produce one identical native-plane contract. UI code must not infer which side computed a value or implement detection math.

## Preserve eight-frame evidence without an extra full residual transfer

The frozen review requires logical access to **all eight actual per-frame signed residuals**, not just the final maximum response. Geometry/raw-profile checks also retain all eight gray/valid planes. Returning onlyR32 plus selected-source gray cannot satisfy the contract. Existing0108 already retains the actual eight raw frames; those exact gray values determine their per-frame residuals uniquely.

The selected target uses a bounded host tile cache (`ResidualAccess`) to reconstruct the exact numerator only where frozen review requests native coordinates. Tiles have four-pixel halos with savedROI REFLECT_101 mapping. No threshold, score or proposed path changes. Thus PL still computes full-frameH2 and eight-frame fusion; PC performs only the requested local residual calculations for review. This is an explicit division of work, not a claim that every residual calculation is on PL.

`hybrid.py` consumes native eightGRAY8/SAT planes and losslessR32, applies the frozen PC validity rule and all frozen postprocessing, then supplies on-demand residuals to review. Initial acceptance used software-packed referenceR32; subsequent real0108 saved-input comparisons verified the same native-plane/result path. New frozen-host integration is checked by replaying those real archives without contacting hardware. The ordinary live0108 production backend is blocked pending board acceptance. A separately labeled UI engineering action prepares a plan offline, then runs the qualified executor only after an operator confirms bit and pose. Strict physical archives can be imported into the frozen final pipeline; software peer fixtures cannot masquerade as board evidence. No full-frame PC fallback is labeled as fully offloaded, and no fused residual substitutes for individual-frame evidence.

EightGRAY8+SAT1 payloads cost9P bytes plus finalR32 at4P, totaling13P before protocol overhead in gray-evidence mode. RGB/debug modes cost more. Exporting eight additionalR16 planes would add16P and require new wire logic; the exact local-access method avoids that extension. No total-time or bandwidth improvement is claimed from these payload calculations. Benchmarking remains deferred by user.

## Common native-plane contract

- Fixed order: CH1_low,CH1_high,CH2_low,CH2_high,CH3_low,CH3_high,CH4_low,CH4_high.
- One immutable group/specimen/pose, complete frame/session/request identity, actual exposure/gain/light readbacks, format and coordinate metadata.
- `gray`: uint8[8,H,W]; `sat1`: binary bool or uint8[8,H,W] (0/1 only, preserving original archives); `valid`: bool[8,H,W]; `board`: bool[H,W]. `residual_n` is a logical signed-int16[8,H,W] value source: dense arrays on the stable backend, or exact frame/y/x access with a bounded host cache on the hybrid backend.
- Residual unit is numerator `81*gray-sum9`, no early division/rounding. Reflect domain is the entire savedROI.
- All computation coordinates refer to native savedROI. Sensor coordinates add the recordedROI origin; display headers and zoom transforms never enter computation.
- Final fusion retains signed residual, source0/1..8 and unknown. Legacy8/20 flags are baseline fields; current5.2/12 and controlled supplements remain PC frozen postprocessing.
- Result records identify detector/review configurations, source manifests, native/sensorROI, formal mask, review windows/score/reasons and archive locations.

## Transaction and UI ownership

One owner controls hardware. Preview/capture/OFF cannot overlap. Detection is an isolated offline worker process and opens no socket. Capture succeeds only after complete archive andOFF acknowledgment; failed or cancelled groups never automatically enter detection. Cancelling analysis preserves acquired frames and all partial diagnostics. Closing the application waits for capture cancellation/OFF or offline worker termination.

UI uses the existingr5.6 bounded/latest preview mechanism at target2fps and1000-frame budget, coalesced viewport rendering and background processing. Capture and final detection/review live in one window. Independent legacy launchers remain untouched.

The dedicated0108 launcher opens its action page by default. `focus0108.py` privately compiles the unchanged original fast-focus source with only its workflow dependency bound to the qualified0108 SDK/runtime; the original module cache and files remain untouched. This preserves native CRC, identity, freshness, pause/resume/OFF and bounded display semantics without accepting0108 through the0107 firmware gate. The preview still excludes masked H1/H2/formal detection qualification and remains non-training data.

Existing0108's `source_roi_*` execution geometry is latched only by CAP, whereas ROI_SET updates separate configuration registers. BEGIN reads the execution geometry and rejects a new cropped mask after a full-frame preview. v1.3 therefore performs one strict native ROI preparation capture in the same executor before BEGIN. It is independently committed, excluded from the eight fusion slots and source numbering, and explicitly counted in cost. The actual RTL latch behavior and the real SDK over a matching software-peer model are covered separately. This is an engineering compatibility path, not a new bit or a claim that the preparation cost has been eliminated.

## Qualification

BRAM remains below80%; existing0108 routed report is a candidate resource result, not physical acceptance. The final host adapter preserves the original executor's DDR write-completion, group publication, identity and reset guards; cancellation adds cooperative stop with OFF cleanup. No new RTL is needed merely to replace dense host residual storage by exact on-demand access. The unchanged ad2f0422 bit is reused as a final system engineering candidate, with source/build/checkpoint binding retained. Real same-input functional acceptance has been recorded; final interface/reset release checks and reserved-specimen evaluation remain separate. One routine future capture can confirm the new host UI path end to end, without repeating the completed old-bit tests. PC/FPGA speed comparisons remain a separate deferred task.
