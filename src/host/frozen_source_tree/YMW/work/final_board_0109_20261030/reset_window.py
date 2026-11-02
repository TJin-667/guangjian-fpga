"""One KEY2 engineering window. Import/check-only never accesses the board."""
import argparse
import contextlib
import datetime
import hashlib
import importlib.util
import json
import secrets
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
HOST = HERE / 'host'
RUNTIME = HERE / 'runtime'
QUALIFICATION = Path('E:/GuangjianData/final_board_0109_20261030/engineering_bit_01/QUALIFICATION.json')
DATA = Path('E:/GuangjianData/Reset0109Acceptance')
ROI = (896, 496, 81, 21)
SAMPLE = 'ENGINEERING_RESET_NOT_TRAINING'


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def verify_tool():
    record = read(HERE / 'RESET_TOOL_BINDING.json')
    for name, digest in record['files_sha256'].items():
        relative = Path(name)
        need(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe tool member')
        need(sha(HERE / relative) == digest, 'Reset tool changed: ' + name)
    return record


def validate_pre(pre):
    frame = pre['frame']
    need(frame['status'] == 'COMMITTED' and frame['strict_verified'], 'No strict pre-reset frame')
    need(frame['identity']['session'] != 0 and frame['identity']['request_id'] != 0, 'No dirty old identity')
    extension = pre['extension']
    need(extension['status'] == 0 and extension['flags'] & 0xA0 == 0xA0, 'Old group must be locked and armed')
    need(not extension['flags'] & 7 and extension['completed_slots'] == 0, 'Unexpected in-flight/published state')
    need(extension['group'] != 0 and any(bytes.fromhex(extension['digest_hex'])) and extension['slot'] == 1, 'No explicit old group/slot')
    need(pre['cleanup']['acknowledged'], 'Pre-reset OFF not acknowledged')


def validate_reset(rows):
    need([r['kind'] for r in rows] == [3, 14, 9, 19, 31], 'Unexpected reset query sequence')
    status, caps, meta, *extensions = [r['decoded'] for r in rows]
    need(status['firmware'] == 0x109 and status['state'] & 16 and not status['state'] & 3 and status['error'] == 0, 'Reset did not restore ready0109')
    need(status['frames'] == 0 and caps['firmware'] == 0x109 and caps['format'] == 1, 'Frame count/format not reset')
    need(meta['request_counter'] == 0 and not meta['valid'] and not meta['mask_valid'], 'Metadata/mask not cleared')
    need(meta['identity']['session'] == meta['identity']['request_id'] == 0, 'Old session/request survived reset')
    for ext in extensions:
        need(ext['status'] == ext['flags'] == ext['group'] == ext['cookie'] == ext['request'] == 0, 'Old0109 state survived reset')
        need(ext['completed_slots'] == ext['slot'] == ext['scratch_error'] == 0 and not ext['association_error'], 'Old slot/error survived reset')
        need(not any(bytes.fromhex(ext['digest_hex'])) and ext['roi'] == [0, 0, 0, 0], 'Old group geometry/digest survived reset')
    return dict(status='RESET_CONTEXT_VERIFIED', captures_requested=0, configuration_commands=0, query_kinds=[3,14,9,19,31])


def extension_record(response):
    return dict(op=response.op, status=response.status, flags=response.flags, cookie=response.cookie,
                request=response.request, group=response.group, digest_hex=response.digest.hex(), roi=list(response.roi),
                completed_slots=response.completed_slots, slot=response.slot, scratch_error=response.scratch_error,
                association_error=response.association_error, wire_hex=response.wire.hex())


class Link:
    """Bounded raw requests, same sequence/socket when wrapping a live SDK owner."""
    def __init__(self, sock, endpoint, path, timeout=2.0, retries=2):
        self.sock, self.endpoint, self.path = sock, endpoint, path
        self.timeout, self.retries = timeout, retries
        self.rows = []

    def request(self, packet, sequence, timeout, kinds):
        row = dict(kind=packet[5], sequence=sequence, request_hex=packet.hex(), transmissions=0, replies=[])
        self.rows.append(row)
        collected = {}
        for attempt in range(self.retries):
            self.sock.sendto(packet, self.endpoint)
            row['transmissions'] += 1
            write(self.path, dict(status='READING', requests=self.rows))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                self.sock.settimeout(max(.001, deadline - time.monotonic()))
                try:
                    data, peer = self.sock.recvfrom(65535)
                except socket.timeout:
                    break
                if peer != self.endpoint or len(data) < 10 or data[:5] != b'LGHT\x01' or int.from_bytes(data[6:8], 'big') != sequence or data[5] not in kinds:
                    continue
                row['replies'].append(data.hex())
                collected[data[5]] = data
                write(self.path, dict(status='READING', requests=self.rows))
                if all(kind in collected for kind in kinds):
                    return collected
        raise TimeoutError('Query/command timeout: op' + str(packet[5]) + '; no replacement mutation allocated')

    def exchange(self, packet, sequence, timeout):
        return self.request(packet, sequence, timeout, (0x88,))[0x88]


class Runtime:
    """Real runtime; tests explicitly override endpoint, label and qualification."""
    physical = True
    evidence_source = 'real_board'
    endpoint = ('192.168.0.2', 5000)
    bind = '192.168.0.3'
    roi = ROI
    sensor_size = (1920, 1080)

    def __init__(self, *, physical=True):
        self.physical = physical
        self.evidence_source = 'real_board' if physical else 'software_udp_peer'
        sys.path.insert(0, str(HOST))
        spec = importlib.util.spec_from_file_location('_reset109_executor_' + uuid.uuid4().hex, HOST / 'engineering_executor.py')
        self.impl = importlib.util.module_from_spec(spec)
        self.impl.QUALIFICATION_PATH = QUALIFICATION if physical else None
        sys.modules[spec.name] = self.impl
        spec.loader.exec_module(self.impl)
        self.sdk = self.impl.sdk
        core_path = WORK / 'auto_exposure_0105_20261015/app_core.py'
        self.core = self.sdk.wire.pinned_module('_reset109_operator_core', core_path, '448fa6c6388093be794cf47f4932e77b688da92f74aa852ba8609b2cf5992857')
        self.engine = self.core.load_engine()
        self.protocol = self.sdk.support.load_protocol(self.engine.root / 'ymw')
        self.sources = dict(self.sdk.SOURCE_SNAPSHOT)
        self.sources[str(core_path)] = sha(core_path)
        self.sources[str(self.protocol.__file__)] = sha(self.protocol.__file__)
        self.sources[str(Path(__file__))] = sha(__file__)
        self.binding = None
        if physical:
            sys.path.insert(0, str(RUNTIME))
            import integrity
            import frozen_algorithm
            integrity.verify()
            need(frozen_algorithm.configuration()['freeze_id'] == 'f09eb5885e1d', 'Wrong algorithm freeze')
            q = read(QUALIFICATION)
            self.binding = dict(candidate_source_commit=q['candidate_source_commit'], bit_path=q['bit_path'], bit_sha256=q['bit_sha256'])
        sys.path.insert(0, str(RUNTIME))
        from roi_prepare0109 import executor_class
        self.Executor = executor_class(self.impl)

    def guard(self):
        return self.core.operator_lock(Path('C:/BX72_0105_LAB'))

    def source_check(self):
        need(all(sha(p) == digest for p, digest in self.sources.items()), 'Executable evidence changed during window')

    def executor(self, out, group):
        import numpy as np
        _, _, w, h = self.roi
        board = np.ones((h, w), dtype=bool)
        return self.Executor(group_id=group, group_digest=hashlib.sha256((str(group) + SAMPLE).encode()).digest()[:16],
            group_roi=self.roi, group_board=board, result_directory=out / 'fusion', board=self.endpoint[0], port=self.endpoint[1], bind=self.bind,
            ymw_root=self.engine.root / 'ymw', output_root=out / 'captures', pixel_format=49, mode='strict', evidence_source=self.evidence_source,
            candidate_binding=self.binding, sensor_size=self.sensor_size, command_timeout=1.5 if self.physical else .3, retries=2)

    def acquire(self, executor, *, preparation=False, slot=1):
        fn = executor.acquire_roi_preparation if preparation else executor.acquire
        return fn(light_channel=(slot-1)//2+1, brightness=128, exposure_lines=400 if slot % 2 else 800, gain16=16,
            roi=self.roi, board_mask=bytes([1]) * (self.roi[2] * self.roi[3]), settle_frames=1, discard_frames=3,
            timeout_s=90 if self.physical else 12, sample_id=SAMPLE, round_id='KEY2_DIAGNOSTIC_NOT_TRAINING')

    def seed(self, out):
        out.mkdir(parents=True)
        group = time.time_ns() // 100
        executor = self.executor(out, group)
        cleanup = None
        try:
            frame = self.acquire(executor, preparation=True)
            need(frame.metadata['cost']['capture_requests'] == 1, 'Unexpected pre-reset CAP count')
            from offload_wire import ExtensionClient
            link = Link(executor.sock, self.endpoint, out / 'PRE_ARM_WIRE.json')
            client = ExtensionClient(link.exchange, executor._next_seq, timeout_s=1.5 if self.physical else .3)
            client.begin(group, hashlib.sha256((str(group) + SAMPLE).encode()).digest()[:16], self.roi)
            executor._off_group_live = True
            client.arm(1, 1)
            cleanup = executor.lights_off(timeout_s=3)
            response = client.bound(client.rpc(19))
            result = dict(status='OLD_GROUP_ARMED_FOR_KEY2', frame=frame.metadata, frame_record=str(frame.record_path),
                extension=extension_record(response), cleanup=cleanup, captures_requested=1,
                scope='Armed, no formal CAP and no DDR fusion in flight; not a busy-AXI reset test')
            validate_pre(result)
            write(out / 'PRE_RESET.json', result)
            return result
        finally:
            if cleanup is None:
                try:
                    write(out / 'CLEANUP_FAILURE_PATH.json', executor.lights_off(timeout_s=3))
                except Exception as exc:
                    write(out / 'CLEANUP_FAILURE_PATH.json', dict(acknowledged=False, error=str(exc)))
            executor.close()

    def probe_reset(self, out):
        rows = []
        sequence = secrets.randbelow(65000)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((self.bind, 0))
            link = Link(sock, self.endpoint, out / 'POST_RESET_WIRE.json', timeout=3)
            for index, kind in enumerate((3,14,9,19,31)):
                seq = sequence + index
                request = self.sdk.wire.legacy.command(kind, seq, 0)
                kinds = {3:(0x81,0x82),14:(0x86,),9:(0x85,),19:(0x88,),31:(0x88,)}[kind]
                packets = link.request(request, seq, 3 if self.physical else .5, kinds)
                if kind == 3:
                    ack = self.protocol.control(packets[0x81])
                    need(ack['original'] == 3 and ack['result'] == 0, 'Reset STATUS not acknowledged')
                    decoded = self.protocol.control(packets[0x82])
                elif kind == 14:
                    decoded = self.sdk.wire.decode_capabilities(packets[0x86], seq)
                elif kind == 9:
                    decoded = self.sdk.wire.decode_metadata(packets[0x85], seq)
                else:
                    from offload_wire import decode
                    decoded = extension_record(decode(packets[0x88], op=kind, sequence=seq))
                rows.append(dict(kind=kind, sequence=seq, decoded=decoded))
                write(out / 'POST_RESET.json', dict(status='READBACK_PENDING_VALIDATION', queries=rows))
        result = validate_reset(rows)
        write(out / 'POST_RESET.json', dict(**result, queries=rows))
        return result

    def recover(self, out):
        out.mkdir(parents=True)
        group = time.time_ns() // 100
        executor = self.executor(out, group)
        records, cleanup = [], None
        try:
            preparation = self.acquire(executor, preparation=True)
            for slot in range(1, 9):
                frame = self.acquire(executor, slot=slot)
                records.append(str(frame.record_path))
                print('RECOVERY_FRAME', slot, '/ 8', flush=True)
        finally:
            try:
                cleanup = executor.lights_off(timeout_s=3)
                write(out / 'OFF.json', cleanup)
            finally:
                executor.close()
        result = read(out / 'fusion/RESULT.json')
        need(len(records) == 8 and cleanup['acknowledged'], 'Incomplete recovery/OFF')
        need(all(value == 0 for value in result['differences'].values()), 'Recovered FPGA/PC fusion differs')
        need(sum(read(p)['cost']['capture_requests'] for p in [str(preparation.record_path), *records]) == 9, 'Unexpected recovery CAP count')
        recovered = read(records[0])['identity']
        summary = dict(status='EIGHT_FRAME_RECOVERY_SAME_INPUT_PASSED', group=group, first_identity=recovered,
            differences=result['differences'], captures_requested=9, formal_frames=8, preparation_frames=1,
            preparation_record=str(preparation.record_path), records=records, cleanup=cleanup, training_data=False)
        write(out / 'RECOVERY.json', summary)
        write(out / 'SUMMARY.json', dict(status='ENGINEERING_SAME_INPUT_PASSED', cleanup=cleanup, records=records,
            roi_preparation_record=str(preparation.record_path), roi_preparation_in_formal_eight=False,
            formal_expected_frames=8, total_CAP_limit=9, training_data=False, engineering_only=True,
            controller_sha256=sha(__file__), release_ready=False, downloaded_bit_sha_readback_verified=False))
        return summary


def run_window(out, runtime, reset_action):
    out = Path(out).resolve()
    need(not out.exists(), 'New output directory required; never overwrite an earlier attempt')
    out.mkdir(parents=True)
    phase, pre, post, recovery, error = 'seed', None, None, None, None
    write(out / 'SOURCE_INDEX.json', dict(files_sha256=runtime.sources))
    write(out / 'SCOPE.json', dict(training_data=False, physical_hardware=runtime.physical, evidence_source=runtime.evidence_source,
        roi=list(runtime.roi), mask_scope='all-one transport diagnostic, not a physical segmentation or annotation',
        maximum_logical_CAP=10, GUI_or_original_plans_modified=False, bit_downloaded=False, external_IO_qualified=False))
    try:
        runtime.source_check()
        with runtime.guard():
            pre = runtime.seed(out / 'pre')
            phase = 'operator_KEY2'
            reset_action()
            phase = 'post_reset_source_check'
            runtime.source_check()
            phase = 'post_reset_read_before_BIND'
            post = runtime.probe_reset(out / 'reset')
        phase = 'new_session_eight_frame_recovery'
        with runtime.guard():
            runtime.source_check()
            recovery = runtime.recover(out / 'recovery')
        need(recovery['first_identity']['session'] != pre['frame']['identity']['session'], 'Old session reused after reset')
        runtime.source_check()
        phase = 'complete'
    except (Exception, KeyboardInterrupt) as exc:
        error = dict(type=type(exc).__name__, message=str(exc))
    result = dict(status='KEY2_ARMED_RESET_AND_RECOVERY_PASSED' if error is None else 'FAILED', phase=phase, error=error,
        physical_hardware=runtime.physical, evidence_source=runtime.evidence_source, training_data=False, roi=list(runtime.roi),
        pre=pre, post_reset=post, recovery=recovery, maximum_logical_CAP=10, external_IO_qualified=False,
        physical_busy_AXI_reset_tested=False, independent_clock_domain_reset_tested=False,
        full_frozen_detector_quality_tested=False, bit_SHA_readback_verified=False, release_ready=False)
    write(out / 'SUMMARY.json', result)
    # Hash all retained diagnostics even on failure; no failure is replaced by an older success.
    seal = {p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p != out / 'OUTPUT_MANIFEST.json'}
    write(out / 'OUTPUT_MANIFEST.json', dict(files_sha256=seal))
    print(json.dumps(dict(status=result['status'], result_directory=str(out), phase=phase, error=error), ensure_ascii=False), flush=True)
    return result


def operator_reset():
    print('\n现在请按板卡KEY2复位键约1秒后松开。不要断电或重新下载bit。', flush=True)
    print('完成后输入 RESET 并回车；输入其他内容将停止，保留全部记录。', flush=True)
    need(input().strip().upper() == 'RESET', 'Operator stopped; old armed group requires KEY2 before reuse')
    print('等待5秒，让板卡完成复位初始化，然后读取原始状态……', flush=True)
    time.sleep(5)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-only', action='store_true')
    mode.add_argument('--run', action='store_true')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    tool_binding = verify_tool()
    runtime = Runtime()
    runtime.sources.update({str(HERE/name):digest for name,digest in tool_binding['files_sha256'].items()})
    runtime.sources[str(HERE/'RESET_TOOL_BINDING.json')] = sha(HERE/'RESET_TOOL_BINDING.json')
    if args.check_only:
        print(json.dumps(dict(status='RESET109_OFFLINE_READY', hardware_contacted=False, roi=list(ROI), maximum_logical_CAP=10, release_ready=False)))
        return
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    out = args.out or DATA / (now.strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
    need(out.resolve().is_relative_to(DATA.resolve()), 'Real results must stay under E:/GuangjianData/Reset0109Acceptance')
    print('0109工程复位恢复验收；不下载bit，不修改网络。请先关闭预览/采集窗口。', flush=True)
    print('先建立1张小ROI诊断与待采组，再提示按KEY2；恢复最多9张小图，均不计训练数据。', flush=True)
    result = run_window(out, runtime, operator_reset)
    raise SystemExit(0 if result['status'] == 'KEY2_ARMED_RESET_AND_RECOVERY_PASSED' else 1)


if __name__ == '__main__':
    main()
