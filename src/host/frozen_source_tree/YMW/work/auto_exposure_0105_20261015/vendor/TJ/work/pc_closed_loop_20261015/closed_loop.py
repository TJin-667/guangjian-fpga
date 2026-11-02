"""Transport adapter for unchanged XDL rules; logical identity is not optical proof."""
from dataclasses import fields, is_dataclass
import hashlib
import json
from pathlib import Path
import time
import uuid

import cv2
import numpy as np

from dependencies import digest, json_read, verify_dependencies
from transaction_cost import proven_frames

IDENTITY_BOUNDS = dict(session=2**64, request_id=2**32, config_epoch=2**32,
                      dvp_sequence=2**32, publish_sequence=2**32,
                      roi_generation=2**16, camera_generation=2**16,
                      light_generation=2**16, frame_id=2**16, bank=2)


def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    return value


def canonical(value):
    return json.dumps(plain(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def save_json(path, value):
    Path(path).write_text(json.dumps(plain(value), ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")


class AdapterError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def decode_rgb565(raw, width, height):
    if len(raw) != width * height * 2:
        raise AdapterError("RAW_SHAPE", "Incomplete saved image")
    p = np.frombuffer(raw, dtype=">u2").reshape(height, width).astype(np.uint32)
    r, g, b = p >> 11, (p >> 5) & 63, p & 31
    return np.stack(((b << 3) | (b >> 2), (g << 2) | (g >> 4),
                     (r << 3) | (r >> 2)), axis=-1).astype(np.uint8)


class ClosedLoop:
    """Single owner, one new acquire() for every controller request/confirmation.

    MaskProvider is invoked BEFORE acquisition; its bool saved-domain mask is
    uploaded through the existing executor and bound to the result. The first
    usable image establishes the evaluation area. Subsequent source/coverage
    records are added without changing that mask or looking at future images.
    XDL's modeled budget is returned unchanged; transport costs are separate.
    """
    def __init__(self, *, dependencies, executor, config, output, roi, mask_provider,
                 sample_id, pose, context_id=None, settle_frames=1, timeout_s=3.,
                 cancel=None):
        if executor.mode != "strict":
            raise AdapterError("STRICT_REQUIRED", "Compatibility images cannot drive the controller")
        config.validate()
        if type(settle_frames) is not int or not 0 <= settle_frames <= 255:
            raise ValueError("settle_frames bounds")
        if timeout_s <= 0 or not np.isfinite(timeout_s):
            raise ValueError("finite positive timeout")
        self.d, self.executor, self.config = dependencies, executor, config
        self.output, self.roi = Path(output).resolve(), tuple(roi)
        self.provider = mask_provider
        self.sample_id, self.pose = sample_id, pose
        self.context_id = context_id or uuid.uuid4().hex
        self.wait, self.timeout_s, self.cancel = settle_frames, timeout_s, cancel
        self.controller = dependencies.xdl.acquisition_control.Controller(config, self.context_id)
        self.area = None
        self.identities, self.requests, self.publications = set(), set(), set()
        self.transitions, self.ledger, self.observations = [], [], []
        self.reserved_frames = 0
        self.execution_stop_reason = None

    def _trace(self, event, **payload):
        self.trace.write(canonical(dict(event=event, host_monotonic_ns=time.monotonic_ns(),
                                        context_id=self.context_id, **payload)) + "\n")
        self.trace.flush()

    def _transition(self, event=None):
        before = plain(self.controller.snapshot())
        decision = self.controller.start() if event is None else self.controller.feed(event)
        record = dict(index=len(self.transitions)+1, state_before=before,
                      event={"kind": "start"} if event is None else plain(event),
                      state_after=plain(self.controller.snapshot()), decision=plain(decision))
        # This independent XDL oracle tests the full state and Decision, not
        # merely a terminal status or one next-exposure field.
        state, expected = self.d.xdl.fpga_reference.reference_transition(
            before, record["event"], plain(self.config))
        if canonical((state, expected)) != canonical((record["state_after"], decision)):
            raise AdapterError("RULE_REFERENCE_MISMATCH", "Unchanged XDL reference differs")
        self.transitions.append(record)
        self._trace("controller_transition", transition=record)
        return decision

    def _stop_unfulfilled(self, decision, reason):
        self.execution_stop_reason = reason
        event = self.d.xdl.acquisition_control.CaptureEvent(
            "missing_data", self.context_id, None, decision.next_exposure_lines, None, None)
        return self._transition(event)

    def _call_directories(self):
        root = self.executor.output_root
        return {p.name for p in root.iterdir() if p.is_dir()} if root.exists() else set()

    def _record_call(self, before, *, result, error, started, index, action, exposure):
        fresh = self._call_directories() - before
        outcome = None
        record_path = None
        if len(fresh) == 1:
            record_path = self.executor.output_root / fresh.pop() / "outcome.json"
            if record_path.is_file():
                outcome = json_read(record_path)
        if outcome is not None and outcome.get("call_id") != record_path.parent.name:
            raise AdapterError("CALL_IDENTITY", "Call ID and new record directory differ")
        self._new_outcome, self._new_record = outcome, record_path
        transport = outcome.get("cost") if outcome else None
        completed = int(transport["complete_images_received"]) if transport else None
        wait = outcome.get("device_reported_settle_frames") if outcome else None
        drop = outcome.get("device_reported_discard_frames") if outcome else None
        known_frames = proven_frames(outcome,record_path.parent,self.d) if outcome else None
        row = dict(attempt=index, action=action, requested_exposure_lines=exposure,
                   call_id=outcome.get("call_id") if outcome else None,
                   call_record=str(record_path) if outcome else None,
                   call_record_sha256=digest(record_path) if outcome else None,
                   sdk_trace_sha256=digest(record_path.parent/"frame_trace.jsonl") if outcome else None,
                   executor_status=outcome.get("status") if outcome else "NO_DURABLE_CALL_RECORD",
                   acquisition_error=getattr(error, "code", None),
                   adapter_error=None, accepted_observation=False,
                   requested_wait_frames=self.wait,
                   requested_discard_frames=self.config.discard_frames_per_request,
                   frame_reservation=self.wait+self.config.discard_frames_per_request+1,
                   device_reported_wait_frames=wait, device_reported_discard_frames=drop,
                   host_complete_images=completed, known_device_complete_frames=known_frames,
                   frame_cost_lower_bound=(known_frames if known_frames is not None
                                           else completed if completed is not None else 0),
                   frame_cost_complete=known_frames is not None,
                   publication_retries=0,
                   elapsed_ms=(time.monotonic()-started)*1000,
                   transport_cost=transport,
                   actual_identity=outcome.get("identity") if outcome else None,
                   actual_parameters=outcome.get("actual_parameters") if outcome else None)
        self.ledger.append(row)
        # Include untouched executor events in the common trace, explicitly
        # distinguishing host observations from device-proven durations.
        if outcome:
            trace_path = record_path.parent / "frame_trace.jsonl"
            for line in trace_path.read_text(encoding="utf-8").splitlines():
                item = json.loads(line)
                row["publication_retries"] += item["event"] == "publication_retry"
                self._trace("executor_trace", attempt=index, sdk_event=item)
        self._trace("attempt_cost", cost=row)
        return row

    def _validate_result(self, result, mask, exposure):
        meta = result.metadata
        if self._new_outcome is None or meta.get("call_id") != self._new_outcome.get("call_id"):
            raise AdapterError("NEW_CALL_REQUIRED", "Returned result is not from this acquire invocation")
        expected_record = self._new_record.parent / "committed/result.json"
        if result.record_path.resolve() != expected_record.resolve():
            raise AdapterError("RESULT_PATH", "Returned record is not the new committed result")
        if result.png_path.resolve() != (expected_record.parent/"image.png").resolve():
            raise AdapterError("PNG_PATH", "Returned PNG is not from the new committed result")
        if canonical(json_read(expected_record)) != canonical(meta) or canonical(meta) != canonical(self._new_outcome):
            raise AdapterError("DURABLE_RESULT_MISMATCH", "Result, outcome and returned metadata differ")
        if meta.get("status") != "COMMITTED" or meta.get("strict_verified") is not True:
            raise AdapterError("UNVERIFIED_RESULT", "No strict committed result")
        if meta.get("sample_id") != self.sample_id or meta.get("round_id") != self.context_id:
            raise AdapterError("CONTEXT", "Sample/request round mismatch")
        expected = dict(exposure_lines=exposure, gain16=self.config.gain16, light_mask=1,
                        brightness=self.config.led, settle_frames=self.wait,
                        discard_frames=self.config.discard_frames_per_request)
        if meta.get("actual_parameters") != expected:
            raise AdapterError("ACTUAL_PARAMETERS", "Actual settings differ from the controller request")
        requested = meta.get("requested", {})
        if any(requested.get(k) != v for k, v in expected.items()) or requested.get("roi") != list(self.roi):
            raise AdapterError("REQUEST_BINDING", "Capture was not requested with these settings/ROI")
        if meta.get("roi") != list(self.roi) or meta.get("mask_sha256") != hashlib.sha256(mask.tobytes()).hexdigest():
            raise AdapterError("GEOMETRY_BINDING", "ROI/mask binding changed")
        tag = dict(meta.get("identity", {}), bank=meta.get("bank"))
        if set(tag) != set(IDENTITY_BOUNDS) or any(
                type(tag[k]) is not int or not 0 <= tag[k] < bound
                for k, bound in IDENTITY_BOUNDS.items()):
            raise AdapterError("FULL_IDENTITY", "Incomplete or malformed frame identity")
        if not tag["session"] or any(not tag[k] for k in (
                "request_id", "config_epoch", "dvp_sequence", "publish_sequence")):
            raise AdapterError("FULL_IDENTITY", "Missing committed frame identity")
        key = canonical(tag)
        request_key = (tag["session"], tag["request_id"])
        publication_key = (tag["session"], tag["dvp_sequence"], tag["publish_sequence"])
        if key in self.identities or request_key in self.requests or publication_key in self.publications:
            raise AdapterError("INDEPENDENT_OBSERVATION_REQUIRED", "Frame/request/publication already consumed")
        if (meta.get("expected_request_id") != tag["request_id"] or
                meta.get("wire_frame_id") != tag["frame_id"] or
                meta.get("frame_id") != tag["frame_id"]):
            raise AdapterError("REQUEST_FRAME_BINDING", "Expected request and wire image differ")
        diag = meta["diagnostic"]
        self.d.sdk.identity_diag.require_association(
            diag, tag["session"], tag["request_id"], tag["frame_id"],
            result.raw_rgb565, expected_context=meta["identity"])
        if diag["identity"] != meta["identity"] or diag["bank"] != tag["bank"] or (
                diag["parameters"] != expected or diag["statistics"] != meta["statistics"] or
                diag["features"] != meta["features"] or diag["rgb_crc64"] != meta["crc64"]):
            raise AdapterError("SIDECAR_BINDING", "Image, native statistics and settings differ")
        if hashlib.sha256(result.raw_rgb565).hexdigest() != meta["raw_rgb565_sha256"]:
            raise AdapterError("RAW_SHA", "Raw image SHA mismatch")
        raw_path = expected_record.parent / "image.rgb565"
        if raw_path.read_bytes() != result.raw_rgb565 or digest(result.png_path) != meta["png_sha256"]:
            raise AdapterError("IMAGE_SHA", "Saved image differs from returned image")
        image = decode_rgb565(result.raw_rgb565, *self.roi[2:])
        decoded = cv2.imread(str(result.png_path), cv2.IMREAD_COLOR)
        if decoded is None or not np.array_equal(image, decoded):
            raise AdapterError("PNG_RAW_PIXELS", "PNG and original RGB565 disagree")
        expected_h1, expected_h2 = self.d.sdk.acquisition_support.image_metrics(
            result.raw_rgb565, *self.roi[2:], mask.tobytes())
        if list(meta["statistics"].values()) != expected_h1 or meta["features"] != expected_h2:
            raise AdapterError("NATIVE_STATISTICS", "Native statistics differ from original pixels/mask")
        camera = meta["camera_readback"]
        if camera["exposure_lines"] != exposure or camera["gain16"] != self.config.gain16 or (
                camera["generation"] != tag["camera_generation"] or not camera["locked"]):
            raise AdapterError("CAMERA_READBACK", "Readback and complete identity differ")
        self.identities.add(key)
        self.requests.add(request_key)
        self.publications.add(publication_key)
        return meta, tag, image

    def _metrics(self, result, meta, tag, image, native):
        cm = self.d.xdl.capture_metrics
        capture_key = hashlib.sha256(canonical(tag).encode()).hexdigest()
        frame = cm.FrameInput(self.context_id, capture_key, self.sample_id, self.pose,
            meta["actual_parameters"]["exposure_lines"], self.config.gain16,
            self.config.channel, self.config.led, *self.roi[2:], self.roi,
            meta["png_sha256"], meta["raw_rgb565_sha256"], self.executor.evidence_source,
            dict(dataset_id=self.context_id, capture_id=capture_key,
                 frame_id=canonical(tag), member="image.png",
                 complete_identity=tag, mask_source="explicit_saved_domain_native_mask",
                 board_mask_needs_manual_review=True))
        h, w = self.executor.sensor_size[1], self.executor.sensor_size[0]
        if self.area is None:
            self.area = cm.build_common_area([frame], [native], sensor_shape=(h, w))
            (self.output / "common_mask.bin").write_bytes(self.area.mask.tobytes())
            self._trace("common_area_established_from_first_frame",
                        source=plain(frame), common_mask_sha256=self.area.mask_sha256,
                        common_area=int(self.area.mask.sum()), future_frames_used=0)
        # Register THIS new source against the frozen region. The XDL metric
        # implementation intentionally rejects unregistered future sources.
        source = dict(observation_id=frame.observation_id, source_identity=cm.source_identity(frame),
                      roi=frame.roi, native_mask_sha256=hashlib.sha256(native.tobytes()).hexdigest(),
                      mask_source=frame.source_metadata["mask_source"], needs_manual_review=True)
        local = self.area.mask[self.roi[1]:self.roi[1]+self.roi[3],
                               self.roi[0]:self.roi[0]+self.roi[2]]
        if np.any(local & ~native):
            raise AdapterError("FROZEN_AREA_LEFT_NATIVE", "Frozen evaluation area leaves current native board")
        n, native_n = int(self.area.mask.sum()), int(native.sum())
        coverage = dict(observation_id=frame.observation_id, native_area=native_n,
                        common_area=n, coverage_numerator=n,
                        coverage_denominator=native_n if native_n else None)
        sources = tuple(s for s in self.area.sources if s["observation_id"] != frame.observation_id)+(source,)
        areas = tuple(c for c in self.area.coverage if c["observation_id"] != frame.observation_id)+(coverage,)
        reasons = list(self.area.reason_codes)
        if not native_n or n*10000 < native_n*self.config.min_coverage_bp:
            reasons.append("insufficient_native_coverage")
        view = cm.EvaluationArea(self.area.mask, sources, self.area.mask_sha256, areas,
                                 not reasons, tuple(dict.fromkeys(reasons)))
        metric, arrays = cm.compute_metrics(image, frame, native, view, self.d.algorithm)
        # Preserve the independent native counts; common counts are not
        # substituted into the ten legacy device fields.
        record = dict(observation_id=frame.observation_id, complete_identity=tag,
                      call_id=meta["call_id"], actual_parameters=meta["actual_parameters"],
                      image_record=str(result.record_path), image_record_sha256=digest(result.record_path),
                      native_device_statistics=meta["statistics"], native_device_features=meta["features"],
                      native_reference_statistics=plain(metric.native_reference_statistics),
                      common_statistics=plain(metric.controller_statistics), geometry=plain(metric.geometry))
        self.observations.append(record)
        self._trace("observation_metrics", observation=record)
        return frame, metric

    def run(self):
        self.output.mkdir(parents=True, exist_ok=False)
        self.trace = (self.output / "frame_trace.jsonl").open("x", encoding="utf-8")
        self.started = time.monotonic()
        fatal = None
        try:
            decision = self._transition()
            while decision.status == "CONTINUE_ADJUST":
                frames = self.wait+self.config.discard_frames_per_request+1
                if self.cancel is not None and self.cancel.is_set():
                    decision = self._stop_unfulfilled(decision, "cancelled_before_request")
                    break
                if self.reserved_frames+frames > self.config.max_frames:
                    decision = self._stop_unfulfilled(decision, "transport_frame_reservation_budget")
                    break
                remaining_s = self.config.max_time_ms/1000-(time.monotonic()-self.started)
                if remaining_s <= 0:
                    decision = self._stop_unfulfilled(decision, "host_elapsed_budget")
                    break
                exposure = decision.next_exposure_lines
                native = self.provider(len(self.ledger)+1, exposure)
                if (not isinstance(native, np.ndarray) or native.dtype != np.bool_ or
                        native.shape != (self.roi[3], self.roi[2])):
                    raise AdapterError("NATIVE_MASK", "MaskProvider must return a saved-domain bool mask")
                native = np.frombuffer(native.tobytes(), dtype=np.bool_).reshape(native.shape)
                self.reserved_frames += frames
                index, action = len(self.ledger)+1, decision.action_kind
                mask_path = self.output / f"native_mask_{index:02d}.bin"
                mask_path.write_bytes(native.tobytes())
                before, began = self._call_directories(), time.monotonic()
                self._trace("controller_request", attempt=index, action=action,
                            exposure_lines=exposure, roi=self.roi)
                result, error = None, None
                try:
                    result = self.executor.acquire(light_channel=self.config.channel,
                        brightness=self.config.led, exposure_lines=exposure, gain16=self.config.gain16,
                        roi=self.roi, board_mask=native.tobytes(), settle_frames=self.wait,
                        discard_frames=self.config.discard_frames_per_request,
                        timeout_s=min(self.timeout_s, remaining_s), cancel=self.cancel,
                        sample_id=self.sample_id, round_id=self.context_id)
                except self.d.sdk.acquisition_executor.AcquisitionError as exc:
                    error = exc
                row = self._record_call(before, result=result, error=error, started=began,
                                        index=index, action=action, exposure=exposure)
                row.update(native_mask_path=str(mask_path), native_mask_sha256=digest(mask_path))
                if error is not None:
                    event = self.d.xdl.acquisition_control.CaptureEvent(
                        "capture_error", self.context_id, None, exposure, None, error.code)
                    decision = self._transition(event)
                    if decision.status == "CONTINUE_ADJUST" and (error.needs_reset or error.code == "CANCELLED"):
                        decision = self._stop_unfulfilled(decision, "external_recovery_required" if error.needs_reset else "cancelled")
                    continue
                try:
                    meta, tag, image = self._validate_result(result, native, exposure)
                    frame, metric = self._metrics(result, meta, tag, image, native)
                except (AdapterError, ValueError, KeyError, OSError, TypeError) as exc:
                    row["adapter_error"] = getattr(exc, "code", "RESULT_VALIDATION")
                    self._trace("observation_rejected", attempt=index, code=row["adapter_error"], reason=str(exc))
                    if row["adapter_error"] == "FROZEN_AREA_LEFT_NATIVE":
                        decision = self._stop_unfulfilled(decision, "frozen_area_left_native")
                    else:
                        event = self.d.xdl.acquisition_control.CaptureEvent(
                            "capture_error", self.context_id, None, exposure, None, row["adapter_error"])
                        decision = self._transition(event)
                    continue
                row["accepted_observation"] = True
                event = self.d.xdl.acquisition_control.CaptureEvent(
                    "observation", self.context_id, frame.observation_id, exposure, metric, None)
                decision = self._transition(event)
            verify_dependencies(self.d.root)
            if any(digest(p) != value for p, value in self.d.controller_hashes.items()):
                raise AdapterError("SOURCE_CHANGED", "XDL rules changed during execution")
        except BaseException as exc:
            fatal = {"code": getattr(exc, "code", type(exc).__name__), "message": str(exc)}
            self._trace("adapter_failed", failure=fatal)
        finally:
            self.trace.close()
        summary = dict(schema=1, controller_status=self.controller.snapshot().status,
            sdk_output_root=str(self.executor.output_root), roi=list(self.roi),
            controller_config=plain(self.config), context_id=self.context_id,
            sample_id=self.sample_id, pose=self.pose,
            controller_snapshot=plain(self.controller.snapshot()),
            execution_stop_reason=self.execution_stop_reason, fatal_error=fatal,
            evidence_source=self.executor.evidence_source,
            board_verified=False, physical_freshness_verified=False, release_ready=False,
            controller_rules_modified=False, dependencies=self.d.manifest,
            sdk_publication_overlay=self.d.sdk_publication_overlay,
            effective_executor_sha256=self.d.effective_executor_sha256,
            publication_source_sha256=self.d.publication_source_sha256,
            controller_source_sha256=self.d.controller_hashes,
            accepted_observations=len([r for r in self.ledger if r["accepted_observation"]]),
            attempts=len(self.ledger), common_mask_sha256=self.area.mask_sha256 if self.area else None,
            common_sensor_shape=list(self.area.mask.shape) if self.area else None,
            first_frame_common_area=self.area is not None, future_frames_used_to_establish_area=0,
            transport_cost=dict(api_attempts=len(self.ledger),
                retry_acquisitions=sum(r["action"] == "retry_current" for r in self.ledger),
                publication_retries=sum(r["publication_retries"] for r in self.ledger),
                reserved_frame_upper_bound=self.reserved_frames,
                known_frames=sum(r["frame_cost_lower_bound"] for r in self.ledger),
                frame_cost_complete=all(r["frame_cost_complete"] for r in self.ledger),
                frame_cost_scope="requested transaction only; excludes unobserved startup warmup and physical settling",
                unknown_frame_cost_attempts=[r["attempt"] for r in self.ledger if not r["frame_cost_complete"]],
                measured_host_elapsed_ms=(time.monotonic()-self.started)*1000,
                measured_physical_control_cost=None))
        save_json(self.output / "cost_ledger.json", self.ledger)
        save_json(self.output / "observations.json", self.observations)
        save_json(self.output / "transitions.json", self.transitions)
        save_json(self.output / "summary.json", summary)
        summary["result_sha256"] = {p.name: digest(p) for p in self.output.iterdir()
                                   if p.is_file() and p.name != "receipt.json"}
        save_json(self.output / "receipt.json", summary)
        return summary
