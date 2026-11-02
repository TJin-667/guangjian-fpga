"""Bounded request execution. Image selection and fusion belong to XDL."""
from __future__ import annotations

import copy
import datetime
import json
from pathlib import Path
import threading
import time
import uuid

from .contracts import (CaptureRequest, ContractError, Observation, ObservationSet,
                        Profile, Stop, require, sha, validate_progress)
from .ports import CaptureFailure
from .validation import validate_payload


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def safe_cost(value):
    try:
        require(type(value) is dict, 'COST_SCHEMA')
        return json.loads(json.dumps(value, allow_nan=False))
    except (ValueError, TypeError):
        return dict(unknown=True, invalid_cost_report=True)


class ScriptedPolicy:
    """Only for software tests; never describes image-driven online decisions."""
    policy_id = 'scripted_offline'

    def __init__(self, actions):
        self.actions = iter(actions)

    def reset(self, context, output_root, profile):
        self.output_root = Path(output_root)

    def consume(self, observation):
        pass

    def next_action(self, observations, budget):
        return next(self.actions, Stop('REVIEW', 'script ended without an explicit stop'))

    def finalize(self, status, observations, budget):
        return dict(scope='Injected transport actions only; no image selection or fusion', observations=len(observations))


class Ledger:
    def __init__(self, limits, clock):
        self.limits, self.clock = limits, clock
        self.started = clock()
        self.attempts = self.reserved_frames = 0
        self.calls = []

    def remaining_work_s(self):
        return self.limits.max_elapsed_s - self.limits.shutdown_reserve_s - (self.clock() - self.started)

    def reserve(self, frames):
        require(self.remaining_work_s() > 0 and self.attempts < self.limits.max_attempts
                and self.reserved_frames + frames <= self.limits.max_reserved_frames, 'TOTAL_BUDGET_EXHAUSTED')
        self.attempts += 1
        self.reserved_frames += frames

    def describe(self):
        elapsed = self.clock() - self.started
        return dict(attempts=self.attempts, reserved_transaction_frames=self.reserved_frames,
                    elapsed_s=elapsed, total_deadline_exceeded=elapsed > self.limits.max_elapsed_s,
                    calls=copy.deepcopy(self.calls),
                    reserved_is_not_actual_DVP_count=True, failed_unreported_costs_are_unknown=True)


def run(context, limits, policy, open_port, out, *, profile=None, cancel=None, clock=time.monotonic):
    """The caller's port factory owns cleanup until returning a port.

    The port is created only after the timer starts. A caller must separately
    hold the existing operator lock and verify same pose before future SDK use.
    This package has no live-board CLI or GUI launcher.
    """
    profile, cancel = profile or Profile(), cancel or threading.Event()
    ledger = Ledger(limits, clock)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    observations = ObservationSet()
    events, seen_actions, last_seen = [], set(), None
    status, reason, port = 'REVIEW', 'NOT_STARTED', None
    off = dict(requested=False, acknowledged=False, physical_off_verified=False)

    def event(kind, **fields):
        events.append(dict(event_seq=len(events) + 1, event=kind, elapsed_s=clock() - ledger.started, **fields))

    def observe(receipt):
        nonlocal last_seen
        validate_progress(last_seen, receipt)
        last_seen = copy.deepcopy(receipt)

    try:
        if cancel.is_set():
            raise CaptureFailure('CANCELLED')
        require(ledger.remaining_work_s() > 0, 'TOTAL_BUDGET_EXHAUSTED')
        port = open_port()
        require(getattr(port, 'execution_mode', '') in ('software_fake', 'sdk_adapter'), 'PORT_EXECUTION_MODE')
        event('port_opened', execution_mode=port.execution_mode)
        policy.reset(context, out.resolve(), profile)
        while True:
            if cancel.is_set():
                raise CaptureFailure('CANCELLED')
            require(ledger.remaining_work_s() > 0, 'TOTAL_BUDGET_EXHAUSTED')
            action = policy.next_action(observations, ledger.describe())
            if isinstance(action, Stop):
                status, reason = action.status, action.reason
                if status == 'STOP' and not observations.base_complete:
                    status, reason = 'REVIEW', 'MISSING_BASE_DIRECTIONS'
                break
            require(isinstance(action, CaptureRequest), 'INVALID_POLICY_ACTION')
            action.parameters(profile)
            observations.check_request(action, limits.max_supplements)
            require(action.action_id not in seen_actions, 'REUSED_ACTION')
            seen_actions.add(action.action_id)
            succeeded = False
            for retry in range(limits.same_setting_retries + 1):
                if cancel.is_set():
                    raise CaptureFailure('CANCELLED')
                ledger.reserve(1 + profile.settle_frames + profile.discard_frames)
                attempt_id = uuid.uuid4().hex
                event('capture_requested', action_id=action.action_id, attempt_id=attempt_id,
                      retry=retry, role=action.role, channel=action.channel, parameters=action.parameters(profile))
                payload = None
                cost = {}
                try:
                    payload = port.capture(action, context, profile, attempt_id, ledger.remaining_work_s(), cancel)
                    cost = safe_cost(payload.record.get('cost', {}))
                    observe(payload.receipt)  # advances even if pixels/readback are rejected below
                    require(not cancel.is_set(), 'CANCELLED')
                    require(ledger.remaining_work_s() > 0, 'TOTAL_BUDGET_EXHAUSTED')
                    audit = validate_payload(payload, action, context, profile)
                    require(not cancel.is_set(), 'CANCELLED')
                    require(ledger.remaining_work_s() > 0, 'TOTAL_BUDGET_EXHAUSTED')
                    require(payload.execution_mode == port.execution_mode, 'PORT_PAYLOAD_MODE')
                    observation_id = uuid.uuid4().hex
                    files = {name: 'observations/' + observation_id + '/' + file for name, file in
                             (('png', 'image.png'), ('raw', 'image.rgb565'), ('record', 'result.json'))}
                    observation = Observation(observation_id, action.action_id, attempt_id, action.channel, action.role,
                                              action.parameters(profile), copy.deepcopy(payload.receipt), payload.record['call_id'],
                                              sha(payload.png), sha(payload.raw), payload.record['evidence_source'], payload.execution_mode, files,
                                              statistics=copy.deepcopy(payload.record['statistics']), features=copy.deepcopy(payload.record['features']),
                                              camera_readback=copy.deepcopy(payload.record['camera_readback']))
                    observations.check_observation(observation)
                    target = out / 'observations' / observation_id
                    target.mkdir(parents=True, exist_ok=False)
                    (target / 'image.png').write_bytes(payload.png)
                    (target / 'image.rgb565').write_bytes(payload.raw)
                    write_json(target / 'result.json', payload.record)
                    write_json(target / 'observation.json', dict(observation.describe(), audit=audit))
                    observations.append(observation)
                    ledger.calls.append(dict(attempt_id=attempt_id, action_id=action.action_id, status='ACCEPTED', sdk_cost=cost))
                    event('observation_accepted', observation_id=observation_id, identity=payload.receipt)
                    succeeded = True
                    break
                except (CaptureFailure, ContractError) as exc:
                    if isinstance(exc, CaptureFailure):
                        cost = safe_cost(exc.cost)
                        if exc.receipt is not None:
                            observe(exc.receipt)
                    ledger.calls.append(dict(attempt_id=attempt_id, action_id=action.action_id, status='REJECTED',
                                             error=exc.code, sdk_cost=cost, needs_reset=exc.needs_reset))
                    event('capture_rejected', action_id=action.action_id, attempt_id=attempt_id, code=exc.code,
                          observed_receipt=payload.receipt if payload is not None else getattr(exc, 'receipt', None))
                    if exc.code == 'CANCELLED' or cancel.is_set():
                        raise CaptureFailure('CANCELLED') from exc
                    if exc.needs_reset:
                        raise CaptureFailure(exc.code, needs_reset=True) from exc
                    if exc.code == 'TOTAL_BUDGET_EXHAUSTED':
                        raise
                except (Exception, KeyboardInterrupt) as exc:
                    ledger.calls.append(dict(attempt_id=attempt_id, action_id=action.action_id, status='FAILED',
                                             error=type(exc).__name__, sdk_cost=safe_cost(cost)))
                    raise
            if not succeeded:
                status, reason = 'CAPTURE_FAILED', 'SAME_SETTING_RETRY_EXHAUSTED'
                break
            policy.consume(observations.items[-1])
    except (CaptureFailure, ContractError) as exc:
        reason = exc.code
        status = 'CANCELLED' if exc.code == 'CANCELLED' else ('REVIEW' if exc.code == 'TOTAL_BUDGET_EXHAUSTED' else 'CAPTURE_FAILED')
        event('stopped', status=status, reason=reason, needs_reset=exc.needs_reset)
    except (Exception, KeyboardInterrupt) as exc:
        status = 'CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'FAILED'
        reason = type(exc).__name__ + ': ' + str(exc)
        event('stopped', status=status, reason=reason)
    finally:
        if port is not None:
            try:
                off = port.lights_off()
                require(type(off) is dict and off.get('requested') is True and type(off.get('acknowledged')) is bool, 'OFF_RESULT_SCHEMA')
                off['physical_off_verified'] = False
            except (Exception, KeyboardInterrupt) as exc:
                off = dict(requested=True, acknowledged=False, physical_off_verified=False, error=str(exc))
                if isinstance(exc, KeyboardInterrupt):
                    status, reason = 'CANCELLED', 'INTERRUPTED_DURING_SHUTDOWN'
            try:
                port.close()
            except (Exception, KeyboardInterrupt) as exc:
                event('close_failed', error=str(exc))
                if isinstance(exc, KeyboardInterrupt):
                    status, reason = 'CANCELLED', 'INTERRUPTED_DURING_CLOSE'
                elif status == 'STOP':
                    status, reason = 'REVIEW', 'PORT_CLOSE_FAILED'
            if not off['acknowledged'] and status == 'STOP':
                status, reason = 'REVIEW', 'LIGHTS_OFF_UNCONFIRMED'
        event('shutdown', lights_off=off)
        try:
            policy_report = policy.finalize(status, observations.items, ledger.describe())
            require(type(policy_report) is dict, 'POLICY_REPORT_SCHEMA')
            json.dumps(policy_report, allow_nan=False)
        except (Exception, KeyboardInterrupt) as exc:
            policy_report = dict(error=type(exc).__name__ + ': ' + str(exc))
            if isinstance(exc, KeyboardInterrupt):
                status, reason = 'CANCELLED', 'INTERRUPTED_DURING_POLICY_FINALIZE'
            elif status == 'STOP':
                status, reason = 'REVIEW', 'POLICY_FINALIZE_FAILED'
        (out / 'native_mask.bin').write_bytes(context.mask)
        write_json(out / 'context.json', context.describe())
        write_json(out / 'observations.json', observations.describe())
        with (out / 'events.jsonl').open('x', encoding='utf-8') as stream:
            for row in events:
                stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
        budget = ledger.describe()
        if budget['total_deadline_exceeded'] and status == 'STOP':
            status, reason = 'REVIEW', 'TOTAL_DEADLINE_EXCEEDED'
        report = dict(schema='ymw-multiobs-experiment-0.1', status=status, stop_reason=reason,
                      context=context.describe(), policy_id=policy.policy_id, profile=profile.__dict__,
                      policy_report=policy_report,
                      observations=observations.describe(), base_directions_complete=observations.base_complete,
                      execution_mode=port.execution_mode if port else 'not_started', lights_off=off, budget=budget,
                      limits=limits.__dict__, last_observed_identity=last_seen,
                      per_direction_online_strategy_validated=False, multi_exposure_fusion_implemented=False,
                      physical_freshness_verified=False, settling_calibrated=False,
                      terminal_receipt='completion.json is authoritative after report and manifest writes',
                      measured_cost_scope='factory/open through capture/validation/image writes/shutdown and archive; see final completion receipt')
        write_json(out / 'report.json', report)
        manifest = {p.relative_to(out).as_posix(): sha(p.read_bytes()) for p in sorted(out.rglob('*')) if p.is_file()}
        write_json(out / 'manifest.json', dict(files=manifest))
        final_budget = ledger.describe()
        if final_budget['total_deadline_exceeded'] and status == 'STOP':
            status, reason = 'REVIEW', 'TOTAL_DEADLINE_EXCEEDED'
        completion = dict(status=status, stop_reason=reason, budget=final_budget,
                          report_sha256=sha((out / 'report.json').read_bytes()),
                          manifest_sha256=sha((out / 'manifest.json').read_bytes()),
                          measured_through='report and manifest archive; terminal completion.json write itself excluded',
                          final_receipt_is_not_an_optical_or_strategy_acceptance=True)
        write_json(out / 'completion.json', completion)
    return dict(report, status=status, stop_reason=reason, budget=final_budget)
